"""Punto di aggancio del modulo Collezione al toolbox.

Il caricatore cerca questo file: contiene la sottoclasse di `ToolModule`.
Tutto il resto (tabelle, raccoglitori, prezzi, UI) è dettaglio interno.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from core.module_base import ToolModule

from .widget import CollectionWidget


class CollectionModule(ToolModule):
    id = "collection"
    title = "Collezione"

    def create_widget(self) -> QWidget:
        self._widget = CollectionWidget(self.context)
        return self._widget

    def on_stop(self) -> None:
        widget = getattr(self, "_widget", None)
        if widget is not None:
            widget.stop()
