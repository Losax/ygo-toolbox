"""Importazione di un `.ydk`: si scelgono le stampe, una carta alla volta.

Perché serve un dialogo e non un import diretto: **in un `.ydk` la rarità non
c'è**. Il file dice "tre Ash Blossom", non *quali* tre — e nel catalogo prezzi
Ash Blossom ha 36 stampe, da pochi centesimi a parecchi euro. Sceglierne una
al posto dell'utente sarebbe inventare un dato, che è la cosa che questo
progetto non fa (vale già per il ponte dal Database: si passa il nome, la
stampa la decide lui).

Quindi: una riga per carta, e sotto — a fisarmonica — tutte le sue stampe.
Niente è preselezionato; le carte lasciate senza stampa **non entrano nella
base**, e il riepilogo lo dice chiaro invece di farle sparire in silenzio.

Niente miniature, di proposito: sarebbero una quarantina di immagini
scaricate tutte insieme all'apertura, cioè esattamente la raffica verso il CDN
che il progetto vieta. Le pillole di rarità e i codici set si disegnano in
locale, senza rete.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from core import badges, rarity, theme
from core.i18n import tr

from .providers.base import CardRef

BADGE_H = 18            # altezza delle pillole, come nelle altre tabelle
_ROLE_KIND = Qt.ItemDataRole.UserRole          # "card" | "print"
_ROLE_INDEX = Qt.ItemDataRole.UserRole + 1     # indice della carta in _entries
_ROLE_PRINT = Qt.ItemDataRole.UserRole + 2     # indice della stampa


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


class YdkImportDialog(QDialog):
    """Griglia carta → stampe, con la fisarmonica.

    `entries`: lista di dizionari già risolti dal widget (il dialogo non tocca
    il database):
        passcode, name, name_it, copies, sections, printings[]
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

        self.setWindowTitle(tr("Importa mazzo (.ydk)"))
        self.setModal(True)
        self.setMinimumSize(860, 660)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        intro = QLabel(tr(
            "In un file .ydk non c'è la rarità: apri una carta e scegli quale "
            "stampa seguire. Le carte lasciate senza stampa non entrano nella base."))
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

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([tr("Carta / stampa"), tr("Scelta")])
        self.tree.setUniformRowHeights(True)     # ~800 righe: senza, misura tutto
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 260)
        # senza, l'albero scala le pillole a 16px e la sigla
        # della rarità non si legge più
        self.tree.setIconSize(QSize(80, BADGE_H))
        self.tree.itemClicked.connect(self._on_click)
        root.addWidget(self.tree, 1)

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
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Annulla"))

        self._build_tree()
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

    # ------------------------------------------------------------- albero
    def _build_tree(self) -> None:
        self.tree.clear()
        for i, voce in enumerate(self._entries):
            padre = QTreeWidgetItem(self.tree)
            padre.setData(0, _ROLE_KIND, "card")
            padre.setData(0, _ROLE_INDEX, i)
            padre.setText(0, self._card_label(voce))
            font = QFont(padre.font(0))
            font.setBold(True)
            padre.setFont(0, font)
            stampe = voce["printings"]
            if not stampe:
                # capita se il catalogo prezzi non ha quella carta: si dice,
                # non si finge che sia scegliibile
                padre.setText(1, tr("nessuna stampa nel catalogo"))
                padre.setDisabled(True)
                continue
            padre.setText(1, tr("— scegli una stampa"))
            # Nel catalogo capita che due stampe diverse abbiano rarità ed
            # espansione identiche: sono blueprint distinti, con immagini e
            # prezzi propri (152 gruppi su 47.951, misurato sul catalogo
            # vero). Fonderle nasconderebbe una scelta vera, quindi restano
            # entrambe e si distinguono col numero.
            doppie = {d for d in
                      [(s["detail"], s["set_code"]) for s in stampe]
                      if [(x["detail"], x["set_code"]) for x in stampe].count(d) > 1}
            for j, stampa in enumerate(stampe):
                figlio = QTreeWidgetItem(padre)
                figlio.setData(0, _ROLE_KIND, "print")
                figlio.setData(0, _ROLE_INDEX, i)
                figlio.setData(0, _ROLE_PRINT, j)
                etichetta = stampa["detail"] or tr("(senza dettaglio)")
                if (stampa["detail"], stampa["set_code"]) in doppie:
                    etichetta += f"  ·  #{stampa['ref_id']}"
                figlio.setText(0, etichetta)
                nome_rarita = _rarity_of(stampa["detail"])
                if rarity.is_rarity(nome_rarita):
                    figlio.setIcon(0, self._rarity_icon(nome_rarita))
                codice = (stampa["set_code"] or "").upper()
                if codice:
                    figlio.setText(1, codice)
        self._refresh_counter_labels()

    def _rarity_icon(self, nome: str):
        from PySide6.QtGui import QIcon
        return QIcon(rarity.rarity_pixmap(nome, BADGE_H))

    def _card_label(self, voce) -> str:
        etichetta = f"{voce['copies']}× {voce['name']}"
        if voce.get("sections"):
            # solo per le carte divise fra main e side: spiega il totale
            etichetta += f"  ({voce['sections']})"
        return etichetta

    # ------------------------------------------------------------- scelta
    def _on_click(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.data(0, _ROLE_KIND) != "print":
            return
        i = item.data(0, _ROLE_INDEX)
        j = item.data(0, _ROLE_PRINT)
        if self._chosen.get(i) == j:
            self._chosen.pop(i, None)      # ri-clic = ci ho ripensato
        else:
            self._chosen[i] = j
        self._refresh_counter_labels()
        self._refresh_summary()

    def _refresh_counter_labels(self) -> None:
        """Segno di spunta sulla stampa scelta, e riassunto sulla riga della
        carta: chiusa la fisarmonica si deve comunque vedere cosa si è scelto."""
        for k in range(self.tree.topLevelItemCount()):
            padre = self.tree.topLevelItem(k)
            i = padre.data(0, _ROLE_INDEX)
            voce = self._entries[i]
            if not voce["printings"]:
                continue
            scelta = self._chosen.get(i)
            padre.setText(1, voce["printings"][scelta]["detail"] if scelta is not None
                          else tr("— scegli una stampa"))
            for r in range(padre.childCount()):
                figlio = padre.child(r)
                j = figlio.data(0, _ROLE_PRINT)
                codice = (voce["printings"][j]["set_code"] or "").upper()
                figlio.setText(1, f"✓  {codice}" if j == scelta else codice)

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
