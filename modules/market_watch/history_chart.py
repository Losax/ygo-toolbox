"""Grafico dello storico prezzi di una carta.

I dati sono già tutti in `mw_price_history`: qui non si scarica niente e non
si tocca la rete. Le decisioni che contano, tutte figlie della regola "non
inventare numeri":

1. **Linea a GRADINI, non interpolata.** Lo storico registra i *cambi* di
   prezzo, non i controlli: fra due punti il prezzo è rimasto quello. Una
   diagonale disegnerebbe una discesa graduale mai avvenuta.
2. **La linea arriva a "adesso".** L'ultimo prezzo registrato è ancora quello
   in vigore: fermare il tratto all'ultimo punto farebbe sembrare la carta
   "non seguita da giorni".
3. **In pieno colore solo la corsa ATTUALE dei filtri** (l'ultimo blocco di
   punti con la stessa `filters_key`, la stessa definizione di `_run_start`).
   Le corse precedenti sono un ALTRO prodotto — altra lingua, condizione,
   stampa — e si mostrano solo a richiesta, smorzate e separate da una linea
   tratteggiata. Attaccarle alla corsa attuale è esattamente il crollo
   inventato che le v1.0.11/12 hanno tolto di mezzo.
4. **Punti consecutivi con lo stesso prezzo si fondono.** I DB nati prima di
   `record_price` ne contengono a raffica (visti 4 punti identici in 15
   secondi): sono lo stesso prezzo, non quattro eventi.
5. **L'asse dei prezzi NON parte da zero.** Un movimento da 226 a 246 € su un
   asse zero-based sarebbe una riga piatta. In cambio i valori dell'asse sono
   sempre scritti: la scala si legge, non si indovina.
6. Si disegna in un QWidget con QPainter, non in un pixmap: così la scala del
   monitor la gestisce Qt e il grafico resta nitido sugli schermi densi (i 21
   pixmap disegnati a mano restano il debito noto, questo non lo aumenta).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from PySide6.QtCore import (
    QEasingCurve,
    QEventLoop,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import anim, theme
from core.i18n import tr

from .filters_dialog import ToggleSwitch

_DT_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
               "%Y-%m-%d")


# --------------------------------------------------------------- logica pura
# (niente Qt qui sotto: si prova con lo smoke test senza aprire finestre)

@dataclass
class Point:
    when: datetime
    price: float


@dataclass
class Run:
    """Una "corsa": punti consecutivi rilevati con gli STESSI filtri."""
    key: str
    points: list = field(default_factory=list)
    currency: str = "EUR"

    @property
    def first(self) -> float | None:
        return self.points[0].price if self.points else None

    @property
    def last(self) -> float | None:
        return self.points[-1].price if self.points else None

    @property
    def low(self) -> float | None:
        return min(p.price for p in self.points) if self.points else None

    @property
    def high(self) -> float | None:
        return max(p.price for p in self.points) if self.points else None

    def change_pct(self) -> float | None:
        """Variazione dal PRIMO prezzo di questa corsa. Con un punto solo non
        c'è variazione da mostrare: None, che a schermo diventa "—"."""
        if len(self.points) < 2 or not self.first:
            return None
        return (self.last - self.first) / self.first * 100.0


def parse_dt(raw) -> datetime | None:
    if isinstance(raw, datetime):
        return raw
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def split_runs(rows) -> list[Run]:
    """Spezza lo storico in corse: ogni cambio di `filters_key` ne apre una
    nuova. Le righe arrivano in ordine cronologico (`history_points`), quindi
    l'ultima corsa è quella attuale — la stessa cosa che `_run_start` calcola
    con MAX(id) fra i punti di chiave diversa."""
    runs: list[Run] = []
    for row in rows:
        when = parse_dt(row["captured_at"])
        if when is None:
            continue                        # data illeggibile: meglio saltarla
        key = row["filters_key"] or ""
        price = float(row["price"])
        if runs and runs[-1].key == key:
            runs[-1].points.append(Point(when, price))
        else:
            runs.append(Run(key, [Point(when, price)], row["currency"] or "EUR"))
    for run in runs:
        run.points = collapse(run.points)
    return runs


def collapse(points: list) -> list:
    """Toglie i punti consecutivi con lo stesso prezzo: restano gli istanti in
    cui il prezzo è CAMBIATO (i DB vecchi registravano ogni controllo)."""
    out: list = []
    for p in points:
        if out and abs(out[-1].price - p.price) < 1e-9:
            continue
        out.append(p)
    return out


def nice_ticks(lo: float, hi: float, target: int = 4) -> list[float]:
    """Valori "tondi" per l'asse dei prezzi, da lo a hi inclusi."""
    if not (hi > lo):
        pad = max(abs(hi) * 0.05, 0.5)      # serie piatta o punto solo
        lo, hi = lo - pad, hi + pad
    raw = (hi - lo) / max(1, target)
    mag = 10.0 ** math.floor(math.log10(raw)) if raw > 0 else 1.0
    step = mag
    for mult in (1, 2, 2.5, 5, 10):
        step = mult * mag
        if step >= raw:
            break
    ticks, value = [], math.floor(lo / step) * step
    while value < hi + step * 0.5:
        ticks.append(round(value, 10))
        value += step
    return ticks or [lo, hi]


def price_at(points: list, when: datetime) -> float | None:
    """Prezzo in vigore a quell'istante: l'ultimo registrato PRIMA (o a) quel
    momento. È la lettura corretta di una serie a gradini."""
    found = None
    for p in points:
        if p.when <= when:
            found = p.price
        else:
            break
    return found


# ------------------------------------------------------------------ disegno

class PriceChart(QWidget):
    """Il grafico vero e proprio: assi, gradini, punti e mirino al passaggio
    del mouse. Non conosce il DB: riceve le corse già spezzate."""

    PAD_TOP = 14
    PAD_RIGHT = 16
    PAD_BOTTOM = 26

    def __init__(self, parent=None, scale: float = 1.0) -> None:
        super().__init__(parent)
        self._scale = scale
        self._runs: list[Run] = []
        self._show_previous = False
        self._now = datetime.now()
        self._hover_x: float | None = None
        self._reveal = 1.0
        self._plot = QRectF()
        self._geom: dict = {}
        self.setMouseTracking(True)
        self.setMinimumHeight(round(210 * scale))
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(),
                           self.sizePolicy().verticalPolicy())
        # UNA sola animazione, creata qui e riavviata (GOTCHA 11: con
        # DeleteWhenStopped il riferimento Python muore a fine corsa e il giro
        # dopo esplode).
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(430)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_reveal)

    # --- dati -------------------------------------------------------------
    def set_runs(self, runs: list, now: datetime | None = None) -> None:
        self._runs = list(runs)
        self._now = now or datetime.now()
        self._hover_x = None
        cur = self.current_run()
        if anim.is_enabled() and cur is not None and cur.points:
            self._reveal = 0.0
            self._anim.stop()
            self._anim.start()
        else:
            self._reveal = 1.0
        self.update()

    def replay(self) -> None:
        """Rifà la comparsa della linea. Serve al pop-up: durante la
        transizione la finestra è ancora un'istantanea, quindi la linea si
        disegnerebbe dove nessuno la vede — e si atterrerebbe su un grafico
        già finito."""
        cur = self.current_run()
        if not (anim.is_enabled() and cur is not None and cur.points):
            return
        self._reveal = 0.0
        self._anim.stop()
        self._anim.start()
        self.update()

    def set_show_previous(self, on: bool) -> None:
        self._show_previous = bool(on)
        self.update()

    def current_run(self) -> Run | None:
        return self._runs[-1] if self._runs else None

    def previous_runs(self) -> list:
        return self._runs[:-1] if len(self._runs) > 1 else []

    def _visible_runs(self) -> list:
        cur = self.current_run()
        if cur is None:
            return []
        return (self.previous_runs() + [cur]) if self._show_previous else [cur]

    def _on_reveal(self, value) -> None:
        self._reveal = float(value)
        self.update()

    # --- interazione ------------------------------------------------------
    def mouseMoveEvent(self, event) -> None:
        x = event.position().x()
        self._hover_x = x if self._plot.left() <= x <= self._plot.right() else None
        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_x = None
        self.update()
        super().leaveEvent(event)

    # --- disegno ----------------------------------------------------------
    def _font(self, delta: float = 0.0, bold: bool = False) -> QFont:
        font = QFont(theme.FONT_FAMILY)
        font.setPointSizeF(max(6.0, (8.5 + delta) * self._scale))
        font.setBold(bold)
        return font

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        runs = self._visible_runs()
        points = [p for r in runs for p in r.points]
        if not points:
            self._paint_empty(painter)
            painter.end()
            return

        small = self._font()
        metrics = QFontMetrics(small)
        currency = (self.current_run().currency if self.current_run() else "EUR")
        sym = "€" if currency.upper() == "EUR" else currency

        lo = min(p.price for p in points)
        hi = max(p.price for p in points)
        ticks = nice_ticks(lo, hi)
        y_lo, y_hi = ticks[0], ticks[-1]
        label_w = max(metrics.horizontalAdvance(self._fmt(t, sym)) for t in ticks)

        left = label_w + round(12 * self._scale)
        self._plot = QRectF(left, self.PAD_TOP * self._scale,
                            max(10.0, self.width() - left - self.PAD_RIGHT * self._scale),
                            max(10.0, self.height() - (self.PAD_TOP + self.PAD_BOTTOM) * self._scale))

        t0 = min(p.when for p in points)
        t1 = max(self._now, max(p.when for p in points))
        if (t1 - t0).total_seconds() < 60:      # un punto solo: finestra di un giorno
            t0, t1 = t0 - timedelta(hours=12), t1 + timedelta(hours=12)
        self._geom = {"t0": t0, "t1": t1, "y_lo": y_lo, "y_hi": y_hi, "sym": sym}

        self._paint_grid(painter, ticks, small, sym)
        self._paint_time_axis(painter, small, t0, t1)

        painter.save()
        painter.setClipRect(QRectF(self._plot.left(), 0,
                                   self._plot.width() * self._reveal, self.height()))
        if self._show_previous:
            for run in self.previous_runs():
                self._paint_run(painter, run, muted=True)
            self._paint_breaks(painter, small)
        cur = self.current_run()
        if cur is not None:
            self._paint_run(painter, cur, muted=False)
        painter.restore()

        if self._hover_x is not None and self._reveal >= 1.0:
            self._paint_hover(painter, small)
        painter.end()

    def _fmt(self, value: float, sym: str) -> str:
        return f"{value:,.2f} {sym}".replace(",", " ")

    def _x(self, when: datetime) -> float:
        t0, t1 = self._geom["t0"], self._geom["t1"]
        span = (t1 - t0).total_seconds() or 1.0
        frac = (when - t0).total_seconds() / span
        return self._plot.left() + max(0.0, min(1.0, frac)) * self._plot.width()

    def _y(self, price: float) -> float:
        lo, hi = self._geom["y_lo"], self._geom["y_hi"]
        span = (hi - lo) or 1.0
        return self._plot.bottom() - (price - lo) / span * self._plot.height()

    def _paint_empty(self, painter: QPainter) -> None:
        painter.setPen(QColor(theme.TEXT_MUTED))
        painter.setFont(self._font(0.5))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                         tr("Nessun prezzo ancora registrato con questi filtri.\n"
                            "Il grafico compare dal primo controllo."))

    def _paint_grid(self, painter, ticks, font, sym) -> None:
        painter.setFont(font)
        for value in ticks:
            y = self._y(value)
            painter.setPen(QPen(QColor(theme.BORDER), 1))
            painter.drawLine(QPointF(self._plot.left(), y), QPointF(self._plot.right(), y))
            painter.setPen(QColor(theme.TEXT_MUTED))
            painter.drawText(QRectF(0, y - 9 * self._scale,
                                    self._plot.left() - 8 * self._scale, 18 * self._scale),
                             int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                             self._fmt(value, sym))

    def _paint_time_axis(self, painter, font, t0: datetime, t1: datetime) -> None:
        painter.setFont(font)
        painter.setPen(QColor(theme.TEXT_MUTED))
        span = (t1 - t0).total_seconds()
        # con meno di tre giorni la data secca non basta: si vedrebbero
        # etichette identiche una accanto all'altra
        fmt = "%d/%m %H:%M" if span < 3 * 86400 else "%d/%m"
        metrics = QFontMetrics(font)
        n = max(2, min(5, int(self._plot.width() // (metrics.horizontalAdvance("00/00 00:00") + 26 * self._scale))))
        for i in range(n + 1):
            when = t0 + timedelta(seconds=span * i / n)
            x = self._x(when)
            text = when.strftime(fmt)
            w = metrics.horizontalAdvance(text) + 6
            x = max(self._plot.left(), min(x - w / 2, self._plot.right() - w))
            painter.drawText(QRectF(x, self._plot.bottom() + 6 * self._scale, w, 18 * self._scale),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)

    def _step_points(self, run: Run) -> list:
        """La spezzata a gradini: ogni prezzo tenuto fino al cambio successivo,
        e l'ultimo tenuto fino ad ADESSO (è ancora quello in vigore)."""
        pts: list[QPointF] = []
        for i, p in enumerate(run.points):
            x, y = self._x(p.when), self._y(p.price)
            if pts:
                pts.append(QPointF(x, pts[-1].y()))     # tratto orizzontale
            pts.append(QPointF(x, y))
            if i == len(run.points) - 1:
                end = self._now if run is self.current_run() else run.points[-1].when
                pts.append(QPointF(self._x(end), y))
        return pts

    def _paint_run(self, painter: QPainter, run: Run, muted: bool) -> None:
        pts = self._step_points(run)
        if len(pts) < 2:
            return
        color = QColor(theme.TEXT_DISABLED) if muted else QColor(theme.ACCENT)
        if not muted:
            area = QPolygonF(pts + [QPointF(pts[-1].x(), self._plot.bottom()),
                                    QPointF(pts[0].x(), self._plot.bottom())])
            grad = QLinearGradient(0, self._plot.top(), 0, self._plot.bottom())
            top = QColor(theme.ACCENT)
            top.setAlpha(58)
            bottom = QColor(theme.ACCENT)
            bottom.setAlpha(0)
            grad.setColorAt(0.0, top)
            grad.setColorAt(1.0, bottom)
            path = QPainterPath()
            path.addPolygon(area)
            painter.fillPath(path, QBrush(grad))
        pen = QPen(color, (1.4 if muted else 2.0) * self._scale)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawPolyline(QPolygonF(pts))
        # I pallini sui punti rilevati servono anche alle corse smorzate: una
        # serie di pochi punti ravvicinati (capita: quattro letture in pochi
        # minuti) su un asse di settimane si schiaccia in un tratto verticale,
        # che senza pallini si legge come un difetto di disegno invece che
        # come "qui ci sono state alcune rilevazioni".
        painter.setBrush(QBrush(QColor(theme.BG)))
        painter.setPen(QPen(color, (1.2 if muted else 1.6) * self._scale))
        r = (2.2 if muted else 3.0) * self._scale
        for p in run.points:
            painter.drawEllipse(QPointF(self._x(p.when), self._y(p.price)), r, r)

    def _paint_breaks(self, painter: QPainter, font) -> None:
        """Dove i filtri sono cambiati: linea tratteggiata. Di là c'è un altro
        prodotto, e deve VEDERSI che le due serie non si parlano."""
        pen = QPen(QColor(theme.WARN), 1.0 * self._scale, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        for run in self._runs[1:]:
            if not run.points:
                continue
            x = self._x(run.points[0].when)
            painter.drawLine(QPointF(x, self._plot.top()), QPointF(x, self._plot.bottom()))

    def _paint_hover(self, painter: QPainter, font) -> None:
        cur = self.current_run()
        if cur is None or not cur.points:
            return
        t0, t1 = self._geom["t0"], self._geom["t1"]
        frac = (self._hover_x - self._plot.left()) / max(1.0, self._plot.width())
        when = t0 + timedelta(seconds=(t1 - t0).total_seconds() * frac)
        price = price_at(cur.points, when)
        if price is None:
            return
        # istante in cui quel prezzo è stato rilevato: il gradino a sinistra
        since = max((p.when for p in cur.points if p.when <= when), default=cur.points[0].when)
        x, y = self._x(when), self._y(price)
        painter.setPen(QPen(QColor(theme.TEXT_DISABLED), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(x, self._plot.top()), QPointF(x, self._plot.bottom()))
        painter.setBrush(QBrush(QColor(theme.ACCENT)))
        painter.setPen(QPen(QColor(theme.BG), 1.5 * self._scale))
        painter.drawEllipse(QPointF(x, y), 4.5 * self._scale, 4.5 * self._scale)

        text = f"{self._fmt(price, self._geom['sym'])}   {since.strftime('%d/%m %H:%M')}"
        painter.setFont(font)
        metrics = QFontMetrics(font)
        w = metrics.horizontalAdvance(text) + 16 * self._scale
        h = metrics.height() + 10 * self._scale
        bx = min(max(self._plot.left(), x - w / 2), self._plot.right() - w)
        by = self._plot.top()
        box = QRectF(bx, by, w, h)
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.setBrush(QBrush(QColor(theme.SURFACE_2)))
        painter.drawRoundedRect(box, 6 * self._scale, 6 * self._scale)
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)


def lerp_rect(a: QRect, b: QRect, t: float) -> QRect:
    """Rettangolo interpolato. `t` può superare 1: con un'easing che "sfonda"
    (OutBack) è proprio così che si ottiene il rimbalzo del pop-up."""
    return QRect(round(a.x() + (b.x() - a.x()) * t),
                 round(a.y() + (b.y() - a.y()) * t),
                 max(1, round(a.width() + (b.width() - a.width()) * t)),
                 max(1, round(a.height() + (b.height() - a.height()) * t)))


class _ZoomGhost(QWidget):
    """Il "fantasma" che fa la transizione: un'ISTANTANEA della finestra,
    ridisegnata dentro un rettangolo che cresce dalla miniatura della carta.

    Perché un'istantanea invece di animare la geometria della finestra vera:
    a 44 px il layout non ci sta e Qt lo accartoccia (e comunque si rifiuta di
    scendere sotto il minimo dei figli). Scalando un'immagine già disegnata la
    finestra si "gonfia" intera e uniforme, come deve fare un pop-up."""

    def __init__(self, pixmap) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._pixmap = pixmap
        self._opacity = 1.0

    def set_frame(self, rect: QRect, opacity: float) -> None:
        self._opacity = max(0.0, min(1.0, opacity))
        self.setGeometry(rect)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (override Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setOpacity(self._opacity)
        painter.drawPixmap(self.rect(), self._pixmap)
        painter.end()


class HistoryDialog(QDialog):
    """Finestra "Storico prezzi" di una carta: riepilogo + grafico.

    Senza cornice di Windows (card del tema con ombra, come le impostazioni),
    ma **non** una `CardDialog`: quelle sono `Qt.Popup` e si chiudono al primo
    clic fuori — comodo per due interruttori, pessimo per una finestra che si
    guarda, si sorvola col mouse e si tiene aperta. Qui il clic fuori non fa
    niente: si chiude con la ✕, con Esc o col pulsante.

    Senza cornice nativa servono due cose che di solito dà Windows: un pulsante
    di chiusura (in alto a destra) e il **trascinamento dall'intestazione**."""

    def __init__(self, card_name: str, detail: str, filters_text: str,
                 runs: list, parent=None, scale: float = 1.0) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Storico prezzi · {name}").format(name=card_name))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(round(690 * scale), round(470 * scale))
        self._scale = scale
        self._runs = runs
        self._exiting = False
        self._drag_from = None
        self._ghost = None
        self._anim = None

        outer = QVBoxLayout(self)
        margin = round(18 * scale)              # aria per l'ombra della card
        outer.setContentsMargins(margin, margin, margin, margin)
        card = QFrame()
        card.setObjectName("popover")
        anim.drop_shadow(card, blur=38, dy=10, alpha=190)
        outer.addWidget(card)

        root = QVBoxLayout(card)
        root.setContentsMargins(*[round(18 * scale)] * 4)
        root.setSpacing(round(10 * scale))

        head = QHBoxLayout()
        head.setSpacing(round(8 * scale))
        titles = QVBoxLayout()
        titles.setSpacing(round(2 * scale))
        title = QLabel(card_name)
        tf = QFont(theme.FONT_FAMILY)
        tf.setPointSizeF(13 * scale)
        tf.setBold(True)
        title.setFont(tf)
        titles.addWidget(title)

        sub_bits = [b for b in (detail, filters_text) if b]
        subtitle = QLabel(" · ".join(sub_bits) if sub_bits
                          else tr("filtri predefiniti"))
        subtitle.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        titles.addWidget(subtitle)
        head.addLayout(titles, 1)

        shut = QPushButton("✕")
        shut.setObjectName("ghost")
        shut.setFixedSize(round(28 * scale), round(28 * scale))
        shut.setCursor(Qt.CursorShape.PointingHandCursor)
        shut.setToolTip(tr("Chiudi"))
        shut.clicked.connect(self.accept)
        head.addWidget(shut, 0, Qt.AlignmentFlag.AlignTop)
        # l'intestazione fa da barra del titolo: ci si trascina la finestra
        self._drag_height = round(60 * scale)
        root.addLayout(head)

        root.addLayout(self._stats_row(runs[-1] if runs else None, scale))

        self.chart = PriceChart(self, scale)
        self.chart.set_runs(runs)
        root.addWidget(self.chart, 1)

        foot = QHBoxLayout()
        precedenti = runs[:-1] if len(runs) > 1 else []
        if precedenti:
            # L'interruttore compare SOLO se c'è davvero altra storia: un
            # comando spento che non fa niente è peggio di un comando assente.
            self.prev_switch = ToggleSwitch(
                tr("Mostra le {n} serie precedenti (filtri diversi)").format(n=len(precedenti))
                if len(precedenti) > 1 else
                tr("Mostra la serie precedente (filtri diversi)"))
            self.prev_switch.setToolTip(
                tr("Prezzi rilevati con altri filtri: un'altra lingua, condizione o "
                   "stampa, cioè un altro prodotto. Si disegnano smorzati e separati "
                   "da una linea tratteggiata — non sono confrontabili con la serie "
                   "attuale."))
            self.prev_switch.toggled.connect(self.chart.set_show_previous)
            foot.addWidget(self.prev_switch)
        foot.addStretch(1)
        close = QPushButton(tr("Chiudi"))
        close.setDefault(True)
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        root.addLayout(foot)

    # --- apertura e chiusura "dalla carta" --------------------------------
    def open_from(self, origin: QRect | None = None) -> int:
        """Apre la finestra facendola CRESCERE dalla miniatura della carta.

        `origin` è il rettangolo (in coordinate schermo) dell'immagine nella
        riga della watchlist: è da lì che il gesto è partito, ed è da lì che
        deve partire anche la finestra. Senza (riga non visibile, o chiamata
        da altrove) si parte da un rettangolino al centro: il pop-up resta,
        cambia solo da dove nasce."""
        self._place()
        target = self.geometry()
        if not anim.is_enabled():
            return self.exec()
        start = self._start_rect(origin, target)
        ghost = self._snapshot_ghost()
        if ghost is None:
            return self.exec()
        # L'entrata "sfonda" il rettangolo finale e rientra (OutBack): è quello
        # che rende il pop-up pronunciato invece che una comparsa educata.
        curve = QEasingCurve(QEasingCurve.Type.OutBack)
        curve.setOvershoot(2.2)
        self._run_ghost(ghost, start, target, curve, 400, fade_in=True)
        ghost.hide()
        ghost.deleteLater()
        self._ghost = None
        # la linea si disegna ORA, sulla finestra vera appena atterrata
        self.chart.replay()
        return self.exec()

    def done(self, result: int) -> None:  # noqa: N802 (override Qt)
        """Uscita simmetrica: la finestra si RITIRA nella miniatura da cui era
        uscita. La chiusura vera avviene a fine animazione (guardia
        `_exiting` contro il doppio clic sulla ✕)."""
        if self._exiting or not self.isVisible() or not anim.is_enabled():
            super().done(result)
            return
        self._exiting = True
        target = self.geometry()
        start = self._start_rect(self._origin, target)
        ghost = self._snapshot_ghost()
        if ghost is not None:
            self.hide()
            self._run_ghost(ghost, start, target, QEasingCurve(QEasingCurve.Type.InCubic),
                            230, fade_in=False)
            ghost.hide()
            ghost.deleteLater()
        super().done(result)

    _origin: QRect | None = None

    def _place(self) -> None:
        """Centrata sulla finestra dell'app, ma sempre dentro lo schermo."""
        parent = self.parent().window() if self.parent() is not None else None
        if parent is None:
            return
        area = parent.screen().availableGeometry()
        x = parent.geometry().center().x() - self.width() // 2
        y = parent.geometry().center().y() - self.height() // 2
        x = max(area.left() + 8, min(x, area.right() - self.width() - 8))
        y = max(area.top() + 8, min(y, area.bottom() - self.height() - 8))
        self.move(x, y)

    def _start_rect(self, origin: QRect | None, target: QRect) -> QRect:
        """Da dove nasce (e dove torna) la finestra."""
        self._origin = origin
        if origin is not None and origin.isValid() and not origin.isEmpty():
            return QRect(origin)
        return QRect(target.center().x() - 30, target.center().y() - 42, 60, 84)

    def _snapshot_ghost(self):
        """Istantanea della finestra, presa SENZA mostrarla a schermo
        (WA_DontShowOnScreen: layout vero, nessun lampo)."""
        try:
            if self.isVisible():
                pixmap = self.grab()
            else:
                self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
                self.show()
                pixmap = self.grab()
                self.hide()
                self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, False)
        except RuntimeError:
            return None
        if pixmap.isNull():
            return None
        ghost = _ZoomGhost(pixmap)
        self._ghost = ghost
        return ghost

    def _run_ghost(self, ghost, start: QRect, target: QRect,
                   curve: QEasingCurve, duration: int, fade_in: bool) -> None:
        """Fa correre il fantasma e ASPETTA che finisca, dentro un event loop
        annidato: `exec()` del dialogo bloccherebbe comunque il chiamante, e
        così l'animazione resta un dettaglio di `open_from`/`done` invece di
        spargersi in callback."""
        ghost.set_frame(start if fade_in else target, 1.0 if not fade_in else 0.0)
        ghost.show()
        loop = QEventLoop()
        motion = QVariantAnimation(self)
        motion.setStartValue(0.0)
        motion.setEndValue(1.0)
        motion.setDuration(duration)
        motion.setEasingCurve(curve)

        def frame(value):
            t = float(value)
            if not fade_in:
                t = 1.0 - t
            try:
                # in entrata la dissolvenza finisce a metà corsa, così il
                # rimbalzo si vede tutto invece di arrivare mentre è ancora
                # semitrasparente
                ghost.set_frame(lerp_rect(start, target, t),
                                min(1.0, t * 2.0) if fade_in else min(1.0, t * 1.6))
            except RuntimeError:
                pass

        motion.valueChanged.connect(frame)
        motion.finished.connect(loop.quit)
        self._anim = motion
        motion.start()
        loop.exec()

    # --- trascinamento dall'intestazione (non c'è la barra di Windows) ----
    def mousePressEvent(self, event) -> None:  # noqa: N802 (override Qt)
        if (event.button() == Qt.MouseButton.LeftButton
                and event.position().y() <= self._drag_height):
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (override Qt)
        if self._drag_from is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (override Qt)
        self._drag_from = None
        super().mouseReleaseEvent(event)

    def _stats_row(self, run, scale: float) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(round(8 * scale))
        sym = "€" if (run.currency.upper() if run else "EUR") == "EUR" else run.currency

        def money(value):
            return f"{value:.2f} {sym}" if value is not None else "—"

        change = run.change_pct() if run else None
        colore = (theme.TEXT_MUTED if change is None else
                  theme.POSITIVE if change > 0 else
                  theme.NEGATIVE if change < 0 else theme.TEXT)
        periodo = "—"
        if run and run.points:
            giorni = (datetime.now() - run.points[0].when).days
            periodo = (tr("{n} gg").format(n=giorni) if giorni >= 1 else tr("oggi"))
        for label, value, color in (
            (tr("Attuale"), money(run.last if run else None), theme.TEXT),
            (tr("Minimo"), money(run.low if run else None), theme.TEXT),
            (tr("Massimo"), money(run.high if run else None), theme.TEXT),
            (tr("Dal primo prezzo"),
             "—" if change is None else f"{change:+.1f}%", colore),
            (tr("Punti · periodo"),
             f"{len(run.points) if run else 0} · {periodo}", theme.TEXT),
        ):
            card = self._stat_card(label, value, color, scale)
            # Con le serie precedenti a schermo "Minimo" potrebbe sembrare il
            # minimo del grafico: questi numeri parlano SOLO della serie
            # attuale, e va detto invece di lasciarlo intuire.
            card.setToolTip(tr("Riferito alla serie attuale (i filtri di adesso), "
                               "non alle serie precedenti."))
            row.addWidget(card, 1)
        return row

    def _stat_card(self, label: str, value: str, color: str, scale: float) -> QWidget:
        box = QFrame()
        box.setObjectName("popover")
        box.setStyleSheet(
            f"QFrame#popover {{ background: {theme.SURFACE_2};"
            f" border: 1px solid {theme.BORDER}; border-radius: {round(8 * scale)}px; }}")
        v = QVBoxLayout(box)
        v.setContentsMargins(*[round(8 * scale)] * 4)
        v.setSpacing(round(2 * scale))
        cap = QLabel(label)
        cf = QFont(theme.FONT_FAMILY)
        cf.setPointSizeF(8 * scale)
        cap.setFont(cf)
        cap.setStyleSheet(f"color: {theme.TEXT_MUTED}; background: transparent;")
        val = QLabel(value)
        vf = QFont(theme.FONT_FAMILY)
        vf.setPointSizeF(11 * scale)
        vf.setBold(True)
        val.setFont(vf)
        val.setStyleSheet(f"color: {color}; background: transparent;")
        v.addWidget(cap)
        v.addWidget(val)
        return box

    def sizeHint(self) -> QSize:
        return QSize(round(660 * self._scale), round(430 * self._scale))
