"""Dialogo "base": un mazzo di carte, in più copie, con filtri comuni.

Perché non è una `CardDialog` come gli altri: quelle sono `Qt.Popup` e si
chiudono al primo clic fuori. Va benissimo per due interruttori, è pessimo per
un modulo di inserimento dove si compone un mazzo di venti carte — un clic
distratto butterebbe via tutto. Qui serve una finestra normale, modale, che si
chiude solo con OK o Annulla.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QStringListModel, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import theme
from core.i18n import tr

from .search_model import ThumbDelegate

MAX_RESULTS = 60      # come la ricerca principale
MAX_COPIES = 99

# Padding ridotto rispetto al tema: nella cella lo spinbox è basso, e con gli
# 8px sopra/sotto del QSS al numero non resta abbastanza spazio per essere
# disegnato intero. Centrato, perché è una quantità e si legge meglio.
_SPIN_QSS = "QSpinBox { padding: 2px 6px; padding-right: 30px; }"


class DeckDialog(QDialog):
    """Compone/modifica una base.

    `search(testo) -> [(etichetta, CardRef)]` la passa il widget: la ricerca
    "a token" sull'indice del catalogo è già sua, non ha senso rifarla qui.
    """

    ROW_H = 52     # altezza riga: sotto, il numero delle copie viene tagliato

    def __init__(self, search, name: str = "", filters_json: str = "",
                 cards=None, filters_editor=None, thumb_items=None,
                 resolve=None, parent=None) -> None:
        super().__init__(parent)
        self._search = search
        self._resolve = resolve
        self._filters_json = filters_json
        self._filters_editor = filters_editor   # callable(json) -> json | None
        self.setWindowTitle(tr("Base (mazzo)"))
        self.setModal(True)
        self.setMinimumSize(780, 620)   # comporre un mazzo vuole spazio

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        intro = QLabel(tr("Una base è un gruppo di carte in più copie con filtri in comune: "
                          "imposta i filtri una volta, poi aggiungi le carte e le copie."))
        intro.setObjectName("subtitle")
        intro.setWordWrap(True)
        root.addWidget(intro)

        # --- nome + filtri della base ---
        top = QHBoxLayout()
        top.setSpacing(8)
        self.name_input = QLineEdit(name)
        self.name_input.setPlaceholderText(tr("Nome della base (es. Snake-Eye)"))
        self.name_input.textChanged.connect(lambda _t: self._refresh_summary())
        self.filters_btn = QPushButton()
        self.filters_btn.setToolTip(tr("Filtri validi per tutte le carte della base"))
        self.filters_btn.clicked.connect(self._edit_filters)
        top.addWidget(self.name_input, 1)
        top.addWidget(self.filters_btn)
        root.addLayout(top)

        # --- ricerca carte: LA STESSA della barra principale ---
        # Stesso `ThumbDelegate`, quindi stesse miniature, stesso hover animato
        # e stessa pill del codice set. Non si riscrive niente: cambia solo il
        # campo che la pilota.
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr("Cerca una carta da aggiungere…"))
        self.search_input.textEdited.connect(self._on_search)
        root.addWidget(self.search_input)

        self._model = QStringListModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._completer.setMaxVisibleItems(6)
        popup = self._completer.popup()
        popup.setObjectName("searchPopup")
        popup.setUniformItemSizes(True)     # senza, il view misura OGNI riga
        popup.setMouseTracking(True)
        popup.viewport().setMouseTracking(True)
        font = QFont(popup.font())
        font.setPointSizeF(font.pointSizeF() + 3)
        popup.setFont(font)
        self._thumbs = ThumbDelegate(self)
        self._thumbs.set_view(popup)
        popup.setItemDelegate(self._thumbs)
        if thumb_items:
            self._thumbs.set_cards(thumb_items)
        self._completer.activated[str].connect(self._on_pick)
        self.search_input.setCompleter(self._completer)
        # debounce come nella barra principale: il filtro parte dopo la pausa
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._apply_search)
        self._pending = ""

        # --- carte della base ---
        # Copie e "togli" stanno nella STESSA cella: con una colonna a parte
        # per il pulsante, la barra di scorrimento verticale la spingeva fuori
        # dal bordo e spariva.
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([tr("Carta"), tr("Copie")])
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(1, 170)
        # Righe alte: il tema dà ai campi 8px di padding sopra e sotto, e in
        # una riga bassa al numero restavano ~8px — si vedeva mezzo "3", che
        # sembrava un carattere minuscolo. L'altezza si impone RIGA PER RIGA:
        # `setDefaultSectionSize` non ridimensiona le righe già create.
        self.table.verticalHeader().setDefaultSectionSize(self.ROW_H)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        root.addWidget(self.table, 1)

        self.summary = QLabel()
        self.summary.setObjectName("subtitle")
        root.addWidget(self.summary)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)

        self._cards: list[list] = []   # [ref, copie]
        for ref, copies in (cards or []):
            self._cards.append([ref, copies])
        self._rebuild_table()
        self._refresh_filters_btn()
        QTimer.singleShot(0, self.name_input.setFocus)

    # ------------------------------------------------------------- filtri
    def _refresh_filters_btn(self) -> None:
        custom = bool(self._filters_json)
        self.filters_btn.setText(tr("Filtri: propri") if custom else tr("Filtri: predefiniti"))
        self.filters_btn.setStyleSheet(
            f"color: {theme.ACCENT};" if custom else "")

    def _edit_filters(self) -> None:
        if self._filters_editor is None:
            return
        result = self._filters_editor(self._filters_json)
        if result is None:      # annullato
            return
        self._filters_json = result
        self._refresh_filters_btn()

    # ------------------------------------------------------------ ricerca
    def _on_search(self, text: str) -> None:
        self._pending = text
        self._timer.start()

    def _apply_search(self) -> None:
        text = self._pending.strip()
        if not text:
            self._model.setStringList([])
            return
        self._model.setStringList([label for label, _ref in self._search(text)[:MAX_RESULTS]])
        self._completer.complete()

    def _on_pick(self, label: str) -> None:
        ref = self._resolve(label) if self._resolve else None
        if ref is not None:
            self._add(ref)

    def _add(self, ref) -> None:
        """Carta già presente = una copia in più: è quello che ci si aspetta
        cercandola di nuovo, invece di una riga doppia."""
        for entry in self._cards:
            if entry[0].id == ref.id:
                entry[1] = min(MAX_COPIES, entry[1] + 1)
                self._rebuild_table()
                break
        else:
            self._cards.append([ref, 1])
            self._rebuild_table()
        self.search_input.clear()
        self._model.setStringList([])
        self.search_input.setFocus()
        self.table.scrollToBottom()

    # ------------------------------------------------------------- tabella
    def _rebuild_table(self) -> None:
        self.table.setRowCount(len(self._cards))
        for row, (ref, copies) in enumerate(self._cards):
            label = ref.name if not ref.detail else f"{ref.name} · {ref.detail}"
            name_item = QTableWidgetItem(label)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, name_item)
            spin = QSpinBox()
            spin.setRange(1, MAX_COPIES)
            spin.setValue(copies)
            spin.setMinimumSize(96, 34)
            spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spin.setStyleSheet(_SPIN_QSS)
            spin.setToolTip(tr("Quante copie di questa carta"))
            spin.valueChanged.connect(lambda v, r=row: self._set_copies(r, v))
            drop = QPushButton("✕")
            drop.setObjectName("ghost")
            drop.setFixedSize(30, 30)
            drop.setToolTip(tr("Togli dalla base"))
            drop.setCursor(Qt.CursorShape.PointingHandCursor)
            drop.clicked.connect(lambda _=False, r=row: self._remove(r))
            box = QWidget()
            box.setStyleSheet("background: transparent;")
            lay = QHBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(4)
            lay.addWidget(spin, 1)
            lay.addWidget(drop)
            self.table.setCellWidget(row, 1, box)
            self.table.setRowHeight(row, self.ROW_H)
        self._refresh_summary()

    def _set_copies(self, row: int, value: int) -> None:
        if 0 <= row < len(self._cards):
            self._cards[row][1] = value
            self._refresh_summary()

    def _remove(self, row: int) -> None:
        if 0 <= row < len(self._cards):
            del self._cards[row]
            self._rebuild_table()

    def _refresh_summary(self) -> None:
        n = len(self._cards)
        copies = sum(c for _ref, c in self._cards)
        self.summary.setText(tr("{n} carte · {c} copie in totale").format(n=n, c=copies))
        self._ok_btn.setEnabled(bool(self.name_input.text().strip()) and n > 0)

    # ------------------------------------------------------------ risultati
    def result_name(self) -> str:
        return self.name_input.text().strip()

    def result_filters_json(self) -> str:
        return self._filters_json

    def result_cards(self) -> list[tuple]:
        return [(ref, copies) for ref, copies in self._cards]
