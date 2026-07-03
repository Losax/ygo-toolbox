"""YGO Toolbox - punto di ingresso.

Avvia la finestra principale, che a sua volta scopre e carica
automaticamente tutti i moduli presenti nella cartella `modules/`.
"""
import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from core.app import MainWindow
from core.theme import apply_theme


def _resource_path(rel: str) -> str:
    """Percorso di una risorsa, sia in sviluppo sia nell'exe PyInstaller."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def _ensure_streams() -> None:
    """Nell'exe windowed stdout/stderr sono None: la stampa di un traceback
    (anche innocuo, es. dentro uno slot Qt) può far ABORTIRE il processo.
    Li dirottiamo su un file di log in ~/.ygo_toolbox, utile anche per capire
    eventuali errori dell'exe."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        log_dir = Path.home() / ".ygo_toolbox"
        log_dir.mkdir(parents=True, exist_ok=True)
        stream = open(log_dir / "log.txt", "a", encoding="utf-8", buffering=1)
    except OSError:
        stream = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def main() -> int:
    _ensure_streams()
    from core import i18n
    i18n.load_language()   # PRIMA di costruire la UI (le stringhe sono tradotte lì)
    app = QApplication(sys.argv)
    app.setApplicationName("YGO Toolbox")
    app.setQuitOnLastWindowClosed(True)
    apply_theme(app)
    # Icona dell'applicazione: barra del titolo (alto a sinistra) e pulsante taskbar.
    app.setWindowIcon(QIcon(_resource_path("assets/icon.ico")))

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
