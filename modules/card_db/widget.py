"""Modulo Database: la copia locale di YGOPRODeck, con ricerca e scheda.

Perché una copia locale e non un client che interroga a ogni tasto: la guida
di YGOPRODeck lo chiede espressamente (*"download and store all data pulled
from this API locally"*), e in cambio la ricerca diventa una query SQLite —
istantanea, e funziona anche senza rete.

L'unica cosa che resta online sono le **immagini**, prese una alla volta e
salvate su disco per sempre (vedi `images.py`).
"""
from __future__ import annotations

import json

from PySide6.QtCore import QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import anim, badges, i18n, theme
from core.context import AppContext
from core.i18n import tr
from core.rarity import is_rarity, rarity_pixmap, rarity_rank

from . import images
from .api import YgoProError
from .repository import CardDbRepository
from .workers import SetsWorker, SyncWorker, VersionWorker

THUMB = QSize(48, 70)          # miniatura di riga (proporzioni della carta)
ART = QSize(320, 466)          # immagine nella pagina della carta
RESULT_LIMIT = 300
CARD_RATIO = 59 / 86           # proporzioni di una carta Yu-Gi-Oh!

# Lingue in cui si può leggere una carta. L'inglese è la base (c'è sempre);
# l'italiano esiste per 11.599 carte su 14.477. Aggiungerne altre (l'API dà
# anche fr, de, pt) vuol dire un download in più per lingua in `SyncWorker` e
# una coppia di colonne: la lista sta qui apposta.
LANGUAGES = (("en", "EN"), ("it", "IT"))

# Aria da aggiungere all'icona per ottenere l'altezza della riga. NON è un
# margine estetico: il QSS del tema dà agli item della tabella 8px di padding
# sopra e sotto più un bordo da 1px, e senza tenerne conto l'icona da 70px in
# una riga da 78 ne riceve 61 e viene TAGLIATA sopra e sotto (visto dal vivo).
# È la stessa trappola del "numero delle copie illeggibile" nel deck_dialog.
ROW_PADDING = 8 + 8 + 1 + 2

# Colori dello stato in ban list. Sono un GIUDIZIO sulla carta, quindi devono
# essere leggibili come tali: rosso = non si gioca, arancio = una copia sola.
BAN_COLORS = {
    "Banned": theme.NEGATIVE,
    "Limited": theme.WARN,
    "Semi-Limited": "#93c5fd",
}
BAN_LABELS = {
    "Banned": "Vietata",
    "Limited": "Limitata",
    "Semi-Limited": "Semi-limitata",
}


def _pill(text: str, color: str, height: int = 20) -> QPixmap:
    """Badge arrotondato: testo colorato su fondo dello stesso colore, molto
    trasparente. Stessa forma dei badge del market_watch — colorare tutto il
    fondo darebbe righe di macchie accese."""
    font = QFont(theme.FONT_FAMILY)
    font.setPointSizeF(max(6.5, height * 0.42))
    font.setBold(True)
    metrics = QPixmap(1, 1)
    painter = QPainter(metrics)
    painter.setFont(font)
    larghezza = painter.fontMetrics().horizontalAdvance(text) + round(height * 0.9)
    painter.end()

    pixmap = QPixmap(max(1, larghezza), max(1, height))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    tinta = QColor(color)
    fondo = QColor(color)
    fondo.setAlpha(38)
    painter.setBrush(fondo)
    painter.setPen(QPen(QColor(color), 1))
    raggio = height / 2.0
    painter.drawRoundedRect(0.5, 0.5, pixmap.width() - 1, pixmap.height() - 1,
                            raggio, raggio)
    painter.setFont(font)
    painter.setPen(tinta)
    painter.drawText(pixmap.rect(), int(Qt.AlignmentFlag.AlignCenter), text)
    painter.end()
    return pixmap


def set_labels(gruppi: dict) -> dict:
    """Per ogni set, il codice più CORTO che resta univoco in questa carta.

    Normalmente basta il codice del set (`MACR`, `RA01`). Ma **142 codici sono
    condivisi da più espansioni** (misurato: `MVP1` sta per Movie Pack, Gold
    Edition, Secret Edition e Special Edition; `JUMP` copre 70 promo diverse):
    se una carta esce in due di quelle, due badge identici uno sopra l'altro
    sarebbero indistinguibili — ed è proprio il caso in cui la differenza
    conta. Per quelle righe si torna al codice completo della carta.

    `gruppi` = {nome del set: {"corto": codice set, "carta": codice carta}}."""
    quante: dict = {}
    for voce in gruppi.values():
        corto = voce.get("corto") or voce.get("carta") or "—"
        quante[corto] = quante.get(corto, 0) + 1
    etichette = {}
    for nome, voce in gruppi.items():
        corto = voce.get("corto") or voce.get("carta") or "—"
        etichette[nome] = corto if quante[corto] == 1 else (voce.get("carta") or corto)
    return etichette


def _svuota(layout, tieni_ultimo: bool = False) -> None:
    """Svuota un layout **staccando davvero** i widget dal genitore.

    `takeAt` li toglie dal layout ma NON dalla gerarchia: restano figli e Qt
    continua a disegnarli dov'erano. E `deleteLater()` non basta, perché
    l'evento di distruzione differita non viene processato da un semplice
    `processEvents` — nel frattempo si vedono i badge della carta PRECEDENTE
    sovrapposti a quella nuova. È la stessa trappola dei "cell widget
    fantasma" del market_watch (GOTCHA 14): la cura è `setParent(None)`, che
    stacca subito; `deleteLater` resta solo per liberare la memoria."""
    while layout.count() > (1 if tieni_ultimo else 0):
        elemento = layout.takeAt(0)
        widget = elemento.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


def _placeholder(size: QSize) -> QPixmap:
    """Cornice tratteggiata: l'immagine non c'è (ancora). Mai un segnaposto
    che somigli a una carta vera."""
    pixmap = QPixmap(size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(theme.BORDER), 1, Qt.PenStyle.DashLine)
    painter.setPen(pen)
    painter.drawRoundedRect(1, 1, size.width() - 2, size.height() - 2, 4, 4)
    painter.end()
    return pixmap


class _CardArt(QLabel):
    """L'immagine della carta nella scheda.

    Tiene da parte il pixmap ORIGINALE e lo riscala a ogni cambio di
    dimensione. Senza, rimpicciolendo la finestra (la scala UI arriva a 0,9)
    l'etichetta diventava più bassa del pixmap già disegnato e la carta si
    vedeva tagliata.

    NB: nel modulo del grafico prezzi c'è una classe quasi identica. Non si
    importa: i moduli non si conoscono fra loro, e venti righe duplicate
    costano meno di un aggancio fra due moduli indipendenti."""

    def __init__(self, width: int, parent=None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.setFixedWidth(width)
        # Larghezza fissa, altezza dal LAYOUT (`Ignored`): la colonna
        # dell'immagine è alta quanto la pagina, e la carta ci si adatta.
        # Attenzione: `Ignored` va bene SOLO perché l'altezza la decide il
        # layout — dove invece è imposta con `setFixedHeight`, il layout
        # piazza i vicini come se il widget fosse alto la metà e l'immagine
        # finisce disegnata sopra di loro (successo, v1.1.1).
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Ignored)
        self._source = None

    def set_source(self, pixmap) -> None:
        self._source = pixmap
        self._rescale()

    def resizeEvent(self, event) -> None:  # noqa: N802 (override Qt)
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self.width() <= 0 or self.height() <= 0:
            return
        if self._source is None or self._source.isNull():
            alta = min(self.height(), round(self.width() / CARD_RATIO))
            self.setPixmap(_placeholder(QSize(max(1, round(alta * CARD_RATIO)),
                                              max(1, alta))))
            return
        self.setPixmap(self._source.scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))


class CardDbWidget(QWidget):
    """Ricerca + scheda. Tutto locale tranne le immagini."""

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.ctx = context
        self.repo = CardDbRepository(context.storage)
        self._scale = 1.0
        self._sync_worker: SyncWorker | None = None
        self._version_worker: VersionWorker | None = None
        self._sets_worker: SetsWorker | None = None
        self._remote_version = ""
        self._current_id: int | None = None
        # Lingua del testo delle carte: segue l'INTERFACCIA. Con l'app in
        # inglese le carte in italiano sarebbero una sorpresa, e viceversa.
        self._desc_lang = i18n.current()
        self._thumb_pool = QThreadPool(self)
        # Poche corsie: le immagini arrivano da un host che minaccia la
        # blacklist a chi tira di volume. Meglio lente che bloccati un'ora.
        self._thumb_pool.setMaxThreadCount(3)
        self._thumb_signals = images.ImageSignals()
        self._thumb_signals.done.connect(self._on_image)
        self._thumb_inflight: set = set()
        self._rows_by_id: dict = {}
        # ricalcolo delle miniature visibili: coalizzato, altrimenti uno
        # scorrimento lancerebbe una richiesta per ogni pixel
        self._visible_timer = QTimer(self)
        self._visible_timer.setSingleShot(True)
        self._visible_timer.setInterval(120)
        self._visible_timer.timeout.connect(self._load_visible_thumbs)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(160)
        self._search_timer.timeout.connect(self.run_search)

        self._build_ui()
        self._refresh_status()
        if self.repo.count_cards():
            self._fill_filter_values()
            self.run_search()
        self._check_remote_version()
        self._ensure_setinfo()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(10)
        titoli = QVBoxLayout()
        titoli.setSpacing(1)
        titolo = QLabel(tr("Database"))
        titolo.setObjectName("title")
        sottotitolo = QLabel(tr("Tutte le carte Yu-Gi-Oh! (fonte: YGOPRODeck)"))
        sottotitolo.setObjectName("subtitle")
        titoli.addWidget(titolo)
        titoli.addWidget(sottotitolo)
        header.addLayout(titoli)
        header.addStretch(1)
        self.count_chip = QLabel()
        self.count_chip.setObjectName("chip")
        self.update_chip = QLabel()
        self.update_chip.setObjectName("chip")
        self.update_chip.setVisible(False)
        self.sync_btn = QPushButton(tr("Scarica il database"))
        self.sync_btn.clicked.connect(self.sync_now)
        header.addWidget(self.count_chip)
        header.addWidget(self.update_chip)
        header.addWidget(self.sync_btn)
        root.addLayout(header)

        # --- ricerca e filtri ---
        pannello = QFrame()
        pannello.setObjectName("card")
        anim.drop_shadow(pannello, blur=26, dy=6, alpha=120)
        pv = QVBoxLayout(pannello)
        pv.setContentsMargins(16, 14, 16, 14)
        pv.setSpacing(10)

        riga1 = QHBoxLayout()
        riga1.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            tr("Cerca per nome o nel testo dell'effetto…"))
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textEdited.connect(lambda _t: self._search_timer.start())
        self.search_input.returnPressed.connect(self.run_search)
        riga1.addWidget(self.search_input, 1)
        self.reset_btn = QPushButton(tr("Azzera filtri"))
        self.reset_btn.setObjectName("ghost")
        self.reset_btn.clicked.connect(self.reset_filters)
        riga1.addWidget(self.reset_btn)
        pv.addLayout(riga1)

        riga2 = QHBoxLayout()
        riga2.setSpacing(8)
        self.filters: dict = {}
        for chiave, etichetta in (("type", tr("Tipo")), ("race", tr("Razza")),
                                  ("attribute", tr("Attributo")),
                                  ("archetype", tr("Archetipo"))):
            combo = QComboBox()
            combo.addItem(f"{etichetta}: {tr('tutti')}", None)
            combo.currentIndexChanged.connect(lambda _i: self.run_search())
            self.filters[chiave] = combo
            riga2.addWidget(combo, 1)
        self.level_combo = QComboBox()
        self.level_combo.addItem(f"{tr('Livello')}: {tr('tutti')}", None)
        self.level_combo.currentIndexChanged.connect(lambda _i: self.run_search())
        riga2.addWidget(self.level_combo)
        self.ban_combo = QComboBox()
        for etichetta, valore in ((f"{tr('Ban list')}: {tr('tutte')}", None),
                                  (tr("In lista (qualsiasi)"), "any"),
                                  ("TCG", "tcg"), ("OCG", "ocg"), ("Goat", "goat")):
            self.ban_combo.addItem(etichetta, valore)
        self.ban_combo.currentIndexChanged.connect(lambda _i: self.run_search())
        riga2.addWidget(self.ban_combo)
        pv.addLayout(riga2)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(True)
        root.addWidget(self.progress)

        # --- due PAGINE: l'elenco, e la carta scelta ---
        # Non un pannello laterale: scegliendo una carta la pagina diventa
        # sua. Così l'elenco ha tutta la larghezza quando serve scorrerlo, e
        # la carta tutta la larghezza quando serve leggerla — invece di stare
        # stretti in due metà per sempre.
        self.pages = QStackedWidget()
        elenco = QWidget()
        ev = QVBoxLayout(elenco)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.setSpacing(14)
        ev.addWidget(pannello)
        # Elenco ESSENZIALE: immagine e nome. Tipo e stato in ban list stanno
        # nella scheda, dove c'è spazio per dirli per intero — in una colonna
        # stretta erano rumore accanto al nome.
        self.table = QTableWidget(0, 2)
        self.table.horizontalHeader().setVisible(False)  # una colonna sola: l'intestazione non aggiunge nulla
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setIconSize(THUMB)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        # Anche il clic secco, oltre al cambio di selezione: tornando
        # all'elenco la riga di prima è ancora selezionata, e ri-cliccarla non
        # cambierebbe la selezione — la carta non si riaprirebbe più.
        self.table.cellClicked.connect(lambda r, _c: self._open_row(r))
        self.table.verticalScrollBar().valueChanged.connect(
            lambda _v: self._visible_timer.start())
        ev.addWidget(self.table, 1)

        self.status = QLabel("")
        self.status.setObjectName("subtitle")
        ev.addWidget(self.status)

        self.pages.addWidget(elenco)
        self.pages.addWidget(self._build_card_page())
        root.addWidget(self.pages, 1)

    def _build_card_page(self) -> QWidget:
        """La pagina dedicata alla carta: arte grande a sinistra, tutto il
        resto a destra. Occupa la pagina intera — l'elenco sparisce."""
        pagina = QWidget()
        pl = QVBoxLayout(pagina)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(12)

        barra = QHBoxLayout()
        self.back_btn = QPushButton(tr("←  Torna all'elenco"))
        self.back_btn.setObjectName("ghost")
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.clicked.connect(self.show_list)
        self.back_btn.setToolTip(tr("Anche il tasto Esc"))
        barra.addWidget(self.back_btn)
        barra.addStretch(1)
        # Badge delle lingue: la carta si legge in quella accesa. Sono un
        # comando di PAGINA (cambiano nome e testo insieme), per questo stanno
        # qui in alto e non accanto al solo testo dell'effetto.
        self.lang_badges: dict = {}
        for codice, sigla in LANGUAGES:
            badge = QPushButton(sigla)
            badge.setCheckable(True)
            badge.setCursor(Qt.CursorShape.PointingHandCursor)
            badge.setFixedHeight(24)
            badge.setMinimumWidth(38)
            badge.clicked.connect(lambda _c=False, code=codice: self._set_card_lang(code))
            self.lang_badges[codice] = badge
            barra.addWidget(badge)
        pl.addLayout(barra)

        dentro = QFrame()
        dentro.setObjectName("card")
        anim.drop_shadow(dentro, blur=26, dy=6, alpha=120)
        corpo = QHBoxLayout(dentro)
        corpo.setContentsMargins(18, 18, 18, 18)
        corpo.setSpacing(18)

        self.art = _CardArt(ART.width())
        self.art.set_source(None)
        corpo.addWidget(self.art)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setStyleSheet("background: transparent;")
        colonna = QWidget()
        colonna.setStyleSheet("background: transparent;")
        v = QVBoxLayout(colonna)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(10)

        self.d_name = QLabel(tr("Scegli una carta dall'elenco"))
        self.d_name.setWordWrap(True)
        font = QFont(theme.FONT_FAMILY)
        font.setPointSizeF(17)
        font.setBold(True)
        self.d_name.setFont(font)
        v.addWidget(self.d_name)

        self.d_type = QLabel("")
        self.d_type.setWordWrap(True)
        self.d_type.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        v.addWidget(self.d_type)

        self.d_stats = QLabel("")
        self.d_stats.setWordWrap(True)
        v.addWidget(self.d_stats)

        riga_testo = QHBoxLayout()
        riga_testo.setSpacing(6)
        self.d_desc_label = QLabel(tr("Effetto"))
        self.d_desc_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        riga_testo.addWidget(self.d_desc_label)
        riga_testo.addStretch(1)
        v.addLayout(riga_testo)

        self.d_desc = QLabel("")
        self.d_desc.setWordWrap(True)
        self.d_desc.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.d_desc.setStyleSheet(
            f"background: {theme.SURFACE_2}; border: 1px solid {theme.BORDER};"
            f" border-radius: 8px; padding: 10px;")
        v.addWidget(self.d_desc)

        # --- riquadro dei formati: ban list TCG/OCG e punti Genesys.
        # Sono tre informazioni della stessa natura ("questa carta, in quel
        # formato, cosa può fare"): stanno insieme, in un riquadro loro.
        self.d_formats_title = QLabel(tr("Nei formati:"))
        self.d_formats_title.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        v.addWidget(self.d_formats_title)
        self.d_formats_box = QFrame()
        self.d_formats_box.setStyleSheet(
            f"QFrame {{ background: {theme.SURFACE_2};"
            f" border: 1px solid {theme.BORDER}; border-radius: 8px; }}"
            f" QLabel {{ border: none; background: transparent; }}")
        self.d_formats = QGridLayout(self.d_formats_box)
        self.d_formats.setContentsMargins(10, 8, 10, 8)
        self.d_formats.setHorizontalSpacing(12)
        self.d_formats.setVerticalSpacing(5)
        self.d_formats.setColumnStretch(2, 1)
        v.addWidget(self.d_formats_box)

        self.d_sets_title = QLabel("")
        self.d_sets_title.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        v.addWidget(self.d_sets_title)
        # Le ristampe in un riquadro con un bordo netto: sono un ELENCO dentro
        # una scheda, e senza un contorno si confondevano col resto del testo.
        self.d_sets_box = QFrame()
        self.d_sets_box.setStyleSheet(
            f"QFrame {{ background: {theme.SURFACE_2};"
            f" border: 1px solid {theme.BORDER}; border-radius: 8px; }}"
            f" QLabel {{ border: none; background: transparent; }}")
        self.d_sets_grid = QGridLayout(self.d_sets_box)
        self.d_sets_grid.setContentsMargins(10, 8, 10, 8)
        self.d_sets_grid.setHorizontalSpacing(10)
        self.d_sets_grid.setVerticalSpacing(4)
        self.d_sets_grid.setColumnStretch(1, 1)
        v.addWidget(self.d_sets_box)

        self.watch_btn = QPushButton(tr("Segui i prezzi in Market Watch"))
        self.watch_btn.setEnabled(False)
        self.watch_btn.clicked.connect(self._send_to_market_watch)
        v.addWidget(self.watch_btn, 0, Qt.AlignmentFlag.AlignLeft)
        v.addStretch(1)

        area.setWidget(colonna)
        corpo.addWidget(area, 1)
        pl.addWidget(dentro, 1)
        return pagina

    # ------------------------------------------------- passaggio fra pagine
    def show_list(self) -> None:
        if self.pages.currentIndex() == 0:
            return
        self.pages.setCurrentIndex(0)
        anim.fade_in(self.pages.currentWidget(), duration=180)
        self.search_input.setFocus()
        self._visible_timer.start()      # riprende le miniature rimaste indietro

    def _open_row(self, row: int) -> None:
        elemento = self.table.item(row, 0)
        if elemento is None:
            return
        card_id = elemento.data(Qt.ItemDataRole.UserRole)
        if card_id is not None:
            self.show_card(int(card_id))

    def keyPressEvent(self, event) -> None:  # noqa: N802 (override Qt)
        """Esc torna all'elenco: senza cornice di finestra e con la pagina
        piena, è il gesto che ci si aspetta."""
        if (event.key() == Qt.Key.Key_Escape
                and self.pages.currentIndex() == 1):
            self.show_list()
            return
        super().keyPressEvent(event)

    # --------------------------------------------------------- stato/header
    def _refresh_status(self) -> None:
        n = self.repo.count_cards()
        if n:
            self.count_chip.setText(tr("{n} carte").format(n=f"{n:,}".replace(",", ".")))
            self.count_chip.setProperty("state", "ok")
            self.sync_btn.setText(tr("Aggiorna"))
        else:
            self.count_chip.setText(tr("Database vuoto"))
            self.count_chip.setProperty("state", "warn")
            self.sync_btn.setText(tr("Scarica il database"))
        self.count_chip.style().unpolish(self.count_chip)
        self.count_chip.style().polish(self.count_chip)
        quando = self.repo.get_meta("last_update")
        self.count_chip.setToolTip(
            tr("Copia locale del database YGOPRODeck.\nVersione {v}, del {d}.")
            .format(v=self.repo.get_meta("version") or "?", d=quando or "?")
            if n else tr("Scarica il database per cominciare."))

    def _check_remote_version(self) -> None:
        """Una richiesta piccola all'avvio: la copia locale è vecchia?
        Se la rete non c'è, TACE (non è un'operazione chiesta dall'utente)."""
        self._version_worker = VersionWorker(self)
        self._version_worker.done.connect(self._on_remote_version)
        self._version_worker.start()

    def _ensure_setinfo(self) -> None:
        """Le date dei set mancano solo a chi ha scaricato il database prima
        che esistessero: si prende il pezzo mancante (170 KB) invece di
        chiedere di risincronizzare 24 MB."""
        if not self.repo.count_cards() or self.repo.has_setinfo():
            return
        self._sets_worker = SetsWorker(self)
        self._sets_worker.done.connect(self._on_setinfo)
        self._sets_worker.start()

    def _on_setinfo(self, righe: list) -> None:
        self.repo.replace_setinfo(righe)
        if self._current_id is not None:      # riordina la carta già aperta
            self._fill_sets(self.repo.sets_of(self._current_id))

    def _on_remote_version(self, versione: str, quando: str) -> None:
        self._remote_version = versione
        locale = self.repo.get_meta("version")
        if not self.repo.count_cards() or not versione or versione == locale:
            self.update_chip.setVisible(False)
            return
        self.update_chip.setText(tr("↻ aggiornamento disponibile"))
        self.update_chip.setProperty("state", "warn")
        self.update_chip.setToolTip(
            tr("YGOPRODeck è alla versione {remota} (del {d}); la tua copia è la "
               "{locale}. Premi Aggiorna quando vuoi.")
            .format(remota=versione, d=quando or "?", locale=locale or "?"))
        self.update_chip.style().unpolish(self.update_chip)
        self.update_chip.style().polish(self.update_chip)
        self.update_chip.setVisible(True)

    # ---------------------------------------------------- sincronizzazione
    def sync_now(self) -> None:
        if self._sync_worker is not None and self._sync_worker.isRunning():
            return
        self.sync_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.progress.setFormat(tr("Scarico il database…"))
        self.status.setText(tr("Una sola richiesta, poi tutto resta sul tuo computer."))
        self._sync_worker = SyncWorker(self)
        self._sync_worker.progress.connect(self._on_sync_progress)
        self._sync_worker.finished_ok.connect(self._on_sync_done)
        self._sync_worker.failed.connect(self._on_sync_failed)
        self._sync_worker.start()

    def _on_sync_progress(self, fase: str, fatto: int, totale: int) -> None:
        if fase in ("download", "italiano", "genesys"):
            etichetta = {
                "download": tr("Scarico… %.1f MB"),
                "italiano": tr("Scarico i testi italiani… %.1f MB"),
                "genesys": tr("Scarico i punti Genesys… %.1f MB"),
            }[fase]
            if totale > 0:
                self.progress.setRange(0, totale)
                self.progress.setValue(fatto)
            else:
                self.progress.setRange(0, 0)
            self.progress.setFormat(etichetta % (fatto / 1024 / 1024))
        else:
            self.progress.setRange(0, max(1, totale))
            self.progress.setValue(fatto)
            self.progress.setFormat(tr("Preparo le carte… %v/%m"))

    def _on_sync_done(self, carte: list, sets: list, setinfo: list,
                      versione: str, quando: str) -> None:
        # La scrittura su DB avviene QUI, nel thread della GUI (regola del
        # progetto): il worker ha solo scaricato e preparato le righe.
        try:
            self.repo.replace_all(carte, sets)
            if setinfo:
                self.repo.replace_setinfo(setinfo)
        except Exception as exc:               # disco pieno, DB bloccato…
            self._on_sync_failed(str(exc))
            return
        if versione:
            self.repo.set_meta("version", versione)
        if quando:
            self.repo.set_meta("last_update", quando)
        self.progress.setVisible(False)
        self.sync_btn.setEnabled(True)
        self.update_chip.setVisible(False)
        self._refresh_status()
        self._fill_filter_values()
        self.run_search()
        self.status.setText(
            tr("Database aggiornato: {n} carte e {s} stampe.")
            .format(n=len(carte), s=len(sets)))

    def _on_sync_failed(self, messaggio: str) -> None:
        self.progress.setVisible(False)
        self.sync_btn.setEnabled(True)
        self.status.setText(tr("Sincronizzazione non riuscita: {err}").format(err=messaggio))
        QMessageBox.warning(self, tr("Database"), messaggio)

    # ------------------------------------------------------------- ricerca
    def _fill_filter_values(self) -> None:
        """Riempie le tendine coi valori PRESENTI nei dati.

        Non con liste scritte a mano: invecchierebbero al primo tipo di carta
        nuovo, e ci sono 29 tipi diversi solo oggi."""
        for chiave, combo in self.filters.items():
            corrente = combo.currentData()
            combo.blockSignals(True)
            etichetta = combo.itemText(0)
            combo.clear()
            combo.addItem(etichetta, None)
            for valore in self.repo.distinct(chiave):
                combo.addItem(str(valore), valore)
            indice = combo.findData(corrente)
            combo.setCurrentIndex(max(0, indice))
            combo.blockSignals(False)
        self.level_combo.blockSignals(True)
        etichetta = self.level_combo.itemText(0)
        self.level_combo.clear()
        self.level_combo.addItem(etichetta, None)
        for livello in self.repo.levels():
            self.level_combo.addItem(str(livello), livello)
        self.level_combo.blockSignals(False)

    def _current_filters(self) -> dict:
        scelti = {k: c.currentData() for k, c in self.filters.items()}
        scelti["level"] = self.level_combo.currentData()
        scelti["banlist"] = self.ban_combo.currentData()
        return {k: v for k, v in scelti.items() if v is not None}

    def reset_filters(self) -> None:
        for combo in list(self.filters.values()) + [self.level_combo, self.ban_combo]:
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.search_input.clear()
        self.run_search()

    def run_search(self) -> None:
        if not self.repo.count_cards():
            self.status.setText(
                tr("Il database è vuoto: premi «Scarica il database» "
                   "(una richiesta, ~24 MB)."))
            return
        testo = self.search_input.text()
        filtri = self._current_filters()
        righe, totale = self.repo.search_page(testo, filtri, RESULT_LIMIT)
        self._fill_table(righe)
        if totale > len(righe):
            # Mai far credere che siano tutte: chi cerca "drago" deve sapere
            # che ne sta vedendo 300 su 900.
            self.status.setText(
                tr("{mostrate} carte mostrate su {totale} trovate — restringi la ricerca.")
                .format(mostrate=len(righe), totale=totale))
        else:
            self.status.setText(tr("{n} carte trovate.").format(n=totale))

    def _fill_table(self, righe: list) -> None:
        self.table.setUpdatesEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(righe))
        self._rows_by_id = {}
        vuota = QIcon(_placeholder(THUMB))
        for r, riga in enumerate(righe):
            card_id = int(riga["id"])
            self._rows_by_id[card_id] = r
            icona = QTableWidgetItem("")
            percorso = images.cached(card_id, small=True)
            if percorso is not None:
                icona.setIcon(QIcon(str(percorso)))
            else:
                icona.setIcon(vuota)
            icona.setData(Qt.ItemDataRole.UserRole, card_id)
            self.table.setItem(r, 0, icona)
            # Solo il nome inglese: è quello canonico, con cui la carta si
            # cerca ovunque. La traduzione affollava l'elenco senza aiutare a
            # scorrerlo — e la RICERCA continua comunque a coprire entrambe le
            # lingue (si può cercare "cenere" e trovare Ash Blossom).
            nome = QTableWidgetItem(riga["name"])
            nome.setData(Qt.ItemDataRole.UserRole, card_id)
            self.table.setItem(r, 1, nome)
            self.table.setRowHeight(r, self._row_height())
        self.table.setColumnWidth(0, round((THUMB.width() + 12) * self._scale))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setUpdatesEnabled(True)
        self._visible_timer.start()

    def _row_height(self) -> int:
        """Altezza di riga che lascia all'icona TUTTA la sua altezza.
        Vedi ROW_PADDING: senza il padding del QSS l'immagine viene tagliata."""
        return round((THUMB.height() + ROW_PADDING) * self._scale)

    # -------------------------------------------------------------- scheda
    def _on_row_selected(self) -> None:
        elementi = self.table.selectedItems()
        if not elementi:
            return
        card_id = elementi[0].data(Qt.ItemDataRole.UserRole)
        if card_id is None:
            return
        self.show_card(int(card_id))

    def show_card(self, card_id: int) -> None:
        carta = self.repo.card(card_id)
        if carta is None:
            return
        self._current_id = card_id
        if self.pages.currentIndex() != 1:
            self.pages.setCurrentIndex(1)
            anim.fade_in(self.pages.currentWidget(), duration=200)
        # Nome, sottotitolo, testo e badge: li mette tutti `_refresh_desc`,
        # che è anche quello che gira premendo un badge — un solo posto in cui
        # la lingua decide cosa si legge.
        self._refresh_desc()

        stats = []
        if carta["level"] is not None:
            etichetta = "Rango" if "XYZ" in (carta["type"] or "") else "Livello"
            stats.append(f"{tr(etichetta)} {carta['level']}")
        if carta["linkval"] is not None:
            stats.append(f"Link {carta['linkval']}")
        if carta["scale"] is not None:
            stats.append(f"{tr('Scala')} {carta['scale']}")
        if carta["atk"] is not None:
            stats.append(f"ATK {carta['atk']}")
        if carta["def"] is not None:
            stats.append(f"DEF {carta['def']}")
        self.d_stats.setText("   ".join(stats))

        # I badge della ban list non stanno più sciolti accanto al tipo:
        # sono finiti nel riquadro dei formati, insieme a Genesys.
        self._fill_formats(carta)
        self._fill_sets(self.repo.sets_of(card_id))

        self.watch_btn.setEnabled(True)
        self.art.set_source(None)
        percorso = images.cached(card_id, small=False)
        if percorso is not None:
            self._set_art(str(percorso))
        elif carta["image_url"] and not images.failed(carta["image_url"]):
            self._request_image(card_id, carta["image_url"], small=False)

    def _fill_formats(self, carta) -> None:
        """Riquadro dei formati: ban list TCG e OCG, punti Genesys.

        Tre distinzioni che a schermo si scriverebbero uguale e invece non lo
        sono, e vanno tenute separate:
        - **in lista** → il badge con lo stato (Vietata / Limitata / Semi);
        - **legale e non in lista** → 3 copie, che è la regola, non una stima;
        - **mai uscita in quel formato** → si dice, invece di far credere che
          se ne possano giocare tre. Il dato c'è: `formats` della fonte.
        Per Genesys, un `0` è un punteggio VERO (carta senza costo); se invece
        il dato non è stato scaricato si scrive che manca — sono cose diverse.
        """
        _svuota(self.d_formats)
        try:
            formati = {f.lower() for f in json.loads(carta["formats"] or "[]")}
        except (ValueError, TypeError):
            formati = set()
        altezza = round(20 * self._scale)
        riga = 0
        for codice, etichetta in (("tcg", "TCG"), ("ocg", "OCG")):
            nome = QLabel(etichetta)
            nome.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            self.d_formats.addWidget(nome, riga, 0)
            stato = carta[f"ban_{codice}"] or ""
            if stato:
                valore = QLabel()
                valore.setPixmap(_pill(tr(BAN_LABELS.get(stato, stato)),
                                       BAN_COLORS.get(stato, theme.TEXT_MUTED),
                                       altezza))
                valore.setToolTip(stato)
            elif codice in formati:
                valore = QLabel(tr("3 copie"))
                valore.setStyleSheet(f"color: {theme.POSITIVE};")
            else:
                valore = QLabel(tr("non uscita in questo formato"))
                valore.setStyleSheet(f"color: {theme.TEXT_DISABLED};")
            self.d_formats.addWidget(valore, riga, 1)
            riga += 1

        nome = QLabel("Genesys")
        nome.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self.d_formats.addWidget(nome, riga, 0)
        punti = carta["genesys"] if "genesys" in carta.keys() else None
        if punti is None:
            testo = (tr("dato non scaricato — premi Aggiorna")
                     if not self.repo.has_genesys() else tr("nessun punteggio"))
            valore = QLabel(testo)
            valore.setStyleSheet(f"color: {theme.TEXT_DISABLED};")
        else:
            valore = QLabel(tr("{n} punti").format(n=punti))
            valore.setStyleSheet(
                f"color: {theme.WARN if punti else theme.TEXT};")
        self.d_formats.addWidget(valore, riga, 1)

    def _fill_sets(self, stampe: list) -> None:
        """Il riquadro delle ristampe: una riga per CODICE SET, con tutte le
        sue rarità accanto.

        Il nome esteso dell'espansione non si scrive: occupava metà riquadro e
        si ripeteva identico per ogni rarità dello stesso set (RA01-EN016
        compare otto volte). Sta nel suggerimento del codice, insieme alla
        data di uscita — il dato c'è, non ruba spazio.

        Ordine: **cronologico** per data di uscita del set, e dentro ogni set
        le rarità dalla più comune alla più ricercata (`rarity_rank`). Chi non
        ha la data va in fondo, chi non ha una rarità riconosciuta va in fondo
        alla sua riga: un dato mancante non si mette in mezzo agli altri come
        se valesse zero."""
        _svuota(self.d_sets_grid)
        self.d_sets_title.setText(
            tr("Stampata in {n} set:").format(n=len(stampe)) if stampe
            else tr("Nessuna stampa registrata."))
        self.d_sets_box.setVisible(bool(stampe))
        if not stampe:
            return

        # Si raggruppa per NOME del set, non per codice: 142 codici sono
        # condivisi da più espansioni (MVP1 = Movie Pack, Gold Edition,
        # Secret Edition e Special Edition; JUMP copre 70 promo diverse).
        # Raggruppare per codice fonderebbe prodotti diversi in una riga sola.
        gruppi: dict = {}
        for stampa in stampe:                    # già in ordine cronologico
            nome = stampa["set_name"] or stampa["set_code"] or "—"
            voce = gruppi.setdefault(nome, {
                "corto": stampa["set_short"] or (stampa["set_code"] or "").split("-")[0],
                "carta": stampa["set_code"] or "",
                "data": stampa["tcg_date"] or "",
                "rarita": []})
            # `is_rarity` scarta quello che rarità non è: la fonte a volte
            # mette "2", "New" o "European debut" in quel campo (192 stampe su
            # 44.190). Un badge lì darebbe a un refuso della fonte la dignità
            # di un dato.
            rara = stampa["rarity"]
            if rara and is_rarity(rara) and rara not in voce["rarita"]:
                voce["rarita"].append(rara)

        etichette = set_labels(gruppi)     # vedi lì: il codice più corto che basta

        altezza = round(20 * self._scale)
        for riga, (nome, voce) in enumerate(gruppi.items()):
            pillola = QLabel()
            pillola.setPixmap(badges.set_pill(etichette[nome], altezza))
            descrizione = nome
            if voce["data"]:
                descrizione += f" — {voce['data']}"
            pillola.setToolTip(descrizione)
            self.d_sets_grid.addWidget(pillola, riga, 0)

            fila = QWidget()
            fh = QHBoxLayout(fila)
            fh.setContentsMargins(0, 0, 0, 0)
            fh.setSpacing(4)
            for rara in sorted(voce["rarita"],
                               key=lambda r: (rarity_rank(r) < 0, rarity_rank(r))):
                badge = QLabel()
                badge.setPixmap(rarity_pixmap(rara, altezza))
                badge.setToolTip(rara)      # le sigle sono convenzioni, non ovvie
                fh.addWidget(badge)
            fh.addStretch(1)
            self.d_sets_grid.addWidget(fila, riga, 1)

    def _set_card_lang(self, codice: str) -> None:
        """La scelta resta finché non la si cambia: sfogliando le carte non si
        torna alla lingua di partenza a ogni scheda."""
        self._desc_lang = codice
        self._refresh_desc()

    def _refresh_desc(self) -> None:
        """Nome e testo della carta nella lingua accesa.

        Il predefinito è la **lingua dell'interfaccia** (`i18n.current()`):
        chi tiene l'app in inglese si aspetta le carte in inglese.
        Se per quella carta la traduzione non esiste (2.878 su 14.477) il
        badge resta SPENTO e disabilitato, col perché nel tooltip: un badge
        assente farebbe saltare la fila e non direbbe niente; uno spento dice
        "questa carta in italiano non c'è"."""
        if self._current_id is None:
            return
        carta = self.repo.card(self._current_id)
        if carta is None:
            return
        italiano = (carta["desc_it"] if "desc_it" in carta.keys() else "") or ""
        nome_it = (carta["name_it"] if "name_it" in carta.keys() else "") or ""
        disponibili = {"en": True, "it": bool(italiano or nome_it)}
        mostra_it = self._desc_lang == "it" and disponibili["it"]

        for codice, badge in self.lang_badges.items():
            attivo = (codice == "it") == mostra_it
            badge.setEnabled(disponibili.get(codice, False))
            badge.setChecked(attivo)
            badge.setStyleSheet(self._badge_style(attivo, disponibili.get(codice, False)))
            badge.setToolTip(
                tr("Questa carta non esiste in italiano")
                if not disponibili.get(codice, False)
                else tr("Mostra nome e testo in italiano") if codice == "it"
                else tr("Mostra nome e testo originali in inglese"))

        # Titolo nella lingua accesa; il nome inglese non si perde mai — con
        # l'italiano acceso finisce nella riga sotto, perché è quello con cui
        # la carta si cerca, si scambia e si gioca.
        self.d_name.setText(nome_it if (mostra_it and nome_it) else carta["name"])
        pezzi = [p for p in (carta["human_type"] or carta["type"],
                             carta["archetype"]) if p]
        if mostra_it and nome_it and nome_it != carta["name"]:
            pezzi.insert(0, carta["name"])
        self.d_type.setText(" · ".join(pezzi))

        self.d_desc.setText(italiano if mostra_it else (carta["desc"] or ""))
        self.d_desc_label.setText(
            tr("Effetto") if mostra_it or italiano
            else tr("Effetto (in inglese: l'italiano non esiste per questa carta)"))

    def _badge_style(self, attivo: bool, disponibile: bool) -> str:
        """Pillola: accesa in teal, spenta contornata, non disponibile smorta.
        Stessa grammatica dei badge di condizione/rarità del market watch —
        testo colorato su fondo dello stesso colore molto trasparente."""
        if not disponibile:
            colore, fondo, bordo = theme.TEXT_DISABLED, "transparent", theme.BORDER
        elif attivo:
            colore, fondo, bordo = theme.ACCENT, "rgba(26,195,178,0.18)", theme.ACCENT
        else:
            colore, fondo, bordo = theme.TEXT_MUTED, "transparent", theme.BORDER
        return (f"QPushButton {{ color: {colore}; background: {fondo};"
                f" border: 1px solid {bordo}; border-radius: 11px;"
                f" padding: 2px 10px; font-weight: 700; font-size: 11px; }}"
                f"QPushButton:hover:enabled {{ border-color: {theme.ACCENT}; }}")

    def _set_art(self, percorso: str) -> None:
        pixmap = QPixmap(percorso)
        if not pixmap.isNull():
            self.art.set_source(pixmap)

    # ------------------------------------------------------------ immagini
    def _request_image(self, card_id: int, url: str, small: bool) -> None:
        chiave = (card_id, small)
        if not url or chiave in self._thumb_inflight or images.failed(url):
            return
        self._thumb_inflight.add(chiave)
        self._thumb_pool.start(
            images.ImageTask(card_id, url, small, self._thumb_signals))

    def _load_visible_thumbs(self) -> None:
        """Scarica le miniature delle SOLE righe visibili.

        È il freno principale verso il loro CDN: con 300 risultati a schermo
        ne servono una decina, non trecento."""
        if not self.table.rowCount() or self.pages.currentIndex() != 0:
            return          # con la pagina della carta aperta non serve nulla
        viewport = self.table.viewport().rect()
        prima = self.table.rowAt(max(0, viewport.top()))
        ultima = self.table.rowAt(max(0, viewport.bottom()))
        if prima < 0:
            prima = 0
        if ultima < 0:
            ultima = self.table.rowCount() - 1
        for r in range(max(0, prima - 2), min(self.table.rowCount(), ultima + 3)):
            elemento = self.table.item(r, 0)
            if elemento is None:
                continue
            card_id = elemento.data(Qt.ItemDataRole.UserRole)
            if card_id is None or images.cached(int(card_id), small=True):
                continue
            carta = self.repo.card(int(card_id))
            if carta is not None and carta["image_small_url"]:
                self._request_image(int(card_id), carta["image_small_url"], small=True)

    def _on_image(self, card_id: int, small: bool, percorso: str) -> None:
        self._thumb_inflight.discard((card_id, small))
        if not percorso:
            return
        if small:
            riga = self._rows_by_id.get(card_id)
            if riga is not None and riga < self.table.rowCount():
                elemento = self.table.item(riga, 0)
                if elemento is not None:
                    elemento.setIcon(QIcon(percorso))
        elif card_id == self._current_id:
            self._set_art(percorso)

    # ------------------------------------------------- ponte con market_watch
    def _send_to_market_watch(self) -> None:
        """Passa la carta al Market Watch. I due moduli NON si conoscono: si
        parlano attraverso il contesto, per `id` di modulo.

        Si passa il NOME e non l'id: i cataloghi sono diversi (YGOPRODeck ha
        una carta, CardTrader una stampa) e non esiste una corrispondenza
        univoca — la stampa la sceglie l'utente fra i risultati."""
        if self._current_id is None:
            return
        carta = self.repo.card(self._current_id)
        if carta is None:
            return
        ok = self.ctx.open_module("market_watch", {"card_name": carta["name"]})
        if not ok:
            QMessageBox.information(
                self, tr("Market Watch"),
                tr("Il modulo Market Watch non è disponibile."))

    # ------------------------------------------------------------ interfaccia
    def apply_scale(self, scale: float) -> None:
        self._scale = scale
        self.table.setIconSize(QSize(round(THUMB.width() * scale),
                                     round(THUMB.height() * scale)))
        for r in range(self.table.rowCount()):
            self.table.setRowHeight(r, self._row_height())
        self.table.setColumnWidth(0, round((THUMB.width() + 12) * scale))
        # l'altezza la dà il layout; l'immagine si ri-adatta da sola
        self.art.setFixedWidth(round(ART.width() * scale))

    def stop(self) -> None:
        # TUTTI i thread, `_sets_worker` compreso: uno lasciato in corsa
        # sopravvive al widget e fa cadere il processo alla chiusura
        # (visto: uscita 0xC0000409 a fine test, senza un rigo di errore).
        for worker in (self._sync_worker, self._version_worker, self._sets_worker):
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                worker.wait(2000)
        self._thumb_pool.clear()
        self._thumb_pool.waitForDone(2000)
