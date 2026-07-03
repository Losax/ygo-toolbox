"""Lavori in background (thread separati) per non bloccare l'interfaccia.

Entrambi fanno SOLO chiamate di rete e restituiscono i risultati alla GUI
tramite segnali; la scrittura su database avviene poi sul thread principale.
"""
from __future__ import annotations

import requests
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from .net import SESSION
from .providers.base import PriceProvider, PriceQuote
from .providers.cardtrader import CardTraderClient, CardTraderError, fetch_catalog


class PriceFetchWorker(QThread):
    finished_ok = Signal(list)  # [{"ref_id": str, "quote": PriceQuote|None}, ...]
    failed = Signal(str)

    def __init__(self, provider: PriceProvider, jobs: list, parent=None) -> None:
        # jobs: lista di (ref_id, filters) — filtri effettivi (globali o della carta)
        super().__init__(parent)
        self._provider = provider
        self._jobs = jobs

    def run(self) -> None:
        results: list[dict] = []
        try:
            for ref_id, filters in self._jobs:
                quote: PriceQuote | None = self._provider.lowest_price(ref_id, filters)
                results.append({"ref_id": ref_id, "quote": quote})
        except CardTraderError as exc:
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(results)


class ImageFetchWorker(QThread):
    """Scarica E decodifica l'anteprima carta senza bloccare la GUI."""
    done = Signal(str, QImage)  # (url, immagine già decodificata)
    failed = Signal(str)

    def __init__(self, url: str, parent=None) -> None:
        super().__init__(parent)
        self._url = url

    def run(self) -> None:
        try:
            resp = SESSION.get(self._url, timeout=15)
        except requests.RequestException as exc:
            self.failed.emit(str(exc))
            return
        if resp.status_code == 200 and resp.content:
            img = QImage()
            if img.loadFromData(resp.content):
                self.done.emit(self._url, img)
            else:
                self.failed.emit("immagine non valida")
        else:
            self.failed.emit(f"HTTP {resp.status_code}")


class CatalogSyncWorker(QThread):
    progress = Signal(int, int)  # (fatte, totali) espansioni
    finished_ok = Signal(list)   # righe (ref_id, name, detail)
    failed = Signal(str)

    def __init__(self, client: CardTraderClient, parent=None) -> None:
        super().__init__(parent)
        self._client = client

    def run(self) -> None:
        try:
            rows = fetch_catalog(self._client, progress=self.progress.emit)
        except CardTraderError as exc:
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(rows)
