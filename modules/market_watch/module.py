"""Punto di aggancio del modulo Market Watch al toolbox.

È questo file che il caricatore cerca: contiene la sottoclasse di
`ToolModule`. Tutto il resto (UI, API, DB) è dettaglio interno del modulo.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from core.module_base import ToolModule

from .widget import MarketWatchWidget


class MarketWatchModule(ToolModule):
    id = "market_watch"
    title = "Market Watch"

    def create_widget(self) -> QWidget:
        self._widget = MarketWatchWidget(self.context)
        return self._widget

    def on_stop(self) -> None:
        widget = getattr(self, "_widget", None)
        if widget is not None:
            widget.stop()
