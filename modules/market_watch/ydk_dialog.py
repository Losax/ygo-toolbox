"""Importazione di un `.ydk`: il mazzo come griglia di carte, stampa a scelta.

Perché serve un dialogo e non un import diretto: **in un `.ydk` la rarità non
c'è**. Il file dice "tre Ash Blossom", non *quali* tre — e nel catalogo prezzi
Ash Blossom ha 36 stampe, da pochi centesimi a parecchi euro. Sceglierne una
al posto dell'utente sarebbe inventare un dato, che è la cosa che questo
progetto non fa (vale già per il ponte dal Database: si passa il nome, la
stampa la decide lui).

Come è fatto: a sinistra il **mazzo come lo si guarda**, una griglia di
immagini col numero di copie; a destra le stampe della carta selezionata.
Niente è preselezionato; le carte lasciate senza stampa **non entrano nella
base**, e il riepilogo lo dice invece di farle sparire in silenzio.

Le immagini vengono da `core.card_images`, cioè dalla stessa cache su DISCO
del Database: quelle già scaricate compaiono subito e non costano niente, le
altre arrivano **una alla volta e spaziate** (`_slot()`), e restano lì per
sempre. Un mazzo è al massimo una sessantina di carte — un insieme chiuso, non
le 14.000 del database — quindi si chiedono tutte, non solo quelle a schermo.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QThreadPool
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import card_images, rarity, theme
from core.i18n import tr

from .providers.base import CardRef
from .search_model import _make_empty_frame

BADGE_H = 18                     # pillole di rarità, come nelle altre tabelle
CARD = QSize(100, 146)           # proporzioni di carta
CELL = QSize(118, 214)           # cella: immagine + due righe di testo
_ROLE_INDEX = Qt.ItemDataRole.UserRole      # indice della carta in _entries
_ROLE_PRINT = Qt.ItemDataRole.UserRole + 1  # indice della stampa


def _rarity_of(detail: str) -> str:
    """Rarità da "Secret Rare · Maximum Crisis".

    Il campo `detail` del catalogo è "rarità · espansione"; a volte la parte
    sinistra porta altra roba ("Ultra Rare | ©1996"), quindi si taglia anche
    sul `|`.
    """
    testa = (detail or "").split("·")[0]
    return testa.split("|")[0].strip()


def sort_printings(rows) -> list:
    """Stampe dalla più comune alla più ricercata, poi per espansione.

    Non è una preselezione — nessuna stampa è scelta — ma un ordine utile:
    chi importa un mazzo per giocarci parte quasi sempre dalle comuni. Le
    rarità che non riconosciamo (`rank` -1) vanno in fondo, tutte insieme,
    invece di sparpagliarsi.
    """
    def chiave(r):
        rank = rarity.rarity_rank(_rarity_of(r["detail"]))
        return (rank < 0, rank, (r["set_code"] or ""), r["detail"] or "")
    return sorted(rows, key=chiave)


def duplicate_labels(stampe) -> set:
    """Coppie (dettaglio, set) che compaiono più di una volta.

    Nel catalogo capita che due stampe abbiano rarità ed espansione identiche:
    sono blueprint distinti, con immagini e prezzi propri (**152 gruppi su
    47.951**, misurato sul catalogo vero). Fonderle nasconderebbe una scelta
    vera, quindi restano entrambe e si distinguono col numero.
    """
    coppie = [(s["detail"], s["set_code"]) for s in stampe]
    return {c for c in coppie if coppie.count(c) > 1}


class YdkImportDialog(QDialog):
    """Griglia del mazzo a sinistra, stampe della carta scelta a destra.

    `entries`: lista di dizionari già risolti dal widget (il dialogo non tocca
    il database):
        passcode, name, name_it, thumb_url, copies, sections, printings[]
    `unknown`: passcode che il catalogo carte non conosce (mostrati, non
    ingoiati). `ignored`: righe del file non capite.
    """

    def __init__(self, entries, unknown=(), ignored=(), default_name: str = "",
                 filters_json: str = "", filters_editor=None, parent=None) -> None:
        super().__init__(parent)
        self._entries = list(entries)
        self._unknown = list(unknown)
        self._ignored = list(ignored)
        self._filters_json = filters_json
        self._filters_editor = filters_editor
        #: indice della stampa scelta per ogni carta (manca = non scelta)
        self._chosen: dict[int, int] = {}
        self._current = -1

        self.setWindowTitle(tr("Importa mazzo (.ydk)"))
        self.setModal(True)
        self.setMinimumSize(1020, 720)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        intro = QLabel(tr(
            "In un file .ydk non c'è la rarità: scegli una carta dal mazzo e poi "
            "quale stampa seguire. Le carte lasciate senza stampa non entrano nella base."))
        intro.setObjectName("subtitle")
        intro.setWordWrap(True)
        root.addWidget(intro)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.name_input = QLineEdit(default_name)
        self.name_input.setPlaceholderText(tr("Nome della base"))
        self.name_input.textChanged.connect(lambda _t: self._refresh_summary())
        self.filters_btn = QPushButton()
        self.filters_btn.setToolTip(tr("Filtri validi per tutte le carte della base"))
        self.filters_btn.clicked.connect(self._edit_filters)
        top.addWidget(self.name_input, 1)
        top.addWidget(self.filters_btn)
        root.addLayout(top)

        centro = QHBoxLayout()
        centro.setSpacing(14)

        # --- sinistra: il mazzo, come lo si guarda ---
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(CARD)
        self.grid.setGridSize(CELL)
        self.grid.setMovement(QListWidget.Movement.Static)   # non si trascina
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setWordWrap(True)
        self.grid.setSpacing(6)
        self.grid.setUniformItemSizes(True)
        self.grid.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid.currentRowChanged.connect(self._select_card)
        centro.addWidget(self.grid, 5)

        # --- destra: le stampe della carta selezionata ---
        lato = QWidget()
        lato_lay = QVBoxLayout(lato)
        lato_lay.setContentsMargins(0, 0, 0, 0)
        lato_lay.setSpacing(8)
        self.side_title = QLabel(tr("Scegli una carta dal mazzo"))
        titolo_font = QFont(self.side_title.font())
        titolo_font.setBold(True)
        self.side_title.setFont(titolo_font)
        self.side_title.setWordWrap(True)
        lato_lay.addWidget(self.side_title)
        self.side_hint = QLabel()
        self.side_hint.setObjectName("subtitle")
        self.side_hint.setWordWrap(True)
        lato_lay.addWidget(self.side_hint)
        self.prints = QListWidget()
        # senza `setIconSize` l'elenco scala le pillole a 16px e la sigla
        # della rarità non si legge più
        self.prints.setIconSize(QSize(80, BADGE_H))
        self.prints.setAlternatingRowColors(True)
        # Le espansioni hanno nomi lunghissimi ("Legendary Collection Kaiba
        # Mega Pack"): senza accorciamento comparivano tagliate di netto con
        # una barra di scorrimento orizzontale. Si accorciano con i puntini —
        # e per questo il CODICE del set sta davanti, dove non lo si perde.
        self.prints.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.prints.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.prints.itemClicked.connect(self._on_print_clicked)
        lato_lay.addWidget(self.prints, 1)
        centro.addWidget(lato, 2)
        root.addLayout(centro, 1)

        self.summary = QLabel()
        self.summary.setObjectName("subtitle")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setText(tr("Crea la base"))
        # i pulsanti standard li traduce Qt, non noi: in italiano resta "Cancel"
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Annulla"))

        # --- immagini: prima la cache su disco, poi la rete una alla volta ---
        self._pix: dict[int, QPixmap] = {}
        self._asked: set[int] = set()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(4)
        self._img_signals = card_images.ImageSignals()
        self._img_signals.done.connect(self._on_image)

        self._build_grid()
        self._refresh_filters_btn()
        self._refresh_summary()

    # ------------------------------------------------------------- filtri
    def _refresh_filters_btn(self) -> None:
        custom = bool(self._filters_json)
        self.filters_btn.setText(tr("Filtri: propri") if custom else tr("Filtri: predefiniti"))
        self.filters_btn.setStyleSheet(f"color: {theme.ACCENT};" if custom else "")

    def _edit_filters(self) -> None:
        if self._filters_editor is None:
            return
        risultato = self._filters_editor(self._filters_json)
        if risultato is None:
            return
        self._filters_json = risultato
        self._refresh_filters_btn()

    # -------------------------------------------------------------- mazzo
    def _build_grid(self) -> None:
        vuota = QIcon(_make_empty_frame(CARD))
        for i, _voce in enumerate(self._entries):
            item = QListWidgetItem(self.grid)
            item.setData(_ROLE_INDEX, i)
            item.setIcon(vuota)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter
                                  | Qt.AlignmentFlag.AlignTop)
            item.setSizeHint(CELL)
            self._refresh_card_item(i)
            self._request_image(i)

    def _refresh_card_item(self, i: int) -> None:
        """Testo e colore della cella: copie, nome e — se scelta — la spunta."""
        item = self.grid.item(i)
        if item is None:
            return
        voce = self._entries[i]
        scelta = self._chosen.get(i)
        item.setText(("✓ " if scelta is not None else "")
                     + f"{voce['copies']}× {voce['name']}")
        # il teal è il "fatto" di tutta l'app: qui dice quali carte sono a posto
        item.setForeground(QColor(theme.ACCENT) if scelta is not None
                           else QColor(theme.TEXT))
        suggerimento = [voce["name"]]
        if voce.get("sections"):
            suggerimento.append(voce["sections"])
        if scelta is not None:
            suggerimento.append(voce["printings"][scelta]["detail"])
        elif not voce["printings"]:
            suggerimento.append(tr("nessuna stampa nel catalogo"))
        item.setToolTip("\n".join(suggerimento))

    # ----------------------------------------------------------- immagini
    def _request_image(self, i: int) -> None:
        voce = self._entries[i]
        codice, url = int(voce["passcode"]), voce.get("thumb_url") or ""
        pronta = card_images.cached(codice, small=True)
        if pronta is not None:
            pix = QPixmap(str(pronta))
            if not pix.isNull():
                self._pix[codice] = pix
                self._paint_image(codice)
                return
        if not url or codice in self._asked or card_images.failed(url):
            return
        self._asked.add(codice)
        self._pool.start(card_images.ImageTask(codice, url, True, self._img_signals))

    def _on_image(self, card_id: int, _small: bool, percorso: str) -> None:
        if not percorso:
            return          # persa: resta la cornice vuota, non si ritenta
        pix = QPixmap(percorso)
        if pix.isNull():
            return
        self._pix[int(card_id)] = pix
        self._paint_image(int(card_id))

    def _paint_image(self, card_id: int) -> None:
        pix = self._pix.get(card_id)
        if pix is None:
            return
        icona = QIcon(pix.scaled(CARD, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation))
        for i, voce in enumerate(self._entries):
            if int(voce["passcode"]) == card_id:
                item = self.grid.item(i)
                if item is not None:
                    item.setIcon(icona)

    # ------------------------------------------------------------- stampe
    def _select_card(self, i: int) -> None:
        self._current = i
        self.prints.clear()
        if not (0 <= i < len(self._entries)):
            self.side_title.setText(tr("Scegli una carta dal mazzo"))
            self.side_hint.setText("")
            return
        voce = self._entries[i]
        self.side_title.setText(f"{voce['copies']}× {voce['name']}")
        pezzi = []
        if voce.get("sections"):
            pezzi.append(voce["sections"])
        if voce.get("name_it"):
            pezzi.append(voce["name_it"])
        self.side_hint.setText(" · ".join(pezzi))
        stampe = voce["printings"]
        if not stampe:
            # capita se il catalogo prezzi non ha quella carta: si dice, non si
            # finge che sia scegliibile
            avviso = QListWidgetItem(tr("nessuna stampa nel catalogo"))
            avviso.setFlags(Qt.ItemFlag.NoItemFlags)
            self.prints.addItem(avviso)
            return
        doppie = duplicate_labels(stampe)
        scelta = self._chosen.get(i)
        for j, stampa in enumerate(stampe):
            etichetta = stampa["detail"] or tr("(senza dettaglio)")
            codice = (stampa["set_code"] or "").upper()
            # Il numero che distingue due stampe identiche va DENTRO la
            # parentesi, davanti: in coda i puntini di accorciamento se lo
            # mangiavano, cioè proprio nel caso in cui serve.
            if (stampa["detail"], stampa["set_code"]) in doppie:
                codice = f"{codice} #{stampa['ref_id']}" if codice                     else f"#{stampa['ref_id']}"
            if codice:
                etichetta = f"[{codice}]  {etichetta}"
            item = QListWidgetItem(("✓  " + etichetta) if j == scelta else etichetta)
            item.setData(_ROLE_PRINT, j)
            item.setToolTip(etichetta)      # per intero: la riga è accorciata
            nome_rarita = _rarity_of(stampa["detail"])
            if rarity.is_rarity(nome_rarita):
                item.setIcon(QIcon(rarity.rarity_pixmap(nome_rarita, BADGE_H)))
            self.prints.addItem(item)
        if scelta is not None:
            self.prints.setCurrentRow(scelta)

    def _on_print_clicked(self, item: QListWidgetItem) -> None:
        j = item.data(_ROLE_PRINT)
        if j is None or not (0 <= self._current < len(self._entries)):
            return
        self._choose(self._current, j)

    def _choose(self, i: int, j: int) -> None:
        if self._chosen.get(i) == j:
            self._chosen.pop(i, None)      # ri-clic = ci ho ripensato
        else:
            self._chosen[i] = j
        self._refresh_card_item(i)
        self._select_card(i)               # ridisegna la spunta nell'elenco
        self._refresh_summary()

    # ------------------------------------------------------------ riepilogo
    def _refresh_summary(self) -> None:
        scegliibili = [v for v in self._entries if v["printings"]]
        scelte = len(self._chosen)
        copie = sum(self._entries[i]["copies"] for i in self._chosen)
        if scelte == 0:
            # all'apertura non è un problema da segnalare, è cosa fare adesso
            pezzi = [tr("Nessuna stampa scelta: apri una carta e scegline una "
                        "fra le {t} in elenco.").format(t=len(scegliibili))]
        else:
            pezzi = [(tr("{s} carta su {t} con una stampa scelta · {c} copie")
                      if scelte == 1 else
                      tr("{s} carte su {t} con una stampa scelta · {c} copie")).format(
                s=scelte, t=len(scegliibili), c=copie)]
        mancanti = len(scegliibili) - scelte
        if mancanti and scelte:
            pezzi.append((tr("1 carta senza stampa: non entrerà nella base")
                          if mancanti == 1 else
                          tr("{n} carte senza stampa: non entreranno nella base")
                          ).format(n=mancanti))
        senza_catalogo = len(self._entries) - len(scegliibili)
        if senza_catalogo:
            pezzi.append((tr("1 carta senza stampe nel catalogo")
                          if senza_catalogo == 1 else
                          tr("{n} carte senza stampe nel catalogo")
                          ).format(n=senza_catalogo))
        if self._unknown:
            codici = ", ".join(str(c) for c in self._unknown[:6]) + (
                "…" if len(self._unknown) > 6 else "")
            pezzi.append((tr("1 passcode non riconosciuto: {codici}")
                          if len(self._unknown) == 1 else
                          tr("{n} passcode non riconosciuti: {codici}")
                          ).format(n=len(self._unknown), codici=codici))
        if self._ignored:
            pezzi.append((tr("1 riga del file non capita")
                          if len(self._ignored) == 1 else
                          tr("{n} righe del file non capite")
                          ).format(n=len(self._ignored)))
        self.summary.setText(" · ".join(pezzi))
        self._ok_btn.setEnabled(bool(self.name_input.text().strip()) and scelte > 0)

    # ------------------------------------------------------------ risultati
    def result_name(self) -> str:
        return self.name_input.text().strip()

    def result_filters_json(self) -> str:
        return self._filters_json

    def result_cards(self) -> list[tuple]:
        """Solo le carte con una stampa scelta: le altre restano fuori."""
        fuori = []
        for i, j in sorted(self._chosen.items()):
            voce = self._entries[i]
            stampa = voce["printings"][j]
            fuori.append((CardRef(id=str(stampa["ref_id"]),
                                  name=stampa["name"],
                                  detail=stampa["detail"] or "",
                                  image_url=stampa["image_url"] or ""),
                          voce["copies"]))
        return fuori
