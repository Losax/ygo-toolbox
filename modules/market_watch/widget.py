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

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QRectF,
    QSize,
    Qt,
    QStringListModel,
    QThreadPool,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCompleter,
    QDialog,
    QDoubleSpinBox,
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.context import AppContext
from core import anim, i18n, theme
from core.i18n import tr

from . import config
from .filters_dialog import DisplayDialog, FiltersDialog, WelcomeDialog
from .flags import country_name, flag_pixmap
from .rarity import rarity_pixmap
from .providers.base import CardRef, ListingFilters, PriceQuote
from .providers.cardtrader import CardTraderClient, CardTraderProvider
from .repository import MarketWatchRepository
from .search_model import ThumbDelegate, _ThumbSignals, _ThumbTask, _thumb_url
from .workers import CatalogSyncWorker, ImageFetchWorker, PriceFetchWorker

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


class _WatchTable(QTableWidget):
    """Tabella watchlist con drag&drop di RIGHE delegato all'esterno.

    Il drop di Qt sposterebbe i singoli item (rompendo span delle cartelle e
    cell widget): qui si intercetta e si emette solo (riga_sorgente,
    riga_destinazione); la logica di spostamento e il re-render li fa il
    widget, che è l'unico a conoscere cartelle e posizioni."""
    row_moved = Signal(int, int)   # riga trascinata, riga di destinazione (-1 = in fondo)

    def __init__(self, rows: int, cols: int, parent=None) -> None:
        super().__init__(rows, cols, parent)
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


_set_pill_cache: dict[tuple[str, int], QPixmap] = {}


def _make_set_pill(code: str, height: int) -> QPixmap:
    """Pill del codice set, stessa estetica del popup di ricerca:
    sfondo scuro (#2f3744) e sigla teal in grassetto."""
    key = (code, height)
    cached = _set_pill_cache.get(key)
    if cached is not None:
        return cached
    font = QFont(theme.FONT_FAMILY)
    font.setBold(True)
    font.setPixelSize(max(6, round(height * 0.58)))
    fm = QFontMetrics(font)
    w = max(round(height * 1.6), fm.horizontalAdvance(code) + round(height * 0.9))
    pm = QPixmap(w, height)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(theme.BORDER))          # #2f3744, come _PILL_BG della ricerca
    p.setPen(Qt.PenStyle.NoPen)
    radius = height / 3.0
    p.drawRoundedRect(QRectF(0, 0, w, height), radius, radius)
    p.setFont(font)
    p.setPen(QColor(theme.ACCENT))
    p.drawText(QRectF(0, 0, w, height), Qt.AlignmentFlag.AlignCenter, code)
    p.end()
    _set_pill_cache[key] = pm
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
    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.repo = MarketWatchRepository(context.storage)
        # igiene del DB: via i dati di carte non più seguite e lo storico
        # vecchio viene sfoltito (1 riga/giorno oltre i 90 giorni)
        self.repo.cleanup_orphans(PROVIDER)
        self.repo.prune_history()
        self._selected_ref: CardRef | None = None
        self._label_to_ref: dict[str, CardRef] = {}
        self._search_index: list[tuple[str, str]] = []  # (label_minuscolo, label)
        # ref senza annuncio conforme ai filtri: persistito, così "Nessuna copia"
        # sopravvive al riavvio (altrimenti tornerebbe a mostrare il vecchio prezzo).
        self._no_match_refs: set[str] = self._load_no_match()
        # miniature per le righe della watchlist (download async + cache)
        self._row_thumb_cache: dict[str, QPixmap] = {}
        self._row_thumb_inflight: set[str] = set()
        self._url_ref: dict[str, str] = {}   # thumb_url -> ref_id (per aggiornare la riga giusta)
        self._row_thumb_pool = QThreadPool(self)
        self._row_thumb_pool.setMaxThreadCount(6)
        self._row_thumb_signals = _ThumbSignals(self)
        self._row_thumb_signals.done.connect(self._on_row_thumb)
        self._price_worker: PriceFetchWorker | None = None
        self._sync_worker: CatalogSyncWorker | None = None
        self._img_worker: ImageFetchWorker | None = None
        self._img_cache: dict[str, QPixmap] = {}
        self._current_img_url: str = ""
        self._filters = ListingFilters.from_dict(self._load_filters())
        # preferenze di visualizzazione della watchlist (rarità icona/nome,
        # set codice/nome, animazioni on/off) — dialogo Opzioni
        self._display = self._load_display()
        anim.set_enabled(bool(self._display.get("animations", True)))
        self._trash_icon = _make_trash_icon()
        self._settings_icon = _make_settings_icon()
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
        self.options_btn = QPushButton()
        self.options_btn.setIcon(_make_settings_icon())
        self.options_btn.setToolTip(tr("Opzioni di visualizzazione della watchlist"))
        self.options_btn.clicked.connect(self.open_options)
        self.overview_btn = QPushButton()
        self.overview_btn.setIcon(_make_grid_icon())
        self.overview_btn.setCheckable(True)
        self.overview_btn.setToolTip(tr("Panoramica: nasconde la ricerca e allarga la watchlist"))
        self.overview_btn.toggled.connect(self._toggle_overview)
        self._header_buttons = (self.token_btn, self.sync_btn,
                                self.options_btn, self.overview_btn)
        header.addWidget(self.token_label)
        header.addWidget(self.catalog_label)
        header.addWidget(self.token_btn)
        header.addWidget(self.sync_btn)
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
        # barra di ricerca + pulsante FILTRI (imbuto) affiancato: i filtri
        # sugli annunci si aprono da qui, non più dalle Opzioni dell'header
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_row.addWidget(self.search_input, 1)
        self.filters_btn = QPushButton()
        self.filters_btn.setIcon(_make_filter_icon())
        self.filters_btn.setToolTip(tr("Filtri degli annunci (lingua, condizione, Zero, …)"))
        self.filters_btn.clicked.connect(self.open_filters)
        search_row.addWidget(self.filters_btn)
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
        self.table.row_moved.connect(self._on_row_moved)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        # Il fit delle colonne dipende dalla larghezza REALE del viewport della
        # tabella: ci agganciamo al suo evento di resize (lì la geometria è
        # definitiva), non a quello del widget (dove i figli sono ancora stantii).
        self.table.viewport().installEventFilter(self)
        self._apply_column_layout(overview=False)
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
        for btn in (self.token_btn, self.sync_btn, self.options_btn,
                    self.overview_btn, self.filters_btn, self.check_btn, self.add_btn):
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
        prev = getattr(self, "_scroll_anim", None)
        running = (prev is not None
                   and prev.state() == QAbstractAnimation.State.Running)
        base = self._scroll_target if running else sb.value()
        # ~108 px per scatto di rotellina; gli scatti rapidi si accumulano
        self._scroll_target = max(0, min(sb.maximum(),
                                         base - round(event.angleDelta().y() * 0.9)))
        if prev is not None:
            try:
                prev.stop()
            except RuntimeError:
                pass
        anim_ = QVariantAnimation(self)
        anim_.setDuration(150)
        anim_.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim_.setStartValue(float(sb.value()))
        anim_.setEndValue(float(self._scroll_target))
        anim_.valueChanged.connect(lambda v: sb.setValue(round(float(v))))
        self._scroll_anim = anim_
        anim_.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        return True

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
        for btn in (*self._header_buttons, self.filters_btn):  # pulsanti-icona quadrati
            btn.setFixedSize(self._sp(38), self._sp(38))
            btn.setIconSize(QSize(self._sp(20), self._sp(20)))
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
                      4: 110, 5: 62, 6: 56, 7: 56,
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

    def open_filters(self) -> None:
        """Filtri annunci globali: dal pulsante a imbuto accanto alla ricerca."""
        dialog = FiltersDialog(self._filters, self)
        if dialog.open_near(self.filters_btn) != QDialog.DialogCode.Accepted:
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
        for row in self.repo.all_catalog(PROVIDER):
            name = row["name"]
            detail = row["detail"] or ""          # "rarità · espansione" (per la tabella)
            image_url = row["image_url"] or ""
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
            items.append((label, image_url, left, code, expansion))  # expansion = tooltip
            labels.append(label)
        self._label_to_ref = mapping
        # indice per la ricerca "a token" (label minuscolo pre-calcolato)
        self._search_index = [(lbl.lower(), lbl) for lbl in labels]
        self._completer_model.setStringList([])        # vuoto: si riempie coi match
        self._thumb_delegate.set_cards(items)          # immagini + codice gestiti dal delegate

    def _on_search_text(self, text: str) -> None:
        # ogni modifica manuale annulla la carta selezionata in precedenza
        self._selected_ref = None
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
        self.add_btn.setEnabled(True)
        shown = ref.name if not ref.detail else f"{ref.name} · {ref.detail}"
        self.selected_label.setText(f"✓  {shown}")
        self._show_image(ref.image_url)

    # ------------------------------------------------------------- anteprima
    def _show_image(self, url: str) -> None:
        """Mostra l'anteprima della carta (con cache; scarico in un thread)."""
        self._current_img_url = url
        if not url:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(tr("Nessuna\nanteprima"))
            return
        cached = self._img_cache.get(url)
        if cached is not None:
            self._set_preview_pixmap(cached)
            return
        self.preview.setPixmap(QPixmap())
        self.preview.setText(tr("Caricamento…"))
        self._img_worker = ImageFetchWorker(url, self)
        self._img_worker.done.connect(self._on_image_done)
        self._img_worker.failed.connect(self._on_image_failed)
        self._img_worker.start()

    def _on_image_done(self, url: str, image: QImage) -> None:
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)  # già decodificata nel thread: solo incarto
        self._img_cache[url] = pixmap
        if url == self._current_img_url:  # ignora risposte ormai sorpassate
            self._set_preview_pixmap(pixmap)

    def _on_image_failed(self, _message: str) -> None:
        if self.preview.pixmap() is None or self.preview.pixmap().isNull():
            self.preview.setText(tr("Immagine non\ndisponibile"))

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
        self.repo.add_watch(PROVIDER, ref.id, ref.name, ref.detail, self.threshold_spin.value())
        self._reload_table()
        self.search_input.clear()
        self._on_search_text("")
        self._set_busy(False, tr("Aggiunta: {name}. Recupero prezzo iniziale…").format(name=ref.name))
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
        icon = self._row_icon(ref_id)
        if icon is not None:
            img_item.setIcon(icon)
        self.table.setItem(row, 0, img_item)
        # 1 Nome (leggermente indentato se la carta sta in una cartella)
        in_folder = ("folder_id" in watch.keys()) and watch["folder_id"] is not None
        self.table.setItem(row, 1, cell(("    " if in_folder else "") + watch["card_name"]))
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
        self.table.setItem(row, 4, cell((q.condition if q is not None else "") or "—"))
        lang_item = cell((q.language if q is not None else "") or "—")
        lang_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 5, lang_item)
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
        settings_btn.setIcon(self._settings_icon)
        settings_btn.setIconSize(icon_sz)
        custom = tr(" (personalizzati)") if raw_filters else ""
        settings_btn.setToolTip(tr("Filtri di questa carta") + custom)
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.clicked.connect(
            lambda _=False, wid=watch["id"], rf=raw_filters, nm=watch["card_name"]:
            self._open_item_settings(wid, rf, nm))
        remove_btn = QPushButton()
        remove_btn.setObjectName("ghost")
        remove_btn.setIcon(self._trash_icon)
        remove_btn.setIconSize(icon_sz)
        remove_btn.setToolTip(tr("Rimuovi dalla watchlist"))
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.clicked.connect(lambda _=False, wid=watch["id"]: self._remove(wid))
        arow.addWidget(settings_btn)
        arow.addWidget(remove_btn)
        self.table.setCellWidget(row, 15, actions)

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

    def _effective_filters(self, watch):
        """Filtri della singola carta se presenti, altrimenti quelli globali."""
        raw = watch["filters"] if "filters" in watch.keys() else ""
        if raw:
            try:
                return ListingFilters.from_dict(json.loads(raw))
            except (ValueError, TypeError):
                pass
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
    def _row_icon(self, ref_id: str):
        """Icona miniatura per la riga: da cache se c'è, altrimenti la scarica."""
        image_url = self.repo.catalog_image(PROVIDER, ref_id)
        turl = _thumb_url(image_url or "")
        if not turl:
            return None
        self._url_ref[turl] = ref_id
        pixmap = self._row_thumb_cache.get(turl)
        if pixmap is not None:
            return QIcon(pixmap)
        if turl not in self._row_thumb_inflight:
            self._row_thumb_inflight.add(turl)
            self._row_thumb_pool.start(_ThumbTask(turl, self._row_thumb_signals, ROW_THUMB))
        return None  # arriverà via _on_row_thumb

    def _on_row_thumb(self, turl: str, image: QImage) -> None:
        self._row_thumb_inflight.discard(turl)
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        self._row_thumb_cache[turl] = pixmap
        ref_id = self._url_ref.get(turl)
        if ref_id is None:
            return
        icon = QIcon(pixmap)
        for r in range(self.table.rowCount()):   # applica alla riga giusta (watchlist piccola)
            item = self.table.item(r, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == ref_id:
                item.setIcon(icon)
                break

    def _on_table_selection(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        ref_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not ref_id:
            return
        self._show_image(self.repo.catalog_image(PROVIDER, ref_id) or "")

    def _remove(self, watch_id) -> None:
        removed = self.repo.remove_watch(watch_id)  # pulisce anche storico/annuncio
        if removed is not None:
            _, ref_id = removed
            self._last_quotes.pop(ref_id, None)
            self._no_match_refs.discard(ref_id)
        self._reload_table()

    # ------------------------------------------------ cartelle & ordinamento
    def _on_cell_clicked(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._row_entries):
            kind, payload = self._row_entries[row]
            if kind == "folder":
                self._toggle_folder(payload)

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

    def _folder_at(self, row: int):
        """Cartella 'di pertinenza' della riga visuale (None = fuori)."""
        if not (0 <= row < len(self._row_entries)):
            return None
        kind, payload = self._row_entries[row]
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
                for it in items:  # torna agli sfondi di default (QSS/alternati)
                    it.setData(Qt.ItemDataRole.BackgroundRole, None)
                if is_folder and items:
                    items[0].setBackground(QColor(theme.SURFACE_2))
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
        elif entry is not None and entry[0] == "folder":
            f = entry[1]
            menu.addAction(tr("Rinomina cartella…"), lambda folder=f: self._rename_folder(folder))
            menu.addAction(tr("Elimina cartella (le carte tornano fuori)"),
                           lambda folder=f: self._delete_folder(folder))
        menu.addSeparator()
        menu.addAction(tr("Nuova cartella…"), lambda: self._new_folder())
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

    def _rename_folder(self, folder) -> None:
        name, ok = QInputDialog.getText(self, tr("Rinomina cartella"), tr("Nuovo nome:"),
                                        text=folder["name"])
        if ok and name.strip():
            self.repo.rename_folder(folder["id"], name.strip())
            self._reload_table()

    def _delete_folder(self, folder) -> None:
        self.repo.delete_folder(folder["id"])
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
        self._set_busy(True, tr("Controllo prezzi su CardTrader…"))
        jobs = [(w["ref_id"], self._effective_filters(w)) for w in watches]
        self._price_worker = PriceFetchWorker(self.provider, jobs)
        self._price_worker.finished_ok.connect(self._on_prices)
        self._price_worker.failed.connect(self._on_error)
        self._price_worker.start()

    def _on_error(self, message: str) -> None:
        self.sync_btn.setEnabled(self.provider is not None)
        self._set_busy(False, tr("Errore: {msg}").format(msg=message))

    def _on_prices(self, results: list[dict]) -> None:
        self._last_quotes = {r["ref_id"]: r["quote"] for r in results}  # per le info in Panoramica
        watches = {w["ref_id"]: w for w in self.repo.list_watches() if w["provider"] == PROVIDER}
        for result in results:
            watch = watches.get(result["ref_id"])
            quote = result["quote"]
            if watch is None or quote is None:
                continue  # nessun annuncio attivo per questa carta
            old = self.repo.last_price(PROVIDER, result["ref_id"])
            new = quote.amount
            self.repo.record_price(PROVIDER, result["ref_id"], new, quote.currency)
            if old is not None and new < old:
                drop_pct = (old - new) / old * 100.0
                if drop_pct >= watch["threshold_pct"]:
                    self.context.notifier.notify(
                        tr("Nuovo prezzo più basso su CardTrader"),
                        f"{watch['card_name']}: {old:.2f} € → {new:.2f} € (-{drop_pct:.1f}%)",
                    )
        # carte per cui nessun annuncio soddisfa i filtri (o nessun annuncio attivo)
        self._no_match_refs = {r["ref_id"] for r in results if r.get("quote") is None}
        # persiste l'ultimo annuncio per carta (upsert, '' = "Nessuna copia"):
        # al riavvio la Panoramica riparte da qui invece che vuota
        self.repo.set_last_quotes(PROVIDER, [
            (r["ref_id"], json.dumps(r["quote"].to_dict()) if r["quote"] is not None else "")
            for r in results
        ])
        checked = datetime.now().strftime("%d/%m %H:%M")
        self.repo.set_setting("last_checked", checked)
        self._render_after_check(checked)
        self._set_busy(False, tr("Ultimo controllo: {when}.").format(when=checked))

    def _render_after_check(self, checked: str, pulse: bool = True) -> None:
        # updates sospesi durante il rebuild: un solo repaint alla fine
        # (niente sfarfallio quando si ricreano righe e cell widget)
        self.table.setUpdatesEnabled(False)
        try:
            self._do_render(checked, pulse)
        finally:
            self.table.setUpdatesEnabled(True)

    def _do_render(self, checked: str, pulse: bool) -> None:
        self._last_checked = checked
        watches = self.repo.list_watches()
        folders = self.repo.list_folders(PROVIDER)
        by_folder: dict = {}
        for w in watches:
            fid = w["folder_id"] if "folder_id" in w.keys() else None
            by_folder.setdefault(fid, []).append(w)
        # totale (somma degli ultimi prezzi noti) per l'intestazione di cartella
        totals: dict = {}
        for fid, ws in by_folder.items():
            if fid is None:
                continue
            totals[fid] = sum(
                self.repo.last_price(w_["provider"], w_["ref_id"]) or 0.0
                for w_ in ws if str(w_["ref_id"]) not in self._no_match_refs
            )
        # modello visuale: cartelle (con le loro carte, se espanse) e poi le
        # carte fuori dalle cartelle
        entries: list[tuple[str, object]] = []
        for f in folders:
            entries.append(("folder", f))
            if f["expanded"]:
                entries.extend(("watch", w) for w in by_folder.get(f["id"], []))
        entries.extend(("watch", w) for w in by_folder.get(None, []))
        self._row_entries = entries

        self.table.clearSpans()   # gli span delle cartelle si ricreano da zero
        self.table.setRowCount(len(entries))
        default_h = self.table.verticalHeader().defaultSectionSize()
        for row, (kind, payload) in enumerate(entries):
            if kind == "folder":
                self._set_folder_row(row, payload,
                                     len(by_folder.get(payload["id"], [])),
                                     totals.get(payload["id"], 0.0))
                continue
            self.table.setRowHeight(row, default_h)  # annulla eventuali altezze da cartella
            watch = payload
            no_match = str(watch["ref_id"]) in self._no_match_refs
            prices = self.repo.last_price_change(watch["provider"], watch["ref_id"])
            last = prices[0] if prices else None
            prev = prices[1] if len(prices) > 1 else None
            change = None
            if last is not None and prev not in (None, 0):
                change = (last - prev) / prev * 100.0
            self._set_row(row, watch, last_price=last, change=change, checked=checked, no_match=no_match)
            if pulse and change and not no_match:  # cella prezzo "lampeggia" al cambio
                price_item = self.table.item(row, 8)
                if price_item is not None:
                    color = theme.POSITIVE if change >= 0 else theme.NEGATIVE
                    anim.pulse_item(price_item, color, self.table)

    def _set_folder_row(self, row: int, folder, count: int, total: float = 0.0) -> None:
        """Riga-cartella 'canonica': freccia + icona cartella + nome +
        numero di carte + totale €, e pulsanti dedicati (rinomina/elimina)
        nella colonna Azioni."""
        expanded = bool(folder["expanded"])
        arrow = "▾" if expanded else "▸"
        icon_char = "📂" if expanded else "📁"
        pieces = [(tr("1 carta") if count == 1 else tr("{n} carte").format(n=count))
                  if count else tr("vuota")]
        if total > 0:
            pieces.append(f"{total:.2f} €")
        label = f"  {arrow}  {icon_char}  {folder['name']}    ·    " + "    ·    ".join(pieces)
        for c in range(16):   # via i resti di un eventuale render precedente
            self.table.removeCellWidget(row, c)
            self.table.setItem(row, c, QTableWidgetItem(""))
        item = QTableWidgetItem(label)
        font = QFont(self.table.font())
        font.setBold(True)
        item.setFont(font)
        item.setBackground(QColor(theme.SURFACE_2))
        item.setToolTip(tr("Clic per aprire/chiudere · trascina qui le carte per spostarle dentro"))
        self.table.setItem(row, 0, item)
        # azioni della cartella (colonna Azioni, fuori dallo span)
        actions = QWidget()
        actions.setStyleSheet("background: transparent;")
        arow = QHBoxLayout(actions)
        arow.setContentsMargins(0, 0, 0, 0)
        arow.setSpacing(2)
        icon_sz = QSize(self._rp(16), self._rp(16))
        for icon, tip, slot in (
            (self._pencil_icon, tr("Rinomina cartella"),
             lambda _=False, f=folder: self._rename_folder(f)),
            (self._trash_icon, tr("Elimina cartella (le carte tornano fuori)"),
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
        self.table.setSpan(row, 0, 1, 15)   # tutte le colonne tranne Azioni
        self.table.setRowHeight(row, self._rp(40))

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
                worker.wait(2000)
