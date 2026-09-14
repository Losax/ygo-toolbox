"""La pagina di un raccoglitore: nove tasche, disegnate a mano.

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

Si trascina: dentro la pagina per riordinare (chi arriva **scambia** con chi
c'era, vedi `repository.place`) e dall'elenco delle carte sfuse per metterle
dentro.
"""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QListWidget, QWidget

from core import theme
from core.i18n import tr

from .format import soldi

#: Formato di trascinamento nostro: il testo è l'id della riga di `col_items`.
#: Uno proprio e non `text/plain` perché così la pagina accetta solo ciò che
#: viene davvero dalla collezione, e non qualunque testo trascinato da fuori.
MIME = "application/x-ygo-collection-item"

CARD_RATIO = 59 / 86        # proporzioni di una carta Yu-Gi-Oh!
GAP = 10                    # aria fra una tasca e l'altra
PAD = 6                     # margine interno della tasca


def _empty_pocket(painter: QPainter, rect: QRect) -> None:
    """Tasca vuota: un contorno tratteggiato, niente di più.

    Deve leggersi come "qui ci sta una carta", non come un errore: per questo è
    un tratteggio tenue e non un riquadro pieno o un punto interrogativo.
    """
    penna = QPen(QColor(theme.BORDER), 1, Qt.PenStyle.DashLine)
    painter.setPen(penna)
    painter.setBrush(QColor(theme.BG))
    painter.drawRoundedRect(rect, 8, 8)


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
        self.setMinimumSize(QSize(320, 300))

    # ------------------------------------------------------------- dati ---
    def set_thumbs(self, thumbs) -> None:
        self._thumbs = thumbs

    def set_layout_size(self, cols: int, rows: int) -> None:
        self._cols, self._rows = max(1, int(cols)), max(1, int(rows))
        self.update()

    def set_page(self, page: int) -> None:
        self._page = max(0, int(page))
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

    def page_slots(self) -> range:
        base = self._page * self.per_page
        return range(base, base + self.per_page)

    # --------------------------------------------------------- geometria ---
    def _cell_size(self) -> QSize:
        """Tasche il più grandi possibile, tutte uguali, proporzioni di carta."""
        larghezza = max(1, (self.width() - GAP * (self._cols + 1)) // self._cols)
        altezza = max(1, (self.height() - GAP * (self._rows + 1)) // self._rows)
        # la carta comanda: si prende il lato che sta dentro entrambi
        if larghezza / max(1, altezza) > CARD_RATIO:
            larghezza = int(altezza * CARD_RATIO)
        else:
            altezza = int(larghezza / CARD_RATIO)
        return QSize(max(40, larghezza), max(58, altezza))

    def _origin(self, cella: QSize) -> QPoint:
        """La griglia sta al centro: una pagina storta si nota subito."""
        usata_x = cella.width() * self._cols + GAP * (self._cols - 1)
        usata_y = cella.height() * self._rows + GAP * (self._rows - 1)
        return QPoint(max(0, (self.width() - usata_x) // 2),
                      max(0, (self.height() - usata_y) // 2))

    def _rect_for(self, indice: int) -> QRect:
        """Rettangolo della tasca `indice` (0..per_page-1) nella pagina corrente."""
        cella = self._cell_size()
        origine = self._origin(cella)
        riga, colonna = divmod(indice, self._cols)
        return QRect(origine.x() + colonna * (cella.width() + GAP),
                     origine.y() + riga * (cella.height() + GAP),
                     cella.width(), cella.height())

    def slot_at(self, punto: QPoint) -> int:
        """Slot ASSOLUTO sotto il puntatore, o -1 fuori dalle tasche."""
        for i in range(self.per_page):
            if self._rect_for(i).contains(punto):
                return self._page * self.per_page + i
        return -1

    # ----------------------------------------------------------- disegno ---
    def paintEvent(self, event) -> None:  # noqa: N802 (firma Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for i, slot in enumerate(self.page_slots()):
            rect = self._rect_for(i)
            riga = self._items.get(slot)
            if riga is None:
                _empty_pocket(painter, rect)
            else:
                self._draw_card(painter, rect, riga)
            if slot == self._selected or slot == self._hover:
                colore = QColor(theme.ACCENT)
                colore.setAlpha(255 if slot == self._selected else 120)
                painter.setPen(QPen(colore, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 8, 8)
        painter.end()

    def _draw_card(self, painter: QPainter, rect: QRect, riga) -> None:
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.setBrush(QColor(theme.SURFACE_2))
        painter.drawRoundedRect(rect, 8, 8)

        interno = rect.adjusted(PAD, PAD, -PAD, -PAD)
        # Riga del prezzo in fondo: una collezione si sfoglia per guardare, ma
        # la domanda "quanto vale questa" arriva subito dopo.
        alt_prezzo = max(12, int(interno.height() * 0.11))
        area_img = QRect(interno.x(), interno.y(),
                         interno.width(), interno.height() - alt_prezzo - 2)
        pix: QPixmap | None = None
        if self._thumbs is not None:
            pix = self._thumbs.pixmap(riga["card_name"])
        if pix is not None and not pix.isNull():
            scalato = pix.scaled(area_img.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            x = area_img.x() + (area_img.width() - scalato.width()) // 2
            y = area_img.y() + (area_img.height() - scalato.height()) // 2
            painter.drawPixmap(x, y, scalato)
        else:
            painter.setPen(QPen(QColor(theme.BORDER), 1))
            painter.setBrush(QColor(theme.BG))
            painter.drawRoundedRect(area_img, 6, 6)
            font = QFont(painter.font())
            font.setPointSizeF(max(6.5, area_img.height() * 0.055))
            painter.setFont(font)
            painter.setPen(QColor(theme.TEXT_MUTED))
            painter.drawText(area_img.adjusted(4, 4, -4, -4),
                             int(Qt.AlignmentFlag.AlignCenter
                                 | Qt.TextFlag.TextWordWrap),
                             riga["card_name"])

        # prezzo (o "—": mai un numero inventato al posto di un dato mancante)
        font = QFont(painter.font())
        font.setPointSizeF(max(6.0, alt_prezzo * 0.62))
        painter.setFont(font)
        prezzo = riga["price"]
        painter.setPen(QColor(theme.TEXT_DISABLED if prezzo is None
                              else theme.TEXT_MUTED))
        testo = soldi(prezzo, riga["currency"])
        riga_prezzo = QRect(interno.x(), interno.bottom() - alt_prezzo,
                            interno.width(), alt_prezzo)
        painter.drawText(riga_prezzo, int(Qt.AlignmentFlag.AlignLeft
                                          | Qt.AlignmentFlag.AlignVCenter), testo)

        copie = int(riga["quantity"] or 1)
        if copie > 1:
            painter.setPen(QColor(theme.ACCENT))
            painter.drawText(riga_prezzo, int(Qt.AlignmentFlag.AlignRight
                                              | Qt.AlignmentFlag.AlignVCenter),
                             f"×{copie}")

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
                    96, Qt.TransformationMode.SmoothTransformation))
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
