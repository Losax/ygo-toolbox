"""Bandierine dei paesi disegnate a runtime (QPainter).

Niente asset né rete: i venditori CardTrader sono in gran parte europei e
quasi tutte quelle bandiere sono strisce o croci semplici. Le forme più
complesse (USA, Regno Unito, …) sono semplificate; per i codici non coperti
si disegna una "pill" neutra col codice paese.

Uso: ``flag_pixmap("IT", 16)`` → QPixmap 24×16 con angoli arrotondati e
bordo del tema (cache per (codice, altezza)).
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from core import theme

BORDER = "#2f3744"       # come i bordi del tema (stacca la bandiera dallo sfondo)
PILL_BG = "#2a313c"      # sfondo della pill di ripiego (SURFACE_2)
PILL_TEXT = "#94a1b2"

# --- disegni per famiglia -------------------------------------------------- #
# tricolori a bande VERTICALI (sinistra → destra)
_V3 = {
    "IT": ("#009246", "#ffffff", "#ce2b37"),
    "FR": ("#0055a4", "#ffffff", "#ef4135"),
    "BE": ("#2d2926", "#fdda24", "#ef3340"),
    "IE": ("#169b62", "#ffffff", "#ff883e"),
    "RO": ("#002b7f", "#fcd116", "#ce1126"),
    "MX": ("#006847", "#ffffff", "#ce1126"),
}
# tricolori a bande ORIZZONTALI (alto → basso); alcune semplificate (senza stemma)
_H3 = {
    "DE": ("#1b1b1b", "#dd0000", "#ffce00"),
    "NL": ("#ae1c28", "#ffffff", "#21468b"),
    "AT": ("#ed2939", "#ffffff", "#ed2939"),
    "HU": ("#cd2a3e", "#ffffff", "#436f4d"),
    "LU": ("#ed2939", "#ffffff", "#00a1de"),
    "RU": ("#ffffff", "#0039a6", "#d52b1e"),
    "BG": ("#ffffff", "#00966e", "#d62612"),
    "EE": ("#0072ce", "#1b1b1b", "#ffffff"),
    "LT": ("#fdb913", "#006a44", "#c1272d"),
    "LV": ("#9e3039", "#ffffff", "#9e3039"),
    "HR": ("#ff0000", "#ffffff", "#171796"),
    "SI": ("#ffffff", "#005da4", "#ed1c24"),
    "SK": ("#ffffff", "#0b4ea2", "#ee1c25"),
}
# bicolori orizzontali
_H2 = {
    "PL": ("#ffffff", "#dc143c"),
    "UA": ("#005bbb", "#ffd500"),
    "MC": ("#ce1126", "#ffffff"),
    "ID": ("#ce1126", "#ffffff"),
}
# croci scandinave: (sfondo, croce esterna, croce interna o None)
_CROSS = {
    "DK": ("#c8102e", "#ffffff", None),
    "SE": ("#006aa7", "#fecc00", None),
    "FI": ("#ffffff", "#002f6c", None),
    "NO": ("#ba0c2f", "#ffffff", "#00205b"),
    "IS": ("#02529c", "#ffffff", "#dc1e35"),
}

# nomi in italiano per i tooltip (fallback: il codice stesso)
COUNTRY_NAMES = {
    "IT": "Italia", "US": "Stati Uniti", "GB": "Regno Unito", "UK": "Regno Unito",
    "DE": "Germania", "FR": "Francia", "ES": "Spagna", "PT": "Portogallo",
    "NL": "Paesi Bassi", "BE": "Belgio", "AT": "Austria", "CH": "Svizzera",
    "IE": "Irlanda", "PL": "Polonia", "CZ": "Cechia", "SK": "Slovacchia",
    "HU": "Ungheria", "RO": "Romania", "GR": "Grecia", "SE": "Svezia",
    "NO": "Norvegia", "DK": "Danimarca", "FI": "Finlandia", "IS": "Islanda",
    "JP": "Giappone", "CA": "Canada", "CN": "Cina", "BR": "Brasile",
    "UA": "Ucraina", "BG": "Bulgaria", "HR": "Croazia", "SI": "Slovenia",
    "EE": "Estonia", "LT": "Lituania", "LV": "Lettonia", "LU": "Lussemburgo",
    "MC": "Monaco", "RU": "Russia", "TR": "Turchia", "MX": "Messico",
    "ID": "Indonesia",
}


def country_name(code: str) -> str:
    code = (code or "").upper()
    return COUNTRY_NAMES.get(code, code)


_cache: dict[tuple[str, int], QPixmap] = {}


def flag_pixmap(code: str, height: int) -> QPixmap:
    """Bandierina (3:2, angoli arrotondati, bordo tema) per il codice paese."""
    code = (code or "").upper()
    key = (code, height)
    cached = _cache.get(key)
    if cached is None:
        cached = _cache[key] = _draw_flag(code, height)
    return cached


# --------------------------------------------------------------------------- #
def _draw_flag(code: str, h: int) -> QPixmap:
    w = h if code == "CH" else round(h * 1.5)  # svizzera: bandiera quadrata
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(0, 0, w, h)
    radius = max(2.0, h / 6.0)
    clip = QPainterPath()
    clip.addRoundedRect(rect, radius, radius)
    p.setClipPath(clip)
    p.setPen(Qt.PenStyle.NoPen)
    _paint_design(p, code, float(w), float(h))
    # bordo sottile sopra il disegno (leggibile su sfondo scuro)
    p.setClipping(False)
    p.setPen(QPen(QColor(BORDER), 1.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    p.end()
    return pm


def _paint_design(p: QPainter, code: str, w: float, h: float) -> None:
    def fill(color: str, x: float, y: float, fw: float, fh: float) -> None:
        p.fillRect(QRectF(x, y, fw, fh), QColor(color))

    if code in _V3:
        a, b, c = _V3[code]
        fill(a, 0, 0, w / 3, h)
        fill(b, w / 3, 0, w / 3, h)
        fill(c, 2 * w / 3, 0, w / 3 + 1, h)
    elif code in _H3:
        a, b, c = _H3[code]
        fill(a, 0, 0, w, h / 3)
        fill(b, 0, h / 3, w, h / 3)
        fill(c, 0, 2 * h / 3, w, h / 3 + 1)
    elif code in _H2:
        a, b = _H2[code]
        fill(a, 0, 0, w, h / 2)
        fill(b, 0, h / 2, w, h / 2)
    elif code in _CROSS:
        bg, outer, inner = _CROSS[code]
        fill(bg, 0, 0, w, h)
        bw = h * 0.28
        cx = w * 0.38          # croce spostata verso l'asta, come da tradizione
        fill(outer, cx - bw / 2, 0, bw, h)
        fill(outer, 0, (h - bw) / 2, w, bw)
        if inner:
            iw = bw * 0.5
            fill(inner, cx - iw / 2, 0, iw, h)
            fill(inner, 0, (h - iw) / 2, w, iw)
    elif code in ("GB", "UK"):  # Union Jack semplificata
        fill("#012169", 0, 0, w, h)
        white = QPen(QColor("#ffffff"), h * 0.30)
        red = QPen(QColor("#c8102e"), h * 0.12)
        for pen in (white, red):
            p.setPen(pen)
            p.drawLine(QPointF(0, 0), QPointF(w, h))
            p.drawLine(QPointF(0, h), QPointF(w, 0))
        p.setPen(QPen(QColor("#ffffff"), h * 0.38))
        p.drawLine(QPointF(w / 2, 0), QPointF(w / 2, h))
        p.drawLine(QPointF(0, h / 2), QPointF(w, h / 2))
        p.setPen(QPen(QColor("#c8102e"), h * 0.20))
        p.drawLine(QPointF(w / 2, 0), QPointF(w / 2, h))
        p.drawLine(QPointF(0, h / 2), QPointF(w, h / 2))
        p.setPen(Qt.PenStyle.NoPen)
    elif code == "US":          # strisce + cantone blu (senza stelle: troppo piccole)
        fill("#ffffff", 0, 0, w, h)
        stripe = h / 13
        for i in range(0, 13, 2):
            fill("#b22234", 0, i * stripe, w, stripe)
        fill("#3c3b6e", 0, 0, w * 0.42, stripe * 7)
    elif code == "JP":
        fill("#ffffff", 0, 0, w, h)
        p.setBrush(QColor("#bc002d"))
        p.drawEllipse(QPointF(w / 2, h / 2), h * 0.3, h * 0.3)
    elif code == "ES":
        fill("#aa151b", 0, 0, w, h / 4)
        fill("#f1bf00", 0, h / 4, w, h / 2)
        fill("#aa151b", 0, 3 * h / 4, w, h / 4 + 1)
    elif code == "PT":
        fill("#046a38", 0, 0, w * 0.4, h)
        fill("#da291c", w * 0.4, 0, w * 0.6 + 1, h)
        p.setBrush(QColor("#ffe900"))
        p.drawEllipse(QPointF(w * 0.4, h / 2), h * 0.18, h * 0.18)
    elif code == "CH":          # quadrata: croce bianca su rosso
        fill("#da291c", 0, 0, w, h)
        arm = h * 0.2
        fill("#ffffff", w / 2 - arm / 2, h * 0.2, arm, h * 0.6)
        fill("#ffffff", w * 0.2, h / 2 - arm / 2, w * 0.6, arm)
    elif code == "CZ":
        fill("#ffffff", 0, 0, w, h / 2)
        fill("#d7141a", 0, h / 2, w, h / 2)
        p.setBrush(QColor("#11457e"))
        p.drawPolygon(QPolygonF([QPointF(0, 0), QPointF(w * 0.5, h / 2), QPointF(0, h)]))
    elif code == "GR":
        stripe = h / 9
        for i in range(9):
            fill("#0d5eaf" if i % 2 == 0 else "#ffffff", 0, i * stripe, w, stripe + 1)
        cw, ch = w * 0.37, stripe * 5
        fill("#0d5eaf", 0, 0, cw, ch)
        arm = stripe * 0.9
        fill("#ffffff", cw / 2 - arm / 2, 0, arm, ch)
        fill("#ffffff", 0, ch / 2 - arm / 2, cw, arm)
    elif code == "CA":          # pali rossi + "foglia" stilizzata (rombo)
        fill("#ffffff", 0, 0, w, h)
        fill("#d80621", 0, 0, w / 4, h)
        fill("#d80621", 3 * w / 4, 0, w / 4 + 1, h)
        p.setBrush(QColor("#d80621"))
        r = h * 0.28
        p.drawPolygon(QPolygonF([
            QPointF(w / 2, h / 2 - r), QPointF(w / 2 + r * 0.8, h / 2),
            QPointF(w / 2, h / 2 + r), QPointF(w / 2 - r * 0.8, h / 2),
        ]))
    elif code == "CN":
        fill("#ee1c25", 0, 0, w, h)
        _star(p, "#ffde00", w * 0.2, h * 0.32, h * 0.2)
    elif code == "BR":
        fill("#009c3b", 0, 0, w, h)
        p.setBrush(QColor("#ffdf00"))
        p.drawPolygon(QPolygonF([
            QPointF(w / 2, h * 0.08), QPointF(w * 0.92, h / 2),
            QPointF(w / 2, h * 0.92), QPointF(w * 0.08, h / 2),
        ]))
        p.setBrush(QColor("#002776"))
        p.drawEllipse(QPointF(w / 2, h / 2), h * 0.22, h * 0.22)
    elif code == "TR":
        fill("#e30a17", 0, 0, w, h)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(w * 0.38, h / 2), h * 0.26, h * 0.26)
        p.setBrush(QColor("#e30a17"))
        p.drawEllipse(QPointF(w * 0.44, h / 2), h * 0.21, h * 0.21)
        _star(p, "#ffffff", w * 0.6, h / 2, h * 0.13)
    else:                       # ripiego: pill neutra col codice paese
        fill(PILL_BG, 0, 0, w, h)
        font = QFont(theme.FONT_FAMILY)
        font.setBold(True)
        font.setPixelSize(max(6, round(h * 0.55)))
        p.setFont(font)
        p.setPen(QColor(PILL_TEXT))
        p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, code[:3] or "?")
        p.setPen(Qt.PenStyle.NoPen)


def _star(p: QPainter, color: str, cx: float, cy: float, r: float) -> None:
    """Stella a 5 punte piena, centrata in (cx, cy)."""
    points = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        radius = r if i % 2 == 0 else r * 0.4
        points.append(QPointF(cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(QPolygonF(points))
