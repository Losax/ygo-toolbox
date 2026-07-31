"""Badge "a pillola" condivisi da tutti i moduli.

Stavano dentro il market_watch, ma il codice set e la rarità si mostrano
ovunque si parli di una stampa — nel market_watch e nel Database — e i moduli
**non si importano fra loro** (si parlano solo tramite `AppContext`). Il posto
giusto per un vocabolario visivo comune è il core, accanto a `theme` e `anim`.

La rarità sta in `core/rarity.py` (ha una sua tabella di sigle e colori).
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap

from core import theme


def pill(text: str, height: int, ink: QColor, bg: QColor) -> QPixmap:
    """Pillola generica: stessa forma e stesso font di tutte le altre."""
    font = QFont(theme.FONT_FAMILY)
    font.setBold(True)
    font.setPixelSize(max(6, round(height * 0.58)))
    metrics = QFontMetrics(font)
    width = max(round(height * 1.6),
                metrics.horizontalAdvance(text) + round(height * 0.9))
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(bg)
    painter.setPen(Qt.PenStyle.NoPen)
    radius = height / 3.0
    painter.drawRoundedRect(QRectF(0, 0, width, height), radius, radius)
    painter.setFont(font)
    painter.setPen(ink)
    painter.drawText(QRectF(0, 0, width, height),
                     Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return pixmap


_set_cache: dict[tuple[str, int], QPixmap] = {}


def set_pill(code: str, height: int) -> QPixmap:
    """Pillola del codice set: fondo scuro e sigla teal in grassetto.
    Cache per (codice, altezza) — la stessa sigla ricompare su molte righe."""
    key = (code, height)
    cached = _set_cache.get(key)
    if cached is None:
        cached = _set_cache[key] = pill(code, height, QColor(theme.ACCENT),
                                        QColor(theme.BORDER))
    return cached
