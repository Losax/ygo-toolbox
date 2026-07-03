"""Tema visivo dell'applicazione (scuro, accento teal) — versione "liscia".

Strategia: stile Qt "Fusion" + palette scura (widget nativi leggibili) e sopra
un QSS curato: superfici con profondità (card più chiare dello sfondo), angoli
morbidi, più aria, stati hover/pressed, tabella con hover di riga.

Le ombre morbide e le animazioni NON stanno qui (QSS non le fa): vedi
`core/anim.py` (drop shadow, pulse, dissolvenze) applicato dai widget.

I colori sono definiti UNA volta qui: il QSS li usa come letterali, il codice
Python importa le costanti.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QImage,
    QPainter,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import QApplication

FONT_FAMILY = "Inter"   # incorporato in assets/fonts (fallback: Segoe UI)


def _resource_path(rel: str) -> str:
    """Risorsa sia in sviluppo sia nell'exe PyInstaller (theme.py sta in core/)."""
    base = getattr(sys, "_MEIPASS",
                   os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, rel)


def _load_fonts() -> None:
    """Registra i font incorporati (Inter); se mancano si resta su Segoe UI."""
    fonts_dir = _resource_path(os.path.join("assets", "fonts"))
    if not os.path.isdir(fonts_dir):
        return
    for name in os.listdir(fonts_dir):
        if name.lower().endswith((".ttf", ".otf")):
            QFontDatabase.addApplicationFont(os.path.join(fonts_dir, name))

# --- palette ---
BG = "#13161c"           # sfondo finestra (scuro: fa risaltare le card)
SURFACE = "#1f242d"      # card / pannelli (più chiari dello sfondo = elevazione)
SURFACE_2 = "#2a313c"    # input / bottoni / header tabella
SURFACE_3 = "#333b48"    # hover superfici
SIDEBAR = "#10131a"
BORDER = "#2f3744"
TEXT = "#eef1f6"
TEXT_MUTED = "#94a1b2"
TEXT_DISABLED = "#586273"
ACCENT = "#1ac3b2"
ACCENT_HOVER = "#27d6c4"
ACCENT_PRESSED = "#13a596"
ACCENT_INK = "#042521"
POSITIVE = "#34d399"
NEGATIVE = "#fb7185"
WARN = "#fbbf24"
SHADOW = "#000000"

_CHEVRON_DIR = Path.home() / ".ygo_toolbox" / "cache"


def _chevron_url(px: int, up: bool = False) -> str:
    """PNG della freccetta ▾/▴ (menu a tendina e spinbox), generato al volo e
    cacheato su disco: il QSS accetta solo url() per ::down-arrow/::up-arrow
    (quelle di default di Fusion sono squadrate e quasi invisibili sul tema
    scuro, e nei QSpinBox sbordano dal bordo arrotondato)."""
    if QGuiApplication.instance() is None:
        return ""   # chiamata prima di QApplication: si resta sulla default
    path = _CHEVRON_DIR / f"chevron_{'up_' if up else ''}{px}.png"
    if not path.exists():
        try:
            _CHEVRON_DIR.mkdir(parents=True, exist_ok=True)
            w, h = px, max(6, round(px * 0.62))
            img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(0)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(TEXT_MUTED))
            pen.setWidthF(max(1.6, px / 7.0))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            m = pen.widthF() * 0.8
            if up:
                points = [QPointF(m, h - m), QPointF(w / 2, m), QPointF(w - m, h - m)]
            else:
                points = [QPointF(m, m), QPointF(w / 2, h - m), QPointF(w - m, m)]
            p.drawPolyline(points)
            p.end()
            img.save(str(path))
        except OSError:
            return ""
    return path.as_posix()


def build_qss(scale: float = 1.0) -> str:
    """Genera il QSS con misure (font, padding, raggi, ecc.) scalate.

    Solo le grandezze in pixel vengono scalate; i colori e le larghezze dei
    bordi (1px) restano invariati. `scale` arriva dalla larghezza della finestra
    (vedi `MainWindow._update_ui_scale`)."""
    def s(v: float) -> int:
        return max(1, round(v * scale))

    arrow = _chevron_url(s(12))
    arrow_css = f'image: url("{arrow}");' if arrow else ""
    spin_dn = _chevron_url(s(11))
    spin_up = _chevron_url(s(11), up=True)
    spin_dn_css = f'image: url("{spin_dn}");' if spin_dn else ""
    spin_up_css = f'image: url("{spin_up}");' if spin_up else ""

    return f"""
* {{ font-family: "Inter", "Segoe UI", sans-serif; font-size: {s(13)}px; }}
QMainWindow, QWidget {{ background: #13161c; color: #eef1f6; }}
/* i testi non dipingono MAI uno sfondo proprio: si appoggiano alla card
   che li ospita (senza questa regola comparirebbero riquadri scuri) */
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
QToolTip {{
    background: #2a313c; color: #eef1f6; border: 1px solid #2f3744;
    border-radius: {s(8)}px; padding: {s(5)}px {s(9)}px;
}}

/* ---- menu laterale ---- */
QListWidget#sidebar {{
    background: #10131a;
    border: none;
    border-right: 1px solid #2f3744;
    outline: 0;
    padding: {s(12)}px {s(8)}px;
}}
QListWidget#sidebar::item {{
    padding: {s(12)}px {s(14)}px;
    margin: {s(3)}px {s(4)}px;
    border-radius: {s(12)}px;
    color: #94a1b2;
}}
QListWidget#sidebar::item:hover {{ background: #1f242d; color: #eef1f6; }}
QListWidget#sidebar::item:selected {{ background: #2a313c; color: #ffffff; }}

/* ---- card / pannelli ---- */
QFrame#card {{
    background: #1f242d;
    border: 1px solid #2f3744;
    border-radius: {s(18)}px;
}}

/* ---- dialoghi "in-app" senza cornice (CardDialog) ---- */
QFrame#popover {{
    background: #232935;
    border: 1px solid #3a4452;
    border-radius: {s(16)}px;
}}
QLabel#popoverTitle {{ font-size: {s(15)}px; font-weight: 700; color: #ffffff; }}

/* ---- testi speciali ---- */
QLabel#title {{ font-size: {s(22)}px; font-weight: 800; color: #ffffff; }}
QLabel#subtitle {{ font-size: {s(12)}px; color: #94a1b2; }}
QLabel#status {{ color: #94a1b2; }}
QLabel#chip {{
    background: #2a313c; border: 1px solid #2f3744; border-radius: {s(13)}px;
    padding: {s(5)}px {s(12)}px; color: #94a1b2; font-size: {s(12)}px;
}}
QLabel#chip[state="ok"]   {{ color: #1ac3b2; border-color: rgba(26,195,178,0.55); }}
QLabel#chip[state="warn"] {{ color: #fbbf24; border-color: rgba(251,191,36,0.45); }}

/* ---- input ---- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: #2a313c;
    border: 1px solid #2f3744;
    border-radius: {s(12)}px;
    padding: {s(8)}px {s(12)}px;
    color: #eef1f6;
    selection-background-color: #1ac3b2;
    selection-color: #042521;
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: #3f4858; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid #1ac3b2; }}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    width: {s(30)}px; border: none;
}}
QComboBox::down-arrow {{ {arrow_css} }}
/* ---- spinbox: pulsantini +/− con chevron (i nativi di Fusion sono
   minuscoli e sbordano dal bordo arrotondato) ---- */
QSpinBox, QDoubleSpinBox {{ padding-right: {s(32)}px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right;
    width: {s(26)}px; border: none; background: transparent;
    margin: {s(3)}px {s(4)}px 0 0; border-radius: {s(6)}px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: {s(26)}px; border: none; background: transparent;
    margin: 0 {s(4)}px {s(3)}px 0; border-radius: {s(6)}px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: #333b48; }}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{ background: #3f4858; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ {spin_up_css} }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ {spin_dn_css} }}

/* il CONTENITORE del menu (finestra popup privata di Qt) deve sparire:
   senza questo, dietro gli angoli arrotondati della lista spuntano
   fasce squadrate sopra e sotto le voci */
QComboBoxPrivateContainer {{ background: transparent; border: none; }}
QComboBox QAbstractItemView {{
    background: #2a313c; border: 1px solid #3a4452; border-radius: {s(12)}px;
    selection-background-color: #1ac3b2; selection-color: #042521; outline: 0;
    padding: {s(6)}px;
}}
QComboBox QAbstractItemView::item {{
    padding: {s(6)}px {s(8)}px; border-radius: {s(7)}px;
}}

/* ---- checkbox ---- */
QCheckBox {{ spacing: {s(8)}px; }}
QCheckBox::indicator {{
    width: {s(16)}px; height: {s(16)}px; border-radius: {s(5)}px;
    border: 1px solid #4a5568; background: #1b2027;
}}
QCheckBox::indicator:hover {{ border-color: #1ac3b2; }}
QCheckBox::indicator:checked {{ background: #1ac3b2; border-color: #1ac3b2; }}
QCheckBox::indicator:checked:disabled {{ background: #1d4f49; border-color: #1d4f49; }}
QCheckBox::indicator:disabled {{ border-color: #2f3744; }}

/* ---- bottoni ---- */
QPushButton {{
    background: #2a313c;
    border: 1px solid #2f3744;
    border-radius: {s(12)}px;
    padding: {s(8)}px {s(16)}px;
    color: #eef1f6;
}}
QPushButton:hover {{ background: #333b48; border-color: #3f4858; }}
QPushButton:pressed {{ background: #252b35; }}
QPushButton:checked {{ background: #1ac3b2; border-color: #1ac3b2; color: #042521; font-weight: 700; }}
QPushButton:disabled {{ color: #586273; background: #1b2027; border-color: #252b35; }}

QPushButton#primary {{
    background: #1ac3b2; border: 1px solid #1ac3b2; color: #042521; font-weight: 700;
}}
QPushButton#primary:hover {{ background: #27d6c4; border-color: #27d6c4; }}
QPushButton#primary:pressed {{ background: #13a596; border-color: #13a596; }}
QPushButton#primary:disabled {{ background: #1d4f49; border-color: #1d4f49; color: #6f8e88; }}

QPushButton#ghost {{
    background: transparent; border: none; color: #94a1b2;
    padding: {s(6)}px {s(10)}px; border-radius: {s(10)}px;
}}
QPushButton#ghost:hover {{ background: rgba(251,113,133,0.16); color: #fb7185; }}

/* ---- tabella ---- */
QTableWidget {{
    background: #1f242d;
    alternate-background-color: #242a35;
    border: 1px solid #2f3744;
    border-radius: {s(18)}px;
    gridline-color: transparent;
    selection-background-color: rgba(26,195,178,0.16);
    selection-color: #eef1f6;
    outline: 0;
}}
QTableWidget::item {{ padding: {s(8)}px {s(10)}px; border-bottom: 1px solid #39424f; }}
QTableWidget::item:hover {{ background: #2b3340; }}
QHeaderView::section {{
    background: #1f242d; color: #94a1b2;
    padding: {s(10)}px {s(5)}px; border: none; border-bottom: 1px solid #2f3744;
    font-weight: 700;
}}
QTableCornerButton::section {{ background: #1f242d; border: none; }}

/* ---- barra di avanzamento (stato "occupato") ---- */
QProgressBar {{
    background: #2a313c; border: none; border-radius: {s(4)}px; max-height: {s(6)}px; min-height: {s(6)}px;
    text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: #1ac3b2; border-radius: {s(4)}px; }}

/* ---- riquadro anteprima immagine ---- */
QLabel#preview {{
    background: #171b22;
    border: 1px solid #2f3744;
    border-radius: {s(16)}px;
    color: #94a1b2;
}}

/* ---- popup della ricerca live ---- */
QListView#searchPopup {{
    background: #20262f;
    border: 1px solid #2f3744;
    border-radius: {s(14)}px;
    padding: {s(6)}px;
    outline: 0;
    color: #eef1f6;
}}

/* ---- scrollbar ---- */
QScrollBar:vertical {{ background: transparent; width: {s(12)}px; margin: {s(4)}px {s(2)}px; }}
QScrollBar::handle:vertical {{ background: #333b48; border-radius: {s(6)}px; min-height: {s(32)}px; }}
QScrollBar::handle:vertical:hover {{ background: #44506a; }}
QScrollBar:horizontal {{ background: transparent; height: {s(12)}px; margin: {s(2)}px {s(4)}px; }}
QScrollBar::handle:horizontal {{ background: #333b48; border-radius: {s(6)}px; min-width: {s(32)}px; }}
QScrollBar::handle:horizontal:hover {{ background: #44506a; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""



def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")

    # Font Inter incorporato + hinting leggero: testo più morbido e uniforme
    # (l'hinting pieno di Windows "spigolizza" le lettere ai corpi piccoli).
    _load_fonts()
    base_font = QFont(FONT_FAMILY, 9)
    base_font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(base_font)

    pal = QPalette()
    R = QPalette.ColorRole
    G = QPalette.ColorGroup
    pal.setColor(R.Window, QColor(BG))
    pal.setColor(R.WindowText, QColor(TEXT))
    pal.setColor(R.Base, QColor(SURFACE))
    pal.setColor(R.AlternateBase, QColor(SURFACE_2))
    pal.setColor(R.Text, QColor(TEXT))
    pal.setColor(R.Button, QColor(SURFACE_2))
    pal.setColor(R.ButtonText, QColor(TEXT))
    pal.setColor(R.ToolTipBase, QColor(SURFACE_2))
    pal.setColor(R.ToolTipText, QColor(TEXT))
    pal.setColor(R.PlaceholderText, QColor(TEXT_MUTED))
    pal.setColor(R.Highlight, QColor(ACCENT))
    pal.setColor(R.HighlightedText, QColor(ACCENT_INK))
    pal.setColor(G.Disabled, R.Text, QColor(TEXT_DISABLED))
    pal.setColor(G.Disabled, R.ButtonText, QColor(TEXT_DISABLED))
    pal.setColor(G.Disabled, R.WindowText, QColor(TEXT_DISABLED))
    app.setPalette(pal)

    app.setStyleSheet(build_qss(1.0))


def apply_scale(app: QApplication, scale: float) -> None:
    """Ri-applica il QSS con le misure scalate (font/padding/raggi/…).

    Chiamata dalla finestra principale quando cambia la larghezza: gli elementi
    stilizzati via QSS (titolo, chip, bottoni, input, tabella, sidebar) seguono
    la dimensione della finestra."""
    app.setStyleSheet(build_qss(scale))
