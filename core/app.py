"""Finestra principale.

Si occupa di:
- creare il contesto condiviso (storage + notifier);
- scoprire i moduli e mostrarne uno per voce nel menu laterale;
- gestire la chiusura pulita (stop dei moduli, chiusura DB).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QWidget,
)

from core import anim, theme
from core.context import AppContext, Notifier
from core.module_loader import discover_modules
from core.storage import Storage
from core.version import APP_VERSION

APP_DIR = Path.home() / ".ygo_toolbox"

# Larghezza di riferimento (= dimensione iniziale della finestra): la scala UI è
# larghezza_attuale / BASE_WIDTH, così a schermo intero gli elementi crescono.
BASE_WIDTH = 1040
SCALE_MIN, SCALE_MAX, SCALE_STEP = 0.9, 1.3, 0.05


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        # Stato scala UI: inizializzato PRIMA di resize()/show, perché
        # resizeEvent può scattare subito e legge questi attributi.
        self._ui_scale = 1.0
        self._pending_scale: float | None = None
        self._module_widgets: list = []
        # La riscalatura (QSS rigenerato = re-stile di TUTTI i widget) è
        # costosa: durante il trascinamento del bordo viene DIFFERITA e
        # coalizzata; si applica quando il resize si ferma un attimo.
        self._scale_timer = QTimer(self)
        self._scale_timer.setSingleShot(True)
        self._scale_timer.setInterval(120)
        self._scale_timer.timeout.connect(self._apply_pending_scale)
        self.setWindowTitle(f"YGO Toolbox v{APP_VERSION}")
        self.resize(1040, 660)
        self.setMinimumSize(880, 560)

        # --- contesto condiviso ---
        storage = Storage(APP_DIR / "ygo_toolbox.db")
        app_icon = QApplication.instance().windowIcon()
        if app_icon.isNull():
            app_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.setWindowIcon(app_icon)
        self.tray = QSystemTrayIcon(app_icon, self)
        self.tray.setToolTip("YGO Toolbox")
        self.tray.show()
        self.context = AppContext(
            storage=storage,
            notifier=Notifier(self.tray),
            data_dir=APP_DIR,
        )

        # --- layout: menu laterale + area contenuti ---
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(190)
        self.sidebar.setObjectName("sidebar")
        self.stack = QStackedWidget()

        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.stack.currentChanged.connect(self._fade_current_page)

        self.modules = []
        self._load_modules()

    def _load_modules(self) -> None:
        modules = sorted(discover_modules(self.context), key=lambda m: m.title)
        for mod in modules:
            widget = mod.create_widget()
            self.stack.addWidget(widget)
            self._module_widgets.append(widget)
            QListWidgetItem(mod.title, self.sidebar)
            mod.on_start()
            self.modules.append(mod)

        if self.modules:
            self.sidebar.setCurrentRow(0)
        else:
            placeholder = QLabel("Nessun modulo trovato in modules/.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.stack.addWidget(placeholder)

    def _fade_current_page(self, _index: int) -> None:
        page = self.stack.currentWidget()
        if page is not None:
            anim.fade_in(page, duration=200)

    def resizeEvent(self, event) -> None:  # noqa: N802 (firma Qt)
        super().resizeEvent(event)
        self._update_ui_scale()

    def _update_ui_scale(self) -> None:
        """Ricalcola la scala UI dalla larghezza e la programma (QSS + moduli).

        La scala è quantizzata a passi di SCALE_STEP e applicata in modo
        DIFFERITO (timer coalescente): durante il trascinamento del bordo non
        si ri-stilizza tutto a ogni scatto — solo alla pausa."""
        if not hasattr(self, "_ui_scale") or not hasattr(self, "sidebar"):
            return  # resize troppo precoce (attributi non ancora pronti)
        raw = self.width() / BASE_WIDTH
        raw = max(SCALE_MIN, min(raw, SCALE_MAX))
        scale = round(raw / SCALE_STEP) * SCALE_STEP
        if abs(scale - self._ui_scale) < 1e-6:
            self._pending_scale = None
            return
        self._pending_scale = scale
        self._scale_timer.start()

    def _apply_pending_scale(self) -> None:
        scale = self._pending_scale
        if scale is None or abs(scale - self._ui_scale) < 1e-6:
            return
        self._pending_scale = None
        self._ui_scale = scale
        app = QApplication.instance()
        if app is not None:
            theme.apply_scale(app, scale)
        self.sidebar.setFixedWidth(round(190 * scale))
        for widget in self._module_widgets:
            if hasattr(widget, "apply_scale"):
                widget.apply_scale(scale)

    def closeEvent(self, event) -> None:  # noqa: N802 (firma Qt)
        for mod in self.modules:
            mod.on_stop()
        self.context.storage.close()
        super().closeEvent(event)
