"""Mettere una carta in collezione: quale stampa, in che stato, quante copie.

La scelta della **stampa** è la parte che non si può saltare. "Ho Ash Blossom"
non dice quanto vale: nel catalogo ce ne sono 36 stampe, dalla Common da pochi
centesimi alla Secret da parecchi euro. Come per l'importazione di un `.ydk`,
niente è preselezionato — scegliere al posto dell'utente vorrebbe dire
inventare il valore della sua collezione.

Lo **stato** (condizione, lingua, prima edizione) si registra ma NON cambia il
prezzo mostrato: quello resta l'annuncio più basso per quella stampa. Dirlo è
più onesto che applicare uno sconto a occhio — una Played non vale "il 60%
della Near Mint" per decreto.

Il **prezzo pagato** può restare vuoto, e vuoto vuol dire *non lo so*: è per
questo che è un campo di testo e non uno spinbox, che uno zero lo scriverebbe
da solo. Zero invece è un'informazione vera (regalata, o dentro una busta).
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QVBoxLayout,
)

from core import rarity
from core.i18n import tr
from core.prices.cardtrader import CONDITIONS

# Anteprima piccola apposta: con una piu grande la colonna dei campi non
# stava nel dialogo e le tendine uscivano col testo tagliato a meta
# (visto in una schermata coi font veri).
PREVIEW = QSize(126, 184)
BADGE_H = 18

#: Lingue in cui escono le carte (lo stesso elenco dei filtri del Market Watch,
#: meno "Qualsiasi": qui si dichiara cosa si ha in mano, non cosa si cerca).
LANGUAGES = [
    ("Non indicata", ""), ("Italiano", "it"), ("Inglese", "en"),
    ("Tedesco", "de"), ("Francese", "fr"), ("Spagnolo", "es"),
    ("Portoghese", "pt"), ("Giapponese", "jp"), ("Coreano", "ko"),
    ("Cinese", "cn"),
]


def parse_amount(testo: str):
    """Testo → cifra, o None se non c'è nulla di leggibile.

    Accetta la virgola: in italiano si scrive `1,50`, e rifiutarlo sarebbe un
    dispetto. Un testo incomprensibile diventa None — "non lo so" — e mai zero.
    """
    pulito = (testo or "").strip().replace("€", "").replace(",", ".").strip()
    if not pulito:
        return None
    try:
        valore = float(pulito)
    except ValueError:
        return None
    return valore if valore >= 0 else None


def printing_label(riga) -> str:
    """`[SET] Rarità · Espansione`: il codice del set sta DAVANTI.

    È la stessa scelta della griglia del `.ydk`: chi cerca la propria stampa
    guarda prima il codice, e in fondo alla riga si perderebbe nell'elisione.
    """
    codice = (riga["set_code"] or "").upper()
    testo = riga["detail"] or tr("stampa senza dettagli")
    return f"[{codice}] {testo}" if codice else testo


class AddCardDialog(QDialog):
    """Cerca → scegli la stampa → dichiara lo stato. Non tocca il database.

    Riceve due funzioni dal widget (`cerca_nomi`, `stampe_di`) invece della
    connessione: così si può provare senza database, che è il motivo per cui i
    controlli automatici di questo modulo esistono.
    """

    def __init__(self, cerca_nomi, stampe_di, binders=(), thumbs=None,
                 iniziale=None, parent=None) -> None:
        super().__init__(parent)
        self._cerca_nomi = cerca_nomi
        self._stampe_di = stampe_di
        self._binders = list(binders)
        self._thumbs = thumbs
        self._stampe: list = []
        self._scelta: int | None = None
        #: modifica di una carta già in collezione: la stampa non si ricerca
        self._modifica = dict(iniziale) if iniziale else None
        self.setWindowTitle(tr("Modifica la carta") if self._modifica
                            else tr("Aggiungi alla collezione"))
        self.setMinimumSize(720, 620)
        self._build_ui()
        if self._modifica:
            self._carica_modifica()

    # ------------------------------------------------------------- forma ---
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        centro = QHBoxLayout()
        centro.setSpacing(14)

        sinistra = QVBoxLayout()
        sinistra.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("🔍  Nome della carta (in inglese)…"))
        self.search.setClearButtonEnabled(True)
        self.search.textEdited.connect(self._on_search_text)
        sinistra.addWidget(self.search)

        self.names = QListWidget()
        self.names.setObjectName("softList")
        self.names.setMaximumHeight(120)
        self.names.currentItemChanged.connect(self._on_name_chosen)
        sinistra.addWidget(self.names)

        self.prints_label = QLabel(tr("Stampe"))
        self.prints_label.setObjectName("subtitle")
        sinistra.addWidget(self.prints_label)
        self.prints = QListWidget()
        self.prints.setObjectName("softList")
        self.prints.setIconSize(QSize(46, BADGE_H))
        self.prints.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.prints.currentRowChanged.connect(self._on_print_chosen)
        sinistra.addWidget(self.prints, 1)
        centro.addLayout(sinistra, 3)

        destra = QVBoxLayout()
        destra.setSpacing(10)
        self.preview = QLabel()
        self.preview.setObjectName("preview")
        self.preview.setFixedSize(PREVIEW)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setWordWrap(True)
        self.preview.setText(tr("nessuna carta\nselezionata"))
        destra.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)

        modulo = QFormLayout()
        modulo.setSpacing(8)
        self.copies = QSpinBox()
        self.copies.setRange(1, 999)
        modulo.addRow(tr("Copie"), self.copies)

        self.condition = QComboBox()
        self.condition.addItem(tr("Non indicata"), "")
        for nome in CONDITIONS:
            self.condition.addItem(nome, nome)
        modulo.addRow(tr("Condizione"), self.condition)

        self.language = QComboBox()
        for etichetta, codice in LANGUAGES:
            self.language.addItem(tr(etichetta), codice)
        modulo.addRow(tr("Lingua"), self.language)

        self.first_edition = QCheckBox(tr("Prima edizione"))
        modulo.addRow("", self.first_edition)

        self.paid = QLineEdit()
        self.paid.setPlaceholderText(tr("vuoto = non lo so"))
        modulo.addRow(tr("Pagata"), self.paid)

        self.binder = QComboBox()
        self.binder.addItem(tr("Nessuno (carte sfuse)"), None)
        for b in self._binders:
            self.binder.addItem(b["name"], int(b["id"]))
        modulo.addRow(tr("Raccoglitore"), self.binder)

        self.note = QLineEdit()
        modulo.addRow(tr("Nota"), self.note)
        destra.addLayout(modulo)
        destra.addStretch(1)
        centro.addLayout(destra, 2)
        root.addLayout(centro, 1)

        self.hint = QLabel()
        self.hint.setObjectName("subtitle")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok.setText(tr("Salva") if self._modifica else tr("Aggiungi"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Annulla"))

        # Ricerca differita: la si aggiorna quando si smette di scrivere, non a
        # ogni tasto (stessa scelta della ricerca del Market Watch).
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._cerca)
        self._aggiorna_stato()

    def _carica_modifica(self) -> None:
        """Modifica: la stampa è già decisa, si cambia solo lo stato."""
        dati = self._modifica
        for w in (self.search, self.names, self.prints, self.prints_label):
            w.setVisible(False)
        self.copies.setValue(int(dati.get("quantity", 1) or 1))
        self._seleziona(self.condition, dati.get("condition", ""))
        self._seleziona(self.language, dati.get("language", ""))
        self.first_edition.setChecked(bool(dati.get("first_edition")))
        pagato = dati.get("paid")
        self.paid.setText("" if pagato is None else f"{float(pagato):.2f}")
        self._seleziona(self.binder, dati.get("binder_id"))
        self.note.setText(dati.get("note", "") or "")
        self._mostra_anteprima(dati.get("card_name", ""))
        self.hint.setText(f"{dati.get('card_name', '')} · "
                          f"{dati.get('detail', '') or tr('stampa senza dettagli')}")
        self._ok.setEnabled(True)

    @staticmethod
    def _seleziona(combo: QComboBox, valore) -> None:
        indice = combo.findData(valore)
        combo.setCurrentIndex(indice if indice >= 0 else 0)

    # ----------------------------------------------------------- ricerca ---
    def _on_search_text(self, _testo: str) -> None:
        self._timer.start()

    def _cerca(self) -> None:
        query = self.search.text().strip()
        self.names.clear()
        self.prints.clear()
        self._stampe = []
        self._scelta = None
        if len(query) < 2:
            self._aggiorna_stato()
            return
        nomi = self._cerca_nomi(query)
        for nome in nomi:
            QListWidgetItem(nome, self.names)
        if not nomi:
            self.hint.setText(tr("Nessuna carta con questo nome nel catalogo."))
        self._aggiorna_stato()

    def _on_name_chosen(self, corrente, _precedente) -> None:
        self.prints.clear()
        self._stampe = []
        self._scelta = None
        if corrente is None:
            self._aggiorna_stato()
            return
        nome = corrente.text()
        self._stampe = list(self._stampe_di(nome))
        for riga in self._stampe:
            item = QListWidgetItem(printing_label(riga))
            nome_rar = rarity.from_detail(riga["detail"] or "")
            if nome_rar:
                item.setIcon(self._icona_rarita(nome_rar))
            self.prints.addItem(item)
        self._mostra_anteprima(nome)
        if not self._stampe:
            self.hint.setText(tr("Questa carta non ha stampe nel catalogo dei prezzi."))
        self._aggiorna_stato()

    @staticmethod
    def _icona_rarita(nome_rar: str) -> QIcon:
        return QIcon(rarity.rarity_pixmap(nome_rar, BADGE_H))

    def _on_print_chosen(self, riga: int) -> None:
        self._scelta = riga if 0 <= riga < len(self._stampe) else None
        self._aggiorna_stato()

    def _mostra_anteprima(self, nome: str) -> None:
        if not nome:
            return
        if self._thumbs is None:
            self.preview.setText(nome)
            return
        self._thumbs.resolve([nome])
        self._thumbs.request(nome)      # una carta sola, quella a schermo
        pix = self._thumbs.pixmap(nome)
        if pix is not None and not pix.isNull():
            self.preview.setPixmap(pix.scaled(
                PREVIEW, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            self.preview.setText(nome)

    def _aggiorna_stato(self) -> None:
        pronto = self._modifica is not None or self._scelta is not None
        self._ok.setEnabled(pronto)
        if self._modifica is None and self._scelta is not None:
            riga = self._stampe[self._scelta]
            self.hint.setText(f"{riga['name']} · {riga['detail'] or ''}")
        elif self._modifica is None and self.prints.count():
            self.hint.setText(tr("Scegli la stampa: è quella che decide il prezzo."))

    # --------------------------------------------------------- risultato ---
    def result_card(self) -> dict | None:
        """I dati da salvare, o None se non c'è una stampa scelta."""
        comuni = {
            "quantity": self.copies.value(),
            "condition": self.condition.currentData() or "",
            "language": self.language.currentData() or "",
            "first_edition": self.first_edition.isChecked(),
            "paid": parse_amount(self.paid.text()),
            "note": self.note.text().strip(),
            "binder_id": self.binder.currentData(),
        }
        if self._modifica is not None:
            return {**self._modifica, **comuni}
        if self._scelta is None:
            return None
        riga = self._stampe[self._scelta]
        return {
            "ref_id": str(riga["ref_id"]),
            "card_name": riga["name"],
            "detail": riga["detail"] or "",
            "set_code": (riga["set_code"] or "").upper(),
            "image_url": riga["image_url"] or "",
            **comuni,
        }
