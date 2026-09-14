"""Collezione: cosa possiedo, quanto vale, e come lo tengo in ordine.

Due modi di guardare la stessa collezione, e servono davvero entrambi:

- **Inventario** — la tabella: ogni stampa con le sue copie, il suo stato, il
  suo prezzo e quanto pesa sul totale. È la vista per cercare, ordinare e fare
  i conti;
- **Raccoglitori** — le pagine: nove tasche per volta, immagini grandi,
  trascinamento. È la vista per *guardarsela*, che è metà del motivo per cui si
  colleziona.

## Il valore, e perché non è mai un numero solo

Il prezzo di una carta qui è **l'annuncio più basso su CardTrader per quella
stampa** — la stessa misura del Market Watch, presa dallo stesso provider
condiviso (`core/prices`), quindi con lo stesso freno anti-raffica. Da questo
discendono tre scelte che l'interfaccia non nasconde mai:

1. il totale vale per **la parte di collezione che ha un prezzo**, e quante
   copie non ce l'hanno è scritto accanto. Una collezione di 500 carte con 88
   senza prezzo non ha "un valore": ne ha uno parziale, e va detto;
2. **"nessuno la vende" ≠ "mai controllata"**. La prima è un'informazione (la
   carta è stata guardata), la seconda è un buco. Sono contate a parte;
3. il **guadagno** confronta valore e spesa solo sulle carte che hanno
   entrambi i dati. Sottrarre la spesa di una parte dal valore di tutto darebbe
   un numero più grande e completamente falso.

## Perché i prezzi non si aggiornano da soli

Ogni stampa è **una richiesta** all'API (vedi `PriceFetchWorker` nel Market
Watch: l'API non sa rispondere per più stampe insieme). Una collezione vera
sono centinaia o migliaia di stampe: un aggiornamento automatico a ogni avvio
sarebbe una raffica verso un servizio dietro Cloudflare, cioè esattamente
quello che le regole di questo progetto vietano. Quindi si aggiorna **quando lo
chiedi tu**, il pulsante dice **quante richieste costerà**, e si può fermare a
metà senza perdere quello che è già arrivato.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QPointF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import badges, rarity, theme
from core.context import AppContext
from core.i18n import tr
from core.prices import catalog, cardtrader, config
from core.prices.cardtrader import CardTraderClient, CardTraderProvider

from .add_dialog import AddCardDialog
from .binder_view import BinderPage, CardTray
from .format import quando as _quando
from .format import soldi as _soldi
from .images import ThumbSource
from .repository import LAYOUTS, CollectionRepository
from .workers import PriceRefreshWorker

PROVIDER = "cardtrader"

#: Oltre questi giorni un prezzo è "vecchio" e rientra nell'aggiornamento
#: rapido. Sette perché è il ritmo con cui si muove il mercato delle singole:
#: più corto vorrebbe dire ricontrollare tutto ogni volta, più lungo vorrebbe
#: dire mostrare la settimana scorsa.
STALE_DAYS = 7

ROW_ICON = QSize(40, 56)
#: "questa riga ha gia la sua miniatura": non basta guardare se l'icona e
#: nulla, perche la cornice vuota e comunque un'icona.
_ROLE_HA_IMG = Qt.ItemDataRole.UserRole + 1
ROW_H = 64
BADGE_H = 18

COLONNE = ("", "Carta", "Set", "Rarità", "Stato", "Copie", "Prezzo",
           "Valore", "Pagata", "Raccoglitore")
COL_ICONA, COL_NOME, COL_SET, COL_RAR, COL_STATO = 0, 1, 2, 3, 4
COL_COPIE, COL_PREZZO, COL_VALORE, COL_PAGATA, COL_BINDER = 5, 6, 7, 8, 9

ORDINAMENTI = (
    ("nome", "Nome"), ("valore", "Valore"), ("prezzo", "Prezzo"),
    ("copie", "Copie"), ("set", "Set"), ("recenti", "Aggiunte di recente"),
)


def _arrow_icon(verso: str, color: str = theme.TEXT_MUTED, size: int = 28) -> QIcon:
    """Triangolino disegnato a runtime.

    ◀ ▶ ▲ ▼ come CARATTERI non ci sono nel font incorporato (Inter): i pulsanti
    uscivano vuoti. Visto in una schermata coi font veri — che è esattamente il
    motivo per cui in questo progetto le schermate si guardano.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    u = size / 100.0
    punti = {
        "left":  [(62, 22), (62, 78), (30, 50)],
        "right": [(38, 22), (38, 78), (70, 50)],
        "up":    [(22, 62), (78, 62), (50, 30)],
        "down":  [(22, 38), (78, 38), (50, 70)],
    }[verso]
    painter.drawPolygon(QPolygonF([QPointF(x * u, y * u) for x, y in punti]))
    painter.end()
    return QIcon(pixmap)


def _empty_frame(size: QSize) -> QIcon:
    """Cornice vuota al posto della miniatura: dice "qui c'è una carta, la sua
    immagine no" invece di lasciare un buco che sembra una riga rotta."""
    pixmap = QPixmap(size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(theme.BORDER), 1))
    painter.setBrush(QColor(theme.SURFACE_2))
    painter.drawRoundedRect(0.5, 0.5, size.width() - 1.0, size.height() - 1.0, 4, 4)
    painter.end()
    return QIcon(pixmap)


class _CatalogoPerProvider:
    """Il minimo che `CardTraderProvider` si aspetta da un "repo".

    Il provider vuole saper cercare per nome (`search_catalog`); la Collezione
    non ha una tabella di catalogo sua, legge quella condivisa. Invece di
    passargli `None` e sperare che nessuno chiami quel metodo, gli si dà
    l'oggetto piccolo che sa rispondere.
    """

    def __init__(self, storage) -> None:
        self._storage = storage

    def search_catalog(self, provider, query, limit: int = 25):
        return catalog.search_rows(self._storage, provider, query, limit)


class CollectionWidget(QWidget):
    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.repo = CollectionRepository(context.storage)
        self.repo.cleanup_prices(PROVIDER)     # niente prezzi orfani
        self.thumbs = ThumbSource(context.storage, self)
        self.thumbs.ready.connect(self._on_thumb)
        self._items: list = []                 # righe mostrate in Inventario
        self._rows_by_name: dict[str, list[int]] = {}
        self._price_worker: PriceRefreshWorker | None = None
        self._binder_id = None                 # raccoglitore aperto
        self._page = 0
        #: pixel che lo stile toglie ai lati dei widget di cella; si misura
        #: al primo disegno (vedi `_misura_cell_pad`), qui c'è solo una stima
        #: per non far comparire la prima tabella già tagliata
        self._cell_pad = 26
        #: le righe piccole del riepilogo (vedi `_sottoriga`)
        self._sottorighe: list[QLabel] = []
        self._sort = self.repo.get_setting("sort", "nome")
        self._sort_desc = self.repo.get_setting("sort_desc", "0") == "1"
        self._build_provider()
        self._load_rate_interval()
        self._build_ui()
        self._reload()
        # Le miniature delle righe visibili si chiedono dopo il primo disegno:
        # prima della `show()` la tabella non sa ancora quali righe siano a
        # schermo, e le chiederebbe tutte.
        QTimer.singleShot(300, self._load_visible_thumbs)

    # ------------------------------------------------------------- setup ---
    def _build_provider(self) -> None:
        token = config.load_token(self.context.data_dir)
        if token:
            self.client = CardTraderClient(token)
            self.provider = CardTraderProvider(
                self.client, _CatalogoPerProvider(self.context.storage))
        else:
            self.client = None
            self.provider = None

    def _load_rate_interval(self) -> None:
        """La spaziatura fra le chiamate si porta avanti fra le sessioni.

        Il limitatore è **uno solo** per tutta l'app, e il valore imparato sta
        in **un** file condiviso (`core/prices/config.py`): con una copia per
        modulo vinceva sempre chi si costruiva per ultimo — in ordine
        alfabetico il Market Watch — e la calibrazione fatta qui spariva a ogni
        avvio senza che si vedesse.
        """
        salvato = config.load_interval(self.context.data_dir)
        if salvato > 0:
            cardtrader.LIMITER.adopt(salvato)

    def _save_rate_interval(self) -> None:
        config.save_interval(self.context.data_dir, cardtrader.LIMITER.interval)

    # ---------------------------------------------------------------- UI ---
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        # --- intestazione ---
        header = QHBoxLayout()
        header.setSpacing(10)
        titolo_box = QVBoxLayout()
        titolo_box.setSpacing(1)
        titolo = QLabel(tr("Collezione"))
        titolo.setObjectName("title")
        sottotitolo = QLabel(tr("Quello che possiedi, e quanto vale"))
        sottotitolo.setObjectName("subtitle")
        titolo_box.addWidget(titolo)
        titolo_box.addWidget(sottotitolo)
        header.addLayout(titolo_box)
        header.addStretch(1)
        self.chip_stato = QLabel()
        self.chip_stato.setObjectName("chip")
        header.addWidget(self.chip_stato)
        self.add_btn = QPushButton(tr("Aggiungi carta"))
        self.add_btn.setObjectName("primary")
        self.add_btn.clicked.connect(lambda: self.add_card())
        header.addWidget(self.add_btn)
        self.refresh_btn = QPushButton(tr("Aggiorna i prezzi"))
        self.refresh_btn.clicked.connect(self._menu_aggiorna)
        header.addWidget(self.refresh_btn)
        root.addLayout(header)

        # --- riepilogo: i conti, con accanto quello che non si sa ---
        riepilogo = QFrame()
        riepilogo.setObjectName("card")
        riep = QHBoxLayout(riepilogo)
        riep.setContentsMargins(16, 12, 16, 12)
        riep.setSpacing(20)
        self.stat_valore = self._stat(riep, tr("Valore"))
        self.stat_carte = self._stat(riep, tr("Carte"))
        self.stat_spesa = self._stat(riep, tr("Spesa"))
        self.stat_guadagno = self._stat(riep, tr("Differenza"))
        riep.addStretch(1)
        self.stat_agg = QLabel()
        self.stat_agg.setObjectName("subtitle")
        self.stat_agg.setAlignment(Qt.AlignmentFlag.AlignRight
                                   | Qt.AlignmentFlag.AlignVCenter)
        # Va a capo invece di essere tagliata: in una finestra stretta il
        # riepilogo non ci sta tutto, e Qt accorcia i figli sotto la loro
        # misura naturale — "Prezzi aggiornati" diventava "ezzi aggiornati".
        self.stat_agg.setWordWrap(True)
        self._sottorighe.append(self.stat_agg)
        riep.addWidget(self.stat_agg)
        root.addWidget(riepilogo)

        # --- selettore delle due viste ---
        barra = QHBoxLayout()
        barra.setSpacing(8)
        self.tab_inv = QPushButton(tr("Inventario"))
        self.tab_inv.setCheckable(True)
        self.tab_inv.setChecked(True)
        self.tab_inv.clicked.connect(lambda: self._mostra(0))
        self.tab_bind = QPushButton(tr("Raccoglitori"))
        self.tab_bind.setCheckable(True)
        self.tab_bind.clicked.connect(lambda: self._mostra(1))
        # Larghezza fissa: senza, nascondendo la ricerca (vista Raccoglitori) i
        # due pulsanti si allargavano su tutta la riga.
        for b in (self.tab_inv, self.tab_bind):
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        barra.addWidget(self.tab_inv)
        barra.addWidget(self.tab_bind)
        barra.addSpacing(14)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("🔍  Filtra per nome, set o rarità…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._fill_table())
        barra.addWidget(self.search, 1)
        self.sort_combo = QComboBox()
        for chiave, etichetta in ORDINAMENTI:
            self.sort_combo.addItem(tr(etichetta), chiave)
        indice = self.sort_combo.findData(self._sort)
        self.sort_combo.setCurrentIndex(max(0, indice))
        self.sort_combo.currentIndexChanged.connect(self._on_sort)
        barra.addWidget(self.sort_combo)
        self.sort_dir = QPushButton()
        self.sort_dir.setIcon(_arrow_icon("down" if self._sort_desc else "up"))
        self.sort_dir.setFixedWidth(34)
        self.sort_dir.setToolTip(tr("Inverti l'ordine"))
        self.sort_dir.clicked.connect(lambda: self._on_sort_dir())
        barra.addWidget(self.sort_dir)
        barra.addStretch(0)
        root.addLayout(barra)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_inventory())
        self.stack.addWidget(self._build_binders())
        root.addWidget(self.stack, 1)

        # --- piede: avanzamento e stato ---
        piede = QHBoxLayout()
        piede.setSpacing(10)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setMaximumHeight(10)
        self.progress.setTextVisible(False)
        self.stop_btn = QPushButton(tr("Ferma"))
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(lambda: self._stop_refresh())
        self.status = QLabel()
        self.status.setObjectName("status")
        piede.addWidget(self.status, 1)
        piede.addWidget(self.progress, 1)
        piede.addWidget(self.stop_btn)
        root.addLayout(piede)

    #: tetto alla larghezza chiesta da una riga piccola del riepilogo: senza,
    #: una frase lunga si prenderebbe tutta la card
    SOTTORIGA_MAX = 230

    def _sottoriga(self, label: QLabel, testo: str) -> None:
        """Scrive una riga piccola del riepilogo e ricorda quanto le servirebbe.

        Le righe del riepilogo hanno `wordWrap`, e con quello acceso Qt dichiara
        una larghezza *preferita* più stretta del testo: in una finestra larga
        andavano a capo con mezza card libera. Ma un minimo fisso è peggio del
        male — in una finestra stretta i blocchi si sovrapponevano e "Prezzi
        aggiornati" tornava tagliato. Quindi la larghezza naturale si **ricorda**
        e si concede solo finché c'è spazio (`_applica_minimi`): larga quando
        si può, a capo quando serve.
        """
        label.setText(testo)
        label.setProperty("naturale",
                          min(label.fontMetrics().horizontalAdvance(testo) + 2,
                              self.SOTTORIGA_MAX))
        self._applica_minimi()

    def _applica_minimi(self) -> None:
        for label in getattr(self, "_sottorighe", ()):
            naturale = label.property("naturale") or 0
            label.setMinimumWidth(0 if self.width() < self.STRETTA else naturale)

    def _stat(self, dove, titolo: str):
        """Un blocchetto del riepilogo: cifra grande, riga piccola sotto."""
        colonna = QVBoxLayout()
        colonna.setSpacing(0)
        etichetta = QLabel(titolo)
        etichetta.setObjectName("subtitle")
        valore = QLabel("—")
        font = valore.font()
        font.setPointSizeF(font.pointSizeF() + 5)
        font.setBold(True)
        valore.setFont(font)
        dettaglio = QLabel("")
        dettaglio.setObjectName("subtitle")
        dettaglio.setWordWrap(True)
        self._sottorighe.append(dettaglio)
        colonna.addWidget(etichetta)
        colonna.addWidget(valore)
        colonna.addWidget(dettaglio)
        dove.addLayout(colonna)
        return valore, dettaglio

    def _build_inventory(self) -> QWidget:
        pagina = QWidget()
        lay = QVBoxLayout(pagina)
        lay.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, len(COLONNE))
        self.table.setHorizontalHeaderLabels([tr(c) if c else "" for c in COLONNE])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setIconSize(ROW_ICON)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.table.cellDoubleClicked.connect(self._on_double_click)
        self.table.verticalScrollBar().valueChanged.connect(
            lambda _v: self._load_visible_thumbs())
        intestazione = self.table.horizontalHeader()
        intestazione.setSectionResizeMode(COL_NOME, QHeaderView.ResizeMode.Stretch)
        for c in (COL_STATO, COL_COPIE, COL_PREZZO, COL_VALORE, COL_PAGATA,
                  COL_BINDER):
            intestazione.setSectionResizeMode(
                c, QHeaderView.ResizeMode.ResizeToContents)
        # Set, rarità e miniatura NON sono elementi di tabella ma widget di
        # cella: `ResizeToContents` misura l'elemento — che lì non c'è — e le
        # pillole uscivano tagliate a metà ("QC…" invece di "QCSR"). La
        # larghezza la calcoliamo noi dopo aver riempito (`_fit_columns`).
        for c in (COL_ICONA, COL_SET, COL_RAR):
            intestazione.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(COL_ICONA, ROW_ICON.width() + 18)
        lay.addWidget(self.table)
        self.empty = QLabel()
        self.empty.setObjectName("subtitle")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setVisible(False)
        lay.addWidget(self.empty)
        return pagina

    def _build_binders(self) -> QWidget:
        """Tre colonne: gli scaffali, la pagina aperta, le carte da sistemare.

        Le carte sfuse stanno a DESTRA e non sotto l'elenco: così la pagina si
        stringe sulle tasche invece di galleggiare in mezzo a un'area vuota, e
        il gesto viene da sé — si prende da destra e si posa sulla pagina.
        """
        pagina = QWidget()
        lay = QHBoxLayout(pagina)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        # --- gli scaffali ---
        sinistra = QVBoxLayout()
        sinistra.setSpacing(8)
        etichetta = QLabel(tr("Raccoglitori"))
        etichetta.setObjectName("subtitle")
        sinistra.addWidget(etichetta)
        self.binder_list = QListWidget()
        self.binder_list.setObjectName("softList")
        self.binder_list.setFixedWidth(206)
        self.binder_list.currentItemChanged.connect(self._on_binder_chosen)
        self.binder_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.binder_list.customContextMenuRequested.connect(self._binder_menu)
        sinistra.addWidget(self.binder_list, 1)
        nuovo = QPushButton(tr("Nuovo raccoglitore"))
        nuovo.clicked.connect(lambda: self.new_binder())
        sinistra.addWidget(nuovo)
        lay.addLayout(sinistra)

        # --- la pagina aperta ---
        centro = QVBoxLayout()
        centro.setSpacing(8)
        testa = QHBoxLayout()
        testa.setSpacing(8)
        self.binder_title = QLabel(tr("Nessun raccoglitore"))
        font = self.binder_title.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() + 2)
        self.binder_title.setFont(font)
        testa.addWidget(self.binder_title)
        testa.addStretch(1)
        self.binder_value = QLabel()
        self.binder_value.setObjectName("subtitle")
        testa.addWidget(self.binder_value)
        self.layout_combo = QComboBox()
        for colonne, righe in LAYOUTS:
            self.layout_combo.addItem(f"{colonne}×{righe}", (colonne, righe))
        self.layout_combo.setToolTip(tr("Formato della pagina"))
        self.layout_combo.currentIndexChanged.connect(self._on_layout)
        testa.addWidget(self.layout_combo)
        self.prev_btn = QPushButton()
        self.prev_btn.setIcon(_arrow_icon("left"))
        self.prev_btn.setFixedWidth(34)
        self.prev_btn.setToolTip(tr("Pagina precedente"))
        self.prev_btn.clicked.connect(lambda: self._gira(-1))
        self.page_label = QLabel("—")
        self.page_label.setObjectName("subtitle")
        self.page_label.setMinimumWidth(86)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_btn = QPushButton()
        self.next_btn.setIcon(_arrow_icon("right"))
        self.next_btn.setFixedWidth(34)
        self.next_btn.setToolTip(tr("Pagina successiva"))
        self.next_btn.clicked.connect(lambda: self._gira(+1))
        testa.addWidget(self.prev_btn)
        testa.addWidget(self.page_label)
        testa.addWidget(self.next_btn)
        centro.addLayout(testa)

        self.page = BinderPage()
        self.page.set_thumbs(self.thumbs)
        self.page.setSizePolicy(QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Expanding)
        self.page.dropped.connect(self._on_drop)
        self.page.slot_menu.connect(self._slot_menu)
        self.page.slot_activated.connect(self._on_slot_activated)
        # La pagina sta dentro una "card" del tema: senza, le tasche
        # galleggiavano sullo sfondo e non si capiva dove finisse il foglio.
        foglio = QFrame()
        foglio.setObjectName("card")
        foglio_lay = QVBoxLayout(foglio)
        foglio_lay.setContentsMargins(10, 10, 10, 10)
        foglio_lay.addWidget(self.page)
        centro.addWidget(foglio, 1)
        lay.addLayout(centro, 1)

        # --- le carte ancora da sistemare ---
        destra = QVBoxLayout()
        destra.setSpacing(8)
        etichetta2 = QLabel(tr("Carte sfuse"))
        etichetta2.setObjectName("subtitle")
        etichetta2.setToolTip(tr("Trascinale in una tasca per metterle nel raccoglitore"))
        destra.addWidget(etichetta2)
        self.tray = CardTray()
        self.tray.setObjectName("softList")
        self.tray.setFixedWidth(230)
        self.tray.setIconSize(QSize(30, 42))
        self.tray.setToolTip(tr("Trascina una carta in una tasca della pagina"))
        self.tray.verticalScrollBar().valueChanged.connect(
            lambda _v: self._load_visible_tray())
        destra.addWidget(self.tray, 1)
        self.tray_hint = QLabel()
        self.tray_hint.setObjectName("subtitle")
        self.tray_hint.setWordWrap(True)
        destra.addWidget(self.tray_hint)
        lay.addLayout(destra)
        return pagina

    # -------------------------------------------------------- caricamento ---
    def _mostra(self, indice: int) -> None:
        self._refresh_chip()       # il token può essere comparso nel frattempo
        self.stack.setCurrentIndex(indice)
        self.tab_inv.setChecked(indice == 0)
        self.tab_bind.setChecked(indice == 1)
        for w in (self.search, self.sort_combo, self.sort_dir):
            w.setVisible(indice == 0)
        if indice == 1:
            self._reload_binders()
        else:
            self._load_visible_thumbs()

    def _reload(self) -> None:
        self._items = self.repo.list_items(PROVIDER)
        self.thumbs.resolve([r["card_name"] for r in self._items])
        self._fill_table()
        self._refresh_summary()
        self._refresh_chip()
        if self.stack.currentIndex() == 1:
            self._reload_binders()

    def _rileggi_token(self) -> None:
        """Ricostruisce il provider se il token è comparso (o sparito).

        Serve perché la Collezione stessa dice "il token si imposta dal Market
        Watch": chi segue il consiglio tornava qui e trovava tutto spento fino
        al riavvio, cioè il contrario di quello che gli era stato promesso.
        """
        aveva = self.provider is not None
        adesso = bool(config.load_token(self.context.data_dir))
        if aveva != adesso:
            self._build_provider()

    def _refresh_chip(self) -> None:
        """Un solo chip, che dice la cosa che manca per prima."""
        self._rileggi_token()
        if not catalog.sincronizzato(self.context.storage, PROVIDER):
            self._set_chip(self.chip_stato,
                           tr("Catalogo stampe da sincronizzare"), "warn")
            return
        if self.provider is None:
            self._set_chip(self.chip_stato, tr("Token CardTrader mancante"), "warn")
            return
        self._set_chip(self.chip_stato, tr("Pronta"), "ok")

    @staticmethod
    def _set_chip(label: QLabel, testo: str, stato: str) -> None:
        label.setText(testo)
        label.setProperty("state", stato)
        label.style().unpolish(label)
        label.style().polish(label)

    def _filtrate(self) -> list:
        testo = self.search.text().strip().lower()
        righe = self._items
        if testo:
            righe = [r for r in righe
                     if testo in (r["card_name"] or "").lower()
                     or testo in (r["set_code"] or "").lower()
                     or testo in (r["detail"] or "").lower()]
        return self._ordinate(righe)

    def _ordinate(self, righe: list) -> list:
        """L'ordine scelto. Chi non ha il dato va in FONDO in entrambi i versi.

        È la stessa regola del Market Watch e del Database: invertendo
        l'ordine, le righe senza prezzo galleggerebbero in cima e la lista
        sembrerebbe ordinata per sbaglio.
        """
        def chiave(r):
            prezzo = r["price"]
            copie = int(r["quantity"] or 0)
            if self._sort == "valore":
                return (prezzo is None, -(float(prezzo or 0) * copie))
            if self._sort == "prezzo":
                return (prezzo is None, -float(prezzo or 0))
            if self._sort == "copie":
                return (False, -copie)
            if self._sort == "set":
                return (not (r["set_code"] or ""), (r["set_code"] or "").lower())
            if self._sort == "recenti":
                return (False, "")     # l'ordine è già quello di inserimento
            return (False, (r["card_name"] or "").lower())

        if self._sort == "recenti":
            ordinate = sorted(righe, key=lambda r: int(r["id"]), reverse=True)
        else:
            ordinate = sorted(righe, key=chiave)
        if self._sort_desc:
            # Il verso si inverte solo fra le righe che HANNO il dato: quelle
            # senza restano in fondo (vedi sopra).
            con = [r for r in ordinate if not self._manca(r)]
            senza = [r for r in ordinate if self._manca(r)]
            ordinate = list(reversed(con)) + senza
        return ordinate

    def _manca(self, r) -> bool:
        if self._sort in ("valore", "prezzo"):
            return r["price"] is None
        if self._sort == "set":
            return not (r["set_code"] or "")
        return False

    def _on_sort(self, _indice: int) -> None:
        self._sort = self.sort_combo.currentData()
        self.repo.set_setting("sort", self._sort)
        self._fill_table()

    def _on_sort_dir(self) -> None:
        self._sort_desc = not self._sort_desc
        self.sort_dir.setIcon(_arrow_icon("down" if self._sort_desc else "up"))
        self.repo.set_setting("sort_desc", "1" if self._sort_desc else "0")
        self._fill_table()

    # ------------------------------------------------------- inventario ---
    def _fill_table(self) -> None:
        righe = self._filtrate()
        self._rows_by_name = {}
        self.table.setRowCount(len(righe))
        for r, dato in enumerate(righe):
            self.table.setRowHeight(r, ROW_H)
            nome = dato["card_name"]
            self._rows_by_name.setdefault(nome, []).append(r)

            icona = QTableWidgetItem()
            icona.setData(Qt.ItemDataRole.UserRole, int(dato["id"]))
            pix = self.thumbs.pixmap(nome)
            if pix is not None and not pix.isNull():
                icona.setIcon(QIcon(pix))
                icona.setData(_ROLE_HA_IMG, True)
            else:
                icona.setIcon(self._empty_icon())
            self.table.setItem(r, COL_ICONA, icona)

            titolo = QTableWidgetItem(nome)
            titolo.setData(Qt.ItemDataRole.UserRole, int(dato["id"]))
            # Il suggerimento porta TUTTO: in una finestra stretta il nome è
            # accorciato e due colonne spariscono, e quel che si toglie da
            # vedere deve restare a portata di puntatore.
            tip = [nome, dato["detail"] or ""]
            if dato["paid"] is not None:
                tip.append(tr("Pagata {prezzo}").format(
                    prezzo=_soldi(dato["paid"], dato["currency"])))
            if dato["binder_name"]:
                tip.append(tr("Raccoglitore: {name}").format(
                    name=dato["binder_name"]))
            if dato["note"]:
                tip.append(dato["note"])
            titolo.setToolTip("\n".join(x for x in tip if x))
            self.table.setItem(r, COL_NOME, titolo)

            codice = (dato["set_code"] or "").upper()
            self.table.setCellWidget(
                r, COL_SET,
                self._pill(badges.set_pill(codice, BADGE_H), codice) if codice
                else self._testo("—"))
            nome_rar = rarity.from_detail(dato["detail"] or "")
            self.table.setCellWidget(
                r, COL_RAR,
                self._pill(rarity.rarity_pixmap(nome_rar, BADGE_H), nome_rar)
                if nome_rar else self._testo("—"))

            self.table.setItem(r, COL_STATO, QTableWidgetItem(self._stato(dato)))
            copie = QTableWidgetItem(str(int(dato["quantity"] or 1)))
            copie.setTextAlignment(int(Qt.AlignmentFlag.AlignRight
                                       | Qt.AlignmentFlag.AlignVCenter))
            self.table.setItem(r, COL_COPIE, copie)

            prezzo = dato["price"]
            cella_prezzo = QTableWidgetItem(_soldi(prezzo, dato["currency"]))
            cella_prezzo.setTextAlignment(int(Qt.AlignmentFlag.AlignRight
                                              | Qt.AlignmentFlag.AlignVCenter))
            if prezzo is None:
                cella_prezzo.setForeground(QColor(theme.TEXT_DISABLED))
                cella_prezzo.setToolTip(
                    tr("Controllata il {quando}: nessuno la vende").format(
                        quando=_quando(dato["checked_at"]))
                    if dato["checked_at"] else tr("Prezzo mai controllato"))
            else:
                cella_prezzo.setToolTip(tr("Rilevato il {quando}").format(
                    quando=_quando(dato["checked_at"])))
            self.table.setItem(r, COL_PREZZO, cella_prezzo)

            totale = None if prezzo is None else float(prezzo) * int(dato["quantity"] or 1)
            cella_val = QTableWidgetItem(_soldi(totale, dato["currency"]))
            cella_val.setTextAlignment(int(Qt.AlignmentFlag.AlignRight
                                           | Qt.AlignmentFlag.AlignVCenter))
            if totale is None:
                cella_val.setForeground(QColor(theme.TEXT_DISABLED))
            self.table.setItem(r, COL_VALORE, cella_val)

            # Come il Valore: il TOTALE per le copie della riga. Con il
            # prezzo pagato per copia accanto a un valore per tutte, la riga
            # "3 copie · valore 37,20 € · pagata 8,50 €" si leggeva come un
            # guadagno tre volte più grande del vero.
            copie_riga = int(dato["quantity"] or 1)
            speso = None if dato["paid"] is None else float(dato["paid"]) * copie_riga
            pagata = QTableWidgetItem(_soldi(speso, dato["currency"]))
            pagata.setTextAlignment(int(Qt.AlignmentFlag.AlignRight
                                        | Qt.AlignmentFlag.AlignVCenter))
            if speso is None:
                pagata.setForeground(QColor(theme.TEXT_DISABLED))
            elif copie_riga > 1:
                pagata.setToolTip(tr("{prezzo} a copia").format(
                    prezzo=_soldi(dato["paid"], dato["currency"])))
            self.table.setItem(r, COL_PAGATA, pagata)

            self.table.setItem(r, COL_BINDER,
                               QTableWidgetItem(dato["binder_name"] or "—"))
        self._fit_columns()
        self._apply_responsive()
        self._refresh_empty()
        self._dillo_se_filtrato()

    def _fit_columns(self) -> None:
        """Larghezza delle colonne a pillola: quanto serve alla più larga."""
        for colonna in (COL_SET, COL_RAR):
            serve = 0
            for r in range(self.table.rowCount()):
                cella = self.table.cellWidget(r, colonna)
                if cella is not None:
                    serve = max(serve, cella.sizeHint().width())
            self.table.setColumnWidth(colonna, max(56, serve + self._cell_pad))
        # La misura vera si può prendere solo a widget disposti (vedi sotto):
        # si rimanda di un giro di eventi.
        QTimer.singleShot(0, self._misura_cell_pad)

    def _misura_cell_pad(self) -> None:
        """Quanti pixel lo stile mangia ai lati di un widget di cella.

        `QTableWidget::item` nel QSS ha un padding orizzontale, e Qt piazza il
        widget di cella dentro il rettangolo GIÀ ridotto: la colonna era larga
        72 e il widget dentro 52, quindi le pillole larghe ("QCSR", "MACR")
        uscivano tagliate di netto sul bordo destro. Il numero non si può
        scrivere a mano perché **scala con l'interfaccia** (a scala 1.3 è un
        altro): si misura, e se è cresciuto si rifà la larghezza.
        """
        for colonna in (COL_SET, COL_RAR):
            cella = self.table.cellWidget(0, colonna)
            if cella is None or cella.width() <= 0:
                continue
            perso = self.table.columnWidth(colonna) - cella.width()
            if perso > self._cell_pad - 4:
                self._cell_pad = perso + 6
                for c in (COL_SET, COL_RAR):
                    serve = max((self.table.cellWidget(r, c).sizeHint().width()
                                 for r in range(self.table.rowCount())
                                 if self.table.cellWidget(r, c) is not None),
                                default=0)
                    self.table.setColumnWidth(c, max(56, serve + self._cell_pad))
                return

    #: sotto questa larghezza il nome della carta veniva schiacciato a
    #: "Ash Bloss…": meglio togliere due colonne che rendere illeggibile la
    #: colonna per cui si guarda la tabella
    STRETTA = 1120

    def resizeEvent(self, event) -> None:  # noqa: N802 (firma Qt)
        super().resizeEvent(event)
        self._apply_responsive()

    def _apply_responsive(self) -> None:
        """Pagata e Raccoglitore spariscono in finestra stretta.

        Sono le due che si ritrovano altrove — la prima nel dialogo di
        modifica, la seconda nella vista Raccoglitori — e comunque restano nel
        suggerimento della riga. Il nome della carta, invece, non ha un
        altrove: è la colonna per cui si guarda la tabella.
        """
        stretta = self.width() < self.STRETTA
        for colonna in (COL_PAGATA, COL_BINDER):
            self.table.setColumnHidden(colonna, stretta)
        self._applica_minimi()

    def _dillo_se_filtrato(self) -> None:
        """Con un filtro attivo, il riepilogo in alto NON è quello che si vede.

        Il riepilogo è della collezione intera, ed è giusto così: è il valore
        di quello che possiedi, non di quello che stai cercando. Ma due numeri
        diversi sullo stesso schermo senza una parola di spiegazione sono un
        tranello, quindi la riga di stato lo dice.
        """
        if not self.search.text().strip():
            return
        self.status.setText(tr(
            "Filtro attivo: {n} righe di {tot}. Il riepilogo in alto è di "
            "tutta la collezione.").format(
                n=self.table.rowCount(), tot=len(self._items)))

    def _refresh_empty(self) -> None:
        """Il vuoto dice cosa manca: e sono tre vuoti diversi."""
        if self.table.rowCount():
            self.empty.setVisible(False)
            self.table.setVisible(True)
            return
        self.table.setVisible(False)
        self.empty.setVisible(True)
        if self._items:
            self.empty.setText(tr("Nessuna carta con questo filtro."))
        elif not catalog.sincronizzato(self.context.storage, PROVIDER):
            self.empty.setText(tr(
                "Per aggiungere carte serve il catalogo delle stampe: si "
                "sincronizza dal Market Watch (una volta sola, qualche minuto)."))
        else:
            self.empty.setText(tr(
                "La collezione è vuota. «Aggiungi carta» per cominciare: "
                "scegli la carta, poi la stampa che hai in mano."))

    @staticmethod
    def _stato(dato) -> str:
        pezzi = []
        if dato["condition"]:
            pezzi.append(dato["condition"])
        if dato["language"]:
            pezzi.append(dato["language"].upper())
        if dato["first_edition"]:
            pezzi.append(tr("1ª ed."))
        return " · ".join(pezzi) if pezzi else "—"

    def _empty_icon(self) -> QIcon:
        if getattr(self, "_icona_vuota", None) is None:
            self._icona_vuota = _empty_frame(self.table.iconSize())
        return self._icona_vuota

    def _pill(self, pixmap: QPixmap, tooltip: str = "") -> QWidget:
        contenitore = QWidget()
        lay = QHBoxLayout(contenitore)
        lay.setContentsMargins(8, 0, 8, 0)
        etichetta = QLabel()
        etichetta.setPixmap(pixmap)
        if tooltip:
            etichetta.setToolTip(tooltip)
        lay.addWidget(etichetta)
        lay.addStretch(1)
        return contenitore

    @staticmethod
    def _testo(testo: str) -> QWidget:
        contenitore = QWidget()
        lay = QHBoxLayout(contenitore)
        lay.setContentsMargins(8, 0, 8, 0)
        etichetta = QLabel(testo)
        etichetta.setStyleSheet(f"color: {theme.TEXT_DISABLED};")
        lay.addWidget(etichetta)
        lay.addStretch(1)
        return contenitore

    # ---------------------------------------------------------- miniature ---
    def _load_visible_thumbs(self) -> None:
        """Scarica le miniature delle SOLE righe visibili.

        Su una collezione da mille carte chiederle tutte sarebbe la raffica che
        YGOPRODeck chiede esplicitamente di non fare: a schermo ne stanno una
        decina, e quelle già su disco non costano niente.
        """
        if not self.table.rowCount() or self.stack.currentIndex() != 0:
            return
        area = self.table.viewport().rect()
        prima = self.table.rowAt(max(0, area.top()))
        ultima = self.table.rowAt(max(0, area.bottom()))
        if prima < 0:
            prima = 0
        if ultima < 0:
            ultima = self.table.rowCount() - 1
        for r in range(max(0, prima - 2), min(self.table.rowCount(), ultima + 3)):
            elemento = self.table.item(r, COL_ICONA)
            if elemento is None or elemento.data(_ROLE_HA_IMG):
                continue
            nome_item = self.table.item(r, COL_NOME)
            if nome_item is None:
                continue
            nome = nome_item.text()
            pix = self.thumbs.pixmap(nome)
            if pix is None or pix.isNull():
                self.thumbs.request(nome)   # SOLO qui si scarica
                continue
            elemento.setIcon(QIcon(pix))
            elemento.setData(_ROLE_HA_IMG, True)

    def _on_thumb(self, nome: str) -> None:
        pix = self.thumbs.pixmap(nome)
        if pix is None or pix.isNull():
            return
        for r in self._rows_by_name.get(nome, ()):
            if r < self.table.rowCount():
                elemento = self.table.item(r, COL_ICONA)
                if elemento is not None:
                    elemento.setIcon(QIcon(pix))
                    elemento.setData(_ROLE_HA_IMG, True)
        if self.stack.currentIndex() == 1:
            self.page.update()
            self._refresh_tray_icons()

    # ------------------------------------------------------------ conti ---
    def _refresh_summary(self) -> None:
        c = self.repo.totals(PROVIDER)
        valuta = c["valuta"] or "EUR"
        valore, dett_valore = self.stat_valore
        valore.setText(_soldi(c["valore"], valuta) if c["copie_valutate"] else "—")
        mancanti = c["copie_da_controllare"] + c["copie_senza_annuncio"]
        if not c["copie"]:
            self._sottoriga(dett_valore, tr("collezione vuota"))
        elif mancanti:
            # Il totale vale per la parte che ha un prezzo, e si dice quanta.
            pezzi = [tr("su {n} copie di {tot}").format(
                n=c["copie_valutate"], tot=c["copie"])]
            if c["copie_da_controllare"]:
                pezzi.append(tr("{n} mai controllate").format(
                    n=c["copie_da_controllare"]))
            if c["copie_senza_annuncio"]:
                pezzi.append(tr("{n} non in vendita").format(
                    n=c["copie_senza_annuncio"]))
            self._sottoriga(dett_valore, " · ".join(pezzi))
        else:
            self._sottoriga(dett_valore,
                            tr("tutte le {n} copie").format(n=c["copie"]))

        carte, dett_carte = self.stat_carte
        carte.setText(str(c["copie"]))
        self._sottoriga(dett_carte,
                        tr("{n} stampe diverse").format(n=c["stampe"]))
        carte.setToolTip(tr("{r} righe: la stessa stampa in stati diversi "
                            "(condizione, lingua) sta su righe separate").format(
                                r=c["righe"]))

        spesa, dett_spesa = self.stat_spesa
        spesa.setText(_soldi(c["spesa"], valuta) if c["copie_con_spesa"] else "—")
        self._sottoriga(
            dett_spesa,
            tr("su {n} copie").format(n=c["copie_con_spesa"])
            if c["copie_con_spesa"] else tr("nessun prezzo d'acquisto"))

        guadagno, dett_guadagno = self.stat_guadagno
        if c["copie_confrontabili"]:
            delta = c["guadagno"]
            segno = "+" if delta >= 0 else "−"
            guadagno.setText(f"{segno}{_soldi(abs(delta), valuta)}")
            guadagno.setStyleSheet(
                f"color: {theme.POSITIVE if delta >= 0 else theme.NEGATIVE};")
            # Il confronto vale SOLO dove ci sono entrambi i dati: dirlo è ciò
            # che separa un numero vero da uno suggestivo.
            self._sottoriga(dett_guadagno,
                            tr("su {n} copie con valore e spesa").format(
                                n=c["copie_confrontabili"]))
        else:
            guadagno.setText("—")
            guadagno.setStyleSheet("")
            self._sottoriga(dett_guadagno, tr("serve il prezzo pagato"))

        # **Il più VECCHIO, non il più recente.** Con `MAX(checked_at)` bastava
        # aggiornare una carta sola per far scrivere la data di oggi accanto a
        # un valore fatto di prezzi di mesi prima: l'unico indicatore di
        # freschezza avrebbe detto sempre la cosa più ottimista. È la lezione
        # della v1.6.1 (il prezzo fantasma) applicata al totale.
        vecchio, recente = self.repo.price_span(PROVIDER)
        if not vecchio:
            testo = tr("Prezzi mai aggiornati")
        elif vecchio[:10] == recente[:10]:
            testo = tr("Prezzi aggiornati: {quando}").format(quando=_quando(recente))
        else:
            testo = tr("Prezzi dal {vecchio} al {recente}").format(
                vecchio=_quando(vecchio), recente=_quando(recente))
        self._sottoriga(self.stat_agg, testo)

    # ------------------------------------------------------ aggiungi/modifica ---
    def add_card(self, nome_iniziale: str = ""):
        """Apre l'aggiunta e torna l'**id della riga** toccata (None = niente).

        Torna l'id perché chi aggiunge "in questa tasca" deve poterci mettere
        la carta, e la riga può essere **fusa** con una che c'era già.
        """
        if not catalog.sincronizzato(self.context.storage, PROVIDER):
            self._chiedi_catalogo()
            return None
        dialogo = AddCardDialog(
            cerca_nomi=lambda q: catalog.search_names(
                self.context.storage, PROVIDER, q),
            stampe_di=lambda n: catalog.printings(
                self.context.storage, PROVIDER, n),
            binders=self.repo.list_binders(), thumbs=self.thumbs, parent=self)
        if nome_iniziale:
            dialogo.search.setText(nome_iniziale)
            dialogo._cerca()
        if dialogo.exec() != AddCardDialog.DialogCode.Accepted:
            return None
        dati = dialogo.result_card()
        if not dati:
            return None
        binder_id = dati.pop("binder_id", None)
        slot = self.repo.first_free_slot(binder_id) if binder_id else -1
        item_id = self.repo.add_item(PROVIDER, binder_id=binder_id, slot=slot,
                                     **dati)
        self._reload()
        self.status.setText(tr("{n}× {name} in collezione.").format(
            n=dati["quantity"], name=dati["card_name"]))
        return item_id

    def _chiedi_catalogo(self) -> None:
        """Senza catalogo non si può aggiungere niente: si offre la strada.

        Il ponte è quello di sempre (`AppContext.open_module`): i moduli non si
        importano fra loro, si chiamano per nome.
        """
        risposta = QMessageBox.question(
            self, tr("Catalogo mancante"),
            tr("Per aggiungere carte serve il catalogo delle stampe di "
               "CardTrader, che si scarica dal Market Watch (una volta sola, "
               "qualche minuto).\n\nVuoi aprirlo adesso?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if risposta == QMessageBox.StandardButton.Yes:
            if not self.context.open_module("market_watch", None):
                QMessageBox.information(
                    self, tr("Market Watch"),
                    tr("Aprilo dal menu a sinistra e premi il pulsante di "
                       "sincronizzazione del catalogo."))

    def edit_item(self, item_id) -> None:
        riga = self.repo.item(item_id)
        if riga is None:
            return
        iniziale = {chiave: riga[chiave] for chiave in
                    ("ref_id", "card_name", "detail", "set_code", "image_url",
                     "quantity", "condition", "language", "first_edition",
                     "paid", "note", "binder_id")}
        iniziale["first_edition"] = bool(iniziale["first_edition"])
        dialogo = AddCardDialog(
            cerca_nomi=lambda q: [], stampe_di=lambda n: [],
            binders=self.repo.list_binders(), thumbs=self.thumbs,
            iniziale=iniziale, parent=self)
        if dialogo.exec() != AddCardDialog.DialogCode.Accepted:
            return
        dati = dialogo.result_card() or {}
        binder_prima = riga["binder_id"]
        binder_dopo = dati.get("binder_id")
        campi = {
            "quantity": dati.get("quantity", 1),
            "condition": dati.get("condition", ""),
            "language": dati.get("language", ""),
            "first_edition": int(bool(dati.get("first_edition"))),
            "paid": dati.get("paid"),
            "note": dati.get("note", ""),
        }
        if binder_dopo != binder_prima:
            campi["binder_id"] = binder_dopo
            campi["slot"] = (self.repo.first_free_slot(binder_dopo)
                             if binder_dopo is not None else -1)
        self.repo.update_item(item_id, **campi)
        self._reload()

    def _selected_item(self):
        riga = self.table.currentRow()
        if riga < 0:
            return None
        elemento = self.table.item(riga, COL_NOME)
        return None if elemento is None else elemento.data(Qt.ItemDataRole.UserRole)

    def _on_double_click(self, riga: int, _colonna: int) -> None:
        elemento = self.table.item(riga, COL_NOME)
        if elemento is not None:
            self.edit_item(elemento.data(Qt.ItemDataRole.UserRole))

    def _table_menu(self, pos) -> None:
        riga = self.table.rowAt(pos.y())
        if riga < 0:
            return
        self.table.selectRow(riga)
        item_id = self._selected_item()
        if item_id is None:
            return
        dato = self.repo.item(item_id)
        menu = QMenu(self)
        azione_mod = QAction(tr("Modifica…"), menu)
        azione_mod.triggered.connect(lambda: self.edit_item(item_id))
        menu.addAction(azione_mod)

        # Sottomenu col PADRE esplicito: `menu.addMenu(titolo)` lascerebbe
        # l'unico riferimento in una variabile Python e Qt porterebbe via
        # l'oggetto C++ appena questa funzione ritorna (GOTCHA 30).
        sub = QMenu(tr("Metti nel raccoglitore"), menu)
        vuoto = QAction(tr("Nessuno (carte sfuse)"), sub)
        vuoto.setCheckable(True)
        vuoto.setChecked(dato is not None and dato["binder_id"] is None)
        vuoto.triggered.connect(lambda: self._sposta_in(item_id, None))
        sub.addAction(vuoto)
        for b in self.repo.list_binders():
            bid = int(b["id"])
            azione = QAction(b["name"], sub)
            azione.setCheckable(True)
            azione.setChecked(dato is not None and dato["binder_id"] == bid)
            azione.triggered.connect(
                lambda _c=False, x=bid: self._sposta_in(item_id, x))
            sub.addAction(azione)
        menu.addMenu(sub)

        menu.addSeparator()
        azione_prezzo = QAction(tr("Aggiorna il prezzo di questa carta"), menu)
        azione_prezzo.setEnabled(self.provider is not None)
        azione_prezzo.triggered.connect(
            lambda: self._avvia_refresh([str(dato["ref_id"])]) if dato else None)
        menu.addAction(azione_prezzo)
        azione_del = QAction(tr("Togli dalla collezione"), menu)
        azione_del.triggered.connect(lambda: self._elimina(item_id))
        menu.addAction(azione_del)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _sposta_in(self, item_id, binder_id) -> None:
        if binder_id is None:
            self.repo.place(item_id, None, -1)
        else:
            self.repo.place(item_id, binder_id, self.repo.first_free_slot(binder_id))
        self._reload()

    def _elimina(self, item_id) -> None:
        dato = self.repo.item(item_id)
        if dato is None:
            return
        copie = int(dato["quantity"] or 1)
        if copie > 1:
            quante, ok = QInputDialog.getInt(
                self, tr("Togli dalla collezione"),
                tr("Quante copie di {name} vuoi togliere?").format(
                    name=dato["card_name"]), copie, 1, copie)
            if not ok:
                return
            if quante < copie:
                self.repo.set_quantity(item_id, copie - quante)
                self._reload()
                return
        else:
            conferma = QMessageBox.question(
                self, tr("Togli dalla collezione"),
                tr("Togliere {name} dalla collezione?").format(
                    name=dato["card_name"]),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if conferma != QMessageBox.StandardButton.Yes:
                return
        self.repo.remove_item(item_id)
        self.repo.cleanup_prices(PROVIDER)
        self._reload()

    # ----------------------------------------------------- raccoglitori ---
    def _reload_binders(self) -> None:
        precedente = self._binder_id
        self.binder_list.blockSignals(True)
        self.binder_list.clear()
        binders = self.repo.list_binders()
        for b in binders:
            elemento = QListWidgetItem(
                f"{b['name']}  ({int(b['copie'])})", self.binder_list)
            elemento.setData(Qt.ItemDataRole.UserRole, int(b["id"]))
        self.binder_list.blockSignals(False)
        if binders:
            ids = [int(b["id"]) for b in binders]
            scelto = precedente if precedente in ids else ids[0]
            self.binder_list.setCurrentRow(ids.index(scelto))
            self._binder_id = scelto
        else:
            self._binder_id = None
        self._refresh_page()
        self._refresh_tray()

    def _on_binder_chosen(self, corrente, _precedente) -> None:
        if corrente is None:
            return
        self._binder_id = corrente.data(Qt.ItemDataRole.UserRole)
        self._page = 0
        self._refresh_page()

    def _refresh_tray(self) -> None:
        """Le carte fuori dai raccoglitori, pronte da trascinare."""
        self.tray.clear()
        for riga in self.repo.list_items(PROVIDER, binder_id=None):
            testo = riga["card_name"]
            copie = int(riga["quantity"] or 1)
            if copie > 1:
                testo = f"{copie}× {testo}"
            elemento = QListWidgetItem(testo, self.tray)
            elemento.setData(Qt.ItemDataRole.UserRole, int(riga["id"]))
            elemento.setToolTip(f"{riga['card_name']}\n{riga['detail'] or ''}")
            pix = self.thumbs.pixmap(riga["card_name"])
            if pix is not None and not pix.isNull():
                elemento.setIcon(QIcon(pix))
        self._load_visible_tray()
        self.tray_hint.setText(
            tr("Trascinale in una tasca della pagina.") if self.tray.count()
            else tr("Tutte le carte sono in un raccoglitore."))

    def _refresh_tray_icons(self) -> None:
        for i in range(self.tray.count()):
            elemento = self.tray.item(i)
            if elemento is None or not elemento.icon().isNull():
                continue
            pix = self.thumbs.pixmap(self._nome_voce(elemento))
            if pix is not None and not pix.isNull():
                elemento.setIcon(QIcon(pix))

    @staticmethod
    def _nome_voce(elemento) -> str:
        """Il nome della carta di una voce del vassoio (il testo porta le copie)."""
        return (elemento.toolTip() or "").split("\n")[0]

    def _load_visible_tray(self) -> None:
        """Scarica le miniature delle SOLE voci visibili del vassoio.

        Il vassoio è largo 230 px e ne mostra una decina: con 800 carte sfuse,
        chiederle tutte sarebbe la stessa raffica della tabella.
        """
        area = self.tray.viewport().rect()
        for i in range(self.tray.count()):
            elemento = self.tray.item(i)
            if elemento is None or not elemento.icon().isNull():
                continue
            rect = self.tray.visualItemRect(elemento)
            if rect.bottom() < area.top() - 60 or rect.top() > area.bottom() + 60:
                continue
            self.thumbs.request(self._nome_voce(elemento))

    def _refresh_page(self) -> None:
        if self._binder_id is None:
            self.binder_title.setText(tr("Nessun raccoglitore"))
            self.binder_value.setText("")
            self.page_label.setText("—")
            self.page.set_items({})
            for w in (self.prev_btn, self.next_btn, self.layout_combo):
                w.setEnabled(False)
            return
        for w in (self.prev_btn, self.next_btn, self.layout_combo):
            w.setEnabled(True)
        b = self.repo.binder(self._binder_id)
        if b is None:
            self._binder_id = None
            self._refresh_page()
            return
        self.binder_title.setText(b["name"])
        colonne, righe_pag = int(b["cols"]), int(b["rows"])
        indice = self.layout_combo.findData((colonne, righe_pag))
        self.layout_combo.blockSignals(True)
        self.layout_combo.setCurrentIndex(indice if indice >= 0 else 0)
        self.layout_combo.blockSignals(False)
        self.page.set_layout_size(colonne, righe_pag)

        carte = self.repo.list_items(PROVIDER, binder_id=self._binder_id)
        self.thumbs.resolve([r["card_name"] for r in carte])
        per_pagina = max(1, colonne * righe_pag)
        slots = {}
        for r in carte:
            slot = int(r["slot"])
            if slot < 0:
                slot = self.repo.first_free_slot(self._binder_id)
                self.repo.update_item(int(r["id"]), slot=slot)
            slots[slot] = r
        pagine = max(1, (max(slots) // per_pagina + 1) if slots else 1)
        self._page = min(self._page, pagine - 1)
        self.page.set_page(self._page)
        self.page.set_items(slots)
        self.page_label.setText(tr("Pagina {n} di {tot}").format(
            n=self._page + 1, tot=pagine))
        self._pagine = pagine
        self._chiedi_immagini_pagina(slots)

        # Stessa onestà del riepilogo grande: un valore che copre quattro copie
        # accostato a "6 copie" si legge come il valore di sei.
        conti = self.repo.totals(PROVIDER, binder_id=self._binder_id)
        if not conti["copie"]:
            self.binder_value.setText(tr("ancora vuoto"))
        elif not conti["copie_valutate"] and conti["copie_da_controllare"]:
            self.binder_value.setText(tr("{n} copie · valore da aggiornare").format(
                n=conti["copie"]))
        elif not conti["copie_valutate"]:
            # tutte controllate, nessuna in vendita: è un risultato, non un buco
            self.binder_value.setText(tr("{n} copie · nessuna in vendita").format(
                n=conti["copie"]))
        elif conti["copie_valutate"] < conti["copie"]:
            self.binder_value.setText(tr("{valore} su {n} copie di {tot}").format(
                valore=_soldi(conti["valore"], conti["valuta"]),
                n=conti["copie_valutate"], tot=conti["copie"]))
        else:
            self.binder_value.setText(tr("{valore} · {n} copie").format(
                valore=_soldi(conti["valore"], conti["valuta"]), n=conti["copie"]))

    def _chiedi_immagini_pagina(self, slots: dict) -> None:
        """Le immagini delle tasche **della pagina aperta**, non di tutte.

        Un raccoglitore può avere cinquanta pagine; a schermo ce n'è una, e
        `BinderPage._draw_card` legge soltanto (`pixmap`), non scarica: se
        scaricasse, un `paintEvent` metterebbe in coda mezzo raccoglitore.
        """
        for slot in self.page.page_slots():
            riga = slots.get(slot)
            if riga is not None:
                self.thumbs.request(riga["card_name"])

    def _gira(self, passo: int) -> None:
        pagine = getattr(self, "_pagine", 1)
        # Una pagina in più in fondo quando l'ultima è piena: è lì che si
        # trascinano le carte nuove, e senza non ci sarebbe posto dove metterle.
        self._page = max(0, min(self._page + passo, pagine))
        self._refresh_page_soft()

    def _refresh_page_soft(self) -> None:
        """Cambia pagina senza ricostruire tutto (le carte sono già in mano)."""
        pagine = max(getattr(self, "_pagine", 1), self._page + 1)
        self.page.set_page(self._page)
        self.page_label.setText(tr("Pagina {n} di {tot}").format(
            n=self._page + 1, tot=pagine))
        self._chiedi_immagini_pagina(self.page._items)

    def _on_layout(self, _indice: int) -> None:
        if self._binder_id is None:
            return
        colonne, righe = self.layout_combo.currentData()
        self.repo.set_binder_layout(self._binder_id, colonne, righe)
        self._refresh_page()

    def new_binder(self) -> None:
        nome, ok = QInputDialog.getText(self, tr("Nuovo raccoglitore"),
                                        tr("Come si chiama?"))
        if not ok or not nome.strip():
            return
        nuovo = self.repo.add_binder(nome.strip())
        self._binder_id = nuovo
        self._page = 0
        self._reload_binders()

    def _binder_menu(self, pos) -> None:
        elemento = self.binder_list.itemAt(pos)
        if elemento is None:
            return
        bid = elemento.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        rinomina = QAction(tr("Rinomina…"), menu)
        rinomina.triggered.connect(lambda: self._rinomina(bid))
        menu.addAction(rinomina)
        elimina = QAction(tr("Elimina…"), menu)
        elimina.triggered.connect(lambda: self._elimina_binder(bid))
        menu.addAction(elimina)
        menu.exec(self.binder_list.viewport().mapToGlobal(pos))

    def _rinomina(self, binder_id) -> None:
        b = self.repo.binder(binder_id)
        if b is None:
            return
        nome, ok = QInputDialog.getText(self, tr("Rinomina"), tr("Nuovo nome:"),
                                        text=b["name"])
        if ok and nome.strip():
            self.repo.rename_binder(binder_id, nome.strip())
            self._reload_binders()

    def _elimina_binder(self, binder_id) -> None:
        """Chiede sempre, e distingue le due cose che si possono volere.

        Stessa lezione dei gruppi del Market Watch (v1.5.4): "elimina" senza
        domanda si preme per sbaglio, e un raccoglitore può contenere anni di
        collezione.
        """
        b = self.repo.binder(binder_id)
        if b is None:
            return
        copie = self.repo.totals(PROVIDER, binder_id=binder_id)["copie"]
        if not copie:
            self.repo.delete_binder(binder_id)
            self._reload()
            self._reload_binders()
            return
        box = QMessageBox(self)
        box.setWindowTitle(tr("Elimina il raccoglitore"))
        box.setText(tr("«{name}» contiene {n} copie.").format(
            name=b["name"], n=copie))
        box.setInformativeText(tr("Cosa ne facciamo delle carte?"))
        solo = box.addButton(tr("Tienile (diventano sfuse)"),
                             QMessageBox.ButtonRole.AcceptRole)
        tutto = box.addButton(tr("Elimina anche le carte"),
                              QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(tr("Annulla"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        premuto = box.clickedButton()
        if premuto is solo:
            self.repo.delete_binder(binder_id, con_carte=False)
        elif premuto is tutto:
            self.repo.delete_binder(binder_id, con_carte=True)
            self.repo.cleanup_prices(PROVIDER)
        else:
            return
        self._binder_id = None
        self._reload()
        self._reload_binders()

    # --- gesti sulla pagina ---
    def _on_drop(self, item_id: int, slot: int) -> None:
        if self._binder_id is None:
            return
        self.repo.place(item_id, self._binder_id, slot)
        self._items = self.repo.list_items(PROVIDER)
        self._fill_table()
        self._refresh_page()
        self._refresh_tray()
        self._refresh_summary()

    def _on_slot_activated(self, slot: int) -> None:
        riga = self.repo.item_at(self._binder_id, slot) if self._binder_id else None
        if riga is not None:
            self.edit_item(int(riga["id"]))

    def _slot_menu(self, slot: int, pos) -> None:
        if self._binder_id is None:
            return
        riga = self.repo.item_at(self._binder_id, slot)
        menu = QMenu(self)
        if riga is None:
            aggiungi = QAction(tr("Aggiungi una carta qui…"), menu)
            aggiungi.triggered.connect(lambda: self._aggiungi_in_tasca(slot))
            menu.addAction(aggiungi)
        else:
            item_id = int(riga["id"])
            modifica = QAction(tr("Modifica…"), menu)
            modifica.triggered.connect(lambda: self.edit_item(item_id))
            menu.addAction(modifica)
            sfila = QAction(tr("Togli dal raccoglitore"), menu)
            sfila.triggered.connect(lambda: self._sposta_in(item_id, None))
            menu.addAction(sfila)
            menu.addSeparator()
            elimina = QAction(tr("Togli dalla collezione"), menu)
            elimina.triggered.connect(lambda: self._elimina(item_id))
            menu.addAction(elimina)
        menu.exec(pos)

    def _aggiungi_in_tasca(self, slot: int) -> None:
        """Aggiunge una carta e la mette **in quella tasca**.

        Guardare "quali righe sono nuove" non bastava: `add_item` FONDE le
        copie con una riga identica già esistente, quindi aggiungendo una carta
        che si possiede già non nasceva nessuna riga nuova e la tasca restava
        vuota senza dire niente. `add_card` torna l'id della riga toccata,
        nuova o fusa che sia.
        """
        item_id = self.add_card()
        if item_id is not None and self._binder_id is not None:
            self.repo.place(item_id, self._binder_id, slot)
            self._reload()
            self._refresh_page()

    # ------------------------------------------------------------ prezzi ---
    def _menu_aggiorna(self) -> None:
        """Il menu dice **quante richieste** costa ogni scelta.

        Non è un dettaglio tecnico: è il tempo che l'utente sta per spendere e
        il traffico che sta per mandare a un servizio che non è suo.
        """
        self._rileggi_token()
        if self.provider is None:
            QMessageBox.information(
                self, tr("Token mancante"),
                tr("Per leggere i prezzi serve il token CardTrader: si "
                   "imposta dal Market Watch (pulsante con la chiave)."))
            return
        soglia = (datetime.now() - timedelta(days=STALE_DAYS)).isoformat(
            timespec="seconds")
        vecchie = self.repo.refs_to_check(PROVIDER, soglia)
        tutte = self.repo.all_refs(PROVIDER)
        if not tutte:
            self.status.setText(tr("Non c'è ancora niente da aggiornare."))
            return
        menu = QMenu(self)
        azione_vecchie = QAction(
            tr("Solo mancanti o più vecchie di {g} giorni  ({n} richieste)").format(
                g=STALE_DAYS, n=len(vecchie)), menu)
        azione_vecchie.setEnabled(bool(vecchie))
        azione_vecchie.triggered.connect(lambda: self._avvia_refresh(vecchie))
        menu.addAction(azione_vecchie)
        azione_tutte = QAction(
            tr("Tutta la collezione  ({n} richieste)").format(n=len(tutte)), menu)
        azione_tutte.triggered.connect(lambda: self._avvia_refresh(tutte))
        menu.addAction(azione_tutte)
        menu.exec(self.refresh_btn.mapToGlobal(
            self.refresh_btn.rect().bottomLeft()))

    def _avvia_refresh(self, refs: list) -> None:
        if self.provider is None or not refs:
            return
        if self._price_worker is not None and self._price_worker.isRunning():
            self.status.setText(tr("C'è già un aggiornamento in corso."))
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, len(refs))
        self.progress.setValue(0)
        self.stop_btn.setVisible(True)
        self.refresh_btn.setEnabled(False)
        self.status.setText(tr("Aggiorno {n} stampe…").format(n=len(refs)))
        self._chieste = len(refs)
        self._price_worker = PriceRefreshWorker(self.provider, refs, self)
        self._price_worker.progress.connect(self._on_progress)
        self._price_worker.finished_ok.connect(self._on_prices)
        self._price_worker.failed.connect(self._on_price_failed)
        self._price_worker.start()

    def _on_progress(self, fatte: int, totali: int) -> None:
        self.progress.setValue(fatte)
        self.status.setText(tr("Aggiorno i prezzi… {a} di {b}").format(
            a=fatte, b=totali))

    def _on_prices(self, righe: list, falliti: int, ultimo_errore: str) -> None:
        if righe:
            self.repo.set_prices(PROVIDER, righe)
        self._save_rate_interval()
        self._fine_refresh()
        senza = sum(1 for r in righe if r[1] is None)
        pezzi = [tr("{n} stampe aggiornate").format(n=len(righe) - senza)]
        if senza:
            pezzi.append(tr("{n} senza annunci").format(n=senza))
        if falliti:
            pezzi.append(tr("{n} non riuscite ({err})").format(
                n=falliti, err=ultimo_errore[:60]))
        # Fermandosi a metà, le stampe MAI tentate non compaiono da nessuna
        # parte: senza questo conto il riepilogo sembrerebbe completo.
        saltate = max(0, getattr(self, "_chieste", 0) - len(righe) - falliti)
        if saltate:
            pezzi.append(tr("{n} non controllate").format(n=saltate))
        self.status.setText(" · ".join(pezzi) + ".")
        self._reload()

    def _on_price_failed(self, messaggio: str) -> None:
        self._save_rate_interval()
        self._fine_refresh()
        self.status.setText(tr("Aggiornamento non riuscito: {err}").format(
            err=messaggio))

    def _fine_refresh(self) -> None:
        self.progress.setVisible(False)
        self.stop_btn.setVisible(False)
        self.refresh_btn.setEnabled(True)

    def _stop_refresh(self) -> None:
        """Ferma, ma non butta via: quello che è già arrivato viene salvato.

        Il worker consegna comunque il parziale, quindi mezz'ora di
        aggiornamento non si perde perché si è chiuso in anticipo.
        """
        if self._price_worker is not None and self._price_worker.isRunning():
            self._price_worker.requestInterruption()
            self.status.setText(tr("Fermo l'aggiornamento…"))

    # ------------------------------- messaggi da altri moduli (ponte) ---
    def handle_request(self, payload) -> bool:
        """`{"card_name": "..."}` dal Database: apre l'aggiunta già cercata."""
        if not isinstance(payload, dict):
            return False
        nome = (payload.get("card_name") or "").strip()
        if not nome:
            return False
        self._mostra(0)
        QTimer.singleShot(0, lambda: self.add_card(nome))
        return True

    # --------------------------------------------------- ciclo di vita ---
    def busy_reason(self) -> str:
        """Convenzione a papera: il piede dell'aggiornamento la chiede prima di
        chiudere l'app, per non interrompere un lavoro lungo."""
        if self._price_worker is not None and self._price_worker.isRunning():
            return tr("l'aggiornamento dei prezzi della collezione")
        return ""

    def apply_scale(self, scale: float) -> None:
        self.table.setIconSize(QSize(int(ROW_ICON.width() * scale),
                                     int(ROW_ICON.height() * scale)))
        self._icona_vuota = None        # la cornice vuota cambia misura
        for r in range(self.table.rowCount()):
            self.table.setRowHeight(r, int(ROW_H * scale))
        # Il padding del QSS scala insieme al resto: la misura va rifatta,
        # altrimenti a scala 1.3 le pillole tornano tagliate.
        self._cell_pad = int(26 * scale)
        self._fit_columns()

    def stop(self) -> None:
        if self._price_worker is not None and self._price_worker.isRunning():
            self._price_worker.requestInterruption()
            self._price_worker.wait(4000)
        # Anche i download delle miniature: sono `QRunnable` in un pool, e
        # senza svuotarlo l'uscita dell'app resta appesa quanto dura la coda.
        self.thumbs.stop()
        self._save_rate_interval()
