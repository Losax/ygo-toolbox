"""La pagina di un raccoglitore: un foglio con gli anelli e le sue tasche.

Perché un widget dipinto e non una griglia di elementi Qt. Un raccoglitore
vero ha **tasche vuote**, e sono importanti quanto quelle piene: chi colleziona
lascia il posto alla carta che gli manca. Una lista a icone (`QListWidget` in
IconMode, quella dell'importazione `.ydk`) sa solo mettere gli elementi uno
dopo l'altro: i buchi in mezzo non esistono, e ogni carta tolta fa scalare
tutte le altre — cioè esattamente quello che un raccoglitore non fa.

Qui invece la tasca è una **posizione** (`slot`, un numero assoluto dentro il
raccoglitore): la pagina è `slot // (colonne × righe)`, e una tasca vuota è
semplicemente uno slot senza carta. Cambiare formato alla pagina ridistribuisce
le carte senza spostarne nessuna, come travasando un raccoglitore vero.

## Perché sembra un raccoglitore e non una tabella

Dipingere da soli costa qualche riga in più e in cambio dà le cose che fanno
riconoscere l'oggetto in mezzo secondo, prima di leggere qualunque scritta:

- il **foglio** è una superficie a sé, con gli **anelli** lungo il bordo
  sinistro, uno per fila di tasche;
- la tasca è **incassata** (fondo più scuro del foglio, filo di luce in alto):
  si legge come un alloggiamento, non come un riquadro disegnato sopra;
- la carta ci sta **dentro**, con la sua ombra e gli angoli tondi, e sopra
  passa il **riflesso** della bustina di plastica — è quel riflesso, più di
  ogni altra cosa, a dire "questa carta è in una tasca";
- in fondo alla carta una **striscia foil** col colore della rarità (lo stesso
  vocabolario delle pillole, `core/rarity.py`): sfogliando si vede al volo
  dove stanno le carte buone, senza leggere una sigla;
- il prezzo sta su una **velatura** in fondo alla carta invece che in una
  riga sotto: la carta resta grande, che è il motivo per cui si apre questa
  vista.

Il resto è comportamento, non decorazione: passando sopra una tasca la carta
si **solleva**, cambiando pagina le tasche **scorrono** nel verso in cui si
sfoglia (e se le animazioni sono spente, no — `core/anim.py` comanda).

Si trascina: dentro la pagina per riordinare (chi arriva **scambia** con chi
c'era, vedi `repository.place`) e dall'elenco delle carte sfuse per metterle
dentro.
"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QMimeData,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDrag,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QListWidget, QWidget

from core import anim, rarity, theme
from core.i18n import tr

from .format import soldi

#: Formato di trascinamento nostro: il testo è l'id della riga di `col_items`.
#: Uno proprio e non `text/plain` perché così la pagina accetta solo ciò che
#: viene davvero dalla collezione, e non qualunque testo trascinato da fuori.
MIME = "application/x-ygo-collection-item"

CARD_RATIO = 59 / 86        # proporzioni di una carta Yu-Gi-Oh!
GAP = 12                    # aria fra una tasca e l'altra
SPINE = 34                  # striscia degli anelli, sul bordo sinistro
MARGINE = 16                # aria fra il bordo del foglio e le tasche
PAD = 7                     # quanto la carta sta dentro la tasca
R_TASCA = 9                 # raggio degli angoli della tasca
R_CARTA = 5                 # raggio degli angoli della carta

#: Di quanto si solleva la carta passandoci sopra (frazione del lato).
SOLLEVA = 0.035


def _colore(base: str, alpha: int) -> QColor:
    c = QColor(base)
    c.setAlpha(alpha)
    return c


def _ombra(painter: QPainter, rect: QRectF, raggio: float,
           passi: int = 5, forza: int = 46) -> None:
    """Ombra morbida senza `QGraphicsEffect`.

    Un effetto Qt vuole un widget suo; qui si dipinge dentro un `paintEvent`
    solo, quindi la sfocatura si approssima con qualche rettangolo sempre più
    largo e sempre più trasparente. Costa nulla per nove tasche e a schermo è
    indistinguibile da una vera sfocatura piccola.
    """
    painter.setPen(Qt.PenStyle.NoPen)
    for i in range(passi, 0, -1):
        alpha = max(1, int(forza / (i * 1.6)))
        painter.setBrush(_colore(theme.SHADOW, alpha))
        painter.drawRoundedRect(
            rect.adjusted(-i * 0.8, -i * 0.3 + 1.6, i * 0.8, i * 1.1 + 1.6),
            raggio + i * 0.6, raggio + i * 0.6)


def _percorso(rect: QRectF, raggio: float) -> QPainterPath:
    percorso = QPainterPath()
    percorso.addRoundedRect(rect, raggio, raggio)
    return percorso


#: Colori delle coste, per dare a ogni raccoglitore una faccia riconoscibile.
#: Scelti dentro il tema (nessuno grida più dell'accento) e assegnati per
#: NOME: lo stesso raccoglitore ha sempre lo stesso colore, anche riordinando
#: l'elenco o riaprendo l'app. È decorazione, non un dato — per questo si può
#: derivare, mentre un prezzo no.
_COSTE = ["#1ac3b2", "#7fb2f9", "#cfaef0", "#f5cf57", "#fb7185", "#34d399",
          "#f6a75c", "#8ce6d8"]

_icone: dict[tuple[str, int], QIcon] = {}


def binder_icon(nome: str, lato: int = 34) -> QIcon:
    """Un raccoglitore chiuso, visto di tre quarti: costa colorata e anelli.

    Disegnato a runtime come le bandierine e le rarità: niente file, niente
    rete, e si riscala con l'interfaccia. In cache per (nome, lato) — la stessa
    icona ricompare a ogni ricostruzione dell'elenco.
    """
    chiave = (nome, lato)
    pronta = _icone.get(chiave)
    if pronta is not None:
        return pronta
    colore = QColor(_COSTE[sum(nome.encode("utf-8")) % len(_COSTE)])
    ombra = colore.darker(190)
    pixmap = QPixmap(lato, lato)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    u = lato / 34.0
    corpo = QRectF(9 * u, 4 * u, 21 * u, 26 * u)
    costa = QRectF(4 * u, 4 * u, 6 * u, 26 * u)

    _ombra(painter, corpo, 3 * u, passi=3, forza=70)
    copertina = QLinearGradient(corpo.topLeft(), corpo.bottomRight())
    copertina.setColorAt(0.0, colore.lighter(106))
    copertina.setColorAt(1.0, colore.darker(140))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(copertina)
    painter.drawRoundedRect(corpo, 3 * u, 3 * u)
    painter.setBrush(ombra)
    painter.drawRoundedRect(costa, 2 * u, 2 * u)
    # le carte che spuntano dal taglio
    painter.setBrush(_colore("#eef1f6", 160))
    painter.drawRect(QRectF(corpo.right() - 2.4 * u, corpo.y() + 3 * u,
                            2.0 * u, corpo.height() - 6 * u))
    # i tre anelli sulla costa
    painter.setPen(QPen(_colore("#ffffff", 170), max(1.0, 1.4 * u)))
    for k in range(3):
        cy = costa.y() + costa.height() * (0.22 + 0.28 * k)
        painter.drawEllipse(QRectF(costa.center().x() - 2.2 * u, cy - 2.2 * u,
                                   4.4 * u, 4.4 * u))
    painter.end()
    # Lo STESSO pixmap per Normal, Selected e Active: di suo Qt ridisegna
    # l'icona della voce selezionata stendendoci sopra una velatura del colore
    # di evidenziazione, e su una copertina colorata si vede come uno
    # sbiadimento (è la stessa cura di `ydk_dialog._icon_for`).
    icona = QIcon()
    for modo in (QIcon.Mode.Normal, QIcon.Mode.Selected, QIcon.Mode.Active,
                 QIcon.Mode.Disabled):
        icona.addPixmap(pixmap, modo, QIcon.State.Off)
    _icone[chiave] = icona
    return icona


class CardTray(QListWidget):
    """Elenco trascinabile: le carte da mettere nel raccoglitore.

    `QListWidget` sa già trascinare, ma con un formato interno di Qt che parla
    di righe e modelli. Qui si riscrive `mimeData` per consegnare l'id della
    carta: è l'unico dato che serve dall'altra parte, e rende il trascinamento
    indipendente da quale riga stia dove.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)

    def mimeData(self, items):  # noqa: N802 (firma Qt)
        dati = QMimeData()
        if items:
            item_id = items[0].data(Qt.ItemDataRole.UserRole)
            if item_id is not None:
                dati.setData(MIME, str(int(item_id)).encode("ascii"))
        return dati


class BinderPage(QWidget):
    """Una pagina di tasche. Non tocca il database: chiede e riceve."""

    #: (item_id, slot di destinazione) — una carta è stata lasciata in una tasca
    dropped = Signal(int, int)
    #: slot cliccato (anche vuoto: serve per "metti una carta qui")
    slot_clicked = Signal(int)
    slot_activated = Signal(int)          # doppio clic
    slot_menu = Signal(int, QPoint)       # clic destro (posizione globale)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self._cols = 3
        self._rows = 3
        self._page = 0
        self._items: dict[int, object] = {}    # slot assoluto -> riga di col_items
        self._thumbs = None
        self._selected = -1
        self._hover = -1
        self._drag_from = QPoint()
        self._drag_slot = -1
        #: scorrimento della pagina mentre si sfoglia: 1 = appena entrata da
        #: destra, -1 = da sinistra, 0 = ferma
        self._shift = 0.0
        self._anim = None
        self.setMinimumSize(QSize(320, 300))

    # ------------------------------------------------------------- dati ---
    def set_thumbs(self, thumbs) -> None:
        self._thumbs = thumbs

    def set_layout_size(self, cols: int, rows: int) -> None:
        self._cols, self._rows = max(1, int(cols)), max(1, int(rows))
        self.update()

    def set_page(self, page: int) -> None:
        nuova = max(0, int(page))
        verso = 0 if nuova == self._page else (1 if nuova > self._page else -1)
        self._page = nuova
        if verso:
            self._sfoglia(verso)
        self.update()

    def _sfoglia(self, verso: int) -> None:
        """Le tasche entrano scorrendo dal lato da cui si sta sfogliando.

        È l'unica animazione della pagina e serve a una cosa sola: far capire
        che si è **girato un foglio**, non che il contenuto è cambiato da sé.
        Con le animazioni spente (Opzioni) non parte nemmeno.
        """
        if not anim.is_enabled():
            self._shift = 0.0
            return
        if self._anim is not None:
            self._anim.stop()
        self._shift = float(verso)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(float(verso))
        self._anim.setEndValue(0.0)
        self._anim.setDuration(190)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_shift)
        self._anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _on_shift(self, valore) -> None:
        self._shift = float(valore)
        self.update()

    def set_items(self, items: dict) -> None:
        """items: slot assoluto → riga di `col_items` (con prezzo agganciato)."""
        self._items = dict(items)
        self.update()

    def set_selected(self, slot: int) -> None:
        self._selected = int(slot)
        self.update()

    @property
    def per_page(self) -> int:
        return self._cols * self._rows

    def page_slots(self) -> list[int]:
        """Gli slot delle tasche **a schermo**, in ordine di disegno.

        Con due pagine sono quelli della pagina corrente seguiti da quelli
        della successiva: la pagina di destra è `self._page + 1`, come in un
        raccoglitore aperto.
        """
        base = self._page * self.per_page
        quante = self.pages_shown() * self.per_page
        return list(range(base, base + quante))

    # --------------------------------------------------------- geometria ---
    # Un raccoglitore APERTO mostra due pagine affiancate, con gli anelli in
    # mezzo: è così che lo si riconosce prima ancora di guardare le carte. Ma
    # due pagine ci stanno solo se c'è larghezza — in una finestra stretta, o
    # con un formato 4×3, le tasche diventerebbero francobolli. Quindi il
    # numero di pagine a schermo lo decide lo spazio, e lo decide UNA volta in
    # `_layout()`: tutto il resto (tasche, foglio, anelli, trascinamento) legge
    # da lì, così non possono raccontarsi due geometrie diverse.
    def _layout(self) -> tuple[int, QSize, QRect]:
        """`(pagine a schermo, dimensione della tasca, rettangolo del foglio)`.

        L'ordine del calcolo non è casuale: la tasca si misura **sull'altezza**
        (è il lato che comanda quasi sempre), poi si guarda se due griglie di
        quella misura ci stanno in larghezza. Decidere prima le pagine e poi la
        tasca farebbe oscillare la scelta a ogni ridisegno.
        """
        colonne, righe = self._cols, self._rows
        altezza = max(1, (self.height() - 2 * MARGINE
                          - GAP * (righe - 1)) // righe)
        larghezza = int(altezza * CARD_RATIO)
        griglia = larghezza * colonne + GAP * (colonne - 1)
        if larghezza >= 40 and 2 * griglia + 4 * MARGINE + SPINE <= self.width():
            pagine = 2
            totale = 2 * griglia + 4 * MARGINE + SPINE
        else:
            pagine = 1
            utile = max(1, self.width() - SPINE - 2 * MARGINE
                        - GAP * (colonne - 1))
            larghezza = min(larghezza, utile // colonne)
            altezza = int(larghezza / CARD_RATIO)
            griglia = larghezza * colonne + GAP * (colonne - 1)
            totale = SPINE + 2 * MARGINE + griglia
        cella = QSize(max(40, larghezza), max(58, altezza))
        alta = 2 * MARGINE + cella.height() * righe + GAP * (righe - 1)
        foglio = QRect(max(0, (self.width() - totale) // 2),
                       max(0, (self.height() - alta) // 2), totale, alta)
        return pagine, cella, foglio

    def pages_shown(self) -> int:
        """Quante pagine si vedono adesso (1 o 2): lo chiede chi sfoglia."""
        return self._layout()[0]

    def _cell_size(self) -> QSize:
        return self._layout()[1]

    def _sheet_rect(self) -> QRect:
        return self._layout()[2]

    def _origin(self, lato: int = 0) -> QPoint:
        """Angolo in alto a sinistra della griglia `lato` (0 = sinistra)."""
        pagine, cella, foglio = self._layout()
        griglia = cella.width() * self._cols + GAP * (self._cols - 1)
        if pagine == 1:
            return QPoint(foglio.x() + SPINE + MARGINE, foglio.y() + MARGINE)
        if lato == 0:
            return QPoint(foglio.x() + MARGINE, foglio.y() + MARGINE)
        return QPoint(foglio.x() + MARGINE + griglia + MARGINE + SPINE + MARGINE,
                      foglio.y() + MARGINE)

    def _rect_for(self, indice: int) -> QRect:
        """Rettangolo della tasca `indice` fra quelle a schermo.

        Con due pagine gli indici da `per_page` in su stanno sulla pagina di
        destra: è la stessa numerazione di `page_slots()`, e tenerle allineate
        è ciò che impedisce di posare una carta nella tasca sbagliata.
        """
        cella = self._cell_size()
        lato, dentro = divmod(int(indice), self.per_page)
        origine = self._origin(min(lato, 1))
        riga, colonna = divmod(dentro, self._cols)
        return QRect(origine.x() + colonna * (cella.width() + GAP),
                     origine.y() + riga * (cella.height() + GAP),
                     cella.width(), cella.height())

    def slot_at(self, punto: QPoint) -> int:
        """Slot ASSOLUTO sotto il puntatore, o -1 fuori dalle tasche."""
        visibili = list(self.page_slots())
        for i, slot in enumerate(visibili):
            if self._rect_for(i).contains(punto):
                return slot
        return -1

    # ----------------------------------------------------------- disegno ---
    def paintEvent(self, event) -> None:  # noqa: N802 (firma Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        pagine, cella, _foglio = self._layout()
        self._disegna_foglio(painter, pagine, cella)

        # Mentre si sfoglia le tasche scorrono e sbiadiscono; il foglio no,
        # altrimenti sembrerebbe che si muova il raccoglitore invece della
        # pagina.
        scostamento = self._shift * cella.width() * 0.45
        if abs(self._shift) > 0.001:
            painter.save()
            painter.translate(scostamento, 0)
            painter.setOpacity(max(0.0, 1.0 - abs(self._shift) * 0.85))

        for i, slot in enumerate(self.page_slots()):
            rect = QRectF(self._rect_for(i))
            riga = self._items.get(slot)
            sopra = (slot == self._hover)
            if riga is None:
                self._disegna_tasca_vuota(painter, rect, sopra)
            else:
                self._disegna_tasca(painter, rect, riga, sopra)
            if slot == self._selected:
                self._disegna_anello_scelta(painter, rect)

        if abs(self._shift) > 0.001:
            painter.restore()
        painter.end()

    # --- il foglio e i suoi anelli ---
    def _disegna_foglio(self, painter: QPainter, pagine: int,
                        cella: QSize) -> None:
        foglio = QRectF(self._sheet_rect())
        _ombra(painter, foglio, 16, passi=6, forza=110)
        sfondo = QLinearGradient(foglio.topLeft(), foglio.bottomLeft())
        sfondo.setColorAt(0.0, QColor(theme.SURFACE).lighter(112))
        sfondo.setColorAt(1.0, QColor(theme.SURFACE))
        painter.setBrush(sfondo)
        painter.setPen(QPen(_colore(theme.BORDER, 200), 1))
        painter.drawRoundedRect(foglio, 16, 16)

        # Dove passa la rilegatura: a sinistra con una pagina sola, in MEZZO
        # con due — ed è quello il segno che dice "raccoglitore aperto".
        if pagine == 2:
            griglia = cella.width() * self._cols + GAP * (self._cols - 1)
            cx = foglio.x() + MARGINE + griglia + MARGINE + SPINE / 2.0
            self._disegna_piega(painter, foglio, cx)
        else:
            cx = foglio.x() + SPINE / 2.0
            self._disegna_piega(painter, foglio, foglio.x() + SPINE, solo_destra=True)

        origine = self._origin(0)
        for r in range(self._rows):
            cy = origine.y() + r * (cella.height() + GAP) + cella.height() / 2.0
            self._disegna_anello(painter, cx, cy)

    @staticmethod
    def _disegna_piega(painter: QPainter, foglio: QRectF, x: float,
                       solo_destra: bool = False) -> None:
        """L'ombra della rilegatura: la carta si incurva verso la piega.

        Corre per TUTTA l'altezza del foglio, ritagliata sugli angoli tondi:
        fermandola qualche pixel prima si vedevano due estremità nette, e una
        piega con un inizio e una fine non è una piega.
        """
        painter.save()
        painter.setClipPath(_percorso(foglio, 16))
        if not solo_destra:
            sfumatura = QLinearGradient(QPointF(x - 28, 0), QPointF(x + 28, 0))
            sfumatura.setColorAt(0.0, _colore(theme.SHADOW, 0))
            sfumatura.setColorAt(0.5, _colore(theme.SHADOW, 95))
            sfumatura.setColorAt(1.0, _colore(theme.SHADOW, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(sfumatura)
            painter.drawRect(QRectF(x - 28, foglio.y(), 56, foglio.height()))
        painter.setPen(QPen(_colore(theme.BORDER, 150), 1))
        painter.drawLine(QPointF(x, foglio.y()), QPointF(x, foglio.bottom()))
        painter.setPen(QPen(_colore("#ffffff", 10), 1))
        painter.drawLine(QPointF(x + 1, foglio.y()),
                         QPointF(x + 1, foglio.bottom()))
        painter.restore()

    @staticmethod
    def _disegna_anello(painter: QPainter, cx: float, cy: float) -> None:
        """Un occhiello: il buco nel foglio e l'anello di metallo che ci passa."""
        buco = QRectF(cx - 5.5, cy - 5.5, 11, 11)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.BG))
        painter.drawEllipse(buco)
        painter.setPen(QPen(_colore(theme.SHADOW, 90), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(buco)

        metallo = QLinearGradient(QPointF(cx, cy - 10), QPointF(cx, cy + 10))
        metallo.setColorAt(0.0, QColor("#f2f5f9"))
        metallo.setColorAt(0.40, QColor("#b9c3d1"))
        metallo.setColorAt(1.0, QColor("#697382"))
        painter.setPen(QPen(metallo, 2.8))
        painter.drawEllipse(QRectF(cx - 10, cy - 10, 20, 20))

    # --- le tasche ---
    @staticmethod
    def _incasso(painter: QPainter, rect: QRectF) -> None:
        """Il fondo della tasca: più scuro del foglio, con un filo di luce in
        alto. Sono i due segni che il cervello legge come "incassato"."""
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.BG).lighter(108))
        painter.drawRoundedRect(rect, R_TASCA, R_TASCA)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_colore(theme.SHADOW, 120), 1))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5),
                                R_TASCA, R_TASCA)
        painter.setPen(QPen(_colore("#ffffff", 16), 1))
        painter.drawLine(QPointF(rect.x() + R_TASCA, rect.y() + 1.2),
                         QPointF(rect.right() - R_TASCA, rect.y() + 1.2))

    def _disegna_tasca_vuota(self, painter: QPainter, rect: QRectF,
                             sopra: bool) -> None:
        """Tasca vuota: un alloggiamento, non un errore.

        Deve leggersi come "qui ci sta una carta": per questo c'è la sagoma
        tenue di una carta, e il segno "+" compare **solo** passandoci sopra —
        sempre visibile sarebbe un invito insistente su nove tasche per pagina.
        """
        self._incasso(painter, rect)
        sagoma = rect.adjusted(rect.width() * 0.13, rect.height() * 0.11,
                               -rect.width() * 0.13, -rect.height() * 0.11)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_colore(theme.BORDER, 110 if sopra else 70), 1,
                            Qt.PenStyle.DashLine))
        painter.drawRoundedRect(sagoma, R_CARTA, R_CARTA)
        if not sopra:
            return
        painter.setBrush(_colore(theme.ACCENT, 16))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, R_TASCA, R_TASCA)
        # Il "+" è disegnato, non scritto: i glifi che non esistono nel font
        # incorporato lasciano il pulsante vuoto (GOTCHA 33).
        braccio = min(rect.width(), rect.height()) * 0.09
        cx, cy = rect.center().x(), rect.center().y()
        painter.setPen(QPen(_colore(theme.ACCENT, 190), 2,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(cx - braccio, cy), QPointF(cx + braccio, cy))
        painter.drawLine(QPointF(cx, cy - braccio), QPointF(cx, cy + braccio))

    def _disegna_tasca(self, painter: QPainter, rect: QRectF, riga,
                       sopra: bool) -> None:
        self._incasso(painter, rect)
        carta = rect.adjusted(PAD, PAD, -PAD, -PAD)
        if sopra:
            # la carta si solleva: sporge un filo dalla tasca e la sua ombra
            # cresce, come sfilandola per guardarla meglio
            cresci = min(carta.width(), carta.height()) * SOLLEVA
            carta = carta.adjusted(-cresci, -cresci * 1.4, cresci,
                                   cresci * 0.6)
        _ombra(painter, carta, R_CARTA, passi=4,
               forza=120 if sopra else 70)

        percorso = _percorso(carta, R_CARTA)
        painter.save()
        painter.setClipPath(percorso)
        self._disegna_immagine(painter, carta, riga)
        self._disegna_velatura(painter, carta, riga)
        self._disegna_foil(painter, carta, riga)
        painter.restore()

        # bordo della carta + riflesso della bustina, sopra a tutto
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_colore("#000000", 120), 1))
        painter.drawRoundedRect(carta, R_CARTA, R_CARTA)
        self._disegna_riflesso(painter, rect)

    def _disegna_immagine(self, painter: QPainter, carta: QRectF, riga) -> None:
        pix: QPixmap | None = None
        if self._thumbs is not None:
            pix = self._thumbs.pixmap(riga["card_name"])
        if pix is not None and not pix.isNull():
            # riempie la tasca: l'immagine ha già le proporzioni di una carta,
            # e le briciole che avanzano stanno fuori dal ritaglio
            scalato = pix.scaled(carta.size().toSize(),
                                 Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                 Qt.TransformationMode.SmoothTransformation)
            x = carta.x() + (carta.width() - scalato.width()) / 2.0
            y = carta.y() + (carta.height() - scalato.height()) / 2.0
            painter.drawPixmap(QPointF(x, y), scalato)
            return
        # senza immagine: il dorso di una carta, col nome sopra
        fondo = QLinearGradient(carta.topLeft(), carta.bottomRight())
        fondo.setColorAt(0.0, QColor(theme.SURFACE_3))
        fondo.setColorAt(1.0, QColor(theme.SURFACE_2))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fondo)
        painter.drawRoundedRect(carta, R_CARTA, R_CARTA)
        font = QFont(painter.font())
        font.setPointSizeF(max(6.5, carta.height() * 0.055))
        painter.setFont(font)
        painter.setPen(QColor(theme.TEXT_MUTED))
        painter.drawText(carta.adjusted(6, 6, -6, -6).toRect(),
                         int(Qt.AlignmentFlag.AlignCenter
                             | Qt.TextFlag.TextWordWrap),
                         riga["card_name"])

    def _disegna_velatura(self, painter: QPainter, carta: QRectF, riga) -> None:
        """Prezzo e copie su una velatura in fondo alla carta.

        Sopra l'immagine e non in una riga sotto: così la carta resta grande —
        che è il motivo per cui si apre la vista dei raccoglitori — e il dato
        resta leggibile su qualunque illustrazione.
        """
        alta = max(14.0, carta.height() * 0.165)
        strato = QRectF(carta.x(), carta.bottom() - alta, carta.width(), alta)
        velo = QLinearGradient(strato.topLeft(), strato.bottomLeft())
        velo.setColorAt(0.0, _colore("#05070b", 0))
        velo.setColorAt(0.45, _colore("#05070b", 170))
        velo.setColorAt(1.0, _colore("#05070b", 225))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(velo)
        painter.drawRect(strato)

        font = QFont(painter.font())
        font.setPointSizeF(max(6.0, alta * 0.36))
        font.setBold(True)
        painter.setFont(font)
        prezzo = riga["price"]
        testo = QRectF(strato.x() + 5, strato.y(), strato.width() - 10,
                       strato.height() - 2)
        painter.setPen(QColor(theme.TEXT_DISABLED if prezzo is None
                              else theme.TEXT))
        painter.drawText(testo, int(Qt.AlignmentFlag.AlignLeft
                                    | Qt.AlignmentFlag.AlignVCenter),
                         soldi(prezzo, riga["currency"]))
        copie = int(riga["quantity"] or 1)
        if copie > 1:
            painter.setPen(QColor(theme.ACCENT))
            painter.drawText(testo, int(Qt.AlignmentFlag.AlignRight
                                        | Qt.AlignmentFlag.AlignVCenter),
                             f"×{copie}")

    @staticmethod
    def _disegna_foil(painter: QPainter, carta: QRectF, riga) -> None:
        """Striscia col colore della rarità, in fondo alla carta.

        Lo stesso vocabolario delle pillole di `core/rarity.py`, su un altro
        supporto: sfogliando un raccoglitore si vede dove stanno le carte buone
        senza fermarsi a leggere una sigla. Rarità sconosciuta = grigio neutro,
        mai un colore inventato.
        """
        nome = rarity.from_detail(riga["detail"] or "")
        if not nome:
            return
        colori = rarity.rarity_colors(nome)
        striscia = QRectF(carta.x(), carta.bottom() - 3.0, carta.width(), 3.0)
        if len(colori) == 1:
            painter.setBrush(QColor(colori[0]))
        else:
            sfumatura = QLinearGradient(striscia.topLeft(), striscia.topRight())
            for i, c in enumerate(colori):
                sfumatura.setColorAt(i / (len(colori) - 1), QColor(c))
            painter.setBrush(sfumatura)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(striscia)

    @staticmethod
    def _disegna_riflesso(painter: QPainter, rect: QRectF) -> None:
        """Il riflesso della bustina di plastica sopra la carta.

        È il dettaglio che fa la differenza fra "un'immagine dentro un
        riquadro" e "una carta dentro una tasca": la luce appartiene alla
        tasca, non alla carta, quindi si dipinge sul rettangolo della TASCA e
        resta ferma anche quando la carta si solleva.
        """
        painter.save()
        painter.setClipPath(_percorso(rect, R_TASCA))
        luce = QLinearGradient(rect.topLeft(), rect.bottomRight())
        luce.setColorAt(0.00, _colore("#ffffff", 30))
        luce.setColorAt(0.20, _colore("#ffffff", 12))
        luce.setColorAt(0.34, _colore("#ffffff", 0))
        luce.setColorAt(0.62, _colore("#ffffff", 0))
        luce.setColorAt(0.70, _colore("#ffffff", 9))
        luce.setColorAt(0.80, _colore("#ffffff", 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(luce)
        painter.drawRoundedRect(rect, R_TASCA, R_TASCA)
        painter.restore()

    @staticmethod
    def _disegna_anello_scelta(painter: QPainter, rect: QRectF) -> None:
        """La tasca scelta: un alone teal, non un rettangolo netto."""
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_colore(theme.ACCENT, 70), 4))
        painter.drawRoundedRect(rect.adjusted(-1.5, -1.5, 1.5, 1.5),
                                R_TASCA + 2, R_TASCA + 2)
        painter.setPen(QPen(_colore(theme.ACCENT, 235), 1.6))
        painter.drawRoundedRect(rect.adjusted(0.8, 0.8, -0.8, -0.8),
                                R_TASCA, R_TASCA)

    # ------------------------------------------------------------- mouse ---
    def mousePressEvent(self, event) -> None:  # noqa: N802 (firma Qt)
        slot = self.slot_at(event.position().toPoint())
        if event.button() == Qt.MouseButton.RightButton:
            if slot >= 0:
                self.slot_menu.emit(slot, event.globalPosition().toPoint())
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.position().toPoint()
            self._drag_slot = slot
            if slot >= 0:
                self.set_selected(slot)
                self.slot_clicked.emit(slot)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (firma Qt)
        prima = self._hover
        self._hover = self.slot_at(event.position().toPoint())
        if self._hover != prima:
            self.update()
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if self._drag_slot < 0 or self._drag_slot not in self._items:
            return
        # `QStyle.PixelMetric.PM_StartDragDistance` NON esiste in questa
        # PySide6 (c'è `PM_MaximumDragDistance`, che è un'altra cosa): la
        # soglia giusta la tiene l'applicazione. Una riga che si esegue solo
        # trascinando davvero, quindi invisibile a qualunque schermata — l'ha
        # smascherata una prova che fa il gesto al posto della mano.
        distanza = (event.position().toPoint() - self._drag_from).manhattanLength()
        if distanza < QApplication.startDragDistance():
            return
        riga = self._items[self._drag_slot]
        dati = QMimeData()
        dati.setData(MIME, str(int(riga["id"])).encode("ascii"))
        trascina = QDrag(self)
        trascina.setMimeData(dati)
        if self._thumbs is not None:
            pix = self._thumbs.pixmap(riga["card_name"])
            if pix is not None and not pix.isNull():
                trascina.setPixmap(pix.scaledToHeight(
                    110, Qt.TransformationMode.SmoothTransformation))
        self._drag_slot = -1
        trascina.exec(Qt.DropAction.MoveAction)

    def leaveEvent(self, event) -> None:  # noqa: N802 (firma Qt)
        if self._hover != -1:
            self._hover = -1
            self.update()
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (firma Qt)
        slot = self.slot_at(event.position().toPoint())
        if slot >= 0:
            self.slot_activated.emit(slot)

    # ---------------------------------------------------- trascinamento ---
    def dragEnterEvent(self, event) -> None:  # noqa: N802 (firma Qt)
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (firma Qt)
        if not event.mimeData().hasFormat(MIME):
            return
        slot = self.slot_at(event.position().toPoint())
        if slot != self._hover:
            self._hover = slot
            self.update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 (firma Qt)
        self._hover = -1
        self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 (firma Qt)
        self._hover = -1
        if not event.mimeData().hasFormat(MIME):
            return
        slot = self.slot_at(event.position().toPoint())
        if slot < 0:
            return          # lasciata fuori dalle tasche: non succede niente
        try:
            item_id = int(bytes(event.mimeData().data(MIME)).decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            return
        event.acceptProposedAction()
        self.dropped.emit(item_id, slot)

    # ------------------------------------------------------------ utile ---
    def tooltip_for(self, slot: int) -> str:
        riga = self._items.get(slot)
        if riga is None:
            return tr("Tasca vuota")
        pezzi = [riga["card_name"]]
        if riga["detail"]:
            pezzi.append(riga["detail"])
        if riga["condition"]:
            pezzi.append(riga["condition"])
        return "\n".join(pezzi)
