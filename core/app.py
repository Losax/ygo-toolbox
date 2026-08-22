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
    QVBoxLayout,
    QWidget,
)

from core import anim, theme
from core.context import AppContext, Notifier
from core.module_loader import discover_modules
from core.storage import Storage
from core.update_widget import UpdateFooter
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
        self.sidebar.setObjectName("sidebar")
        self.stack = QStackedWidget()

        # Colonna di sinistra: le voci in alto, il piede dell'aggiornamento in
        # basso. La larghezza fissa sta sulla COLONNA e non più sulla lista,
        # così i due pezzi restano allineati quando la finestra si riscala.
        self.left_column = QWidget()
        self.left_column.setFixedWidth(190)
        colonna = QVBoxLayout(self.left_column)
        colonna.setContentsMargins(0, 0, 0, 0)
        colonna.setSpacing(0)
        colonna.addWidget(self.sidebar, 1)
        self.update_footer = UpdateFooter(
            self.left_column,
            occupato=self._lavoro_in_corso,
            chiudi=self._chiudi_per_aggiornamento,
        )
        colonna.addWidget(self.update_footer)

        layout.addWidget(self.left_column)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.stack.currentChanged.connect(self._fade_current_page)

        self.modules = []
        self.context.open_module = self._open_module
        self._load_modules()

        # Aggiornamenti: com'è finito il tentativo precedente (una volta sola,
        # subito), poi UN controllo in un thread. Il ritardo lascia finire
        # l'avvio dei moduli, che è la parte che l'utente sta guardando.
        self.update_footer.controlla_esito_precedente()
        QTimer.singleShot(6000, self.update_footer.avvia_controllo)

    def _open_module(self, module_id: str, payload=None) -> bool:
        """Porta in primo piano il modulo `module_id` e gli consegna un
        messaggio (se sa riceverlo, cioè se espone `handle_request`).

        È l'unico ponte fra moduli: si conoscono per `id`, non per import, così
        restano scoperti dinamicamente e nessuno dipende dall'altro."""
        for index, mod in enumerate(self.modules):
            if mod.id != module_id:
                continue
            self.sidebar.setCurrentRow(index)
            widget = self._module_widgets[index]
            if payload is not None and hasattr(widget, "handle_request"):
                return bool(widget.handle_request(payload))
            return True
        return False

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

    # ------------------------------------------------------- aggiornamento

    def _lavoro_in_corso(self) -> str:
        """La prima frase che descrive un lavoro lungo in corso, o "".

        Chiede ai widget che sanno rispondere (`busy_reason`), con la stessa
        convenzione a papera di `apply_scale` e `handle_request`: nessun
        protocollo da implementare per chi non ha niente da dire."""
        for widget in self._module_widgets:
            motivo = getattr(widget, "busy_reason", None)
            if motivo is None:
                continue
            try:
                testo = motivo()
            except Exception:
                continue
            if testo:
                return str(testo)
        return ""

    def _chiudi_per_aggiornamento(self) -> None:
        """Chiusura ORDINATA prima che Setup copra i file.

        Non è pulizia formale: se ci facciamo ammazzare da
        `CloseApplications=force`, Inno aspetta il suo timeout — **31 secondi
        misurati** — prima di poter copiare. Chiudendoci da soli sono ~2.
        E chiudersi bene è anche ciò che fa ripulire al bootloader onefile la
        cartella `_MEIxxxxxx` da decine di MB in %TEMP% e toglie l'icona
        fantasma dalla tray."""
        self.close()
        app = QApplication.instance()
        if app is not None:
            # I processi sono DUE (padre e figlio onefile) e devono sparire
            # entrambi prima che Inno copi: non ci si affida alla sola
            # chiusura della finestra.
            QTimer.singleShot(0, app.quit)

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
        self.left_column.setFixedWidth(round(190 * scale))
        for widget in self._module_widgets:
            if hasattr(widget, "apply_scale"):
                widget.apply_scale(scale)

    def closeEvent(self, event) -> None:  # noqa: N802 (firma Qt)
        self.update_footer.stop()
        for mod in self.modules:
            mod.on_stop()
        self.context.storage.close()
        # Via l'icona dalla tray a mano: se il processo viene sostituito da un
        # aggiornamento resta l'icona fantasma, che sparisce solo passandoci
        # sopra col mouse.
        self.tray.hide()
        super().closeEvent(event)
