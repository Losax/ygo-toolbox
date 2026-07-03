"""Ricerca live con miniatura su ogni voce — versione veloce.

Il filtraggio del QCompleter resta su un QStringListModel (C++): scansionare
47k stringhe a ogni tasto in C++ è istantaneo. Le miniature NON passano dal
modello (lo renderebbe lento, perché il completer chiamerebbe data() in Python
47k volte per tasto): le disegna un ItemDelegate, che le scarica/decodifica
fuori dalla GUI solo per le righe effettivamente visibili.
"""
from __future__ import annotations

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
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QToolTip

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


class _ThumbSignals(QObject):
    done = Signal(str, QImage)


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
        self._meta: dict[str, tuple] = {}   # label -> (testo_sinistra, codice_set)
        self._cache: dict[str, QPixmap] = {}
        self._inflight: set[str] = set()
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

    def set_cards(self, items: list[tuple[str, str, str, str, str]]) -> None:
        """items: (label, image_url, testo_sinistra, codice_set, nome_set_completo)."""
        self._map = {it[0]: _thumb_url(it[1]) for it in items}
        self._meta = {it[0]: (it[2], it[3], it[4]) for it in items}

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
        pm = self._cache.get(url)
        if pm is not None and not pm.isNull():
            painter.drawPixmap(tx + (THUMB.width() - pm.width()) // 2,
                               ty + (THUMB.height() - pm.height()) // 2, pm)
        else:
            painter.fillRect(QRect(tx, ty, THUMB.width(), THUMB.height()), _PLACEHOLDER)
            if url:
                self._request(url)

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

    # --- download miniatura (pigro, limitato, asincrono) ---
    def _request(self, url: str) -> None:
        if url in self._cache or url in self._inflight or len(self._inflight) >= MAX_INFLIGHT:
            return
        self._inflight.add(url)
        self._pool.start(_ThumbTask(url, self._sig))

    def _on_thumb(self, url: str, image: QImage) -> None:
        self._inflight.discard(url)
        if not image.isNull():
            self._cache[url] = QPixmap.fromImage(image)
        if self._view is not None:
            self._view.viewport().update()  # ridisegna le righe visibili
