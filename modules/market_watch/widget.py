"""Interfaccia del Market Watch (fonte: API ufficiale CardTrader).

Flusso d'uso:
1. Imposta il token CardTrader (una volta).
2. Sincronizza il catalogo Yu-Gi-Oh! (una volta, per cercare per nome) —
   oppure aggiungi direttamente una carta col suo blueprint ID.
3. Aggiungi le carte alla watchlist con una soglia di calo %.
4. "Controlla ora" o il controllo automatico riscarica il prezzo PIÙ BASSO
   su CardTrader; se è sceso oltre la soglia, parte una notifica.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QStringListModel,
    QThreadPool,
    QUrl,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCompleter,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.context import AppContext
from core import anim, badges, i18n, theme
from core.rarity import rarity_pixmap, rarity_rank
from core.version import APP_VERSION
from core.i18n import tr

from . import config
from . import transfer
from . import ydk
from .deck_dialog import DeckDialog
from .filters_dialog import DisplayDialog, FiltersDialog, WelcomeDialog
from .flags import country_name, flag_pixmap
from .history_chart import HistoryDialog, Run, split_runs
from .providers import cardtrader
from .providers.base import CardRef, ListingFilters, PriceQuote
from .providers.cardtrader import CardTraderClient, CardTraderProvider
from .repository import CardCatalogError, MarketWatchRepository
from .search_model import (
    ThumbDelegate,
    _make_empty_frame,
    _ThumbSignals,
    _ThumbTask,
    _thumb_url,
    stock_pixmap,
    sweep_orphan_cell_widgets,
)
from .workers import CatalogSyncWorker, ImageFetchWorker, PriceFetchWorker
from .ydk_dialog import YdkImportDialog, sort_printings

PROVIDER = "cardtrader"
# Le miniature si scaricano/cachano grandi (ROW_THUMB) e vengono rimpicciolite
# dalla tabella in vista normale (downscale = nitido). In Panoramica si usa la
# dimensione piena e righe/font più grandi.
ROW_THUMB = QSize(92, 128)          # dimensione di download/cache
ROW_ICON_NORMAL = QSize(40, 56)
ROW_H_NORMAL = 64
ROW_ICON_BIG = QSize(92, 128)
ROW_H_BIG = 148


def _make_trash_icon(color: str = "#94a1b2", size: int = 32) -> QIcon:
    """Disegna un'icona 'cestino' a tratto, coerente col tema (per il tasto Rimuovi)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(size / 16.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    u = size / 32.0
    def ln(x1, y1, x2, y2):
        p.drawLine(round(x1 * u), round(y1 * u), round(x2 * u), round(y2 * u))
    ln(6, 9, 26, 9)                       # coperchio
    ln(13, 6, 19, 6); ln(13, 6, 13, 9); ln(19, 6, 19, 9)   # manico
    ln(9, 9, 11, 26); ln(23, 9, 21, 26); ln(11, 26, 21, 26)  # corpo (trapezio) + fondo
    for x in (13, 16, 19):                # nervature
        ln(x, 13, x, 23)
    p.end()
    return QIcon(pm)


def _make_key_icon(color: str = "#94a1b2", size: int = 32) -> QIcon:
    """Icona 'chiave' (token), a tratto, coerente col tema."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(size / 16.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    u = size / 32.0
    p.drawEllipse(round(6 * u), round(11 * u), round(10 * u), round(10 * u))  # testa
    def ln(x1, y1, x2, y2):
        p.drawLine(round(x1 * u), round(y1 * u), round(x2 * u), round(y2 * u))
    ln(16, 16, 27, 16)          # gambo
    ln(22, 16, 22, 21)          # dente 1
    ln(26, 16, 26, 22)          # dente 2
    p.end()
    return QIcon(pm)


def _make_sync_icon(color: str = "#94a1b2", size: int = 32) -> QIcon:
    """Icona 'sincronizza' (due frecce circolari), a tratto."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(size / 16.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    u = size / 32.0
    rect = (round(7 * u), round(7 * u), round(18 * u), round(18 * u))
    p.drawArc(*rect, 40 * 16, 130 * 16)     # arco alto (senso antiorario)
    p.drawArc(*rect, 220 * 16, 130 * 16)    # arco basso
    def ln(x1, y1, x2, y2):
        p.drawLine(round(x1 * u), round(y1 * u), round(x2 * u), round(y2 * u))
    ln(8.2, 12.4, 5.6, 8.6)     # punta freccia sinistra
    ln(8.2, 12.4, 12.6, 11.6)
    ln(23.8, 19.6, 26.4, 23.4)  # punta freccia destra
    ln(23.8, 19.6, 19.4, 20.4)
    p.end()
    return QIcon(pm)


def _make_filter_icon(color: str = "#94a1b2", size: int = 32) -> QIcon:
    """Icona 'imbuto' (filtri annunci), a tratto."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(size / 16.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    u = size / 32.0
    def ln(x1, y1, x2, y2):
        p.drawLine(round(x1 * u), round(y1 * u), round(x2 * u), round(y2 * u))
    ln(6, 8, 26, 8)      # bocca dell'imbuto
    ln(6, 8, 14, 17)     # spalla sinistra
    ln(26, 8, 18, 17)    # spalla destra
    ln(14, 17, 14, 24)   # collo
    ln(18, 17, 18, 26)   # collo (più lungo: goccia che scende)
    p.end()
    return QIcon(pm)


def _make_grid_icon(color: str = "#94a1b2", size: int = 32) -> QIcon:
    """Icona 'panoramica' (griglia 2×2), a tratto."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(size / 16.0)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    u = size / 32.0
    r = round(2.5 * u)
    for x, y in ((6, 6), (18, 6), (6, 18), (18, 18)):
        p.drawRoundedRect(round(x * u), round(y * u), round(8 * u), round(8 * u), r, r)
    p.end()
    return QIcon(pm)


def _make_pencil_icon(color: str = "#94a1b2", size: int = 32) -> QIcon:
    """Icona 'matita' (rinomina), a tratto, coerente col tema."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(size / 16.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    u = size / 32.0
    def ln(x1, y1, x2, y2):
        p.drawLine(round(x1 * u), round(y1 * u), round(x2 * u), round(y2 * u))
    ln(9, 23, 20, 12)      # lato inferiore del corpo
    ln(13, 27, 24, 16)     # lato superiore
    ln(20, 12, 24, 16)     # fondo (gomma)
    ln(9, 23, 13, 27)      # base della punta
    ln(9, 23, 6, 30)       # punta
    ln(13, 27, 6, 30)
    p.end()
    return QIcon(pm)


def _make_link_icon(color: str = "#94a1b2", size: int = 32) -> QIcon:
    """Icona 'apri fuori': riquadro con freccia che esce in alto a destra."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(size / 16.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    u = size / 32.0
    # riquadro aperto sull'angolo da cui esce la freccia
    p.drawLine(QPointF(18 * u, 7 * u), QPointF(7 * u, 7 * u))
    p.drawLine(QPointF(7 * u, 7 * u), QPointF(7 * u, 25 * u))
    p.drawLine(QPointF(7 * u, 25 * u), QPointF(25 * u, 25 * u))
    p.drawLine(QPointF(25 * u, 25 * u), QPointF(25 * u, 14 * u))
    # freccia in uscita
    p.drawLine(QPointF(15 * u, 17 * u), QPointF(26 * u, 6 * u))
    p.drawLine(QPointF(19 * u, 6 * u), QPointF(26 * u, 6 * u))
    p.drawLine(QPointF(26 * u, 6 * u), QPointF(26 * u, 13 * u))
    p.end()
    return QIcon(pm)


def _make_deck_icon(color: str = "#94a1b2", size: int = 32) -> QIcon:
    """Icona 'base/mazzo': carte a ventaglio, a tratto.

    Stesso glifo delle righe-base in watchlist (`_make_base_icon`): chi preme
    questo pulsante deve ritrovare la stessa forma nell'elenco."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(size / 16.0)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    u = size / 32.0
    for angle in (-24, 0, 24):
        p.save()
        p.translate(16 * u, 25 * u)
        p.rotate(angle)
        p.drawRoundedRect(QRectF(-6 * u, -19 * u, 12 * u, 19 * u), 2.0 * u, 2.0 * u)
        p.restore()
    p.end()
    return QIcon(pm)


def _make_gear_icon(color: str = "#94a1b2", size: int = 32) -> QIcon:
    """Icona 'ingranaggio' (Opzioni), a tratto.

    Gli sliders sono ormai il glifo dei FILTRI DI UNA CARTA (riga in watchlist
    e carta in arrivo): usarli anche per le Opzioni faceva sembrare due cose
    diverse la stessa. L'ingranaggio è generico quanto basta a coprire
    visualizzazione, animazioni e lingua."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(size / 16.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    u = size / 32.0
    p.translate(16 * u, 16 * u)
    for _ in range(8):                      # denti, uno ruotato 8 volte
        p.drawLine(QPointF(0, -10.5 * u), QPointF(0, -14.0 * u))
        p.rotate(45)
    p.drawEllipse(QPointF(0, 0), 9.5 * u, 9.5 * u)   # corona
    p.drawEllipse(QPointF(0, 0), 3.6 * u, 3.6 * u)   # foro
    p.end()
    return QIcon(pm)


def _make_settings_icon(color: str = "#94a1b2", size: int = 32) -> QIcon:
    """Icona 'sliders' (filtri/impostazioni), a tratto, coerente col tema."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(size / 16.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    u = size / 32.0
    for i, (y, kx) in enumerate([(9, 20), (16, 12), (23, 22)]):  # 3 barre + manopola
        p.drawLine(round(7 * u), round(y * u), round(25 * u), round(y * u))
        cx, cy, r = kx * u, y * u, 3.0 * u
        p.setBrush(QColor(color)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(round(cx - r), round(cy - r), round(2 * r), round(2 * r))
        p.setPen(pen)
    p.end()
    return QIcon(pm)


_mini_funnel_cache: dict[tuple[int, str], QPixmap] = {}


def _make_mini_funnel(size: int, color: str) -> QPixmap:
    """Imbutino pieno: marca nella colonna Nome le carte con filtri PROPRI.

    La stessa cosa la dice anche il pulsante filtri della riga (teal invece di
    grigio), ma quello sta in fondo a destra: scorrendo l'elenco l'occhio è sui
    nomi, e il marcatore deve stare lì."""
    key = (size, color)
    cached = _mini_funnel_cache.get(key)
    if cached is not None:
        return cached
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    u = size / 16.0
    p.drawPolygon([QPointF(1.5 * u, 3 * u), QPointF(14.5 * u, 3 * u),
                   QPointF(9.5 * u, 8.5 * u), QPointF(9.5 * u, 13.5 * u),
                   QPointF(6.5 * u, 11.5 * u), QPointF(6.5 * u, 8.5 * u)])
    p.end()
    _mini_funnel_cache[key] = pm
    return pm


class _IndentDelegate(QStyledItemDelegate):
    """Colonna NOME: rientro delle carte in cartella + marcatore "filtri propri".

    Il rientro sposta il RETTANGOLO di disegno invece di infilare spazi nel
    testo: con gli spazi rientrava solo la PRIMA riga, e in Panoramica i nomi
    lunghi vanno a capo, lasciando le righe successive disallineate.
    Il marcatore sta PRIMA del nome, in una colonnina riservata su TUTTE le
    righe (anche quelle senza): messo in fondo alla cella finiva lontano dal
    nome, e riservando lo spazio solo dove serve i nomi si disallineerebbero."""

    MARKER_GAP = 4

    def __init__(self, indent_px, marker_px, has_marker, parent=None) -> None:
        super().__init__(parent)
        self._indent_px = indent_px     # callable(row) -> px di rientro
        self._marker_px = marker_px     # callable() -> lato del marcatore in px
        self._has_marker = has_marker   # callable(row) -> bool

    def _slot(self) -> int:
        return self._marker_px() + self.MARKER_GAP

    def _offset(self, row: int) -> int:
        return self._indent_px(row) + self._slot()

    def _content(self, option, index):
        """Rettangolo del testo: dopo il rientro e la colonnina del marcatore."""
        shifted = QStyleOptionViewItem(option)
        shifted.rect = option.rect.adjusted(self._offset(index.row()), 0, 0, 0)
        return shifted

    def paint(self, painter, option, index) -> None:  # noqa: N802 (firma Qt)
        # Lo sfondo va dipinto sul rect PIENO: disegnando solo quello spostato
        # resterebbe a sinistra una striscia scoperta (si vedeva come una linea
        # verticale lungo la colonna Nome). Prima lo sfondo (zebra/selezione,
        # via lo stile, con testo e icona svuotati), poi il contenuto.
        back = QStyleOptionViewItem(option)
        self.initStyleOption(back, index)
        back.text = ""
        back.icon = QIcon()
        widget = back.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, back, painter, widget)
        super().paint(painter, self._content(option, index), index)
        if self._has_marker(index.row()):
            side = self._marker_px()
            painter.drawPixmap(option.rect.left() + self._indent_px(index.row()),
                               option.rect.center().y() - side // 2,
                               _make_mini_funnel(side, theme.ACCENT))

    def sizeHint(self, option, index):  # noqa: N802 (firma Qt)
        # larghezza ridotta da rientro e colonnina → il calcolo del ritorno a
        # capo usa lo spazio davvero disponibile
        size = super().sizeHint(self._content(option, index), index)
        size.setWidth(size.width() + self._offset(index.row()))
        return size


# Sigle delle condizioni. Match ESATTO sul nome intero (niente sottostringhe:
# "played" è dentro "light played" e "slightly played", e un match parziale le
# ridurrebbe tutte a PL). Ci sono sia i nomi dell'API sia quelli del sito, che
# NON coincidono — vedi la nota su `_open_card_page` nel registro tecnico.
_CONDITION_SHORT = {
    "mint": "M",
    "near mint": "NM",
    "excellent": "EX",
    "good": "GD",
    "light played": "LP",
    "slightly played": "SP",
    "moderately played": "MP",
    "played": "PL",
    "poor": "PO",
}


def _condition_short(name: str) -> str:
    """Sigla della condizione (NM, LP, …), o il nome com'è se sconosciuto.

    In tabella lo spazio è prezioso e il nome per esteso non dice niente che
    il tooltip non possa dire; una sigla inventata, invece, ingannerebbe."""
    return _CONDITION_SHORT.get((name or "").strip().lower(), name or "")


_folder_icon_cache: dict[tuple[bool, int, str], QIcon] = {}


def _make_base_icon(open_: bool, size: int = 24) -> QIcon:
    """Icona di una BASE (mazzo): chevron + carte a ventaglio.

    Il ventaglio è stato scelto fra sei proposte perché è l'unico che si legge
    ancora come "mazzo di carte" alla dimensione VERA della riga (~24px): le
    varianti a pila, ingrandite più belle, lì impastavano i contorni."""
    key = (open_, size, "deck")
    cached = _folder_icon_cache.get(key)
    if cached is not None:
        return cached
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    u = size / 32.0
    _draw_chevron(p, u, open_)
    stroke = QPen(QColor(theme.ACCENT))
    stroke.setWidthF(max(1.0, 1.7 * u))
    stroke.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    stroke.setCapStyle(Qt.PenCapStyle.RoundCap)
    fill = QColor(theme.ACCENT)
    fill.setAlpha(34 if open_ else 66)
    p.setPen(stroke)
    p.setBrush(fill)
    # tre carte che ruotano attorno a un perno in basso: si disegnano dalla
    # più a sinistra alla più a destra, così la sovrapposizione è naturale
    for angle in (-22, 0, 22):
        p.save()
        p.translate(20.5 * u, 22.0 * u)
        p.rotate(angle)
        p.drawRoundedRect(QRectF(-5 * u, -15 * u, 10 * u, 15 * u), 1.6 * u, 1.6 * u)
        p.restore()
    p.end()
    icon = QIcon(pm)
    _folder_icon_cache[key] = icon
    return icon


def _draw_chevron(p: QPainter, u: float, open_: bool) -> None:
    """Freccetta di apertura, a sinistra del glifo (▸ chiusa, ▾ aperta)."""
    pen = QPen(QColor(theme.TEXT_MUTED))
    pen.setWidthF(max(1.1, 2.2 * u))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    if open_:
        p.drawLine(QPointF(1.5 * u, 13.5 * u), QPointF(5.0 * u, 17.5 * u))
        p.drawLine(QPointF(5.0 * u, 17.5 * u), QPointF(8.5 * u, 13.5 * u))
    else:
        p.drawLine(QPointF(3.0 * u, 11.0 * u), QPointF(7.0 * u, 15.5 * u))
        p.drawLine(QPointF(7.0 * u, 15.5 * u), QPointF(3.0 * u, 20.0 * u))


def _make_folder_icon(open_: bool, size: int = 24) -> QIcon:
    """Icona cartella (chiusa/aperta) con chevron, disegnata a runtime.

    Sostituisce le emoji 📁/📂: quelle cambiano faccia da un sistema all'altro,
    non seguono il tema e stonano accanto alle altre icone, tutte a tratto.
    Qui il glifo usa l'accento del tema ed è nitido a qualsiasi scala.
    Cache per (aperta, dimensione) come per rarità e bandierine."""
    key = (open_, size, "folder")
    cached = _folder_icon_cache.get(key)
    if cached is not None:
        return cached
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    u = size / 32.0
    _draw_chevron(p, u, open_)

    # corpo della cartella: linguetta + rettangolo arrotondato
    stroke = QPen(QColor(theme.ACCENT))
    stroke.setWidthF(max(1.0, 1.8 * u))
    stroke.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    fill = QColor(theme.ACCENT)
    fill.setAlpha(34 if open_ else 66)   # aperta = più "vuota"
    p.setPen(stroke)
    p.setBrush(fill)
    r = 2.2 * u
    p.drawRoundedRect(QRectF(11 * u, 8.0 * u, 8.5 * u, 4.5 * u), r, r)   # linguetta
    p.drawRoundedRect(QRectF(11 * u, 11.0 * u, 19 * u, 13.5 * u), r, r)  # corpo
    if open_:   # bordo del coperchio sollevato
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(11 * u, 15.5 * u), QPointF(30 * u, 15.5 * u))
    p.end()
    icon = QIcon(pm)
    _folder_icon_cache[key] = icon
    return icon


class _WatchTable(QTableWidget):
    """Tabella watchlist con drag&drop di RIGHE delegato all'esterno.

    Il drop di Qt sposterebbe i singoli item (rompendo span delle cartelle e
    cell widget): qui si intercetta e si emette solo (riga_sorgente,
    riga_destinazione); la logica di spostamento e il re-render li fa il
    widget, che è l'unico a conoscere cartelle e posizioni.

    Disegna inoltre i GRUPPI-cartella: una barra verticale d'accento lungo
    tutta la cartella (intestazione + carte contenute) e una riga di chiusura
    sotto l'ultima carta. È così che si vede a colpo d'occhio dove finisce una
    cartella e dove ricominciano le carte sciolte — con i soli sfondi delle
    celle il confine restava ambiguo."""
    row_moved = Signal(int, int)   # riga trascinata, riga di destinazione (-1 = in fondo)

    def __init__(self, rows: int, cols: int, parent=None) -> None:
        super().__init__(rows, cols, parent)
        self._groups: list[tuple[int, int]] = []   # (prima riga, ultima riga)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QTableWidget.DragDropMode.InternalMove)
        self.setDropIndicatorShown(True)
        self.setDragDropOverwriteMode(False)

    def dropEvent(self, event) -> None:  # noqa: N802 (firma Qt)
        source = self.currentRow()
        target = self.indexAt(event.position().toPoint()).row()
        event.setDropAction(Qt.DropAction.IgnoreAction)  # niente move di Qt
        event.accept()
        if source >= 0:
            self.row_moved.emit(source, target)

    def set_groups(self, groups: list[tuple[int, int]]) -> None:
        self._groups = groups
        self.viewport().update()

    def paintEvent(self, event) -> None:  # noqa: N802 (firma Qt)
        super().paintEvent(event)
        if not self._groups:
            return
        painter = QPainter(self.viewport())
        width = self.viewport().width()
        bar_w = max(2, round(3 * self.fontMetrics().height() / 14))
        bar = QColor(theme.ACCENT)
        bar.setAlpha(150)
        edge = QColor(theme.ACCENT)
        edge.setAlpha(70)
        for start, end in self._groups:
            if start >= self.rowCount() or end >= self.rowCount():
                continue   # render in corso: gruppi non ancora riallineati
            top = self.rowViewportPosition(start)
            bottom = self.rowViewportPosition(end) + self.rowHeight(end)
            if bottom < 0 or top > self.viewport().height():
                continue   # gruppo fuori dalla parte visibile
            # barra verticale = "queste righe stanno insieme"
            painter.fillRect(QRect(0, top, bar_w, max(0, bottom - top)), bar)
            # riga di chiusura = "la cartella finisce qui"
            painter.fillRect(QRect(0, bottom - 1, width, 1), edge)
        painter.end()


# Codice set e rarità stanno nel CORE (`core.badges`, `core.rarity`): li usa
# anche il modulo Database, e i moduli non si importano fra loro.
_make_set_pill = badges.set_pill


_cond_pill_cache: dict[tuple[str, int], QPixmap] = {}
_lang_pill_cache: dict[tuple[str, int], QPixmap] = {}

# Posizione della condizione sulla scala 0 (perfetta) → 1 (rovinata). Sono
# elencate TUTTE le condizioni note, dell'API e del sito: un dizionario, non
# un indice calcolato, perché le due scale hanno lunghezze diverse e un
# indice/len darebbe posizioni incoerenti fra loro (una "Played" verde-ino in
# una scala e arancione nell'altra).
_CONDITION_RANK = {
    "mint": 0.0,
    "near mint": 0.12,
    "excellent": 0.30,
    "slightly played": 0.30,
    "good": 0.50,
    "moderately played": 0.55,
    "light played": 0.45,
    "played": 0.78,
    "poor": 1.0,
}


def _condition_color(name: str) -> QColor:
    """Verde per le carte perfette, rosso per quelle rovinate, passando per il
    giallo. Sconosciuta → grigio: meglio non dire niente che dire un colore
    sbagliato su una condizione che non sappiamo collocare."""
    rank = _CONDITION_RANK.get((name or "").strip().lower())
    if rank is None:
        return QColor(theme.TEXT_MUTED)
    verde, giallo, rosso = QColor(theme.POSITIVE), QColor(theme.WARN), QColor(theme.NEGATIVE)
    if rank <= 0.5:      # verde → giallo
        a, b, t = verde, giallo, rank / 0.5
    else:                # giallo → rosso
        a, b, t = giallo, rosso, (rank - 0.5) / 0.5
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


_pill = badges.pill      # forma comune di tutte le pillole (vedi core/badges.py)


def _make_condition_pill(name: str, height: int) -> QPixmap:
    """Sigla della condizione su pill colorata secondo lo stato della carta.

    Il colore è quello del testo, su un fondo dello stesso colore molto
    diluito: colorare tutto il fondo darebbe cinque macchie accese per riga,
    che in una tabella fitta stancano più di quanto informino."""
    key = (name, height)
    cached = _cond_pill_cache.get(key)
    if cached is not None:
        return cached
    ink = _condition_color(name)
    bg = QColor(ink)
    bg.setAlpha(38)
    pm = _pill(_condition_short(name) or "—", height, ink, bg)
    _cond_pill_cache[key] = pm
    return pm


def _make_language_pill(code: str, height: int) -> QPixmap:
    """Codice lingua su pill neutra: distingue a colpo d'occhio senza rubare
    attenzione al colore della condizione, che lì accanto porta un giudizio."""
    key = (code, height)
    cached = _lang_pill_cache.get(key)
    if cached is not None:
        return cached
    pm = _pill(code.upper(), height, QColor(theme.TEXT), QColor(theme.SURFACE_3))
    _lang_pill_cache[key] = pm
    return pm


def _make_pro_badge(height: int) -> QPixmap:
    """Badge 'PRO' (venditore professionale): pill teal come l'accento del tema."""
    w = round(height * 2.2)
    pm = QPixmap(w, height)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(theme.ACCENT))
    p.setPen(Qt.PenStyle.NoPen)
    radius = height / 3.0
    p.drawRoundedRect(QRectF(0, 0, w, height), radius, radius)
    font = QFont(theme.FONT_FAMILY)
    font.setBold(True)
    font.setPixelSize(max(6, round(height * 0.6)))
    p.setFont(font)
    p.setPen(QColor(theme.ACCENT_INK))
    p.drawText(QRectF(0, 0, w, height), Qt.AlignmentFlag.AlignCenter, "PRO")
    p.end()
    return pm


class MarketWatchWidget(QWidget):
    # L'avviso di aggiornamento dell'APP non sta più qui: viveva in questo
    # header, ma l'app si apre sul Database e per nove versioni di fila nessuno
    # l'ha visto. Ora è un piede sotto il menu laterale, visibile da ogni
    # pagina, e sa anche scaricare e installare (`core/update_widget.py`).

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.repo = MarketWatchRepository(context.storage)
        # igiene del DB: via i dati di carte non più seguite e lo storico
        # vecchio viene sfoltito (1 riga/giorno oltre i 90 giorni)
        self.repo.cleanup_orphans(PROVIDER)
        self.repo.prune_history()
        self._selected_ref: CardRef | None = None
        # filtri preparati per la carta selezionata ma NON ancora aggiunta
        # (None = userà i predefiniti); si azzerano a ogni cambio selezione
        self._pending_filters: ListingFilters | None = None
        self._label_to_ref: dict[str, CardRef] = {}
        self._search_index: list[tuple[str, str]] = []  # (label_minuscolo, label)
        self._completer_items: list[tuple] = []         # voci per il ThumbDelegate
        # ref senza annuncio conforme ai filtri: persistito, così "Nessuna copia"
        # sopravvive al riavvio (altrimenti tornerebbe a mostrare il vecchio prezzo).
        self._no_match_refs: set[str] = self._load_no_match()
        # miniature per le righe della watchlist (download async + cache)
        self._row_thumb_cache: dict[str, QPixmap] = {}
        self._row_thumb_inflight: set[str] = set()
        self._url_ref: dict[str, str] = {}   # thumb_url -> ref_id (per aggiornare la riga giusta)
        self._url_name: dict[str, str] = {}  # thumb_url -> nome carta (per il segnaposto)
        # immagini che non si riescono a scaricare: ricordate per NON ritentare
        # a ogni render (Cloudflare risponde 403 alle raffiche)
        self._failed_thumbs: set[str] = set()
        self._failed_images: set[str] = set()
        # nome -> immagine di un'altra stampa della stessa carta (ripiego
        # "stock" per le stampe senza immagine); popolato da _rebuild_completer
        self._stock_images: dict[str, str] = {}
        self._current_img_name: str = ""
        # carte (ref_id) di cui è aperto l'elenco "da dove arrivano le copie"
        self._open_sources: set[str] = set()
        self._current_img_exact: str = ""    # URL chiesto (prima dei ripieghi)
        self._current_img_is_stock: bool = False
        self._row_thumb_pool = QThreadPool(self)
        self._row_thumb_pool.setMaxThreadCount(6)
        self._row_thumb_signals = _ThumbSignals(self)
        self._row_thumb_signals.done.connect(self._on_row_thumb)
        self._price_worker: PriceFetchWorker | None = None
        self._sync_worker: CatalogSyncWorker | None = None
        self._img_worker: ImageFetchWorker | None = None
        # finestra dello storico aperta: le si passa l'immagine grande quando
        # arriva, senza chiederne una seconda copia
        self._history_dlg = None
        self._img_cache: dict[str, QPixmap] = {}
        self._current_img_url: str = ""
        self._filters = ListingFilters.from_dict(self._load_filters())
        self._folders_by_id: dict = {}
        self._adopt_deck_flags()     # basi create prima della colonna is_deck
        self._refresh_folder_cache()
        self._adopt_history_keys()   # storico dei DB vecchi: vedi il metodo
        self._load_sort()            # criterio di ordinamento ricordato
        self._load_rate_interval()   # spaziatura anti-429 imparata in passato
        # Scorrimento animato della rotellina: UN SOLO oggetto persistente,
        # riavviato a ogni scatto. Ricrearlo ogni volta con DeleteWhenStopped
        # lasciava un wrapper Python su un C++ già distrutto → RuntimeError al
        # primo scatto DOPO la fine dell'animazione precedente (vedi GOTCHA 11).
        self._scroll_target = 0
        self._scroll_anim = QVariantAnimation(self)
        self._scroll_anim.setDuration(150)
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._scroll_anim.valueChanged.connect(self._on_scroll_anim)
        # preferenze di visualizzazione della watchlist (rarità icona/nome,
        # set codice/nome, animazioni on/off) — dialogo Opzioni
        self._display = self._load_display()
        anim.set_enabled(bool(self._display.get("animations", True)))
        self._trash_icon = _make_trash_icon()
        self._settings_icon = _make_settings_icon()
        # variante teal: segnala a colpo d'occhio le carte con filtri PROPRI,
        # fra tutte le icone grigie della colonna Azioni
        self._settings_icon_custom = _make_settings_icon(theme.ACCENT)
        self._link_icon = _make_link_icon()
        self._pencil_icon = _make_pencil_icon()
        # ref_id -> PriceQuote dell'ultimo controllo: persistito in mw_last_quote
        # e ricaricato qui, così la Panoramica è piena anche appena riavviata.
        self._last_quotes: dict[str, PriceQuote] = self._load_last_quotes()
        self._overview = False
        self._last_checked = self.repo.get_setting("last_checked") or "—"
        # modello visuale della tabella: ("folder", riga cartella) e
        # ("watch", riga carta) nell'ordine in cui compaiono
        self._row_entries: list[tuple[str, object]] = []
        # Scala UI (larghezza finestra / riferimento): la imposta la finestra
        # principale via apply_scale(); qui parte a 1.0 (dimensioni base).
        self._scale = 1.0
        # Densità della Panoramica: 1.0 a schermo intero; sotto, l'intera vista
        # (font, righe, miniature, badge) si rimpicciolisce per restare usabile.
        self._density = 1.0

        self.client: CardTraderClient | None = None
        self.provider: CardTraderProvider | None = None

        self._build_ui()
        self._build_provider()
        self._refresh_header_state()
        self._reload_table()
        # Il completer indicizza tutto il catalogo (~0.5s su 47k voci): lo
        # costruiamo subito DOPO che la finestra è comparsa, così l'avvio è
        # istantaneo e la ricerca diventa pronta un attimo dopo.
        QTimer.singleShot(0, self._rebuild_completer)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_now)
        self._apply_interval()
        # Ricontrollo automatico all'apertura: i dati ricaricati dal DB possono
        # essere vecchi di ore/giorni, così si vede subito la variazione reale
        # del mercato (oltre al timer periodico impostato dall'utente).
        QTimer.singleShot(2500, self._startup_check)
        # Benvenuto al primo avvio (solo utenti non ancora configurati).
        QTimer.singleShot(600, self._maybe_welcome)

    # ------------------------------------------------------------------ setup
    def _build_provider(self) -> None:
        token = config.load_token(self.context.data_dir)
        if token:
            self.client = CardTraderClient(token)
            self.provider = CardTraderProvider(self.client, self.repo, self._filters)
        else:
            self.client = None
            self.provider = None

    # --- spaziatura fra le chiamate API (anti-429) ---
    # Il limitatore si tara da solo durante l'uso, ma vive in memoria: senza
    # ricordarla, ogni avvio ripartirebbe troppo veloce e si riprenderebbe gli
    # stessi 429 prima di ricalibrarsi. Qui la si porta avanti fra le sessioni.
    def _load_rate_interval(self) -> None:
        try:
            saved = float(self.repo.get_setting("api_interval", "") or 0)
        except (TypeError, ValueError):
            return
        if saved > 0:
            cardtrader.LIMITER.adopt(saved)

    def _save_rate_interval(self) -> None:
        self.repo.set_setting("api_interval", f"{cardtrader.LIMITER.interval:.3f}")

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(16)

        # --- header: titolo + stato (chip) + azioni di setup ---
        header = QHBoxLayout()
        header.setSpacing(10)
        titlebox = QVBoxLayout()
        titlebox.setSpacing(1)
        title = QLabel("Market Watch")
        title.setObjectName("title")
        subtitle = QLabel(tr("Prezzo più basso su CardTrader"))
        subtitle.setObjectName("subtitle")
        titlebox.addWidget(title)
        titlebox.addWidget(subtitle)
        header.addLayout(titlebox)
        header.addStretch(1)
        self.token_label = QLabel()
        self.token_label.setObjectName("chip")
        self.catalog_label = QLabel()
        self.catalog_label.setObjectName("chip")
        # Azioni "ovvie" come pulsanti-ICONA quadrati (tooltip al posto del
        # testo): header più pulito. Le icone sono disegnate a runtime.
        self.token_btn = QPushButton()
        self.token_btn.setIcon(_make_key_icon())
        self.token_btn.setToolTip(tr("Token CardTrader (imposta/cambia)"))
        self.token_btn.clicked.connect(self.set_token)
        self.sync_btn = QPushButton()
        self.sync_btn.setIcon(_make_sync_icon())
        self.sync_btn.setToolTip(tr("Sincronizza il catalogo Yu-Gi-Oh! (~4-5 minuti, una tantum)"))
        self.sync_btn.clicked.connect(self.sync_catalog)
        # Filtri PREDEFINITI (imbuto): quelli che una carta si porta dietro
        # quando la aggiungi senza toccare niente. Stanno nell'header, con le
        # altre impostazioni valide per tutta l'app.
        self.defaults_btn = QPushButton()
        self.defaults_btn.setIcon(_make_filter_icon())
        self.defaults_btn.setToolTip(tr(
            "Filtri predefiniti: si applicano alle carte che aggiungi senza "
            "impostarne di propri"))
        self.defaults_btn.clicked.connect(self.open_default_filters)
        self.options_btn = QPushButton()
        self.options_btn.setIcon(_make_gear_icon())   # sliders = filtri di UNA carta
        self.options_btn.setToolTip(tr("Opzioni di visualizzazione della watchlist"))
        self.options_btn.clicked.connect(self.open_options)
        self.overview_btn = QPushButton()
        self.overview_btn.setIcon(_make_grid_icon())
        self.overview_btn.setCheckable(True)
        self.overview_btn.setToolTip(tr("Panoramica: nasconde la ricerca e allarga la watchlist"))
        self.overview_btn.toggled.connect(self._toggle_overview)
        self._header_buttons = (self.token_btn, self.sync_btn,
                                self.defaults_btn, self.options_btn, self.overview_btn)
        header.addWidget(self.token_label)
        header.addWidget(self.catalog_label)
        header.addWidget(self.token_btn)
        header.addWidget(self.sync_btn)
        header.addWidget(self.defaults_btn)
        header.addWidget(self.options_btn)
        header.addWidget(self.overview_btn)
        root.addLayout(header)

        # --- pannello "aggiungi carta" (controlli a sinistra, anteprima a destra) ---
        panel = QFrame()
        panel.setObjectName("card")
        self._panel = panel  # pannello ricerca (nascosto in modalità Panoramica)
        panel_h = QHBoxLayout(panel)
        panel_h.setContentsMargins(16, 16, 16, 16)
        panel_h.setSpacing(16)
        pv = QVBoxLayout()
        pv.setSpacing(11)

        # Ricerca LIVE: i risultati compaiono in un menù a tendina man mano che
        # si digita (QCompleter sul catalogo locale), senza premere "Cerca".
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr("🔍  Scrivi il nome della carta (in inglese)…"))
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(34)
        self.search_input.textEdited.connect(self._on_search_text)
        # Barra di ricerca + pulsante filtri DELLA CARTA SELEZIONATA: si usa
        # fra "scelgo la carta" e "Aggiungi", per darle filtri suoi già in
        # partenza. Icona a sliders, la stessa dei filtri per riga in
        # watchlist: è lo stesso mestiere, su una carta sola. L'imbuto
        # nell'header è invece per i filtri PREDEFINITI.
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_row.addWidget(self.search_input, 1)
        self.filters_btn = QPushButton()
        self.filters_btn.setIcon(_make_settings_icon())
        self.filters_btn.setCheckable(True)   # acceso = questa carta ha filtri suoi
        self.filters_btn.clicked.connect(self.open_card_filters)
        search_row.addWidget(self.filters_btn)
        # Il pulsante delle BASI sta qui, accanto alla ricerca: comporre una
        # base è un gesto di ricerca, non un'impostazione dell'app.
        self.deck_btn = QPushButton()
        self.deck_btn.setIcon(_make_deck_icon())
        self.deck_btn.setToolTip(tr("Nuova base: un mazzo di carte in più copie, con filtri comuni"))
        self.deck_btn.clicked.connect(lambda: self.open_deck())
        search_row.addWidget(self.deck_btn)
        # Pulsante a PAROLE, non un'icona: importare un mazzo è un gesto che si
        # cerca leggendo, e nascosto dentro un menù non lo trovava nessuno.
        self.import_btn = QPushButton(tr("Import"))
        self.import_btn.setToolTip(tr("Importa un mazzo da file .ydk"))
        self.import_btn.clicked.connect(self.import_ydk)
        search_row.addWidget(self.import_btn)
        self._update_card_filters_btn()
        pv.addLayout(search_row)

        # La ricerca "a token" la facciamo NOI (vedi _apply_search_filter) e
        # passiamo al completer solo i primi N risultati: così il popup resta
        # piccolo e istantaneo (niente più freeze su query larghe). Il completer
        # è in modalità Unfiltered: mostra esattamente il modello che gli diamo.
        self._completer_model = QStringListModel(self)  # contiene solo i match correnti
        # Debounce: la ricerca scatta dopo una breve pausa nella digitazione.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(90)
        self._search_timer.timeout.connect(lambda: self._apply_search_filter(self._pending_query))
        self._pending_query = ""
        self._completer = QCompleter(self._completer_model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._completer.setMaxVisibleItems(6)
        popup = self._completer.popup()
        popup.setObjectName("searchPopup")
        # Testo del popup un po' più grande del resto (righe più leggibili).
        # Il font di base viene salvato e riscalato in _apply_responsive_sizing.
        self._search_popup = popup
        self._popup_base_font = QFont(popup.font())
        # Le miniature le disegna un delegate (solo righe visibili), così il
        # filtraggio resta in C++ e non rallenta la digitazione.
        popup.setUniformItemSizes(True)
        popup.setMouseTracking(True)              # per l'evidenziazione all'hover
        popup.viewport().setMouseTracking(True)
        self._thumb_delegate = ThumbDelegate(self)
        self._thumb_delegate.set_view(popup)
        popup.setItemDelegate(self._thumb_delegate)
        self._completer.activated[str].connect(self._on_pick)
        self.search_input.setCompleter(self._completer)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.selected_label = QLabel(tr("Nessuna carta selezionata"))
        self.selected_label.setObjectName("subtitle")
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.0, 100.0)
        self.threshold_spin.setSingleStep(0.5)
        self.threshold_spin.setValue(0.0)
        self.threshold_spin.setSuffix(" %")
        self.threshold_spin.setToolTip(tr("Avvisa quando il prezzo cala almeno di questa percentuale (0 = qualsiasi calo)"))
        self.add_btn = QPushButton(tr("Aggiungi alla watchlist"))
        self.add_btn.setObjectName("primary")
        self.add_btn.clicked.connect(self.add_by_name)
        self.add_btn.setEnabled(False)
        action_row.addWidget(self.selected_label, 1)
        action_row.addWidget(QLabel(tr("Avvisa al calo di")))
        action_row.addWidget(self.threshold_spin)
        action_row.addWidget(self.add_btn)
        pv.addLayout(action_row)

        # Blocco controlli centrato verticalmente rispetto all'anteprima,
        # così gli spazi sopra/sotto sono simmetrici e niente vuoti sbilanciati.
        left = QVBoxLayout()
        left.addStretch(1)
        left.addLayout(pv)
        left.addStretch(1)
        panel_h.addLayout(left, 1)

        # riquadro anteprima immagine
        self.preview = QLabel(tr("Nessuna\nanteprima"))
        self.preview.setObjectName("preview")
        self.preview.setFixedSize(156, 218)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setWordWrap(True)
        panel_h.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignVCenter)

        root.addWidget(panel)

        # --- tabella ---
        # Colonne modulari: 0 Immagine, 1 Nome, 2 Rarità, 3 Set, 4 Condizione,
        # 5 Lingua, 6 1ª ed., 7 Zero, 8 Prezzo, 9 Var., 10 Soglia, 11 Controllo,
        # 12 Venditore, 13 Commenti, 14 Q.tà, 15 Azioni. Quali sono visibili
        # dipende dalla modalità (dettagli annuncio solo in Panoramica,
        # Soglia/Controllo solo in vista normale).
        self.table = _WatchTable(0, 16)
        self.table.setHorizontalHeaderLabels(
            [tr(h) if h else "" for h in
             ["", "Nome", "Rarità", "Set", "Condizione", "Lingua", "1ª ed.",
              "Zero", "Prezzo", "Var.", "Soglia", "Controllo", "Venditore",
              "Commenti", "Q.tà", ""]]
        )
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(ROW_H_NORMAL)
        self.table.setIconSize(ROW_ICON_NORMAL)
        self.table.setWordWrap(True)          # commenti su più righe in Panoramica
        # rientro delle carte in cartella: solo sulla colonna Nome
        self._name_delegate = _IndentDelegate(
            self._row_indent, lambda: self._rp(13), self._row_has_own_filters, self.table)
        self.table.setItemDelegateForColumn(1, self._name_delegate)
        self._table_base_font = self.table.font()
        self.table.setShowGrid(False)
        # righe alternate: differenzia le voci a colpo d'occhio (i colori
        # stanno nel QSS: background / alternate-background-color)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # scorrimento fluido per pixel (di default QTableWidget salta di riga
        # in riga: con righe alte 150px lo scroll risulta a scatti)
        self.table.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.table.verticalScrollBar().setSingleStep(24)
        self.table.itemSelectionChanged.connect(self._on_table_selection)
        # cartelle: clic per aprire/chiudere, drag&drop per spostare/riordinare,
        # tasto destro per creare/rinominare/eliminare
        self.table.cellClicked.connect(self._on_cell_clicked)
        # doppio clic su una carta = storico prezzi (la tabella non è
        # editabile, quindi il gesto era libero e non ruba niente al clic
        # singolo, che apre/chiude cartelle e provenienze)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.row_moved.connect(self._on_row_moved)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        # Il fit delle colonne dipende dalla larghezza REALE del viewport della
        # tabella: ci agganciamo al suo evento di resize (lì la geometria è
        # definitiva), non a quello del widget (dove i figli sono ancora stantii).
        self.table.viewport().installEventFilter(self)
        self._apply_column_layout(overview=False)
        root.addLayout(self._build_sort_row())
        root.addWidget(self.table, 1)

        # --- footer: controlli ---
        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.check_btn = QPushButton(tr("Controlla ora"))
        self.check_btn.setObjectName("primary")
        self.check_btn.clicked.connect(self.check_now)
        footer.addWidget(self.check_btn)
        footer.addSpacing(6)
        footer.addWidget(QLabel(tr("Auto ogni")))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1440)
        self.interval_spin.setValue(30)
        self.interval_spin.setSuffix(tr(" min"))
        self.interval_spin.valueChanged.connect(self._apply_interval)
        footer.addWidget(self.interval_spin)
        footer.addStretch(1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminata (animata)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(150)
        self.progress.setVisible(False)
        footer.addWidget(self.progress)
        self.status = QLabel(tr("Pronto."))
        self.status.setObjectName("status")
        footer.addWidget(self.status)
        root.addLayout(footer)

        # Ombre morbide (card "sollevate") + hover animato — ma NON sulla
        # tabella: un QGraphicsEffect ri-sfoca l'intero widget a OGNI frame di
        # scroll/animazione (~6 ms/frame misurati = fps dimezzati). La tabella
        # è delineata da bordo + righe alternate, l'ombra non le serve.
        anim.hover_lift(panel, base_blur=30, hover_blur=46, dy=8, alpha=110)
        anim.hover_lift(self.preview, base_blur=20, hover_blur=32, dy=5, alpha=120)
        # Glow teal al passaggio del mouse sui bottoni interattivi.
        for btn in (self.token_btn, self.sync_btn, self.deck_btn, self.defaults_btn,
                    self.options_btn, self.overview_btn, self.filters_btn,
                    self.check_btn, self.add_btn):
            anim.hover_glow(btn)

        # Dimensioni iniziali coerenti con la scala corrente (1.0 all'avvio).
        self._apply_responsive_sizing()

    # ------------------------------------------------------- dimensionamento
    def apply_scale(self, scale: float) -> None:
        """Imposta la scala UI (chiamata dalla finestra al variare della
        larghezza) e riadatta gli elementi in pixel del modulo."""
        if abs(scale - self._scale) < 1e-6:
            return
        self._scale = scale
        self._apply_responsive_sizing()

    def eventFilter(self, obj, event):  # noqa: N802 (firma Qt)
        if obj is self.table.viewport():
            # Ricalcola il fit delle colonne quando il viewport cambia
            # dimensione: l'evento arriva DOPO l'aggiornamento della geometria,
            # quindi la larghezza letta è sempre quella definitiva.
            if event.type() == QEvent.Type.Resize and self._overview:
                self._apply_column_layout(True)
            elif event.type() == QEvent.Type.Wheel:
                if self._smooth_wheel(event):
                    return True
        return super().eventFilter(obj, event)

    def _smooth_wheel(self, event) -> bool:
        """Rotellina con scorrimento ANIMATO (easing) invece del salto secco:
        è ciò che dà la sensazione di fluidità sui monitor ad alto refresh.
        I touchpad di precisione (pixelDelta) restano al nativo, già fluido."""
        if not anim.is_enabled():
            return False   # animazioni off: scroll nativo
        if event.angleDelta().x() or not event.angleDelta().y():
            return False
        if not event.pixelDelta().isNull():
            return False
        if event.modifiers() & (Qt.KeyboardModifier.ShiftModifier
                                | Qt.KeyboardModifier.ControlModifier):
            return False
        sb = self.table.verticalScrollBar()
        if sb.maximum() <= 0:
            return False
        running = self._scroll_anim.state() == QAbstractAnimation.State.Running
        base = self._scroll_target if running else sb.value()
        # ~108 px per scatto di rotellina; gli scatti rapidi si accumulano
        self._scroll_target = max(0, min(sb.maximum(),
                                         base - round(event.angleDelta().y() * 0.9)))
        self._scroll_anim.stop()
        self._scroll_anim.setStartValue(float(sb.value()))
        self._scroll_anim.setEndValue(float(self._scroll_target))
        self._scroll_anim.start()
        return True

    def _on_scroll_anim(self, value) -> None:
        self.table.verticalScrollBar().setValue(round(float(value)))

    def _sp(self, base: float) -> int:
        """Scala un valore in pixel con la scala UI corrente."""
        return max(1, round(base * self._scale))

    def _rp(self, base: float) -> int:
        """Come _sp ma per gli elementi DENTRO le righe della tabella:
        in Panoramica applica anche la densità (si rimpiccioliscono insieme
        alla vista quando la finestra non è a schermo intero)."""
        d = self._density if self._overview else 1.0
        return max(1, round(base * self._scale * d))

    def _sz(self, base: QSize) -> QSize:
        """Scala una QSize con la scala UI corrente."""
        return QSize(self._sp(base.width()), self._sp(base.height()))

    def _scaled_font(self, base: QFont, extra: float = 0.0) -> QFont:
        """Copia `base` con dimensione (+extra) riscalata dalla scala UI."""
        font = QFont(base)
        pt = base.pointSizeF()
        if pt > 0:
            font.setPointSizeF((pt + extra) * self._scale)
        else:
            px = base.pixelSize()
            if px > 0:
                font.setPixelSize(max(1, round((px + extra) * self._scale)))
        return font

    def _apply_overview_visuals(self) -> None:
        """Font, altezza righe e miniature della Panoramica alla densità
        corrente (scala UI × densità: sotto lo schermo intero tutto si
        rimpicciolisce, così la vista resta usabile anche in finestra)."""
        d = self._density
        self.table.setIconSize(QSize(round(ROW_ICON_BIG.width() * self._scale * d),
                                     round(ROW_ICON_BIG.height() * self._scale * d)))
        self.table.verticalHeader().setDefaultSectionSize(
            max(1, round(ROW_H_BIG * self._scale * d)))
        font = QFont(self._table_base_font)
        pt = font.pointSizeF()
        if pt > 0:
            font.setPointSizeF((pt + 2) * self._scale * d)
        self.table.setFont(font)

    def _apply_responsive_sizing(self) -> None:
        """Adatta gli elementi in pixel del modulo alla scala UI corrente
        (anteprima, campo ricerca, miniature/altezza righe/font della tabella,
        popup). Gli elementi stilizzati via QSS li scala il tema."""
        big = self._overview
        self.preview.setFixedSize(self._sp(156), self._sp(218))
        self.search_input.setMinimumHeight(self._sp(34))
        for btn in (*self._header_buttons, self.filters_btn, self.deck_btn):  # icone quadrate
            btn.setFixedSize(self._sp(38), self._sp(38))
            btn.setIconSize(QSize(self._sp(20), self._sp(20)))
        # l'Import ha del testo dentro: gli si impone l'altezza, non il lato
        self.import_btn.setFixedHeight(self._sp(38))
        if big:
            self._apply_overview_visuals()   # include la densità
        else:
            self._density = 1.0
            self.table.setIconSize(self._sz(ROW_ICON_NORMAL))
            self.table.verticalHeader().setDefaultSectionSize(self._sp(ROW_H_NORMAL))
            self.table.setFont(self._scaled_font(self._table_base_font))
        self._search_popup.setFont(self._scaled_font(self._popup_base_font, extra=3))
        self._apply_column_layout(big)
        self._render_after_check(self._last_checked, pulse=False)

    # ------------------------------------------------------------ ordinamento
    # (modo, etichetta, tooltip). "manual" = l'ordine deciso col drag&drop.
    _SORT_MODES = (
        ("manual", "Manuale", "Ordine deciso da te trascinando le righe"),
        ("rarity", "Rarità", "Dalla rarità più ricercata alla più comune"),
        ("price", "Prezzo", "Dal più caro al più economico"),
        ("change", "Var.", "Dal rialzo maggiore al calo maggiore"),
    )

    def _build_sort_row(self):
        """Pulsantini di ordinamento sopra la tabella.

        Non sono le intestazioni cliccabili perché l'ordinamento qui NON è
        globale: le cartelle e le basi restano gruppi, si ordina DENTRO ciascuna
        (e fra le carte sciolte). Cliccare l'intestazione suggerirebbe un
        riordino di tutta la tabella, che scioglierebbe i gruppi."""
        row = QHBoxLayout()
        row.setSpacing(6)
        label = QLabel(tr("Ordina per"))
        label.setObjectName("subtitle")
        row.addWidget(label)
        self._sort_buttons: dict[str, QPushButton] = {}
        for mode, testo, tip in self._SORT_MODES:
            btn = QPushButton(tr(testo))
            btn.setObjectName("ghost")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tr(tip) + "\n" + tr("Clic sul criterio attivo = inverte il verso"))
            btn.clicked.connect(lambda _=False, m=mode: self._set_sort(m))
            self._sort_buttons[mode] = btn
            row.addWidget(btn)
        row.addStretch(1)
        self._refresh_sort_buttons()
        return row

    def _set_sort(self, mode: str) -> None:
        """Clic su un criterio: se è già attivo inverte il verso, altrimenti
        passa a quel criterio."""
        if mode == self._sort_mode and mode != "manual":
            self._sort_desc = not self._sort_desc
        else:
            self._sort_mode, self._sort_desc = mode, True
        self.repo.set_setting("sort", f"{self._sort_mode}:{'desc' if self._sort_desc else 'asc'}")
        self._refresh_sort_buttons()
        self._reload_table()

    def _refresh_sort_buttons(self) -> None:
        freccia = "▾" if self._sort_desc else "▴"
        for mode, testo, _tip in self._SORT_MODES:
            btn = self._sort_buttons[mode]
            attivo = mode == self._sort_mode
            btn.setChecked(attivo)
            btn.setText(tr(testo) + (f"  {freccia}" if attivo and mode != "manual" else ""))
            # il :checked dei pulsanti "ghost" è troppo timido per dire quale
            # criterio è in uso: il teal lo rende inequivocabile
            btn.setStyleSheet(f"color: {theme.ACCENT}; font-weight: 700;" if attivo else "")

    def _load_sort(self) -> None:
        raw = (self.repo.get_setting("sort", "") or "").split(":")
        modi = {m for m, _t, _p in self._SORT_MODES}
        self._sort_mode = raw[0] if raw and raw[0] in modi else "manual"
        self._sort_desc = len(raw) < 2 or raw[1] != "asc"

    def _sorted_cards(self, cards: list, metrics: dict) -> list:
        """Le carte di un gruppo nell'ordine scelto. `metrics` ha già prezzo e
        variazione calcolati una volta sola (evita di riconsultare il DB)."""
        if self._sort_mode == "manual":
            return cards
        # Chi non ha il dato (prezzo mai visto, Var. non calcolabile) va SEMPRE
        # in fondo, in entrambi i versi: farlo galleggiare in cima invertendo
        # l'ordine darebbe una lista che sembra ordinata per errore.
        def chiave(w):
            ref = str(w["ref_id"])
            if self._sort_mode == "rarity":
                detail = w["detail"] or ""
                rar = detail.split(" · ", 1)[0] if " · " in detail else ""
                valore = rarity_rank(rar)
                return (valore < 0, -valore if self._sort_desc else valore)
            prezzo, variazione = metrics.get(ref, (None, None))
            valore = prezzo if self._sort_mode == "price" else variazione
            if valore is None:
                return (True, 0.0)
            return (False, -valore if self._sort_desc else valore)
        return sorted(cards, key=chiave)

    def _apply_column_layout(self, overview: bool) -> None:
        """Colonne e ridimensionamento per modalità.
        Panoramica: mostra i dettagli dell'annuncio (Condizione/Lingua/1ª ed./
        Zero/Venditore/Commenti/Q.tà), nasconde Soglia/Controllo, carta a
        larghezza fissa (per la miniatura) e Commenti che riempie."""
        hh = self.table.horizontalHeader()
        RM = QHeaderView.ResizeMode
        for c in (4, 5, 6, 7, 12, 13, 14):  # dettagli annuncio → solo Panoramica
            self.table.setColumnHidden(c, not overview)
        for c in (10, 11):                  # Soglia, Controllo → solo vista normale
            self.table.setColumnHidden(c, overview)
        hh.setSectionResizeMode(0, RM.Fixed)   # colonna immagine
        if overview:
            # Larghezze fisse (contenuto troncato/a capo) + Commenti elastica.
            # Le colonne seguono la scala UI ma SENZA superare lo spazio
            # disponibile: se la somma non ci sta, si riducono per lasciare a
            # Commenti un minimo → mai scroll orizzontale a schermo intero.
            hh.setSectionResizeMode(13, RM.Stretch)   # Commenti riempie lo spazio
            img_w = 116
            # Prezzo (8) e Var. (9) larghe abbastanza da non mandare a capo
            # "123.45 €" / "+10.0%": lo spazio in più lo cede Commenti (Stretch).
            # Rarità/Set più strette quando mostrano badge/codice (Opzioni).
            widths = {1: 150,
                      2: 84 if self._display.get("rarity_icons") else 160,
                      3: 90 if self._display.get("set_codes") else 140,
                      # Condizione ora è una sigla (NM, LP…): non serve più lo
                      # spazio per "Moderately Played", va a Commenti (Stretch)
                      4: 70, 5: 62, 6: 56, 7: 56,
                      8: 118, 9: 96, 12: 150, 14: 50, 15: 60}
            base_total = img_w + sum(widths.values())
            avail = self.table.viewport().width()
            # Riserva per Commenti (Stretch): proporzionale allo spazio, così a
            # schermo intero resta generosa (~13%) senza strozzare le finestre.
            comments_min = max(self._sp(84), round(avail * 0.13)) if avail >= 300 else self._sp(84)
            # DENSITÀ: sotto lo schermo intero non si stringono solo le colonne,
            # si rimpicciolisce l'INTERA vista (font, righe, miniature, badge).
            # Riferimento = rapporto spazio/colonne che si ha a schermo intero
            # (~0.8×scala): lì densità 1.0 (nessun cambiamento), in finestra
            # scende a scatti di 0.05, mai sotto 0.65 (leggibilità).
            FULLSCREEN_RATIO = 0.8
            if avail >= 300:
                fit = (avail - comments_min) / base_total
                raw = fit / (self._scale * FULLSCREEN_RATIO)
                density = max(0.65, min(1.0, round(raw / 0.05) * 0.05))
            else:
                fit = self._scale
                density = self._density
            if abs(density - self._density) > 1e-6:
                self._density = density
                self._apply_overview_visuals()
                # righe ricreate: badge, icone e spaziature alla nuova densità
                self._render_after_check(self._last_checked, pulse=False)
            col_scale = max(0.55, min(self._scale * self._density, fit))
            icon = self.table.iconSize()
            img_scaled = max(icon.width() + self._sp(8), round(img_w * col_scale))
            # Minimi per colonna: testo dell'intestazione (grassetto come da QSS)
            # e, per Prezzo/Var., anche il contenuto tipico ("123.45 €" intero).
            header_font = QFont(hh.font())
            header_font.setBold(True)
            fm = QFontMetrics(header_font)
            fm_cell = QFontMetrics(self.table.font())
            pad = self._sp(14)
            cell_pad = self._sp(20)       # padding orizzontale delle celle (QSS)
            # Primo giro con le etichette complete; se nemmeno comprimendo i
            # margini ci stanno, secondo giro con le ABBREVIATE (Cond., Vend.,
            # … — nome completo nel tooltip): finestra piccola ma tutto visibile.
            sizes: dict[int, int] = {}
            for use_short in (False, True):
                self._apply_header_labels(short=use_short)
                need = {c: fm.horizontalAdvance(self.table.horizontalHeaderItem(c).text()) + pad
                        for c in widths}
                need[8] = max(need[8], fm_cell.horizontalAdvance("888.88 €") + cell_pad)
                need[9] = max(need[9], fm_cell.horizontalAdvance("+88.8%") + cell_pad)
                sizes = {c: max(need[c], round(w * col_scale)) for c, w in widths.items()}
                if avail < 300:
                    break
                overflow = img_scaled + sum(sizes.values()) + comments_min - avail
                if overflow <= 0:
                    break
                slack = {c: sizes[c] - need[c] for c in sizes if sizes[c] > need[c]}
                total_slack = sum(slack.values())
                if total_slack > 0:
                    k = min(1.0, overflow / total_slack)
                    for c, s_ in slack.items():
                        sizes[c] -= round(s_ * k)
                if overflow <= total_slack:
                    break   # rientrato comprimendo i margini: etichette come sono
                # ancora troppo largo → si riprova col giro delle abbreviazioni
            self.table.setColumnWidth(0, img_scaled)
            for c, w in sizes.items():
                hh.setSectionResizeMode(c, RM.Interactive)
                self.table.setColumnWidth(c, w)
        else:
            self._apply_header_labels(short=False)
            self.table.setColumnWidth(0, self._sp(60))
            hh.setSectionResizeMode(1, RM.Stretch)    # Nome riempie
            for c in (2, 3, 8, 9, 10, 11, 15):
                hh.setSectionResizeMode(c, RM.ResizeToContents)
            # ResizeToContents ignora i cell widget (badge/pill): larghezza fissa
            if self._display.get("rarity_icons"):
                hh.setSectionResizeMode(2, RM.Fixed)
                self.table.setColumnWidth(2, self._sp(78))
            if self._display.get("set_codes"):
                hh.setSectionResizeMode(3, RM.Fixed)
                self.table.setColumnWidth(3, self._sp(84))

    # etichette header con variante abbreviata (per le finestre strette)
    _HDR_FULL = {4: "Condizione", 5: "Lingua", 12: "Venditore", 13: "Commenti"}
    _HDR_SHORT = {4: "Cond.", 5: "Ling.", 12: "Vend.", 13: "Comm."}

    def _apply_header_labels(self, short: bool) -> None:
        """Etichette complete o abbreviate (tooltip = nome completo)."""
        for c, full in self._HDR_FULL.items():
            item = self.table.horizontalHeaderItem(c)
            if item is None:
                continue
            item.setText(tr(self._HDR_SHORT[c]) if short else tr(full))
            item.setToolTip(tr(full) if short else "")

    def _toggle_overview(self, on: bool) -> None:
        """Modalità Panoramica: nasconde la ricerca (con animazione a fisarmonica)
        e ingrandisce le voci (miniatura, altezza riga e testo)."""
        self._overview = on
        # icona scura sul fondo teal quando attivo (contrasto), tooltip coerente
        self.overview_btn.setIcon(_make_grid_icon(theme.ACCENT_INK if on else "#94a1b2"))
        self.overview_btn.setToolTip(tr("Torna alla ricerca") if on
                                     else tr("Panoramica: nasconde la ricerca e allarga la watchlist"))
        # icona/altezza riga/font/colonne + ridisegno righe, alla scala corrente
        self._apply_responsive_sizing()
        prev = getattr(self, "_panel_anim", None)
        if prev is not None:
            try:
                prev.stop()  # può essere già stato auto-eliminato (DeleteWhenStopped)
            except RuntimeError:
                pass
        self._panel_anim = anim.animate_collapse(self._panel, collapse=on)

    def _refresh_header_state(self) -> None:
        has_token = self.provider is not None
        self._set_chip(self.token_label,
                       tr("● Token attivo") if has_token else tr("○ Token mancante"),
                       "ok" if has_token else "warn")
        count = self.repo.catalog_count(PROVIDER)
        self._set_chip(self.catalog_label,
                       tr("Catalogo · {n} carte").format(n=count) if count else tr("Catalogo vuoto"),
                       "ok" if count else "warn")
        for w in (self.sync_btn, self.check_btn):
            w.setEnabled(has_token)
        # la ricerca lavora sul catalogo locale: non serve il token, solo il catalogo
        self.search_input.setEnabled(count > 0)
        self.search_input.setPlaceholderText(
            tr("🔍  Scrivi il nome della carta (in inglese)…") if count
            else tr("Sincronizza prima il catalogo per cercare le carte")
        )

    # --- lavori lunghi in corso ---
    def busy_reason(self) -> str:
        """Una frase se c'è un lavoro che non va interrotto a cuor leggero,
        altrimenti "".

        La chiede il piede dell'aggiornamento prima di chiudere l'app: una
        sincronizzazione del catalogo sono 4-5 minuti, ed è l'unico momento in
        cui l'utente può perdere lavoro vero. Convenzione a papera, come
        `apply_scale`: nessun protocollo, chi non ha niente da dire non
        implementa il metodo."""
        if self._sync_worker is not None and self._sync_worker.isRunning():
            return tr("la sincronizzazione del catalogo")
        if self._price_worker is not None and self._price_worker.isRunning():
            return tr("il controllo dei prezzi")
        return ""

    @staticmethod
    def _set_chip(label: QLabel, text: str, state: str) -> None:
        label.setText(text)
        label.setProperty("state", state)
        label.style().unpolish(label)
        label.style().polish(label)

    # ------------------------------------------------------------- opzioni/filtri
    def _load_filters(self) -> dict:
        try:
            return json.loads(self.repo.get_setting("filters") or "{}")
        except (ValueError, TypeError):
            return {}

    def _load_display(self) -> dict:
        try:
            return json.loads(self.repo.get_setting("display") or "{}")
        except (ValueError, TypeError):
            return {}

    def _load_no_match(self) -> set:
        """Ref senza annuncio conforme: righe di mw_last_quote con quote vuota.

        Migra anche il vecchio formato (lista JSON in mw_settings.no_match),
        poi elimina la chiave: un'unica fonte di verità."""
        refs = {str(r["ref_id"]) for r in self.repo.load_last_quotes(PROVIDER)
                if not r["quote"]}
        legacy_raw = self.repo.get_setting("no_match")
        if legacy_raw:
            try:
                legacy = {str(x) for x in json.loads(legacy_raw)}
            except (ValueError, TypeError):
                legacy = set()
            new = legacy - refs
            if new:
                self.repo.set_last_quotes(PROVIDER, [(ref, "") for ref in sorted(new)])
            refs |= legacy
            self.repo.delete_setting("no_match")
        return refs

    def _load_last_quotes(self) -> dict[str, PriceQuote]:
        """Ultimo annuncio salvato per ogni carta (per la Panoramica al riavvio)."""
        quotes: dict[str, PriceQuote] = {}
        for row in self.repo.load_last_quotes(PROVIDER):
            raw = row["quote"]
            if not raw:
                continue  # '' = "Nessuna copia" (gestito da _load_no_match)
            try:
                quotes[str(row["ref_id"])] = PriceQuote.from_dict(json.loads(raw))
            except (ValueError, TypeError):
                pass  # riga corrotta: la ignora, verrà sovrascritta al prossimo check
        return quotes

    def open_default_filters(self) -> None:
        """Filtri PREDEFINITI (imbuto nell'header): valgono per le carte che
        non hanno filtri propri, comprese quelle che aggiungerai."""
        dialog = FiltersDialog(self._filters, self,
                               title=tr("Filtri predefiniti"))
        if dialog.open_near(self.defaults_btn) != QDialog.DialogCode.Accepted:
            return
        self._filters = dialog.result_filters()
        self.repo.set_setting("filters", json.dumps(self._filters.to_dict()))
        if self.provider is not None:
            self.provider.filters = self._filters
        active = self._filters.active()
        self._set_busy(False, tr("Filtri aggiornati: ricontrollo i prezzi…") if active
                       else tr("Filtri rimossi."))
        if active or self.repo.list_watches():
            self.check_now()

    # --- filtri della carta selezionata, PRIMA di aggiungerla ---
    def _update_card_filters_btn(self) -> None:
        """Il pulsante ha senso solo con una carta selezionata; acceso quando
        quella carta ha già filtri propri in attesa."""
        has_card = self._selected_ref is not None
        self.filters_btn.setEnabled(has_card)
        self.filters_btn.setChecked(has_card and self._pending_filters is not None)
        if not has_card:
            self.filters_btn.setToolTip(tr(
                "Filtri solo per la carta da aggiungere: scegli prima una carta"))
        elif self._pending_filters is not None:
            self.filters_btn.setToolTip(tr(
                "Filtri propri impostati per {name} (clic per modificarli)"
            ).format(name=self._selected_ref.name))
        else:
            self.filters_btn.setToolTip(tr(
                "Filtri solo per {name}, invece di quelli predefiniti"
            ).format(name=self._selected_ref.name))

    def open_card_filters(self) -> None:
        """Filtri della SOLA carta selezionata, da applicare all'aggiunta.

        Restano in sospeso in `_pending_filters` finché non si preme Aggiungi:
        la carta non esiste ancora, non c'è una riga su cui scriverli."""
        ref = self._selected_ref
        if ref is None:
            self._update_card_filters_btn()
            return
        base = self._pending_filters if self._pending_filters is not None else self._filters
        dlg = FiltersDialog(base, self, allow_global=True,
                            use_global=self._pending_filters is None,
                            title=tr("Filtri · {name}").format(name=ref.name))
        if dlg.open_near(self.filters_btn) != QDialog.DialogCode.Accepted:
            self._update_card_filters_btn()   # annullato: il pulsante non deve restare acceso
            return
        self._pending_filters = None if dlg.uses_global() else dlg.result_filters()
        self._update_card_filters_btn()
        self._set_busy(False, tr("Filtri pronti per {name}: si applicano quando la aggiungi.")
                       .format(name=ref.name) if self._pending_filters is not None
                       else tr("{name} userà i filtri predefiniti.").format(name=ref.name))

    def open_options(self) -> None:
        """Preferenze di visualizzazione: dal pulsante Opzioni dell'header."""
        dialog = DisplayDialog(self._display, self)
        if dialog.open_near(self.options_btn) != QDialog.DialogCode.Accepted:
            return
        new_display = dialog.result_display()
        if new_display != self._display:
            self._display = new_display
            self.repo.set_setting("display", json.dumps(self._display))
            anim.set_enabled(bool(self._display.get("animations", True)))  # subito
            self._apply_column_layout(self._overview)  # larghezze per icone/codici
            self._reload_table()
            self._set_busy(False, tr("Visualizzazione aggiornata."))
        new_lang = dialog.result_language()
        if new_lang and new_lang != i18n.current():
            i18n.set_language(new_lang)   # la UI si costruisce all'avvio
            self._set_busy(False, tr("Lingua salvata: riavvia l'app per applicarla."))

    # ------------------------------------------------------------- token
    def set_token(self) -> None:
        token, ok = QInputDialog.getText(
            self, tr("Token CardTrader"),
            tr("Incolla qui il tuo token (Bearer) di CardTrader:"),
            QLineEdit.EchoMode.Password,
        )
        if not ok or not token.strip():
            return
        config.save_token(self.context.data_dir, token.strip())
        self._build_provider()
        self._refresh_header_state()
        self._set_busy(False, tr("Token salvato."))

    # ------------------------------------------------------- catalogo
    def sync_catalog(self) -> None:
        if self.client is None:
            QMessageBox.information(self, tr("Token mancante"), tr("Imposta prima il token CardTrader."))
            return
        if self._sync_worker is not None and self._sync_worker.isRunning():
            return
        self._set_busy(True, tr("Sincronizzazione catalogo… (può richiedere qualche minuto)"))
        self.sync_btn.setEnabled(False)
        self._sync_worker = CatalogSyncWorker(self.client)
        self._sync_worker.progress.connect(self._on_sync_progress)
        self._sync_worker.finished_ok.connect(self._on_sync_done)
        self._sync_worker.failed.connect(self._on_error)
        self._sync_worker.start()

    def _on_sync_progress(self, done: int, total: int) -> None:
        self.status.setText(tr("Sincronizzazione catalogo… espansione {done}/{total}").format(done=done, total=total))

    def _on_sync_done(self, rows: list) -> None:
        self.repo.replace_catalog(PROVIDER, rows)
        self._refresh_header_state()
        self._rebuild_completer()
        self._set_busy(False, tr("Catalogo aggiornato: {n} carte.").format(n=len(rows)))

    # ------------------------------------------------------------- ricerca live
    def _rebuild_completer(self) -> None:
        """Ricarica nel completer tutte le stampe del catalogo locale.

        Da richiamare all'avvio e dopo ogni sincronizzazione del catalogo."""
        mapping: dict[str, CardRef] = {}
        items: list[tuple[str, str, str, str, str]] = []
        labels: list[str] = []
        rows = self.repo.all_catalog(PROVIDER)
        # Immagine "stock" per NOME: la prima disponibile fra tutte le stampe
        # della stessa carta. Serve da ripiego per le stampe che nel catalogo
        # non hanno immagine — l'arte è la stessa, cambia la rarità, non il
        # disegno. Si costruisce in questa passata (il catalogo lo stiamo già
        # scorrendo tutto): zero query in più, zero richieste di rete.
        # Si preferisce una stampa SENZA rarità (l'arte "liscia", la più
        # neutra da mostrare al posto di un'altra); altrimenti una qualsiasi.
        stock: dict[str, str] = {}
        stock_plain: dict[str, str] = {}
        for row in rows:
            # usable_*: scarta il segnaposto grigio di CardTrader, altrimenti
            # verrebbe scelto come ripiego al posto di una foto vera
            url = cardtrader.usable_image_url(row["image_url"] or "")
            if not url:
                continue
            name_ = row["name"]
            detail_ = row["detail"] or ""
            rarity_ = detail_.split(" · ", 1)[0].strip() if " · " in detail_ else ""
            stock.setdefault(name_, url)
            if not rarity_:
                stock_plain.setdefault(name_, url)
        self._stock_images = {**stock, **stock_plain}
        for row in rows:
            name = row["name"]
            detail = row["detail"] or ""          # "rarità · espansione" (per la tabella)
            image_url = cardtrader.usable_image_url(row["image_url"] or "")
            code = (row["set_code"] or "").upper()
            if " · " in detail:
                rarity, expansion = detail.rsplit(" · ", 1)
            else:
                rarity, expansion = "", detail
            left = f"{name} — {rarity}" if rarity else name   # mostrato a sinistra
            # label = stringa filtrabile/univoca: nome, rarità e CODICE (non il
            # nome lungo del set). Così si può filtrare anche digitando il codice.
            label = f"{left} · {code}" if code else left
            mapping[label] = CardRef(id=str(row["ref_id"]), name=name,
                                     detail=detail, image_url=image_url)
            # ultimo campo = immagine di ripiego (altra stampa della stessa
            # carta): il delegate la usa, marcata "Stock", se l'esatta non c'è
            items.append((label, image_url, left, code, expansion,
                          self._stock_images.get(name, "")))
            labels.append(label)
        self._label_to_ref = mapping
        # indice per la ricerca "a token" (label minuscolo pre-calcolato)
        self._search_index = [(lbl.lower(), lbl) for lbl in labels]
        self._completer_model.setStringList([])        # vuoto: si riempie coi match
        self._thumb_delegate.set_cards(items)          # immagini + codice gestiti dal delegate
        self._completer_items = items                  # li riusa la ricerca delle basi
        # La mappa dei ripieghi nasce QUI, ma la tabella è già stata disegnata
        # una volta (questo metodo è differito con un singleShot per non
        # rallentare l'avvio): senza questo giro, le carte che dipendono dal
        # ripiego resterebbero con la cornice vuota fino al render successivo.
        self._refresh_row_icons()

    def _on_search_text(self, text: str) -> None:
        # ogni modifica manuale annulla la carta selezionata in precedenza —
        # e con lei gli eventuali filtri preparati, che erano SOLO per quella
        self._selected_ref = None
        self._pending_filters = None
        self._update_card_filters_btn()
        self.add_btn.setEnabled(False)
        self.selected_label.setText(tr("Nessuna carta selezionata"))
        self._show_image("")
        self._pending_query = text
        self._search_timer.start()  # filtro dopo la pausa (debounce)

    _SEARCH_LIMIT = 60  # max risultati mostrati (il popup resta piccolo → veloce)

    def _apply_search_filter(self, text: str) -> None:
        """Ricerca 'a token': tutte le parole devono comparire (in qualsiasi
        ordine) in nome/rarità/codice. Es. 'impulse quarter' → match.

        La facciamo in Python sull'indice pre-calcolato, limitando a N risultati
        (stop appena raggiunti): così è veloce e il popup resta leggero."""
        words = text.lower().split()
        if not words:
            self._completer_model.setStringList([])
            return
        matches: list[str] = []
        for low, label in self._search_index:
            if all(w in low for w in words):
                matches.append(label)
                if len(matches) >= self._SEARCH_LIMIT:
                    break
        self._completer_model.setStringList(matches)
        self._completer.complete()  # mostra i match nel popup

    def _on_pick(self, label: str) -> None:
        ref = self._label_to_ref.get(label)
        if ref is None:
            return
        self._selected_ref = ref
        self._pending_filters = None      # carta nuova: si riparte dai predefiniti
        self._update_card_filters_btn()
        self.add_btn.setEnabled(True)
        shown = ref.name if not ref.detail else f"{ref.name} · {ref.detail}"
        self.selected_label.setText(f"✓  {shown}")
        self._show_image(ref.image_url, ref.name)

    # ------------------------------------------------------------- anteprima
    def _show_image(self, url: str, name: str = "") -> None:
        """Anteprima della carta, stessa scala di ripieghi delle miniature:
        stampa esatta → altra stampa col timbro "Stock" → cornice vuota."""
        self._current_img_exact = url
        self._current_img_name = name
        stock = self._stock_images.get(name, "")
        if url and url not in self._failed_images:
            target, is_stock = url, False
        elif stock and stock != url and stock not in self._failed_images:
            target, is_stock = stock, True
        else:
            self._show_preview_placeholder()
            return
        self._current_img_url = target
        self._current_img_is_stock = is_stock
        cached = self._img_cache.get(target)
        if cached is not None:
            self._set_preview_pixmap(stock_pixmap(target, cached) if is_stock else cached)
            return
        self.preview.setPixmap(QPixmap())
        self.preview.setText(tr("Caricamento…"))
        self._img_worker = ImageFetchWorker(target, self)
        self._img_worker.done.connect(self._on_image_done)
        self._img_worker.failed.connect(self._on_image_failed)
        self._img_worker.start()

    def _show_preview_placeholder(self) -> None:
        self.preview.setText("")
        self.preview.setPixmap(_make_empty_frame(self.preview.size()))

    def _on_image_done(self, url: str, image: QImage) -> None:
        if image.isNull():   # scaricata ma illeggibile: vale come fallimento
            self._on_image_failed("immagine non valida")
            return
        pixmap = QPixmap.fromImage(image)  # già decodificata nel thread: solo incarto
        self._img_cache[url] = pixmap
        if self._history_dlg is not None:  # storico aperto: prende la stessa
            self._history_dlg.image_arrived(url, pixmap)
        if url == self._current_img_url:  # ignora risposte ormai sorpassate
            self._set_preview_pixmap(
                stock_pixmap(url, pixmap) if self._current_img_is_stock else pixmap)

    def _on_image_failed(self, _message: str) -> None:
        # Ricordo il fallimento e rilancio: _show_image scarterà l'URL perso e
        # passerà da solo al ripiego (e poi alla cornice vuota). Niente
        # ritentativi sullo stesso URL: Cloudflare non gradisce.
        if self._current_img_url:
            self._failed_images.add(self._current_img_url)
        self._show_image(self._current_img_exact, self._current_img_name)

    def _set_preview_pixmap(self, pixmap: QPixmap) -> None:
        self.preview.setText("")
        self.preview.setPixmap(pixmap.scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def add_by_name(self) -> None:
        ref = self._selected_ref
        if ref is None:
            return
        # i filtri scelti col pulsante accanto alla ricerca nascono con la
        # carta ('' = usa i predefiniti), così il primo controllo li rispetta già
        filters_json = ("" if self._pending_filters is None
                        else json.dumps(self._pending_filters.to_dict()))
        self.repo.add_watch(PROVIDER, ref.id, ref.name, ref.detail,
                            self.threshold_spin.value(), filters_json)
        custom = self._pending_filters is not None
        self._pending_filters = None
        self._reload_table()
        self.search_input.clear()
        self._on_search_text("")
        self._set_busy(False, (
            tr("Aggiunta: {name}, coi suoi filtri. Recupero prezzo iniziale…") if custom
            else tr("Aggiunta: {name}. Recupero prezzo iniziale…")).format(name=ref.name))
        self.check_now()

    # --------------------------------------------------------------- tabella
    def _reload_table(self) -> None:
        self._render_after_check(self._last_checked, pulse=False)

    def _set_row(self, row, watch, last_price, change, checked, no_match=False) -> None:
        def cell(text: str = "") -> QTableWidgetItem:
            return QTableWidgetItem(text)

        ref_id = str(watch["ref_id"])
        detail = watch["detail"] or ""
        if " · " in detail:            # "rarità · set" → colonne separate
            rarity, setname = detail.split(" · ", 1)
        else:
            rarity, setname = "", detail
        q = self._last_quotes.get(ref_id)

        # 0 Immagine (solo miniatura)
        img_item = cell()
        img_item.setData(Qt.ItemDataRole.UserRole, ref_id)
        img_item.setData(Qt.ItemDataRole.UserRole + 1, watch["card_name"])  # per il ripiego
        icon = self._row_icon(ref_id, watch["card_name"])
        if icon is not None:
            img_item.setIcon(icon)
        self.table.setItem(row, 0, img_item)
        # 1 Nome — il rientro delle carte in cartella lo fa `_IndentDelegate`
        # (spostando il rect): con gli spazi nel testo rientrava solo la prima
        # riga e in Panoramica i nomi a capo restavano disallineati.
        # Le copie stanno davanti al nome ("3× Dark Magician"): in una base è
        # la prima cosa che si vuole vedere, e il prezzo mostrato resta quello
        # UNITARIO (il conto delle copie lo fa il totale della base).
        copies = watch["copies"] if "copies" in watch.keys() else 1
        name_text = watch["card_name"] if copies <= 1 else f"{copies}×  {watch['card_name']}"
        self.table.setItem(row, 1, cell(name_text))
        # 2 Rarità: badge colorato oppure testo (opzione Visualizzazione)
        if self._display.get("rarity_icons") and rarity:
            self.table.setItem(row, 2, cell(""))
            self.table.setCellWidget(
                row, 2, self._pill_cell(rarity_pixmap(rarity, self._rp(18)), rarity))
        else:
            self.table.removeCellWidget(row, 2)
            self.table.setItem(row, 2, cell(rarity or "—"))
        # 3 Set: pill col codice (come nella ricerca; nome nel tooltip) oppure nome
        code = self.repo.catalog_set_code(PROVIDER, ref_id) if self._display.get("set_codes") else ""
        if code:
            self.table.setItem(row, 3, cell(""))
            self.table.setCellWidget(
                row, 3, self._pill_cell(_make_set_pill(code, self._rp(20)), setname))
        else:
            self.table.removeCellWidget(row, 3)
            self.table.setItem(row, 3, cell(setname or "—"))
        # 4 Condizione, 5 Lingua, 6 1ª ed., 7 Zero (annuncio scelto, colonne separate)
        cond_full = (q.condition if q is not None else "") or ""
        lang_code = (q.language if q is not None else "") or ""
        self._set_badge_cells(row, cond_full, lang_code)
        for col, flag in ((6, q is not None and q.first_edition),
                          (7, q is not None and q.zero)):
            flag_item = cell("✓" if flag else "—")
            flag_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if flag:
                flag_item.setForeground(QColor(theme.ACCENT))
            self.table.setItem(row, col, flag_item)
        # 8 Prezzo
        if no_match:
            price_item = cell(tr("Nessuna copia"))
            price_item.setForeground(QColor(theme.WARN))
            price_item.setToolTip(tr("Nessun annuncio soddisfa i filtri impostati (Opzioni)."))
        elif copies > 1 and q is not None and getattr(q, "total", 0.0):
            # Con più copie il prezzo utile è quanto costano TUTTE: il totale
            # della base è la somma di questi, e i conti tornano a vista.
            # L'unitario più basso resta nel tooltip.
            price_item = cell(f"{q.total:.2f} €")
            mancanti = copies - (getattr(q, "covered", 0) or copies)
            tip = tr("{n} copie · più economica {unit:.2f} €").format(n=copies, unit=q.amount)
            if mancanti > 0:
                tip += "\n" + tr("Attenzione: se ne trovano solo {c} su {n}").format(
                    c=q.covered, n=copies)
                price_item.setForeground(QColor(theme.WARN))
            price_item.setToolTip(tip)
        else:
            price_item = cell("—" if last_price is None else f"{last_price:.2f} €")
        self.table.setItem(row, 8, price_item)
        # 9 Var.
        change_item = cell("—" if (no_match or change is None) else f"{change:+.1f}%")
        if change is not None and not no_match:
            change_item.setForeground(QColor(theme.POSITIVE) if change >= 0 else QColor(theme.NEGATIVE))
        self.table.setItem(row, 9, change_item)
        # 10 Soglia, 11 Controllo (solo vista normale)
        self.table.setItem(row, 10, cell(f"≥ {watch['threshold_pct']:.1f}%"))
        self.table.setItem(row, 11, cell(checked))
        # 12 Venditore, 13 Commenti, 14 Q.tà (solo Panoramica, dall'annuncio scelto)
        comment_text = qty_text = ""
        if q is not None:
            comment_text = q.comment or ""
            qty_text = str(q.quantity) if q.quantity else ""
        # Con più copie da venditori diversi, la Q.tà diventa l'appiglio per
        # aprire l'elenco delle provenienze: chevron + numero di venditori.
        fonti = self._card_sources(watch) if copies > 1 else []
        if fonti:
            # la colonna Q.tà è stretta: qui ci sta "3 ▸", il numero di
            # venditori lo dice il tooltip (e l'elenco, una volta aperto)
            aperta = str(watch["ref_id"]) in self._open_sources
            qty_text = f"{copies} {'▾' if aperta else '▸'}"
        # Venditore: nome + iconcine (bandiera del paese, badge PRO)
        self.table.setItem(row, 12, cell(""))
        if q is not None and (q.seller or q.country or q.seller_type):
            self.table.setCellWidget(row, 12, self._seller_cell(q))
        else:
            self.table.removeCellWidget(row, 12)
        comment_item = cell(comment_text)
        comment_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.table.setItem(row, 13, comment_item)
        qty_item = cell(qty_text)
        qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if fonti:
            qty_item.setForeground(QColor(theme.ACCENT))
            qty_item.setToolTip(tr("Le {n} copie arrivano da {v} venditori — "
                                   "clic per vedere da dove").format(n=copies, v=len(fonti)))
        self.table.setItem(row, 14, qty_item)
        actions = QWidget()
        # In Panoramica: pulsanti impilati (verticali) e icone più grandi;
        # in vista normale: affiancati e compatti.
        arow = QVBoxLayout(actions) if self._overview else QHBoxLayout(actions)
        arow.setContentsMargins(0, 0, 0, 0)
        arow.setSpacing(self._rp(4 if self._overview else 2))
        icon_sz = QSize(self._rp(26), self._rp(26)) if self._overview else self._sz(QSize(18, 18))
        raw_filters = watch["filters"] if "filters" in watch.keys() else ""
        settings_btn = QPushButton()
        settings_btn.setObjectName("ghost")
        settings_btn.setIcon(self._settings_icon_custom if raw_filters else self._settings_icon)
        settings_btn.setIconSize(icon_sz)
        settings_btn.setToolTip(
            tr("Filtri PROPRI di questa carta (diversi dai predefiniti) — clic per modificarli")
            if raw_filters else
            tr("Filtri di questa carta (ora usa i predefiniti)"))
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.clicked.connect(
            lambda _=False, wid=watch["id"], rf=raw_filters, nm=watch["card_name"]:
            self._open_item_settings(wid, rf, nm))
        link_btn = QPushButton()
        link_btn.setObjectName("ghost")
        link_btn.setIcon(self._link_icon)
        link_btn.setIconSize(icon_sz)
        link_btn.setToolTip(self._card_page_tip(watch))
        link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        link_btn.clicked.connect(lambda _=False, rid=ref_id: self._open_card_page(rid))
        remove_btn = QPushButton()
        remove_btn.setObjectName("ghost")
        remove_btn.setIcon(self._trash_icon)
        remove_btn.setIconSize(icon_sz)
        remove_btn.setToolTip(tr("Rimuovi dalla watchlist"))
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.clicked.connect(lambda _=False, wid=watch["id"]: self._remove(wid))
        arow.addWidget(settings_btn)
        arow.addWidget(link_btn)
        arow.addWidget(remove_btn)
        self.table.setCellWidget(row, 15, actions)

    def _set_badge_cells(self, row: int, condition: str, language: str) -> None:
        """Colonne 4 (Condizione) e 5 (Lingua) come badge.

        Sono cell WIDGET, non testo: vale la nota del modello dati —
        `ResizeToContents` ignora i cell widget, quindi quelle colonne devono
        avere una larghezza dichiarata (ce l'hanno, in Panoramica)."""
        for col, pm, tip in (
            (4, _make_condition_pill(condition, self._rp(20)) if condition else None, condition),
            (5, _make_language_pill(language, self._rp(20)) if language else None,
             language.upper()),
        ):
            self.table.setItem(row, col, QTableWidgetItem("" if pm is not None else "—"))
            if pm is None:
                self.table.removeCellWidget(row, col)
                self.table.item(row, col).setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            else:
                self.table.setCellWidget(row, col, self._pill_cell(pm, tip))

    def _pill_cell(self, pixmap: QPixmap, tooltip: str = "") -> QWidget:
        """Cella con un badge/pill centrato (rarità, codice set) e tooltip."""
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(self._sp(4), 0, self._sp(4), 0)
        badge = QLabel()
        badge.setPixmap(pixmap)
        if tooltip:
            badge.setToolTip(tooltip)
        lay.addStretch(1)
        lay.addWidget(badge)
        lay.addStretch(1)
        return box

    def _seller_cell(self, q) -> QWidget:
        """Cella Venditore: username sopra; sotto bandierina del paese e,
        per i venditori professionali, il badge 'PRO'."""
        box = QWidget()
        # trasparente: lascia vedere lo sfondo/hover della riga sottostante
        box.setStyleSheet("background: transparent;")
        v = QVBoxLayout(box)
        v.setContentsMargins(self._rp(10), self._rp(2), self._rp(4), self._rp(2))
        v.setSpacing(self._rp(3))
        v.addStretch(1)
        name = QLabel(q.seller or "—")
        name.setToolTip(q.seller or "")
        v.addWidget(name)
        icons = QHBoxLayout()
        icons.setSpacing(self._rp(5))
        icon_h = self._rp(15)
        if q.country:
            flag = QLabel()
            flag.setPixmap(flag_pixmap(q.country, icon_h))
            flag.setToolTip(country_name(q.country))
            icons.addWidget(flag)
        if (q.seller_type or "").lower() == "pro":
            pro = QLabel()
            pro.setPixmap(_make_pro_badge(icon_h))
            pro.setToolTip(tr("Venditore professionale (PRO)"))
            icons.addWidget(pro)
        icons.addStretch(1)
        v.addLayout(icons)
        v.addStretch(1)
        return box

    @staticmethod
    def _filters_key(filters: ListingFilters) -> str:
        """Firma stabile di un insieme di filtri (chiavi ordinate): due insiemi
        equivalenti danno la stessa stringa. Marca i punti dello storico, così
        si confrontano fra loro solo prezzi rilevati con gli STESSI filtri."""
        return json.dumps(filters.to_dict(), sort_keys=True)

    def _watch_key(self, watch) -> str:
        return self._filters_key(self._effective_filters(watch))

    def _adopt_history_keys(self) -> None:
        """Una tantum sui DB nati prima della colonna `filters_key`: assegna ai
        vecchi punti i filtri con cui, verosimilmente, sono stati rilevati.

        SOLO per le carte che usano i predefiniti. Se una carta ha filtri
        PROPRI vuol dire che qualcuno glieli ha messi, e i prezzi precedenti
        sono con ogni probabilità di prima: adottarli riproporrebbe proprio il
        confronto fasullo che stiamo togliendo di mezzo. Quelle carte
        ripartono puliti — la vecchia serie resta comunque nel DB, marcata ''.
        """
        for watch in self.repo.list_watches():
            if watch["provider"] != PROVIDER:
                continue
            own = watch["filters"] if "filters" in watch.keys() else ""
            if own:
                continue
            self.repo.adopt_history_key(PROVIDER, watch["ref_id"], self._watch_key(watch))

    def _adopt_deck_flags(self) -> None:
        """Una tantum, per le basi create prima della colonna `is_deck`:
        una cartella con filtri propri o con carte in più copie è una base,
        altrimenti non ci sarebbe motivo di quei dati."""
        copies_by_folder: dict = {}
        for w in self.repo.list_watches():
            fid = w["folder_id"] if "folder_id" in w.keys() else None
            n = w["copies"] if "copies" in w.keys() else 1
            if fid is not None and n > 1:
                copies_by_folder[fid] = True
        for f in self.repo.list_folders(PROVIDER):
            if "is_deck" not in f.keys() or f["is_deck"]:
                continue
            shared = f["filters"] if "filters" in f.keys() else ""
            if shared or copies_by_folder.get(f["id"]):
                self.repo.set_folder_deck(f["id"], True)

    def _refresh_folder_cache(self) -> None:
        """`_effective_filters` gira per ogni carta a ogni render/controllo:
        le cartelle si leggono una volta sola, non una query per carta."""
        self._folders_by_id = {f["id"]: f for f in self.repo.list_folders(PROVIDER)}

    @staticmethod
    def _parse_filters(raw: str):
        try:
            return ListingFilters.from_dict(json.loads(raw)) if raw else None
        except (ValueError, TypeError):
            return None

    def _effective_filters(self, watch):
        """A cascata: filtri della CARTA → della sua BASE/cartella → predefiniti.

        La base serve proprio a questo: imposti i filtri una volta e valgono per
        tutte le carte che contiene, senza doverli ripetere carta per carta."""
        own = self._parse_filters(watch["filters"] if "filters" in watch.keys() else "")
        if own is not None:
            return own
        fid = watch["folder_id"] if "folder_id" in watch.keys() else None
        if fid is not None:
            folder = self._folders_by_id.get(fid)
            if folder is not None and "filters" in folder.keys():
                shared = self._parse_filters(folder["filters"])
                if shared is not None:
                    return shared
        return self._filters

    def _open_item_settings(self, watch_id, raw_filters: str, card_name: str) -> None:
        base = self._filters
        if raw_filters:
            try:
                base = ListingFilters.from_dict(json.loads(raw_filters))
            except (ValueError, TypeError):
                pass
        dlg = FiltersDialog(base, self, allow_global=True, use_global=not raw_filters,
                            title=tr("Filtri · {name}").format(name=card_name))
        if dlg.open_near() != QDialog.DialogCode.Accepted:  # centrato sulla finestra
            return
        if dlg.uses_global():
            self.repo.set_watch_filters(watch_id, "")
        else:
            self.repo.set_watch_filters(watch_id, json.dumps(dlg.result_filters().to_dict()))
        self._set_busy(False, tr("Filtri aggiornati per {name}. Ricontrollo…").format(name=card_name))
        self.check_now()

    # --- miniature nelle righe della watchlist ---
    def _image_urls_for(self, ref_id: str, name: str = "") -> tuple[str, str]:
        """(url della stampa esatta, url di ripiego di un'ALTRA stampa).

        Il ripiego è l'arte della stessa carta presa da un'altra stampa
        (preferita quella senza rarità): giusta come disegno, sbagliata come
        stampa — per questo va mostrata col timbro "Stock"."""
        exact = cardtrader.usable_image_url(self.repo.catalog_image(PROVIDER, ref_id) or "")
        if not name:
            name = self.repo.catalog_name(PROVIDER, ref_id) or ""
        stock = self._stock_images.get(name, "")
        return exact, ("" if stock == exact else stock)

    def _empty_icon(self) -> QIcon:
        return QIcon(_make_empty_frame(self.table.iconSize()))

    def _queue_thumb(self, turl: str, ref_id: str, name: str) -> None:
        self._url_ref[turl] = ref_id
        self._url_name[turl] = name
        if turl not in self._row_thumb_inflight:
            self._row_thumb_inflight.add(turl)
            self._row_thumb_pool.start(_ThumbTask(turl, self._row_thumb_signals, ROW_THUMB))

    def _row_icon(self, ref_id: str, name: str = ""):
        """Icona miniatura della riga, in ordine di preferenza: immagine della
        stampa esatta → immagine di un'altra stampa col timbro "Stock" →
        cornice vuota. Il ripiego si scarica SOLO dopo che l'esatta è fallita
        (altrimenti sarebbero due richieste per carta)."""
        exact, stock = self._image_urls_for(ref_id, name)
        exact, stock = _thumb_url(exact), _thumb_url(stock)
        if exact and exact not in self._failed_thumbs:
            pixmap = self._row_thumb_cache.get(exact)
            if pixmap is not None:
                return QIcon(pixmap)
            self._queue_thumb(exact, ref_id, name)
            return self._empty_icon()          # in attesa
        if stock and stock not in self._failed_thumbs:
            pixmap = self._row_thumb_cache.get(stock)
            if pixmap is not None:
                return QIcon(stock_pixmap(stock, pixmap))
            self._queue_thumb(stock, ref_id, name)
        return self._empty_icon()

    def _on_row_thumb(self, turl: str, image: QImage) -> None:
        self._row_thumb_inflight.discard(turl)
        if image.isNull():
            # Fallito (403 di Cloudflare, 404, rete): segnalo l'URL come perso.
            # Così i render successivi passano al ripiego e NON si ritenta
            # all'infinito lo stesso download.
            self._failed_thumbs.add(turl)
        else:
            self._row_thumb_cache[turl] = QPixmap.fromImage(image)
        # Ricalcolo le icone di TUTTE le righe invece della sola riga
        # "proprietaria": un'immagine di ripiego è condivisa da più stampe
        # della stessa carta, e un fallimento fa scattare il ripiego.
        self._refresh_row_icons()

    def _refresh_row_icons(self) -> None:
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item is None:
                continue
            ref_id = item.data(Qt.ItemDataRole.UserRole)
            if not ref_id:
                continue   # riga-cartella
            icon = self._row_icon(str(ref_id), item.data(Qt.ItemDataRole.UserRole + 1) or "")
            if icon is not None:
                item.setIcon(icon)

    def _on_table_selection(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        ref_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not ref_id:
            return
        name = self.repo.catalog_name(PROVIDER, ref_id) or ""
        self._show_image(self._image_urls_for(ref_id, name)[0], name)

    def _remove(self, watch_id) -> None:
        removed = self.repo.remove_watch(watch_id)  # pulisce anche storico/annuncio
        if removed is not None:
            _, ref_id = removed
            self._last_quotes.pop(ref_id, None)
            self._no_match_refs.discard(ref_id)
        self._reload_table()

    # ------------------------------------------------ cartelle & ordinamento
    def _on_cell_clicked(self, row: int, col: int) -> None:
        if not (0 <= row < len(self._row_entries)):
            return
        kind, payload = self._row_entries[row]
        if kind == "folder":
            self._toggle_folder(payload)
        elif kind == "watch" and col == 14 and self._card_sources(payload):
            # la cella Q.tà è l'interruttore delle provenienze: sta lì il
            # chevron, ed è la colonna che parla di copie
            self._toggle_sources(payload)

    def _folder_card_rows(self, fid) -> list[int]:
        """Righe visuali delle carte contenute nella cartella `fid`."""
        return [r for r, (k, p) in enumerate(self._row_entries)
                if k == "watch"
                and (p["folder_id"] if "folder_id" in p.keys() else None) == fid]

    def _toggle_folder(self, folder) -> None:
        """Apre/chiude una cartella con animazione a fisarmonica sulle
        altezze delle sue righe."""
        fid = folder["id"]
        if not anim.is_enabled():   # animazioni disattivate: toggle immediato
            self.repo.set_folder_expanded(fid, not folder["expanded"])
            self._reload_table()
            return
        prev = getattr(self, "_folder_anim", None)
        if prev is not None:
            try:
                prev.stop()  # può essere già auto-eliminata (DeleteWhenStopped)
            except RuntimeError:
                pass
            self._folder_anim = None
        if folder["expanded"]:
            rows = self._folder_card_rows(fid)
            if not rows:  # vuota: niente da animare
                self.repo.set_folder_expanded(fid, False)
                self._reload_table()
                return
            heights = {r: self.table.rowHeight(r) for r in rows}
            anim_ = QVariantAnimation(self)
            anim_.setDuration(160)
            anim_.setEasingCurve(QEasingCurve.Type.InCubic)
            anim_.setStartValue(1.0)
            anim_.setEndValue(0.0)
            anim_.valueChanged.connect(lambda v: [
                self.table.setRowHeight(r, max(0, round(h * float(v))))
                for r, h in heights.items()])
            def _close():
                self.repo.set_folder_expanded(fid, False)
                self._reload_table()
            anim_.finished.connect(_close)
            self._folder_anim = anim_
            anim_.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        else:
            self.repo.set_folder_expanded(fid, True)
            self._reload_table()
            rows = self._folder_card_rows(fid)
            if not rows:
                return
            heights = {r: self.table.rowHeight(r) for r in rows}
            for r in rows:  # si parte chiusi e si cresce fino all'altezza piena
                self.table.setRowHeight(r, 1)
            anim_ = QVariantAnimation(self)
            anim_.setDuration(200)
            anim_.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim_.setStartValue(0.0)
            anim_.setEndValue(1.0)
            anim_.valueChanged.connect(lambda v: [
                self.table.setRowHeight(r, max(1, round(h * float(v))))
                for r, h in heights.items()])
            self._folder_anim = anim_
            anim_.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _row_indent(self, row: int) -> int:
        """Rientro in px del nome: solo per le CARTE dentro una cartella
        (la riga della cartella resta a filo, come le carte sciolte)."""
        if not (0 <= row < len(self._row_entries)):
            return 0
        kind, _payload = self._row_entries[row]
        if kind == "source":      # un gradino più dentro della carta che la ospita
            return self._rp(16 if self._folder_at(row) is None else 32)
        return self._rp(16) if (kind == "watch" and self._folder_at(row) is not None) else 0

    # --- provenienza delle copie (carte in più copie, solo in Panoramica) ---
    def _card_sources(self, watch) -> list:
        """Da quali annunci arrivano le copie di questa carta (vuoto se una
        sola copia, o se bastano a coprirla tutte dallo stesso venditore)."""
        quote = self._last_quotes.get(str(watch["ref_id"]))
        if quote is None:
            return []
        sources = getattr(quote, "sources", None) or []
        return sources if len(sources) > 1 else []

    def _visible_sources(self, watch) -> list:
        """Le righe-provenienza si mostrano solo in Panoramica (dove ci sono le
        colonne per leggerle) e solo se la carta è stata aperta."""
        if not self._overview or str(watch["ref_id"]) not in self._open_sources:
            return []
        return self._card_sources(watch)

    def _toggle_sources(self, watch) -> None:
        ref_id = str(watch["ref_id"])
        if ref_id in self._open_sources:
            self._open_sources.discard(ref_id)
        else:
            self._open_sources.add(ref_id)
        self._reload_table()

    def _row_has_own_filters(self, row: int) -> bool:
        """True per le carte con filtri PROPRI (≠ predefiniti): è la riga che
        va marcata nella colonna Nome."""
        if not (0 <= row < len(self._row_entries)):
            return False
        kind, payload = self._row_entries[row]
        if kind != "watch" or "filters" not in payload.keys():
            return False
        return bool(payload["filters"])

    def _folder_at(self, row: int):
        """Cartella 'di pertinenza' della riga visuale (None = fuori)."""
        if not (0 <= row < len(self._row_entries)):
            return None
        kind, payload = self._row_entries[row]
        if kind == "source":      # riga-provenienza: vale la carta che la ospita
            payload = payload[0]
            return payload["folder_id"] if "folder_id" in payload.keys() else None
        if kind == "folder":
            return payload["id"]
        return payload["folder_id"] if "folder_id" in payload.keys() else None

    def _on_row_moved(self, source: int, target: int) -> None:
        """Drop di una riga: carta → riordina/sposta in cartella;
        cartella → riordina le cartelle. All'arrivo la voce si "inserisce"
        con una piccola animazione (altezza + lampo teal)."""
        entries = self._row_entries
        if not (0 <= source < len(entries)) or source == target:
            return
        kind, payload = entries[source]
        if kind == "folder":
            ids = [f["id"] for k, f in entries if k == "folder"]
            ids.remove(payload["id"])
            tgt_fid = self._folder_at(target)
            idx = ids.index(tgt_fid) if tgt_fid in ids else len(ids)
            ids.insert(idx, payload["id"])
            self.repo.set_folder_positions([(fid, i) for i, fid in enumerate(ids)])
            self._reload_table()
            self._flash_folder(payload["id"])
        else:
            if target < 0 or target >= len(entries):
                dest_fid, before_id = None, None          # in fondo, fuori
            else:
                tkind, tpayload = entries[target]
                if tkind == "folder":
                    dest_fid, before_id = tpayload["id"], None   # dentro, in fondo
                else:
                    dest_fid = tpayload["folder_id"] if "folder_id" in tpayload.keys() else None
                    before_id = tpayload["id"]
            self._move_watch(payload["id"], dest_fid, before_id)
            self._reload_table()
            self._flash_watch(payload["id"])

    def _flash_watch(self, watch_id) -> None:
        """Evidenzia la carta appena spostata; se è finita in una cartella
        CHIUSA (riga non visibile), lampeggia la cartella di destinazione."""
        for r, (k, p) in enumerate(self._row_entries):
            if k == "watch" and p["id"] == watch_id:
                self._animate_row_arrival(r)
                return
        rows = [w for w in self.repo.list_watches() if w["id"] == watch_id]
        if rows and ("folder_id" in rows[0].keys()) and rows[0]["folder_id"] is not None:
            self._flash_folder(rows[0]["folder_id"])

    def _flash_folder(self, folder_id) -> None:
        for r, (k, p) in enumerate(self._row_entries):
            if k == "folder" and p["id"] == folder_id:
                self._animate_row_arrival(r)
                return

    def _animate_row_arrival(self, row: int) -> None:
        """Animazione di 'inserimento' della riga: cresce da ~45% all'altezza
        piena mentre un lampo teal svanisce. Ripristina poi gli sfondi di
        default (alternati da QSS, SURFACE_2 per le cartelle)."""
        if not (0 <= row < self.table.rowCount()) or not anim.is_enabled():
            return
        prev = getattr(self, "_move_anim", None)
        if prev is not None:
            try:
                prev.stop()
            except RuntimeError:
                pass
        is_folder = (row < len(self._row_entries)
                     and self._row_entries[row][0] == "folder")
        full_h = self.table.rowHeight(row)
        items = [self.table.item(row, c) for c in range(16)
                 if self.table.item(row, c) is not None]
        anim_ = QVariantAnimation(self)
        anim_.setDuration(260)
        anim_.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim_.setStartValue(0.0)
        anim_.setEndValue(1.0)

        # Gli item possono venire DISTRUTTI da un re-render a metà animazione
        # (vedi anim.pulse_item): ogni accesso è protetto, altrimenti il
        # RuntimeError in uno slot manda in abort l'exe windowed.
        def on_val(v: float) -> None:
            v = float(v)
            try:
                self.table.setRowHeight(row, max(1, round(full_h * (0.45 + 0.55 * v))))
                glow = QColor(theme.ACCENT)
                glow.setAlphaF((1.0 - v) * 0.30)
                for it in items:
                    it.setBackground(glow)
            except RuntimeError:
                anim_.stop()

        def on_done() -> None:
            try:
                self.table.setRowHeight(row, full_h)
                band = QColor(theme.SURFACE_2)
                for it in items:  # torna agli sfondi di default (QSS/alternati)
                    it.setData(Qt.ItemDataRole.BackgroundRole, None)
                    if is_folder:
                        it.setBackground(band)   # la fascia copre TUTTE le celle
            except RuntimeError:
                pass

        anim_.valueChanged.connect(on_val)
        anim_.finished.connect(on_done)
        self._move_anim = anim_
        anim_.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _move_watch(self, watch_id, dest_fid, before_id=None) -> None:
        """Colloca la carta in `dest_fid` (None = fuori), prima di `before_id`
        (None = in fondo), e riscrive il layout normalizzato di tutte."""
        seq: dict = {}   # folder_id -> [watch_id, …] in ordine attuale
        for w in self.repo.list_watches():
            if w["id"] == watch_id:
                continue
            fid = w["folder_id"] if "folder_id" in w.keys() else None
            seq.setdefault(fid, []).append(w["id"])
        bucket = seq.setdefault(dest_fid, [])
        idx = bucket.index(before_id) if before_id in bucket else len(bucket)
        bucket.insert(idx, watch_id)
        triples, pos = [], 0
        for fid, wids in seq.items():
            for wid in wids:
                triples.append((wid, fid, pos))
                pos += 1
        self.repo.set_watch_layout(triples)

    def _table_menu(self, pos) -> None:
        row = self.table.indexAt(pos).row()
        entry = self._row_entries[row] if 0 <= row < len(self._row_entries) else None
        menu = QMenu(self.table)
        if entry is not None and entry[0] == "watch":
            w = entry[1]
            menu.addAction(tr("Storico prezzi…"),
                           lambda watch=w, r=row: self._open_history(watch, r))
            menu.addSeparator()
            cur_fid = w["folder_id"] if "folder_id" in w.keys() else None
            sub = menu.addMenu(tr("Sposta nella cartella"))
            if cur_fid is not None:
                sub.addAction(tr("(Fuori dalle cartelle)"),
                              lambda wid=w["id"]: self._move_and_reload(wid, None))
            for f in self.repo.list_folders(PROVIDER):
                if f["id"] != cur_fid:
                    sub.addAction(f["name"],
                                  lambda wid=w["id"], fid=f["id"]: self._move_and_reload(wid, fid))
            sub.addSeparator()
            sub.addAction(tr("Nuova cartella…"),
                          lambda wid=w["id"]: self._new_folder(move_watch_id=wid))
            menu.addAction(tr("Numero di copie…"),
                           lambda wid=w["id"], nm=w["card_name"],
                           c=(w["copies"] if "copies" in w.keys() else 1):
                           self._ask_copies(wid, nm, c))
        elif entry is not None and entry[0] == "folder":
            f = entry[1]
            menu.addAction(tr("Modifica base…"), lambda folder=f: self.open_deck(folder))
            menu.addAction(tr("Esporta questa base…"),
                           lambda folder=f: self.export_watchlist(folder))
            menu.addAction(tr("Rinomina cartella…"), lambda folder=f: self._rename_folder(folder))
            menu.addAction(tr("Elimina il gruppo…"),
                           lambda folder=f: self._delete_folder(folder))
        menu.addSeparator()
        menu.addAction(tr("Nuova base…"), lambda: self.open_deck())
        menu.addAction(tr("Importa mazzo (.ydk)…"), self.import_ydk)
        menu.addAction(tr("Nuova cartella…"), lambda: self._new_folder())
        menu.addSeparator()
        menu.addAction(tr("Esporta tutto…"), lambda: self.export_watchlist())
        menu.addAction(tr("Importa da file…"), self.import_watchlist)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _move_and_reload(self, watch_id, dest_fid) -> None:
        self._move_watch(watch_id, dest_fid)
        self._reload_table()
        self._flash_watch(watch_id)

    def _new_folder(self, move_watch_id=None) -> None:
        name, ok = QInputDialog.getText(self, tr("Nuova cartella"), tr("Nome della cartella:"))
        if not ok or not name.strip():
            return
        fid = self.repo.add_folder(PROVIDER, name.strip())
        if move_watch_id is not None:
            self._move_watch(move_watch_id, fid)
        self._reload_table()
        if move_watch_id is not None:
            self._flash_watch(move_watch_id)
        else:
            self._flash_folder(fid)

    # ------------------------------------------------------------- basi (mazzi)
    def _deck_search(self, text: str) -> list:
        """Ricerca per il dialogo della base: stesso indice "a token" della
        barra principale, così i risultati sono identici."""
        words = text.lower().split()
        out = []
        for low, label in self._search_index:
            if all(w in low for w in words):
                ref = self._label_to_ref.get(label)
                if ref is not None:
                    out.append((label, ref))
                if len(out) >= 60:
                    break
        return out

    def _edit_deck_filters(self, current_json: str):
        """Editor dei filtri usato DENTRO il dialogo della base.
        Ritorna il nuovo JSON ('' = predefiniti) o None se annullato."""
        base = self._parse_filters(current_json) or self._filters
        dlg = FiltersDialog(base, self, allow_global=True,
                            use_global=not current_json,
                            title=tr("Filtri della base"))
        if dlg.open_near() != QDialog.DialogCode.Accepted:
            return None
        return "" if dlg.uses_global() else json.dumps(dlg.result_filters().to_dict())

    def open_deck(self, folder=None) -> None:
        """Crea o modifica una base: nome, filtri comuni, carte e copie."""
        if self.repo.all_catalog(PROVIDER) == []:
            QMessageBox.information(self, tr("Catalogo vuoto"),
                                    tr("Sincronizza prima il catalogo per cercare le carte"))
            return
        cards = []
        name = filters_json = ""
        if folder is not None:
            name = folder["name"]
            filters_json = folder["filters"] if "filters" in folder.keys() else ""
            for w in self.repo.list_watches():
                if w["provider"] == PROVIDER and w["folder_id"] == folder["id"]:
                    # con l'immagine, altrimenti nell'elenco della base le
                    # carte già presenti sarebbero le uniche senza miniatura
                    exact, stock = self._image_urls_for(str(w["ref_id"]), w["card_name"])
                    cards.append((CardRef(id=str(w["ref_id"]), name=w["card_name"],
                                          detail=w["detail"] or "",
                                          image_url=exact or stock),
                                  w["copies"] if "copies" in w.keys() else 1))
        dlg = DeckDialog(self._deck_search, name=name, filters_json=filters_json,
                         cards=cards, filters_editor=self._edit_deck_filters,
                         thumb_items=self._completer_items,      # stesse miniature
                         resolve=self._label_to_ref.get, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_deck(folder, dlg.result_name(), dlg.result_filters_json(), dlg.result_cards())

    def _save_deck(self, folder, name: str, filters_json: str, cards: list) -> None:
        if folder is None:
            fid = self.repo.add_folder(PROVIDER, name, filters_json, is_deck=True)
        else:
            fid = folder["id"]
            self.repo.rename_folder(fid, name)
            self.repo.set_folder_filters(fid, filters_json)
            # passare dall'editor delle basi la promuove: da qui in poi si
            # mostra come base, non come cartella
            self.repo.set_folder_deck(fid, True)
        existing = {w["ref_id"]: w for w in self.repo.list_watches()
                    if w["provider"] == PROVIDER}
        wanted = {ref.id for ref, _c in cards}
        for ref, copies in cards:
            watch = existing.get(ref.id)
            if watch is None:
                self.repo.add_watch(PROVIDER, ref.id, ref.name, ref.detail,
                                    self.threshold_spin.value(), "", copies)
                watch = [w for w in self.repo.list_watches() if w["ref_id"] == ref.id][0]
            else:
                self.repo.set_watch_copies(watch["id"], copies)
            if watch["folder_id"] != fid:
                self._move_watch(watch["id"], fid)
        # Carte tolte dalla base: NON si cancellano dalla watchlist (si
        # perderebbe lo storico prezzi), escono solo dalla base.
        for watch in existing.values():
            if watch["folder_id"] == fid and watch["ref_id"] not in wanted:
                self._move_watch(watch["id"], None)
        self._refresh_folder_cache()
        self._reload_table()
        self._flash_folder(fid)
        copies_tot = sum(c for _r, c in cards)
        self._set_busy(False, tr("Base «{name}»: {n} carte, {c} copie. Controllo i prezzi…")
                       .format(name=name, n=len(cards), c=copies_tot))
        self.check_now()

    # --- messaggi da altri moduli (ponte via AppContext.open_module) ---
    def handle_request(self, payload) -> bool:
        """Riceve una carta da un altro modulo (oggi: il Database).

        Si riceve un NOME, non un id: i cataloghi sono diversi — YGOPRODeck
        ragiona per carta, CardTrader per STAMPA (rarità + espansione), e la
        stessa carta ha decine di stampe a prezzi diversissimi. Sceglierne una
        al posto dell'utente sarebbe inventare: qui si compila la ricerca e si
        apre l'elenco, la stampa la decide lui.
        """
        nome = ""
        if isinstance(payload, dict):
            nome = str(payload.get("card_name") or "")
        elif isinstance(payload, str):
            nome = payload
        if not nome:
            return False
        if self._overview:
            self.overview_btn.setChecked(False)   # la ricerca è nascosta lì
        self.search_input.setText(nome)
        self.search_input.setFocus()
        self._on_search_text(nome)          # azzera la selezione precedente
        self._apply_search_filter(nome)     # e apre subito l'elenco delle stampe
        self._set_busy(False, tr("Cerca «{nome}»: scegli la stampa da seguire.")
                       .format(nome=nome))
        return True

    # --- storico prezzi (grafico) ---
    def _on_cell_double_clicked(self, row: int, _col: int) -> None:
        entry = self._row_entries[row] if 0 <= row < len(self._row_entries) else None
        if entry is not None and entry[0] == "watch":
            self._open_history(entry[1], row)

    def _thumb_rect_on_screen(self, row: int):
        """Rettangolo della MINIATURA di quella riga in coordinate schermo: è
        il punto da cui far nascere il grafico. None se la riga non è a
        schermo (tabella scrollata): in quel caso il pop-up parte dal centro,
        che è meglio di farlo sbucare da un punto sbagliato."""
        item = self.table.item(row, 0)
        if item is None:
            return None
        rect = self.table.visualItemRect(item)
        if rect.isEmpty() or not self.table.viewport().rect().intersects(rect):
            return None
        return QRect(self.table.viewport().mapToGlobal(rect.topLeft()), rect.size())

    def _history_art(self, ref_id: str, name: str):
        """La migliore immagine GIÀ DISPONIBILE per la finestra dello storico,
        senza scaricare niente: prima l'anteprima grande in cache, poi la
        miniatura della riga (sgranata, ma c'è mentre la grande arriva).

        Ritorna anche l'URL che varrebbe la pena avere, così chi apre la
        finestra sa se serve una richiesta — UNA, la stessa che farebbe
        selezionando la riga, non una raffica (vedi GOTCHA 1)."""
        exact, stock = self._image_urls_for(ref_id, name)
        voluto, voluto_stock = "", False
        for url, is_stock in ((exact, False), (stock, True)):
            if url and url not in self._failed_images:
                voluto, voluto_stock = url, is_stock
                break
        if voluto:
            pixmap = self._img_cache.get(voluto)
            if pixmap is not None:
                return (stock_pixmap(voluto, pixmap) if voluto_stock else pixmap,
                        voluto, voluto_stock)
        for url, is_stock in ((exact, False), (stock, True)):
            turl = _thumb_url(url)
            if turl and turl not in self._failed_thumbs:
                pixmap = self._row_thumb_cache.get(turl)
                if pixmap is not None:
                    return (stock_pixmap(turl, pixmap) if is_stock else pixmap,
                            voluto, voluto_stock)
        return None, voluto, voluto_stock

    def _open_history(self, watch, row: int | None = None) -> None:
        """Apre il grafico dello storico. I dati sono già nel DB: nessuna
        richiesta di rete, quindi il gesto è gratuito e sempre disponibile."""
        ref_id = str(watch["ref_id"])
        rows = self.repo.history_points(PROVIDER, ref_id)
        runs = split_runs(rows)
        chiave = self._watch_key(watch)
        # Se l'ultima corsa NON è quella dei filtri di adesso (filtri appena
        # cambiati e nessun controllo ancora fatto), la corsa attuale è vuota:
        # meglio dirlo che mostrare i prezzi di un'altra versione come se
        # fossero questi.
        if runs and runs[-1].key != chiave:
            runs = runs + [Run(chiave, [], runs[-1].currency)]
        dlg = HistoryDialog(
            watch["card_name"],
            watch["detail"] if "detail" in watch.keys() else "",
            self._filters_summary(self._effective_filters(watch)),
            runs, self, self._scale)
        art, voluto, voluto_stock = self._history_art(ref_id, watch["card_name"])
        dlg.set_card_pixmap(art)
        dlg.expect_image(voluto, voluto_stock)
        # Se l'immagine grande non c'è ancora, la si chiede UNA volta — la
        # stessa richiesta che parte selezionando la riga. Se un download è
        # già in corso non se ne accoda un altro: basta aspettare, ci pensa
        # `_on_image_done` a passarla alla finestra.
        in_corso = self._img_worker is not None and self._img_worker.isRunning()
        if voluto and self._img_cache.get(voluto) is None and not in_corso:
            esatta, _ = self._image_urls_for(ref_id, watch["card_name"])
            self._show_image(esatta, watch["card_name"])
        self._history_dlg = dlg
        try:
            dlg.open_from(self._thumb_rect_on_screen(row) if row is not None else None)
        finally:
            self._history_dlg = None

    # --- apertura della pagina su CardTrader ---
    CARD_PAGE = "https://www.cardtrader.com/cards/{ref_id}"

    @staticmethod
    def _filters_summary(f) -> str:
        """I filtri in vigore, in una riga leggibile."""
        pezzi = []
        if f.language:
            pezzi.append(f.language.upper())
        if f.min_condition:
            pezzi.append(f.min_condition)
        if f.first_edition_only:
            pezzi.append(tr("1ª ed."))
        if f.zero_only:
            pezzi.append("Zero")
        if f.exclude_graded:
            pezzi.append(tr("no graded"))
        if f.pro_only:
            pezzi.append("PRO")
        if f.american_only:
            pezzi.append("USA")
        return " · ".join(pezzi)

    def _card_page_tip(self, watch) -> str:
        """VERIFICATO sul sito (2026-07-29): la pagina carta applica i filtri
        con una POST a `filter.json` e NON li mette mai nell'URL — passarli nel
        link non funziona, restano lì ignorati. Invece di fingere, il tooltip
        elenca quali sono in vigore qui, così si ritrovano in due secondi."""
        tip = tr("Apri la carta su CardTrader")
        attivi = self._filters_summary(self._effective_filters(watch))
        if attivi:
            tip += "\n" + tr("CardTrader non accetta i filtri nel link: là vanno "
                             "rimessi a mano ({filtri})").format(filtri=attivi)
        return tip

    def _open_card_page(self, ref_id: str) -> None:
        """Basta l'id del blueprint: il sito reindirizza alla pagina giusta
        (verificato dal vivo, /cards/382653 → /it/cards/382653-dominus-purge-…)."""
        QDesktopServices.openUrl(QUrl(self.CARD_PAGE.format(ref_id=ref_id)))

    # ------------------------------------------------------- importa un .ydk
    def import_ydk(self) -> None:
        """Un mazzo `.ydk` diventa una base, scegliendo le stampe.

        Il file porta *passcode* e quantità, niente rarità: la traduzione in
        nomi richiede il catalogo del Database, e la stampa la sceglie
        l'utente nel dialogo (vedi `ydk_dialog`).
        """
        stato, dettaglio = self.repo.card_catalog_status()
        if stato in ("assente", "vuota"):
            # non l'ha mai sincronizzato: la cura è sincronizzare
            QMessageBox.information(
                self, tr("Importa mazzo (.ydk)"),
                tr("Serve prima il catalogo delle carte. Apri il modulo "
                   "Database e sincronizzalo: in un file .ydk ci sono solo i "
                   "codici delle carte, e senza catalogo non si possono "
                   "tradurre in nomi."))
            return
        if stato != "ok":
            # la tabella c'è ma non si legge: mandarlo a sincronizzare sarebbe
            # un giro a vuoto — la sincronizzazione riscrive le righe, non la
            # forma della tabella
            self._say_catalog_broken(stato, dettaglio)
            return
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Importa un mazzo"), str(Path.home()),
            tr("Mazzi Yu-Gi-Oh! (*.ydk)"))
        if not path:
            return
        try:
            deck = ydk.parse_file(path)
        except OSError as exc:
            QMessageBox.warning(self, tr("Importa mazzo (.ydk)"), str(exc))
            return
        if not deck.cards:
            QMessageBox.information(
                self, tr("Importa mazzo (.ydk)"),
                tr("Nel file non c'è nessuna carta."))
            return
        try:
            voci, sconosciuti = self._resolve_ydk(deck)
        except CardCatalogError as exc:
            self._say_catalog_broken(exc.stato, exc.dettaglio)
            return
        if not voci:
            QMessageBox.information(
                self, tr("Importa mazzo (.ydk)"),
                tr("Nessuno dei {n} codici del file è nel catalogo delle "
                   "carte. Se il Database è vecchio, sincronizzalo.").format(
                       n=len(deck.cards)))
            return
        dlg = YdkImportDialog(voci, unknown=sconosciuti, ignored=deck.ignored,
                              default_name=Path(path).stem,
                              filters_editor=self._edit_deck_filters, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_deck(None, dlg.result_name(), dlg.result_filters_json(),
                        dlg.result_cards())

    def _say_catalog_broken(self, stato: str, dettaglio: str) -> None:
        """Il catalogo c'è ma non si legge: si dice COSA e cosa farci.

        Sincronizzare non serve (riscrive le righe, non la forma della
        tabella), quindi non lo si consiglia: si dice il problema per nome.
        """
        if stato == "incompleta":
            testo = tr("Il catalogo delle carte ha una forma diversa da quella "
                       "attesa: mancano le colonne {dettaglio}.")
        else:
            testo = tr("Il catalogo delle carte non si riesce a leggere: "
                       "{dettaglio}.")
        QMessageBox.warning(
            self, tr("Importa mazzo (.ydk)"),
            testo.format(dettaglio=dettaglio or "?") + "\n\n"
            + tr("Sincronizzare il Database NON risolve: riscrive le righe, "
                 "non la forma della tabella. Esporta la watchlist (tasto "
                 "destro → Esporta tutto…), chiudi l'app, cancella "
                 "~/.ygo_toolbox/ygo_toolbox.db e risincronizza."))

    def _resolve_ydk(self, deck) -> tuple[list, list]:
        """passcode → carta + tutte le sue stampe. Chi non si traduce esce a
        parte, per essere mostrato: un codice ignoto è un dato mancante."""
        righe = self.repo.cards_by_passcode([c.passcode for c in deck.cards])
        voci, sconosciuti = [], []
        for carta in deck.cards:
            riga = righe.get(carta.passcode)
            if riga is None:
                sconosciuti.append(carta.passcode)
                continue
            nome = riga["name"]
            voci.append({
                "passcode": carta.passcode,
                "name": nome,
                "name_it": riga["name_it"] or "",
                "thumb_url": riga["image_small_url"] or riga["image_url"] or "",
                "copies": carta.total,
                # si spiega il totale solo quando viene da più sezioni
                "sections": carta.sections_label() if carta.split else "",
                "printings": sort_printings(self.repo.printings(PROVIDER, nome)),
            })
        return voci, sconosciuti

    # ------------------------------------------------- esporta / importa (JSON)
    def export_watchlist(self, folder=None) -> None:
        """Salva su file. Con `folder` esporta SOLO quella base (senza storico
        né preferenze: è il file da passare a un amico); senza, esporta tutto."""
        suggerito = (f"ygo-{folder['name']}.json" if folder is not None
                     else "ygo-watchlist.json")
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Esporta la watchlist"),
            str(Path.home() / suggerito), tr("File JSON (*.json)"))
        if not path:
            return
        # storico e preferenze li include (o esclude) `export_data` da sé,
        # in base al fatto che si stia esportando tutto o una sola base
        dati = transfer.export_data(
            self.repo, PROVIDER, app_version=APP_VERSION,
            only_folder_id=(folder["id"] if folder is not None else None))
        try:
            transfer.write_file(path, dati)
        except OSError as exc:
            QMessageBox.warning(self, tr("Esportazione"), str(exc))
            return
        self._set_busy(False, tr("Esportato in {file} — {cosa}").format(
            file=Path(path).name, cosa=transfer.describe(dati)))

    def import_watchlist(self) -> None:
        """Legge un file e chiede COME applicarlo, dopo aver detto cosa contiene:
        una scelta fra 'aggiungi' e 'sostituisci' va fatta sapendo cosa arriva."""
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Importa una watchlist"), str(Path.home()),
            tr("File JSON (*.json)"))
        if not path:
            return
        try:
            dati = transfer.read_file(path)
        except transfer.TransferError as exc:
            QMessageBox.warning(self, tr("Importazione"), str(exc))
            return
        box = QMessageBox(self)
        box.setWindowTitle(tr("Importazione"))
        box.setText(tr("Il file contiene: {cosa}.").format(cosa=transfer.describe(dati)))
        box.setInformativeText(tr(
            "«Aggiungi» unisce al tuo elenco (le carte già presenti vengono "
            "aggiornate con quanto dice il file).\n"
            "«Sostituisci» svuota la watchlist e ci mette il contenuto del file."))
        aggiungi = box.addButton(tr("Aggiungi"), QMessageBox.ButtonRole.AcceptRole)
        sostituisci = box.addButton(tr("Sostituisci"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(tr("Annulla"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(aggiungi)
        box.exec()
        scelto = box.clickedButton()
        if scelto not in (aggiungi, sostituisci):
            return
        replace = scelto is sostituisci
        if replace and QMessageBox.question(
                self, tr("Sostituire?"),
                tr("La watchlist attuale ({n} carte) verrà cancellata. Procedere?")
                .format(n=len([w for w in self.repo.list_watches()
                               if w["provider"] == PROVIDER]))
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            esito = transfer.import_data(self.repo, PROVIDER, dati, replace=replace)
        except Exception as exc:      # un file storto non deve buttare giù l'app
            QMessageBox.warning(self, tr("Importazione"), str(exc))
            return
        if replace:                   # le preferenze possono essere cambiate
            self._filters = ListingFilters.from_dict(self._load_filters())
            self._display = self._load_display()
            self._load_sort()
            self._refresh_sort_buttons()
            if self.provider is not None:
                self.provider.filters = self._filters
        self._refresh_folder_cache()
        self._rebuild_completer()
        self._reload_table()
        self._set_busy(False, tr(
            "Importate: {agg} nuove, {upd} aggiornate, {cart} cartelle, "
            "{st} punti di storico.").format(agg=esito["aggiunte"],
                                             upd=esito["aggiornate"],
                                             cart=esito["cartelle"],
                                             st=esito["storico"]))
        self.check_now()

    def _ask_copies(self, watch_id, card_name: str, current: int) -> None:
        value, ok = QInputDialog.getInt(
            self, tr("Copie"), tr("Quante copie di {name}?").format(name=card_name),
            current, 1, 99)
        if not ok:
            return
        self.repo.set_watch_copies(watch_id, value)
        self._reload_table()

    def _rename_folder(self, folder) -> None:
        name, ok = QInputDialog.getText(self, tr("Rinomina cartella"), tr("Nuovo nome:"),
                                        text=folder["name"])
        if ok and name.strip():
            self.repo.rename_folder(folder["id"], name.strip())
            self._reload_table()

    @staticmethod
    def _folder_field(folder, chiave, default=None):
        """Campo di una cartella, che arrivi da SQLite o da un dizionario."""
        try:
            return folder[chiave]
        except (KeyError, IndexError):
            return default

    def _watches_in_folder(self, folder_id) -> list:
        return [w for w in self.repo.list_watches()
                if w["provider"] == PROVIDER and w["folder_id"] == folder_id]

    def _delete_folder(self, folder) -> None:
        """Eliminare un gruppo PIENO chiede prima — e chiede *cosa*.

        Prima toglieva e basta, all'istante: un clic sul cestino smontava una
        base da quaranta carte senza una parola. Il risultato non sembrava
        nemmeno un'eliminazione — la cartella spariva e le carte restavano
        sparse nella watchlist, così al riavvio dava l'impressione che la base
        si fosse "sfaldata da sola".
        Erano due mancanze in una: nessuna conferma, e nessun modo di buttare
        via la base **insieme** alle sue carte, che è la cosa che si vuole
        fare quando un mazzo non interessa più.
        Un gruppo vuoto non chiede niente: non c'è nulla da perdere.
        """
        dentro = self._watches_in_folder(folder["id"])
        if not dentro:
            self._do_delete_folder(folder, con_carte=False)
            return
        nome = self._folder_field(folder, "name", "") or ""
        e_base = bool(self._folder_field(folder, "is_deck", 0))
        copie = sum(w["copies"] if "copies" in w.keys() else 1 for w in dentro)
        box = QMessageBox(self)
        box.setWindowTitle(tr("Elimina la base") if e_base
                           else tr("Elimina la cartella"))
        box.setText(tr("«{nome}» contiene {n} carte ({c} copie).").format(
            nome=nome, n=len(dentro), c=copie))
        box.setInformativeText(tr(
            "«Solo il gruppo» scioglie il raggruppamento: le carte restano "
            "nella watchlist con il loro storico prezzi.\n"
            "«Gruppo e carte» elimina anche le carte e il loro storico."))
        solo = box.addButton(tr("Solo il gruppo"),
                             QMessageBox.ButtonRole.AcceptRole)
        tutto = box.addButton(tr("Gruppo e carte"),
                              QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(tr("Annulla"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(solo)      # il predefinito è quello che non perde
        box.exec()
        scelto = box.clickedButton()
        if scelto is solo:
            self._do_delete_folder(folder, con_carte=False)
        elif scelto is tutto:
            self._do_delete_folder(folder, con_carte=True)

    def _do_delete_folder(self, folder, con_carte: bool = False) -> None:
        """Elimina davvero. `con_carte=True` porta via anche le carte."""
        if con_carte:
            for w in self._watches_in_folder(folder["id"]):
                self.repo.remove_watch(w["id"])   # toglie anche storico e quote
        self.repo.delete_folder(folder["id"])
        # senza, `_effective_filters` continuerebbe a leggere una cartella morta
        self._refresh_folder_cache()
        self._reload_table()

    def _maybe_welcome(self) -> None:
        """Card di benvenuto SOLO al primo avvio assoluto: se c'è già un token
        l'utente è un veterano e il flag viene marcato in silenzio."""
        if self.repo.get_setting("welcomed"):
            return
        self.repo.set_setting("welcomed", "1")
        if self.provider is not None:
            return
        WelcomeDialog(self).open_near()   # centrata sulla finestra

    # --------------------------------------------------- controllo prezzi
    def _startup_check(self) -> None:
        """Controllo automatico all'apertura dell'app (silenzioso: parte solo
        se c'è il token e la watchlist non è vuota, niente popup)."""
        if self.provider is not None and self.repo.list_watches():
            self._set_busy(True, tr("Controllo automatico all'avvio…"))
            self.check_now()

    def check_now(self) -> None:
        if self.provider is None:
            QMessageBox.information(self, tr("Token mancante"), tr("Imposta prima il token CardTrader."))
            return
        watches = [w for w in self.repo.list_watches() if w["provider"] == PROVIDER]
        if not watches:
            self._set_busy(False, tr("Watchlist vuota."))
            return
        if self._price_worker is not None and self._price_worker.isRunning():
            return
        # Il controllo è il gesto "aggiorna tutto": è l'occasione buona per
        # riprovare le immagini perse (un 403 di Cloudflare è temporaneo).
        # Altrimenti un segnaposto resterebbe lì fino al riavvio.
        self._failed_thumbs.clear()
        self._failed_images.clear()
        self._refresh_folder_cache()   # i filtri effettivi dipendono dalle basi
        self._set_busy(True, tr("Controllo prezzi su CardTrader…"))
        jobs = [(w["ref_id"], self._effective_filters(w),
                 w["copies"] if "copies" in w.keys() else 1) for w in watches]
        self._price_worker = PriceFetchWorker(self.provider, jobs)
        self._price_worker.finished_ok.connect(self._on_prices)
        self._price_worker.progress.connect(self._on_price_progress)
        self._price_worker.failed.connect(self._on_error)
        self._price_worker.start()

    def _on_price_progress(self, done: int, total: int) -> None:
        """Le chiamate sono spaziate per non farsi limitare dall'API: su molte
        carte il controllo dura, quindi va mostrato che sta lavorando."""
        self._set_busy(True, tr("Controllo prezzi su CardTrader… {done}/{total}")
                       .format(done=done, total=total))

    def _on_error(self, message: str) -> None:
        self.sync_btn.setEnabled(self.provider is not None)
        self._save_rate_interval()
        self._set_busy(False, tr("Errore: {msg}").format(msg=message))

    def _on_prices(self, results: list[dict], failed: int = 0, last_error: str = "") -> None:
        # AGGIORNAMENTO PARZIALE: `results` contiene solo le carte davvero
        # controllate. Le altre mantengono prezzo e stato precedenti — non
        # vanno azzerate né scambiate per "Nessuna copia".
        for result in results:
            self._last_quotes[result["ref_id"]] = result["quote"]
        watches = {w["ref_id"]: w for w in self.repo.list_watches() if w["provider"] == PROVIDER}
        for result in results:
            watch = watches.get(result["ref_id"])
            quote = result["quote"]
            if watch is None or quote is None:
                continue  # nessun annuncio attivo per questa carta
            # confronto SOLO con i prezzi rilevati con gli stessi filtri: dopo
            # un cambio di filtri il prezzo è di un altro prodotto, e un calo
            # inventato non deve né comparire in Var. né far scattare l'avviso
            key = self._watch_key(watch)
            old = self.repo.last_price(PROVIDER, result["ref_id"], key)
            new = quote.amount
            self.repo.record_price(PROVIDER, result["ref_id"], new, quote.currency, key)
            if old is not None and new < old:
                drop_pct = (old - new) / old * 100.0
                if drop_pct >= watch["threshold_pct"]:
                    self.context.notifier.notify(
                        tr("Nuovo prezzo più basso su CardTrader"),
                        f"{watch['card_name']}: {old:.2f} € → {new:.2f} € (-{drop_pct:.1f}%)",
                    )
        # carte per cui nessun annuncio soddisfa i filtri (o nessun annuncio
        # attivo) — solo fra quelle controllate ora
        for result in results:
            if result["quote"] is None:
                self._no_match_refs.add(result["ref_id"])
            else:
                self._no_match_refs.discard(result["ref_id"])
        # persiste l'ultimo annuncio per carta (upsert, '' = "Nessuna copia"):
        # al riavvio la Panoramica riparte da qui invece che vuota
        self.repo.set_last_quotes(PROVIDER, [
            (r["ref_id"], json.dumps(r["quote"].to_dict()) if r["quote"] is not None else "")
            for r in results
        ])
        checked = datetime.now().strftime("%d/%m %H:%M")
        self.repo.set_setting("last_checked", checked)
        self._save_rate_interval()
        self._render_after_check(checked)
        if failed:
            # controllo incompleto: dirlo, ma i prezzi arrivati sono già salvati
            self._set_busy(False, tr(
                "Controllo parziale ({done} carte su {total}): {n} non aggiornate. {msg}"
            ).format(done=len(results), total=len(results) + failed, n=failed, msg=last_error))
        else:
            self._set_busy(False, tr("Ultimo controllo: {when}.").format(when=checked))

    def _render_after_check(self, checked: str, pulse: bool = True) -> None:
        # updates sospesi durante il rebuild: un solo repaint alla fine
        # (niente sfarfallio quando si ricreano righe e cell widget)
        self.table.setUpdatesEnabled(False)
        try:
            self._do_render(checked, pulse)
            self._sweep_orphan_cell_widgets()
        finally:
            self.table.setUpdatesEnabled(True)

    def _sweep_orphan_cell_widgets(self) -> None:
        """Butta i cell widget FANTASMA rimasti dai render precedenti.

        I primi render avvengono prima che le colonne abbiano la larghezza
        definitiva, quindi i pulsanti Azioni di allora restavano appiccicati a
        SINISTRA — si vedevano due iconcine davanti al nome della cartella.
        La spazzata sta in `search_model` perché serve anche all'elenco della
        base, che si ricostruisce a ogni carta aggiunta."""
        sweep_orphan_cell_widgets(self.table)

    def _do_render(self, checked: str, pulse: bool) -> None:
        self._last_checked = checked
        self._refresh_folder_cache()   # i filtri di base servono qui sotto
        watches = self.repo.list_watches()
        folders = self.repo.list_folders(PROVIDER)
        by_folder: dict = {}
        for w in watches:
            fid = w["folder_id"] if "folder_id" in w.keys() else None
            by_folder.setdefault(fid, []).append(w)
        # Riepilogo per l'intestazione di cartella: valore totale e sua
        # variazione. La variazione è quella del TOTALE (somma di adesso vs
        # somma di prima), non la media delle percentuali: così una carta da
        # 200 € pesa quanto vale, coerente col totale mostrato accanto.
        # Le carte senza uno storico precedente entrano identiche in entrambe
        # le somme, quindi non falsano il segno.
        # Prezzo e variazione di ogni carta, calcolati UNA volta: servono al
        # riepilogo delle basi, all'ordinamento e alle righe. Prima ogni pezzo
        # se li ricavava per conto suo, interrogando il DB tre volte per carta.
        metrics: dict[str, tuple] = {}
        for w in watches:
            prices = self.repo.last_price_change(w["provider"], w["ref_id"],
                                                 self._watch_key(w))
            last = prices[0] if prices else None
            prev = prices[1] if len(prices) > 1 else None
            change = ((last - prev) / prev * 100.0) if (last is not None
                                                        and prev not in (None, 0)) else None
            metrics[str(w["ref_id"])] = (last, change, prices)

        # Le COPIE moltiplicano: una base con 3× Ash Blossom vale tre Ash
        # Blossom. Vale per il totale e, di conseguenza, per la sua variazione.
        summary: dict = {}
        for fid, ws in by_folder.items():
            if fid is None:
                continue
            # Due grandezze DIVERSE, tenute separate apposta:
            #  - `totale`  = quanto costa davvero comprare tutto oggi (le copie
            #    più economiche disponibili, anche da venditori diversi);
            #  - `ora`/`prima` = movimento dei PREZZI (unitari, pesati per le
            #    copie), che è ciò che misura la Var.
            # Mescolarle darebbe una percentuale calcolata fra due unità di
            # misura diverse, cioè un numero senza significato.
            totale = ora = prima = 0.0
            copies_tot = 0
            comparable = False   # almeno una carta ha un prezzo precedente VERO
            for w_ in ws:
                n = w_["copies"] if "copies" in w_.keys() else 1
                copies_tot += n
                if str(w_["ref_id"]) in self._no_match_refs:
                    continue
                prices = metrics[str(w_["ref_id"])][2]
                if not prices:
                    continue
                q_ = self._last_quotes.get(str(w_["ref_id"]))
                reale = getattr(q_, "total", 0.0) if q_ is not None else 0.0
                totale += reale if (n > 1 and reale) else prices[0] * n
                ora += prices[0] * n
                prima += (prices[1] if len(prices) > 1 else prices[0]) * n
                comparable = comparable or len(prices) > 1
            # senza nemmeno un precedente vero il conto darebbe 0.0%, che si
            # legge come "non si è mosso" invece che "non lo so ancora"
            delta = ((ora - prima) / prima * 100.0) if (comparable and prima) else None
            summary[fid] = (totale, delta, copies_tot)
        # modello visuale: cartelle (con le loro carte, se espanse) e poi le
        # carte fuori dalle cartelle
        def con_provenienze(w):
            """La carta e, se aperta, da dove arrivano le sue copie."""
            righe = [("watch", w)]
            for src in self._visible_sources(w):
                righe.append(("source", (w, src)))
            return righe

        # L'ordinamento agisce DENTRO ogni gruppo (e fra le carte sciolte): le
        # cartelle e le basi restano cartelle e basi.
        ordina = {ref: (m[0], m[1]) for ref, m in metrics.items()}
        entries: list[tuple[str, object]] = []
        for f in folders:
            entries.append(("folder", f))
            if f["expanded"]:
                for w in self._sorted_cards(by_folder.get(f["id"], []), ordina):
                    entries.extend(con_provenienze(w))
        for w in self._sorted_cards(by_folder.get(None, []), ordina):
            entries.extend(con_provenienze(w))
        self._row_entries = entries

        self.table.clearSpans()   # eredità delle versioni con la riga a span
        self.table.setRowCount(len(entries))
        # gruppi da evidenziare: dalla riga della cartella all'ultima carta
        # che contiene (se chiusa, il gruppo è la sola intestazione)
        groups: list[tuple[int, int]] = []
        for row, (kind, _payload) in enumerate(entries):
            if kind == "folder":
                groups.append((row, row))
            elif groups and groups[-1][1] == row - 1 and self._folder_at(row) is not None:
                groups[-1] = (groups[-1][0], row)
        self.table.set_groups(groups)
        default_h = self.table.verticalHeader().defaultSectionSize()
        for row, (kind, payload) in enumerate(entries):
            if kind == "folder":
                total, delta, copies_tot = summary.get(payload["id"], (0.0, None, 0))
                self._set_folder_row(row, payload,
                                     len(by_folder.get(payload["id"], [])),
                                     total, delta, copies_tot)
                continue
            if kind == "source":
                self._set_source_row(row, payload[0], payload[1])
                continue
            self.table.setRowHeight(row, default_h)  # annulla eventuali altezze da cartella
            watch = payload
            no_match = str(watch["ref_id"]) in self._no_match_refs
            last, change, _prices = metrics[str(watch["ref_id"])]
            self._set_row(row, watch, last_price=last, change=change, checked=checked, no_match=no_match)
            if pulse and change and not no_match:  # cella prezzo "lampeggia" al cambio
                price_item = self.table.item(row, 8)
                if price_item is not None:
                    color = theme.POSITIVE if change >= 0 else theme.NEGATIVE
                    anim.pulse_item(price_item, color, self.table)

    def _set_source_row(self, row: int, watch, src: dict) -> None:
        """Riga "da qui arrivano N copie": una per venditore che contribuisce.

        Vive sotto la carta, incolonnata come lei, e mostra solo ciò che
        distingue un'offerta dall'altra — quantità presa, prezzo unitario,
        condizione/lingua e venditore. Niente Var. né soglia: sono della
        carta, non della singola offerta."""
        for c in range(16):
            self.table.removeCellWidget(row, c)
            self.table.setItem(row, c, QTableWidgetItem(""))

        def cell(text: str = "") -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setForeground(QColor(theme.TEXT_MUTED))
            return it

        qty = int(src.get("qty") or 1)
        unit = float(src.get("amount") or 0.0)
        for c in range(16):
            self.table.setItem(row, c, cell())
        # 1 Nome: "↳ 2 copie" — l'indentazione la mette _IndentDelegate
        self.table.setItem(row, 1, cell("↳  " + (
            tr("1 copia") if qty == 1 else tr("{n} copie").format(n=qty))))
        self._set_badge_cells(row, src.get("condition") or "", src.get("language") or "")
        for col, flag in ((6, src.get("first_edition")), (7, src.get("zero"))):
            it = cell("✓" if flag else "—")
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if flag:
                it.setForeground(QColor(theme.ACCENT))
            self.table.setItem(row, col, it)
        # 8 Prezzo: costo di QUESTE copie (unitario nel tooltip)
        price = cell(f"{unit * qty:.2f} €")
        price.setToolTip(tr("{n} × {unit:.2f} € da {seller}").format(
            n=qty, unit=unit, seller=src.get("seller") or "?"))
        self.table.setItem(row, 8, price)
        # 12 Venditore, 13 commento, 14 quantità presa
        self.table.setItem(row, 12, cell(""))
        if src.get("seller") or src.get("country"):
            fake = PriceQuote(amount=unit, currency="EUR", seller=src.get("seller") or "",
                              seller_type=src.get("seller_type") or "",
                              country=src.get("country") or "")
            self.table.setCellWidget(row, 12, self._seller_cell(fake))
        comment = cell(src.get("comment") or "")
        comment.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.table.setItem(row, 13, comment)
        qty_item = cell(str(qty))
        qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 14, qty_item)
        # abbastanza alta da contenere la cella Venditore (nome + bandierina +
        # badge PRO): a 40px il nome finiva sopra le iconcine
        self.table.setRowHeight(row, self._rp(58))

    def _set_folder_row(self, row: int, folder, count: int, total: float = 0.0,
                        change: float | None = None, copies_tot: int = 0) -> None:
        """Riga-cartella allineata alle COLONNE, come se fosse una carta.

        Prima era un unico item spalmato su tutte le colonne (`setSpan`), con
        nome, conteggio e totale infilati nella stessa stringa: leggibile, ma
        scollegato dalle intestazioni. Ora il nome sta sotto "Nome", il totale
        sotto "Prezzo" e la variazione aggregata sotto "Var." — a cartella
        chiusa si legge il riepilogo con lo stesso colpo d'occhio delle carte."""
        expanded = bool(folder["expanded"])
        for c in range(16):   # via i resti di un eventuale render precedente
            self.table.removeCellWidget(row, c)
            self.table.setItem(row, c, QTableWidgetItem(""))

        band = QColor(theme.SURFACE_2)
        bold = QFont(self.table.font())
        bold.setBold(True)
        tip = tr("Clic per aprire/chiudere · trascina qui le carte per spostarle dentro")

        def band_cell(text: str = "") -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setBackground(band)
            it.setToolTip(tip)
            return it

        for c in range(15):   # fascia continua sotto tutta la riga (Azioni esclusa)
            self.table.setItem(row, c, band_cell())

        # 0 icona (al posto della miniatura: stessa colonna delle carte).
        # Base = carte impilate, cartella = cartella: si distinguono da lontano.
        is_deck = bool(folder["is_deck"]) if "is_deck" in folder.keys() else False
        icon_item = band_cell()
        icon_item.setIcon((_make_base_icon if is_deck else _make_folder_icon)
                          (expanded, self._rp(24)))
        self.table.setItem(row, 0, icon_item)

        # 1 Nome (+ conteggio come coda discreta: la cartella resta allineata
        #   ai nomi delle carte, che partono dalla stessa x). In Panoramica la
        #   colonna Nome è stretta e il conteggio ha già la sua casa in Q.tà:
        #   appenderlo lì troncherebbe il nome ("Da comprare …").
        counted = (tr("vuota") if not count else
                   (tr("1 carta") if count == 1 else tr("{n} carte").format(n=count)))
        if copies_tot > count:      # è una base: le copie sono l'informazione utile
            counted += "  ·  " + tr("{c} copie").format(c=copies_tot)
        name_item = band_cell(folder["name"] if not self.table.isColumnHidden(14)
                              else f"{folder['name']}   ·   {counted}")
        name_item.setFont(bold)
        shared = folder["filters"] if "filters" in folder.keys() else ""
        tip_filters = ("\n" + tr("Filtri propri della base")) if shared else ""
        name_item.setToolTip(f"{folder['name']} · {counted}{tip_filters}\n{tip}")
        self.table.setItem(row, 1, name_item)

        # 2 badge "BASE" (colonna Rarità, vuota sulle righe-cartella): la
        # parola toglie ogni dubbio dove l'icona da sola potrebbe non bastare
        if is_deck:
            self.table.setCellWidget(row, 2, self._pill_cell(
                _make_set_pill(tr("BASE"), self._rp(20)),
                tr("Base (mazzo): filtri comuni e copie")))

        # 8 Prezzo = valore totale della cartella
        total_item = band_cell(f"{total:.2f} €" if total > 0 else "—")
        total_item.setFont(bold)
        total_item.setToolTip(tr("Valore totale della cartella (somma degli ultimi prezzi noti)."))
        self.table.setItem(row, 8, total_item)

        # 9 Var. = variazione del VALORE TOTALE, non media delle percentuali:
        #   una carta da 200 € pesa più di una da 2 €, come nel totale sopra.
        change_item = band_cell("—" if change is None else f"{change:+.1f}%")
        if change is not None:
            change_item.setForeground(QColor(theme.POSITIVE) if change >= 0 else QColor(theme.NEGATIVE))
            change_item.setFont(bold)
        change_item.setToolTip(tr("Variazione del valore totale della cartella "
                                  "dall'ultimo cambio di prezzo."))
        self.table.setItem(row, 9, change_item)

        # 14 Q.tà = copie totali della base (o numero di carte, se nessuna
        # carta è in più copie): visibile in Panoramica
        qty_item = band_cell(str(copies_tot or count) if count else "")
        qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 14, qty_item)

        # azioni della cartella (colonna Azioni)
        actions = QWidget()
        actions.setStyleSheet("background: transparent;")
        arow = QHBoxLayout(actions)
        arow.setContentsMargins(0, 0, 0, 0)
        arow.setSpacing(2)
        icon_sz = QSize(self._rp(16), self._rp(16))
        for icon, tip, slot in (
            # la matita apre l'editor completo della base (nome, filtri, carte
            # e copie): rinominare è solo una delle cose che ci si vuole fare
            (self._pencil_icon, tr("Modifica la base: nome, filtri, carte e copie"),
             lambda _=False, f=folder: self.open_deck(f)),
            (self._trash_icon, tr("Elimina il gruppo (chiede se togliere anche le carte)"),
             lambda _=False, f=folder: self._delete_folder(f)),
        ):
            btn = QPushButton()
            btn.setObjectName("ghost")
            btn.setIcon(icon)
            btn.setIconSize(icon_sz)
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(slot)
            arow.addWidget(btn)
        self.table.setCellWidget(row, 15, actions)
        # NIENTE setSpan: le celle devono restare sotto le rispettive
        # intestazioni. (Lo span va comunque azzerato a ogni render — vedi
        # clearSpans() in _do_render — per i DB che vengono da versioni
        # precedenti già renderizzate con lo span.)
        self.table.setRowHeight(row, self._rp(44))

    # ----------------------------------------------------------- helpers
    def _apply_interval(self) -> None:
        self.timer.start(self.interval_spin.value() * 60 * 1000)

    def _set_busy(self, busy: bool, message: str) -> None:
        has_token = self.provider is not None
        self.check_btn.setEnabled(not busy and has_token)
        self.progress.setVisible(busy)
        self.status.setText(message)

    def stop(self) -> None:
        self.timer.stop()
        for worker in (self._price_worker, self._sync_worker, self._img_worker):
            if worker is not None and worker.isRunning():
                # prima CHIEDI di fermarsi (le attese del rate limit mollano
                # subito), poi aspetta: senza questo la chiusura può restare
                # appesa a un backoff da qualche secondo
                worker.requestInterruption()
                worker.wait(2000)
