"""Il contratto che ogni modulo deve rispettare.

Per aggiungere una nuova funzionalità al toolbox basta creare un pacchetto
in `modules/<nome>/` con un file `module.py` che contiene una sottoclasse
di `ToolModule`. Il caricatore la trova e la aggiunge da sola al menu
laterale: non serve toccare nessun altro file del core.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from PySide6.QtWidgets import QWidget

from core.context import AppContext


class ToolModule(ABC):
    #: identificatore univoco e stabile (usato internamente / per le tabelle DB)
    id: str = ""
    #: nome mostrato nel menu laterale
    title: str = "Senza nome"

    def __init__(self, context: AppContext) -> None:
        self.context = context

    @abstractmethod
    def create_widget(self) -> QWidget:
        """Costruisce e restituisce il widget Qt principale del modulo."""

    def on_start(self) -> None:
        """Chiamato dopo che il widget è stato inserito nella finestra."""

    def on_stop(self) -> None:
        """Chiamato alla chiusura dell'app: fermare timer, thread, ecc."""
