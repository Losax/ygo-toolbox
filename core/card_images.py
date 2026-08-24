"""Immagini delle carte: scaricate UNA volta e tenute su DISCO.

Sta nel `core` — e non dentro un modulo — perché la usano in due: il Database
(elenco e pagina della carta) e il Market Watch (griglia dell'importazione
`.ydk`). I moduli **non si importano fra loro**, quindi ciò che serve a due
posti va in un posto comune: la stessa strada già fatta da `badges.py` e
`rarity.py`. La cache su disco è una sola, quindi un'immagine scaricata da un
modulo è già pronta per l'altro.

È la regola più stringente di YGOPRODeck, e va citata per intero perché è il
motivo per cui questo file esiste invece di una semplice cache in memoria:

    *"Do not continually hotlink images directly from this site. Please
    download and re-host the images yourself. Failure to do so will result in
    an IP blacklist."* — *"Please only pull an image once and then store it
    locally."*

Quindi:
- il file scaricato resta in `~/.ygo_toolbox/card_images/` **per sempre** (non
  si svuota a ogni avvio come le cache in memoria del market_watch);
- si scarica **solo la miniatura che serve a schermo**, non le 14.642 del
  database (sarebbero ~400 MB e proprio il "volume alto" che minacciano di
  mettere in blacklist);
- i download sono **spaziati** e gli URL falliti si **ricordano**: senza,
  ogni ridisegno rilancerebbe lo stesso download perso, che è il modo più
  rapido per farsi bloccare (stessa lezione del GOTCHA 1).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage

import requests

# Sessione propria: questo file non può dipendere da un modulo (sarebbe il
# `core` a importare `modules`, cioè il contrario di come sta in piedi
# l'applicazione). Lo User-Agent resta quello dichiarato a YGOPRODeck.
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "YGO-Toolbox (app desktop personale)"

CACHE_DIR = Path.home() / ".ygo_toolbox" / "card_images"

# Spaziatura fra download di immagini. Il limite dichiarato dell'API è 20/s,
# ma sulle immagini parlano di "volume alto" senza dare un numero: si sta
# larghi. Con la lista che scarica solo le righe VISIBILI, ~8 al secondo
# bastano e avanzano.
INTERVAL = 0.13
_slot_lock = threading.Lock()
_next_at = 0.0

_failed: set = set()


def _slot() -> None:
    global _next_at
    with _slot_lock:
        now = time.monotonic()
        start = max(now, _next_at)
        _next_at = start + INTERVAL
    pausa = start - time.monotonic()
    if pausa > 0:
        time.sleep(pausa)


def local_path(card_id: int, small: bool = True) -> Path:
    suffisso = "s" if small else "f"
    return CACHE_DIR / f"{int(card_id)}{suffisso}.jpg"


def cached(card_id: int, small: bool = True) -> Path | None:
    """Il file locale, se già scaricato. Nessuna rete."""
    percorso = local_path(card_id, small)
    return percorso if percorso.exists() and percorso.stat().st_size > 0 else None


def failed(url: str) -> bool:
    return url in _failed


def forget_failures() -> None:
    """Azzera i fallimenti (gesto esplicito dell'utente: "riprova"). Un 403
    temporaneo non deve lasciare segnaposti fino al riavvio."""
    _failed.clear()


class ImageSignals(QObject):
    done = Signal(int, bool, str)     # card_id, small, percorso locale ('' = fallita)


class ImageTask(QRunnable):
    """Scarica UNA immagine e la salva su disco. Gira in QThreadPool: non
    tocca il database, e alla GUI torna solo il percorso del file."""

    def __init__(self, card_id: int, url: str, small: bool,
                 signals: ImageSignals) -> None:
        super().__init__()
        self.card_id = int(card_id)
        self.url = url
        self.small = small
        self.signals = signals

    def run(self) -> None:  # noqa: D102 (contratto QRunnable)
        percorso = local_path(self.card_id, self.small)
        if percorso.exists() and percorso.stat().st_size > 0:
            self.signals.done.emit(self.card_id, self.small, str(percorso))
            return
        _slot()
        try:
            risposta = SESSION.get(self.url, timeout=30)
            if risposta.status_code != 200 or not risposta.content:
                raise ValueError(f"HTTP {risposta.status_code}")
            # Si verifica che sia un'immagine VERA prima di scriverla: salvare
            # una pagina d'errore col nome di un jpg significherebbe non
            # riscaricarla mai più, perché il file "esiste".
            if QImage.fromData(risposta.content).isNull():
                raise ValueError("contenuto non è un'immagine")
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            percorso.write_bytes(risposta.content)
        except Exception:                      # rete, HTTP, disco: uguale
            _failed.add(self.url)
            self.signals.done.emit(self.card_id, self.small, "")
            return
        self.signals.done.emit(self.card_id, self.small, str(percorso))
