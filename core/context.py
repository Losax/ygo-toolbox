"""Contesto applicativo passato a ogni modulo.

`AppContext` è la "scatola di servizi" che ogni modulo riceve:
- storage:  accesso al database condiviso
- notifier: per mandare notifiche di sistema all'utente
- data_dir: cartella dove salvare eventuali file del modulo
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from core.storage import Storage


class Notifier:
    """Manda notifiche di sistema usando l'icona nella tray.

    Se la tray non è disponibile (es. test headless) fa fallback su stdout,
    così il codice resta testabile senza interfaccia grafica.
    """

    def __init__(self, tray_icon=None) -> None:
        self._tray = tray_icon

    def notify(self, title: str, message: str) -> None:
        if self._tray is not None and self._tray.supportsMessages():
            self._tray.showMessage(title, message)
        else:
            print(f"[NOTIFY] {title}: {message}")


def _no_navigation(_module_id: str, _payload=None) -> bool:
    """Predefinito: nessuna navigazione. Un modulo che chiede di passare a un
    altro riceve False e si arrangia (dice all'utente di farlo a mano) invece
    di esplodere — succede nei test headless e in qualunque contesto senza
    finestra principale."""
    return False


@dataclass
class AppContext:
    storage: Storage
    notifier: Notifier
    data_dir: Path
    #: Passa a un altro modulo (per `id`) e gli consegna un messaggio.
    #: La imposta la `MainWindow`; i moduli NON si conoscono fra loro, si
    #: parlano solo attraverso il contesto. Torna True se il modulo esiste ed
    #: ha accettato il messaggio.
    open_module: Callable[[str, object], bool] = field(default=_no_navigation)
