"""Badge delle rarità disegnati a runtime (QPainter), stile pill.

Come per le bandierine (flags.py): niente asset, niente rete. Ogni rarità ha
l'abbreviazione usata dalla community (C, R, SR, UR, ScR, QCSR, …) e un
colore/gradiente che richiama la foil; il nome completo va nel tooltip.
Le rarità CardTrader hanno molte varianti testuali, quindi il riconoscimento
è per SOTTOSTRINGA in ordine dal più specifico al più generico ("quarter
century secret" prima di "secret", "secret" prima di "rare"). Le sconosciute
ricadono su una pill neutra con le iniziali.

Uso: ``rarity_pixmap("Quarter Century Secret Rare", 18)`` (cache per
(nome, altezza)); ``rarity_abbrev(nome)`` per la sola sigla.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)

from core import theme

BORDER = "#2f3744"   # bordo del tema
INK = "#1a1e26"      # testo scuro (gli sfondi sono tutti chiari/medi)
FALLBACK_BG = ["#8e99a8"]

# (sottostringa da cercare, abbreviazione, colori: 1 = tinta unita, 2+ = gradiente)
# L'ORDINE CONTA: dal più specifico al più generico ("rare" DEVE stare in fondo).
_STYLES = [
    ("quarter century secret", "QCSR", ["#f2d868", "#8be0d0", "#e7a4e0"]),
    ("quarter century",        "QCR",  ["#f2d868", "#8be0d0", "#e7a4e0"]),
    ("prismatic secret",       "PScR", ["#bfe6f7", "#ecd0f2", "#f7ecbf"]),
    ("platinum secret",        "PlScR", ["#e6ebf2", "#aeb8c6"]),
    ("gold secret",            "GdScR", ["#f2d868", "#c9971d"]),
    ("premium gold",           "PGR",  ["#f6dd7a", "#c9971d"]),
    ("starlight",              "StR",  ["#ffb3b8", "#ffd98c", "#a8f0c9", "#a8ccff", "#dcaeff"]),
    ("collector",              "CR",   ["#8ce6d8", "#a8ccff", "#dcaeff"]),
    ("ghost",                  "GhR",  ["#f4f7fb", "#c9d2df"]),
    ("ultimate",               "UtR",  ["#d29a5b", "#96612c"]),
    ("parallel",               "PaR",  ["#b8e0e8", "#89bec9"]),
    ("secret",                 "ScR",  ["#cfaef0", "#9673c9"]),
    ("ultra",                  "UR",   ["#f5cf57", "#dca523"]),
    ("super",                  "SR",   ["#7fb2f9", "#3f7fe0"]),
    ("platinum",               "PlR",  ["#e9edf3", "#bcc5d2"]),
    ("gold",                   "GdR",  ["#f2cf5f", "#cfa22e"]),
    ("starfoil",               "SFR",  ["#9fd8f2", "#6fb2dd"]),
    ("mosaic",                 "MSR",  ["#a4e0a8", "#5fb46a"]),
    ("shatterfoil",            "ShR",  ["#9fb6d8", "#6f8ab2"]),
    ("duel terminal",          "DTR",  ["#c8b69a", "#a08a63"]),
    ("short print",            "SP",   ["#aab4c2"]),
    ("common",                 "C",    ["#aab4c2"]),
    ("rare",                   "R",    ["#cdd6e2", "#9fb0c4"]),
]


def _style(name: str) -> tuple[str, list[str]]:
    low = (name or "").strip().lower()
    for needle, abbrev, colors in _STYLES:
        if needle in low:
            return abbrev, colors
    # sconosciuta: iniziali delle parole (max 4) su pill neutra
    initials = "".join(w[0] for w in low.split()[:4]).upper() or "?"
    return initials, FALLBACK_BG


def rarity_abbrev(name: str) -> str:
    return _style(name)[0]


_cache: dict[tuple[str, int], QPixmap] = {}


def rarity_pixmap(name: str, height: int) -> QPixmap:
    """Pill con l'abbreviazione della rarità, colorata come la sua foil."""
    key = ((name or "").strip().lower(), height)
    cached = _cache.get(key)
    if cached is None:
        cached = _cache[key] = _draw(name, height)
    return cached


def _draw(name: str, h: int) -> QPixmap:
    abbrev, colors = _style(name)
    font = QFont(theme.FONT_FAMILY)
    font.setBold(True)
    font.setPixelSize(max(6, round(h * 0.58)))
    fm = QFontMetrics(font)
    w = max(round(h * 1.7), fm.horizontalAdvance(abbrev) + round(h * 0.9))

    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(0, 0, w, h)
    radius = h / 3.0
    if len(colors) == 1:
        p.setBrush(QColor(colors[0]))
    else:
        grad = QLinearGradient(0, 0, w, 0)
        for i, color in enumerate(colors):
            grad.setColorAt(i / (len(colors) - 1), QColor(color))
        p.setBrush(grad)
    p.setPen(QPen(QColor(BORDER), 1.0))
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    p.setFont(font)
    p.setPen(QColor(INK))
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, abbrev)
    p.end()
    return pm
