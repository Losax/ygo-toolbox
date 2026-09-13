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
        """jobs: `(ref_id, filters, copies, candidati)`.

        `candidati` è la lista delle stampe da interrogare per quella carta:
        normalmente una sola (`[ref_id]`), ma in modalità "la più economica in
        questa rarità" sono tutte le stampe di quella rarità. L'API di
        CardTrader **non sa rispondere per più stampe in una volta** (provate
        le virgole, `blueprint_id[]` → 400, e il parametro ripetuto: torna una
        stampa sola), quindi il fan-out si paga a richieste: è il motivo per
        cui la scansione completa non si fa a ogni giro (vedi `check_now`).
        """
        super().__init__(parent)
        self._provider = provider
        # tollera i job a 3 elementi delle versioni precedenti
        self._jobs = [j if len(j) >= 4 else (*j, [j[0]]) for j in jobs]

    @staticmethod
    def _meglio(a: PriceQuote | None, b: PriceQuote | None,
                copies: int) -> PriceQuote | None:
        """La più conveniente fra due quotazioni, a parità di copie richieste.

        Con più copie si confronta il TOTALE, non il prezzo unitario: se ne
        servono tre, la stampa più economica è quella che costa meno *per
        tre*, e non è detto sia quella col singolo annuncio più basso (il
        primo venditore può averne una sola).
        """
        if a is None:
            return b
        if b is None:
            return a
        def costo(q):
            return q.total if (copies > 1 and getattr(q, "total", 0.0)) else q.amount
        return a if costo(a) <= costo(b) else b

    def run(self) -> None:
        results: list[dict] = []
        failed = 0
        consecutive = 0
        last_error = ""
        # Il conto è sulle RICHIESTE, non sulle carte: con il fan-out una sola
        # carta può valerne trenta, e una barra ferma su "3/40" per un minuto
        # sembra un blocco.
        total = sum(max(1, len(c)) for _r, _f, _c, c in self._jobs)
        done = 0
        client = getattr(self._provider, "client", None)
        if client is not None:
            client.should_stop = self.isInterruptionRequested
        try:
            for ref_id, filters, copies, candidati in self._jobs:
                if self.isInterruptionRequested():
                    break
                migliore: PriceQuote | None = None
                vincitore = ""
                riuscita = False
                for cand in (candidati or [ref_id]):
                    if self.isInterruptionRequested():
                        break
                    try:
                        quote = self._provider.lowest_price(cand, filters, copies)
                    except CardTraderError as exc:
                        failed += 1
                        consecutive += 1
                        last_error = str(exc)
                        if consecutive >= self.MAX_CONSECUTIVE_FAILURES:
                            break   # inutile insistere: consegna il parziale
                        continue
                    finally:
                        done += 1
                        self.progress.emit(done, total)
                    consecutive = 0
                    riuscita = True
                    scelta = self._meglio(migliore, quote, copies)
                    if scelta is not None and scelta is quote:
                        vincitore = str(cand)
                    migliore = scelta
                if consecutive >= self.MAX_CONSECUTIVE_FAILURES:
                    break
                if riuscita:
                    # `winner` = la stampa che ha vinto QUESTA volta ('' se la
                    # carta segue la sua stampa esatta e non c'è gara)
                    results.append({"ref_id": ref_id, "quote": migliore,
                                    "winner": vincitore})
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
