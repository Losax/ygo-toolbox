"""Lavoro in background della Collezione: rileggere i prezzi.

Come nel Market Watch, il thread fa SOLO chiamate di rete e restituisce i
risultati alla GUI con un segnale; su SQLite si scrive di là, sul thread
principale (vedi la nota in core/storage.py).
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QThread, Signal

from core.prices.base import PriceProvider
from core.prices.cardtrader import CardTraderError


class PriceRefreshWorker(QThread):
    """Rilegge il prezzo più basso di una lista di stampe, una alla volta.

    Due cose lo distinguono dal controllo del Market Watch, e sono le stesse
    due che rendono onesto il valore della collezione:

    1. **"nessuno la vende" è un risultato, non un errore.** Se il provider non
       trova annunci, la stampa viene salvata con prezzo NULL e la data di
       oggi: così la carta risulta *controllata e senza mercato*, invece di
       restare per sempre "mai controllata" o — peggio — di tenersi un prezzo
       vecchio come se fosse fresco.
    2. **un fallimento non scrive niente.** Un errore di rete non è un prezzo:
       la riga non viene toccata e resta quella di prima, con la sua data.

    Ci si arrende dopo alcuni errori DI FILA (rete giù o rate limit serio),
    consegnando comunque il parziale: su una collezione di mille carte buttare
    via venti minuti di lavoro per l'ultimo errore sarebbe crudele.
    """

    finished_ok = Signal(list, int, str)  # (righe, n° falliti, ultimo errore)
    progress = Signal(int, int)           # (fatte, totali)
    failed = Signal(str)                  # nessun risultato: errore secco

    MAX_CONSECUTIVE_FAILURES = 3

    def __init__(self, provider: PriceProvider, refs: list, parent=None) -> None:
        super().__init__(parent)
        self._provider = provider
        self._refs = [str(r) for r in refs]

    def run(self) -> None:
        righe: list[tuple] = []
        falliti = 0
        di_fila = 0
        ultimo_errore = ""
        totale = len(self._refs)
        client = getattr(self._provider, "client", None)
        if client is not None:
            client.should_stop = self.isInterruptionRequested
        try:
            for fatte, ref in enumerate(self._refs, start=1):
                if self.isInterruptionRequested():
                    break
                try:
                    quote = self._provider.lowest_price(ref)
                except CardTraderError as exc:
                    falliti += 1
                    di_fila += 1
                    ultimo_errore = str(exc)
                    self.progress.emit(fatte, totale)
                    if di_fila >= self.MAX_CONSECUTIVE_FAILURES:
                        break      # inutile insistere: consegna il parziale
                    continue
                di_fila = 0
                quando = datetime.now().isoformat(timespec="seconds")
                if quote is None:
                    righe.append((ref, None, "EUR", quando))
                else:
                    righe.append((ref, float(quote.amount),
                                  quote.currency or "EUR", quando))
                self.progress.emit(fatte, totale)
        finally:
            if client is not None:
                client.should_stop = None

        if not righe and falliti:
            self.failed.emit(ultimo_errore)   # non è passato NIENTE: errore secco
            return
        self.finished_ok.emit(righe, falliti, ultimo_errore)
