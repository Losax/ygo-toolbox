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
    """Controlla i prezzi UNA CARTA ALLA VOLTA, con tolleranza agli errori.

    Una carta che fallisce non fa più buttare via il lavoro delle altre: il
    controllo prosegue e alla fine la GUI riceve i risultati raccolti più il
    conto dei fallimenti. Ci si arrende solo dopo alcuni errori DI FILA
    (rete giù o rate limit serio), consegnando comunque il parziale."""

    finished_ok = Signal(list, int, str)  # (risultati, n° falliti, ultimo errore)
    progress = Signal(int, int)           # (fatte, totali)
    failed = Signal(str)                  # nessun risultato: errore secco

    MAX_CONSECUTIVE_FAILURES = 3

    def __init__(self, provider: PriceProvider, jobs: list, parent=None) -> None:
        # jobs: lista di (ref_id, filters, copies) — filtri effettivi (globali,
        # della base o della carta) e quante copie servono
        super().__init__(parent)
        self._provider = provider
        self._jobs = jobs

    def run(self) -> None:
        results: list[dict] = []
        failed = 0
        consecutive = 0
        last_error = ""
        total = len(self._jobs)
        # le attese del rate limit devono mollare subito se l'app si chiude
        client = getattr(self._provider, "client", None)
        if client is not None:
            client.should_stop = self.isInterruptionRequested
        try:
            for done, (ref_id, filters, copies) in enumerate(self._jobs, start=1):
                if self.isInterruptionRequested():
                    break
                try:
                    quote: PriceQuote | None = self._provider.lowest_price(
                        ref_id, filters, copies)
                except CardTraderError as exc:
                    failed += 1
                    consecutive += 1
                    last_error = str(exc)
                    if consecutive >= self.MAX_CONSECUTIVE_FAILURES:
                        break   # inutile insistere: consegna il parziale
                    continue
                finally:
                    self.progress.emit(done, total)
                consecutive = 0
                results.append({"ref_id": ref_id, "quote": quote})
        finally:
            if client is not None:
                client.should_stop = None

        if not results and failed:
            self.failed.emit(last_error)   # non è passato NIENTE: errore secco
            return
        self.finished_ok.emit(results, failed, last_error)


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
        self._client.should_stop = self.isInterruptionRequested
        try:
            rows = fetch_catalog(self._client, progress=self.progress.emit)
        except CardTraderError as exc:
            self.failed.emit(str(exc))
            return
        finally:
            self._client.should_stop = None
        self.finished_ok.emit(rows)
