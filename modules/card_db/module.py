"""Punto di aggancio del modulo Database al toolbox.

Il caricatore cerca questo file: contiene la sottoclasse di `ToolModule`.
Tutto il resto (API, DB locale, immagini, UI) è dettaglio interno.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from core.module_base import ToolModule

from .widget import CardDbWidget


class CardDbModule(ToolModule):
    id = "card_db"
    title = "Database"

    def create_widget(self) -> QWidget:
        self._widget = CardDbWidget(self.context)
        return self._widget

    def on_stop(self) -> None:
        widget = getattr(self, "_widget", None)
        if widget is not None:
            widget.stop()
