"""Contesto applicativo passato a ogni modulo.

`AppContext` è la "scatola di servizi" che ogni modulo riceve:
- storage:  accesso al database condiviso
- notifier: per mandare notifiche di sistema all'utente
- data_dir: cartella dove salvare eventuali file del modulo
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core import telegram
from core.storage import Storage


class Notifier:
    """Manda notifiche di sistema usando l'icona nella tray.

    Se la tray non è disponibile (es. test headless) fa fallback su stdout,
    così il codice resta testabile senza interfaccia grafica.
    Se Telegram è collegato (Opzioni), la notifica parte ANCHE lì: così
    arriva sul telefono ovunque, ad app chiusa (solo traffico in uscita).
    """

    def __init__(self, tray_icon=None) -> None:
        self._tray = tray_icon

    def notify(self, title: str, message: str) -> None:
        if self._tray is not None and self._tray.supportsMessages():
            self._tray.showMessage(title, message)
        else:
            print(f"[NOTIFY] {title}: {message}")
        telegram.send(f"{title}\n{message}")   # no-op se non configurato


@dataclass
class AppContext:
    storage: Storage
    notifier: Notifier
    data_dir: Path
