"""Animazioni ed effetti riutilizzabili per un feel fluido.

- fade_in: dissolvenza in entrata di un widget;
- drop_shadow: ombra morbida (elevazione "card");
- pulse_item: lampeggio del colore di una cella di tabella (es. prezzo cambiato).

Nota: un QWidget può avere UN SOLO QGraphicsEffect. Quindi un widget con
drop_shadow NON va anche dissolto con fade_in (si escluderebbero a vicenda).
"""
from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QWidget


# Interruttore GLOBALE delle animazioni (Opzioni → "Animazioni dell'interfaccia"):
# con False gli helper saltano direttamente allo stato finale. Le animazioni
# custom dei moduli devono controllare is_enabled() da sole.
ENABLED = True


def set_enabled(enabled: bool) -> None:
    global ENABLED
    ENABLED = bool(enabled)


def is_enabled() -> bool:
    return ENABLED


def fade_in(widget: QWidget, duration: int = 170) -> QPropertyAnimation | None:
    """Dissolvenza in entrata del widget (0 → 1 di opacità).

    L'effetto grafico viene rimosso a fine animazione, così il widget torna
    al rendering normale (e resta pienamente interattivo)."""
    if not ENABLED:
        widget.setGraphicsEffect(None)
        return None
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    # Rimozione differita per non distruggere l'effetto dentro il suo stesso slot.
    anim.finished.connect(lambda: QTimer.singleShot(0, lambda: widget.setGraphicsEffect(None)))
    anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return anim


_FULL = 16_777_215  # QWIDGETSIZE_MAX


def animate_collapse(widget: QWidget, collapse: bool, duration: int = 220):
    """Collassa/espande un widget animandone l'altezza massima (fisarmonica).

    collapse=True → altezza attuale → 0, poi nasconde.
    collapse=False → mostra, 0 → altezza naturale."""
    if not ENABLED:
        widget.setMaximumHeight(_FULL)
        widget.setVisible(not collapse)
        return None
    widget.setMaximumHeight(_FULL)
    target = widget.sizeHint().height()
    anim = QPropertyAnimation(widget, b"maximumHeight", widget)
    anim.setDuration(duration)
    anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
    if collapse:
        anim.setStartValue(widget.height())
        anim.setEndValue(0)

        def _done() -> None:
            widget.setVisible(False)
            widget.setMaximumHeight(_FULL)

        anim.finished.connect(_done)
    else:
        widget.setVisible(True)
        widget.setMaximumHeight(0)
        anim.setStartValue(0)
        anim.setEndValue(max(target, 1))
        anim.finished.connect(lambda: widget.setMaximumHeight(_FULL))
    anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return anim


def drop_shadow(widget: QWidget, blur: int = 30, dy: int = 8, alpha: int = 150) -> QGraphicsDropShadowEffect:
    """Applica un'ombra morbida al widget (effetto 'card sollevata')."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setXOffset(0)
    effect.setYOffset(dy)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)
    return effect


class _HoverShadow(QObject):
    """Anima l'ombra di un widget all'entrata/uscita del mouse.

    Riusa l'eventuale ombra già presente (es. card già 'sollevata') come stato a
    riposo. Anima blurRadius + colore verso lo stato 'hover' e ritorno."""

    def __init__(self, widget: QWidget, base_blur: float, hover_blur: float,
                 base_color: QColor, hover_color: QColor, dy: int, duration: int = 170) -> None:
        super().__init__(widget)
        effect = widget.graphicsEffect()
        if not isinstance(effect, QGraphicsDropShadowEffect):
            effect = QGraphicsDropShadowEffect(widget)
            widget.setGraphicsEffect(effect)
        effect.setXOffset(0)
        effect.setYOffset(dy)
        effect.setBlurRadius(base_blur)
        effect.setColor(base_color)
        self._effect = effect
        self._base = (base_blur, base_color)
        self._hover = (hover_blur, hover_color)
        self._group = QParallelAnimationGroup(self)
        self._blur = QPropertyAnimation(effect, b"blurRadius", self)
        self._col = QPropertyAnimation(effect, b"color", self)
        for a in (self._blur, self._col):
            a.setDuration(duration)
            a.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._group.addAnimation(a)
        widget.installEventFilter(self)

    def _animate_to(self, blur: float, color: QColor) -> None:
        if not ENABLED:   # niente animazione: stato finale immediato
            self._group.stop()
            self._effect.setBlurRadius(float(blur))
            self._effect.setColor(color)
            return
        self._group.stop()
        self._blur.setStartValue(self._effect.blurRadius())
        self._blur.setEndValue(float(blur))
        self._col.setStartValue(self._effect.color())
        self._col.setEndValue(color)
        self._group.start()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Enter:
            self._animate_to(*self._hover)
        elif event.type() == QEvent.Type.Leave:
            self._animate_to(*self._base)
        return False


def hover_glow(widget: QWidget, accent: str = "#1ac3b2", base_blur: int = 6,
               hover_blur: int = 26, dy: int = 3) -> _HoverShadow:
    """Glow teal morbido che compare al passaggio del mouse (per i bottoni)."""
    base = QColor(accent); base.setAlpha(0)        # invisibile a riposo
    hover = QColor(accent); hover.setAlpha(190)
    return _HoverShadow(widget, base_blur, hover_blur, base, hover, dy)


def hover_lift(widget: QWidget, base_blur: int = 30, hover_blur: int = 46,
               dy: int = 8, alpha: int = 110) -> _HoverShadow:
    """Sollevamento: l'ombra (scura) si approfondisce al passaggio del mouse (per le card)."""
    base = QColor(0, 0, 0, alpha)
    hover = QColor(0, 0, 0, min(alpha + 60, 210))
    return _HoverShadow(widget, base_blur, hover_blur, base, hover, dy)


def pulse_item(item, color: str, owner: QObject, duration: int = 750) -> QVariantAnimation:
    """Fa 'lampeggiare' lo sfondo di una cella di tabella e poi lo dissolve.

    Usato quando un prezzo cambia: la cella si accende del colore della
    variazione (verde/rosso) e svanisce dolcemente.

    ATTENZIONE: la cella può venire DISTRUTTA a metà animazione (un re-render
    della tabella ricrea gli item, es. massimizzando la finestra): toccarla
    solleverebbe RuntimeError dentro uno slot Qt — nell'exe windowed (senza
    stderr) PySide ABORTISCE il processo. Quindi ogni accesso è protetto e
    l'animazione si ferma da sola se l'item non esiste più."""
    if not ENABLED:
        return None
    start = QColor(color); start.setAlpha(160)
    end = QColor(color); end.setAlpha(0)
    anim = QVariantAnimation(owner)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setDuration(duration)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _set(c) -> None:
        try:
            item.setBackground(QBrush(c))
        except RuntimeError:      # item eliminato da un re-render: stop
            anim.stop()

    anim.valueChanged.connect(_set)
    anim.finished.connect(lambda: _set(QColor(0, 0, 0, 0)))
    anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return anim
