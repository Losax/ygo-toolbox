"""Ricerca live con miniatura su ogni voce — versione veloce.

Il filtraggio del QCompleter resta su un QStringListModel (C++): scansionare
47k stringhe a ogni tasto in C++ è istantaneo. Le miniature NON passano dal
modello (lo renderebbe lento, perché il completer chiamerebbe data() in Python
47k volte per tasto): le disegna un ItemDelegate, che le scarica/decodifica
fuori dalla GUI solo per le righe effettivamente visibili.
"""
from __future__ import annotations

import threading
import time

import requests
from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QRect,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QVariantAnimation,
    Signal,
)
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QToolTip

from core import theme

from .net import SESSION

THUMB = QSize(64, 92)
MAX_INFLIGHT = 24
_POOL_THREADS = 6
ROW_H = 110
PAD = 12
_PLACEHOLDER = QColor("#2c313b")
_ACCENT = QColor("#1ac3b2")
_ACCENT_INK = QColor("#042521")
_TEXT = QColor("#eef1f6")
_PILL_BG = QColor("#2f3744")
_HOVER_BG = QColor("#2a313c")           # riga evidenziata al passaggio del mouse
_SEPARATOR = QColor(255, 255, 255, 38)  # linea sottile tra le voci


def _thumb_url(image_url: str) -> str:
    """Dalla variante 'show_' ricava quella 'preview_' (più leggera)."""
    return image_url.replace("/show_", "/preview_") if image_url else ""


_placeholder_cache: dict[tuple[int, int], QPixmap] = {}
_marked_cache: dict[tuple[str, int, int], QPixmap] = {}
STOCK_LABEL = "Stock"


def _make_empty_frame(size: QSize) -> QPixmap:
    """Riquadro neutro per quando non c'è NESSUNA immagine utilizzabile,
    nemmeno di un'altra stampa della stessa carta.

    Solo una cornice discreta che tiene il posto: la versione con le iniziali
    del nome era peggio del buco che doveva coprire."""
    key = (size.width(), size.height())
    cached = _placeholder_cache.get(key)
    if cached is not None:
        return cached
    pm = QPixmap(size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    body = QRectF(0.5, 0.5, size.width() - 1.0, size.height() - 1.0)
    radius = max(2.0, min(size.width(), size.height()) / 12.0)
    pen = QPen(QColor(theme.BORDER))
    pen.setWidthF(1.0)
    pen.setStyle(Qt.PenStyle.DashLine)
    p.setPen(pen)
    p.setBrush(QColor(theme.SURFACE_2))
    p.drawRoundedRect(body, radius, radius)
    p.end()
    _placeholder_cache[key] = pm
    return pm


def stock_pixmap(url: str, source: QPixmap) -> QPixmap:
    """Copia dell'immagine con la scritta "Stock" in diagonale, semitrasparente.

    Serve quando si mostra l'immagine di un'ALTRA stampa della stessa carta
    (rarità diversa): l'arte è quella giusta, la stampa no — e chi guarda deve
    accorgersene senza doverlo indovinare. Cache per (url, larghezza, altezza):
    la stessa immagine di ripiego ricorre su più righe."""
    key = (url, source.width(), source.height())
    cached = _marked_cache.get(key)
    if cached is not None:
        return cached
    pm = QPixmap(source)          # copia: l'originale resta pulito in cache
    w, h = pm.width(), pm.height()
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    font = QFont(theme.FONT_FAMILY)
    font.setBold(True)
    font.setPixelSize(max(7, round(w * 0.26)))
    # allarga/stringe finché la scritta non occupa ~l'80% della diagonale
    diagonal = (w * w + h * h) ** 0.5
    while (QFontMetrics(font).horizontalAdvance(STOCK_LABEL) > diagonal * 0.8
           and font.pixelSize() > 7):
        font.setPixelSize(font.pixelSize() - 1)
    p.setFont(font)
    p.translate(w / 2.0, h / 2.0)
    p.rotate(-38)
    band = QRectF(-w, -font.pixelSize(), 2.0 * w, 2.0 * font.pixelSize())
    # ombra scura sotto + testo chiaro sopra: resta leggibile sia sulle arti
    # scure sia su quelle chiare
    p.setPen(QColor(0, 0, 0, 120))
    p.drawText(band.translated(1.0, 1.0), Qt.AlignmentFlag.AlignCenter, STOCK_LABEL)
    p.setPen(QColor(255, 255, 255, 165))
    p.drawText(band, Qt.AlignmentFlag.AlignCenter, STOCK_LABEL)
    p.end()
    _marked_cache[key] = pm
    return pm


class _ThumbSignals(QObject):
    done = Signal(str, QImage)


# Spaziatura fra i download di IMMAGINI (tutti passano da _ThumbTask: righe
# della watchlist e popup di ricerca). Il CDN di CardTrader sta dietro
# Cloudflare e risponde 403 alle raffiche: con 6 thread che partono insieme
# le miniature "ogni tanto non si trovavano" proprio per questo. Non è un
# limite dell'API, è educazione verso il CDN.
_IMG_INTERVAL = 0.08     # ~12 immagini al secondo: fluido, ma non una raffica
_img_lock = threading.Lock()
_img_next_at = 0.0


def _img_slot() -> None:
    """Prenota lo slot successivo sotto lock e dorme FUORI dal lock, così i
    thread si accodano senza bloccarsi a vicenda."""
    global _img_next_at
    with _img_lock:
        due = max(time.monotonic(), _img_next_at)
        _img_next_at = due + _IMG_INTERVAL
    delay = due - time.monotonic()
    if delay > 0:
        time.sleep(delay)


class _ThumbTask(QRunnable):
    """Scarica E decodifica una miniatura fuori dal thread GUI (QImage già scalato)."""

    def __init__(self, url: str, signals: _ThumbSignals, size: QSize = THUMB) -> None:
        super().__init__()
        self._url = url
        self._signals = signals
        self._size = size

    def run(self) -> None:
        img = QImage()
        try:
            _img_slot()
            resp = SESSION.get(self._url, timeout=10)
            if resp.status_code == 200 and resp.content:
                tmp = QImage()
                if tmp.loadFromData(resp.content):
                    img = tmp.scaled(self._size, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
        except requests.RequestException:
            pass
        self._signals.done.emit(self._url, img)


class ThumbDelegate(QStyledItemDelegate):
    """Disegna miniatura + testo per ogni voce del popup, caricando le immagini
    in modo pigro (solo righe visibili) e asincrono, con cache per URL."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._map: dict[str, str] = {}      # label -> thumb_url
        self._stock: dict[str, str] = {}    # label -> thumb_url di ripiego
        self._meta: dict[str, tuple] = {}   # label -> (testo_sinistra, codice_set)
        self._cache: dict[str, QPixmap] = {}
        self._inflight: set[str] = set()
        self._failed: set[str] = set()      # URL persi: non si ritentano
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(_POOL_THREADS)
        self._sig = _ThumbSignals(self)
        self._sig.done.connect(self._on_thumb)
        self._view = None
        self._alpha: dict[int, float] = {}   # riga -> opacità evidenziazione (0..1)
        self._anims: dict[int, QVariantAnimation] = {}

    def set_view(self, view) -> None:
        self._view = view
        view.setMouseTracking(True)
        view.entered.connect(lambda idx: self._hover(idx.row()))
        view.viewport().installEventFilter(self)  # per rilevare l'uscita del mouse

    # --- hover animato (dissolvenza per riga) ---
    def _hover(self, row: int) -> None:
        for r in set(self._alpha) | ({row} if row >= 0 else set()):
            self._animate_row(r, 1.0 if r == row else 0.0)

    def _animate_row(self, row: int, target: float) -> None:
        if abs(self._alpha.get(row, 0.0) - target) < 1e-3:
            return
        old = self._anims.pop(row, None)
        if old is not None:
            old.stop()
        anim = QVariantAnimation(self)
        anim.setDuration(160)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(self._alpha.get(row, 0.0))
        anim.setEndValue(target)

        def on_val(v, r=row):
            self._alpha[r] = float(v)
            if self._view is not None:
                self._view.viewport().update()

        def on_done(r=row, t=target):
            self._anims.pop(r, None)
            if t == 0.0:
                self._alpha.pop(r, None)

        anim.valueChanged.connect(on_val)
        anim.finished.connect(on_done)
        self._anims[row] = anim
        anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Leave:  # mouse fuori dalla lista → svanisce
            self._hover(-1)
        return False

    def set_cards(self, items: list[tuple]) -> None:
        """items: (label, image_url, testo_sinistra, codice_set,
        nome_set_completo, image_url_di_ripiego)."""
        self._map = {it[0]: _thumb_url(it[1]) for it in items}
        self._meta = {it[0]: (it[2], it[3], it[4]) for it in items}
        self._stock = {it[0]: _thumb_url(it[5] if len(it) > 5 else "") for it in items}

    def sizeHint(self, option, index):
        return QSize(option.rect.width() or 280, ROW_H)

    @staticmethod
    def _pill_rect(rect: QRect, code: str, fm: QFontMetrics) -> QRect:
        cw = fm.horizontalAdvance(code) + 20
        ph = 28
        return QRect(rect.right() - PAD - cw, rect.top() + (rect.height() - ph) // 2, cw, ph)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        painter.setRenderHint(painter.RenderHint.SmoothPixmapTransform, True)
        rect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        alpha = 0.0 if selected else self._alpha.get(index.row(), 0.0)  # opacità/scala hover

        # separatore sottile (fuori dalla trasformazione, solo se riga "a riposo")
        if not selected and alpha < 0.06:
            painter.setPen(_SEPARATOR)
            painter.drawLine(rect.left() + PAD, rect.bottom(), rect.right() - PAD, rect.bottom())

        # La riga si "gonfia" sull'hover (scala centrata sul centro). La scala
        # ORIZZONTALE è ridotta: la riga è larga quanto il viewport e oltre i
        # bordi della finestra non si può disegnare — con 1.06 anche in X la
        # pill del codice veniva TAGLIATA al bordo. Con ~0.018 la crescita
        # resta dentro il margine PAD: si gonfia senza mozzarsi.
        if alpha > 0.0:
            center = rect.center()
            painter.translate(center)
            painter.scale(1.0 + 0.018 * alpha, 1.0 + 0.07 * alpha)
            painter.translate(-center)

        bg_rect = rect.adjusted(7, 5, -7, -5)   # inset maggiore → angoli più arrotondati
        painter.setPen(Qt.PenStyle.NoPen)
        if selected:
            painter.setBrush(_ACCENT)
            painter.drawRoundedRect(bg_rect, 18, 18)
        elif alpha > 0.0:
            c = QColor(_HOVER_BG); c.setAlphaF(alpha)
            painter.setBrush(c)
            painter.drawRoundedRect(bg_rect, 18, 18)
        label = index.data() or ""
        left_text, code, _full = self._meta.get(label, (label, "", ""))

        # miniatura
        ty = rect.top() + (rect.height() - THUMB.height()) // 2
        tx = rect.left() + PAD
        url = self._map.get(label, "")
        pm, marked = self._thumb_for(label, url)
        if pm is not None:
            if marked:
                pm = stock_pixmap(marked, pm)
            painter.drawPixmap(tx + (THUMB.width() - pm.width()) // 2,
                               ty + (THUMB.height() - pm.height()) // 2, pm)
        elif self._pending(label, url):
            painter.fillRect(QRect(tx, ty, THUMB.width(), THUMB.height()), _PLACEHOLDER)
        else:
            painter.drawPixmap(tx, ty, _make_empty_frame(THUMB))

        text_left = tx + THUMB.width() + PAD
        text_right = rect.right() - PAD

        # codice set in un "pill" fissato a destra
        if code:
            font = painter.font(); font.setBold(True); painter.setFont(font)
            pill = self._pill_rect(rect, code, painter.fontMetrics())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 55) if selected else _PILL_BG)
            painter.drawRoundedRect(pill, 9, 9)
            painter.setPen(_ACCENT_INK if selected else _ACCENT)
            painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, code)
            text_right = pill.left() - PAD
            font.setBold(False); painter.setFont(font)

        # testo a sinistra (nome — rarità)
        painter.setPen(_ACCENT_INK if selected else _TEXT)
        text_rect = QRect(text_left, rect.top(), max(0, text_right - text_left), rect.height())
        elided = painter.fontMetrics().elidedText(left_text, Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)
        painter.restore()

    def helpEvent(self, event, view, option, index) -> bool:
        """Tooltip col nome completo del set SOLO passando sul pill del codice."""
        if event.type() == QEvent.Type.ToolTip:
            left, code, full = self._meta.get(index.data() or "", ("", "", ""))
            if code and full:
                font = QFont(view.font()); font.setBold(True)
                pill = self._pill_rect(option.rect, code, QFontMetrics(font))
                if pill.contains(event.pos()):
                    QToolTip.showText(event.globalPos(), full, view)
                    return True
            QToolTip.hideText()
            return True
        return super().helpEvent(event, view, option, index)

    # --- scelta dell'immagine: esatta → ripiego "Stock" → cornice vuota ---
    def _thumb_for(self, label: str, url: str):
        """(pixmap, url_da_marcare) — `url_da_marcare` valorizzato solo se il
        pixmap è di un'ALTRA stampa e va quindi timbrato "Stock"."""
        if url and url not in self._failed:
            pm = self._cache.get(url)
            if pm is not None and not pm.isNull():
                return pm, ""
            self._request(url)
            return None, ""
        # l'esatta manca o è persa: si ripiega sull'altra stampa
        stock = self._stock.get(label, "")
        if stock and stock != url and stock not in self._failed:
            pm = self._cache.get(stock)
            if pm is not None and not pm.isNull():
                return pm, stock
            self._request(stock)
        return None, ""

    def _pending(self, label: str, url: str) -> bool:
        """True se c'è ancora un download in corso/da fare per questa voce:
        distingue "sto caricando" (rettangolo neutro) da "non c'è niente da
        mostrare" (cornice vuota)."""
        stock = self._stock.get(label, "")
        return any(u and u not in self._failed and u not in self._cache
                   for u in (url, stock))

    # --- download miniatura (pigro, limitato, asincrono) ---
    def _request(self, url: str) -> None:
        if (url in self._cache or url in self._inflight or url in self._failed
                or len(self._inflight) >= MAX_INFLIGHT):
            return
        self._inflight.add(url)
        self._pool.start(_ThumbTask(url, self._sig))

    def _on_thumb(self, url: str, image: QImage) -> None:
        self._inflight.discard(url)
        if image.isNull():
            # Ricordo il fallimento: senza questo, ogni ridisegno del popup
            # rilanciava lo stesso download perso — proprio la raffica che fa
            # scattare l'anti-bot di Cloudflare.
            self._failed.add(url)
        else:
            self._cache[url] = QPixmap.fromImage(image)
        if self._view is not None:
            self._view.viewport().update()  # ridisegna le righe visibili
