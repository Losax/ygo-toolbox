"""Client YGOPRODeck.

**Le loro regole, verificate sulla guida ufficiale il 2026-07-31, decidono
l'architettura di tutto il modulo:**

1. *"The rate limit is 20 requests per 1 second. If you exceed this, you are
   blocked from accessing the API for 1 hour."* — il limite è largo ma la
   punizione è pesante: un'ora di buio.
2. *"Please download and store all data pulled from this API locally to keep
   the amount of API calls used to a minimum."* — la copia locale non è
   un'ottimizzazione nostra, è quello che chiedono. Il modulo interroga
   SQLite, non la rete: la rete la tocca solo la sincronizzazione.
3. *"Do not continually hotlink images... Please only pull an image once and
   then store it locally."* — le immagini si salvano su DISCO (vedi
   `images.py`), non solo in memoria come nel market_watch.

**Misurato dal vivo (2026-07-31):** l'intero database sono **14.477 carte,
23,6 MB, scaricati in 0,9 s** con una sola richiesta. Non serve paginare:
paginare sarebbe *più* richieste per lo stesso risultato, cioè il contrario
di quello che chiedono.
Le immagini invece sono 14.642 (~27 KB l'una in formato piccolo, ~400 MB in
tutto): quelle NON si scaricano in blocco, si prendono quando servono.
"""
from __future__ import annotations

import json
import threading
import time

import requests

BASE = "https://db.ygoprodeck.com/api/v7"
IMAGE_HOSTS = ("images.ygoprodeck.com",)
TIMEOUT = 60

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "YGO-Toolbox (app desktop personale)"

# Il limite dichiarato è 20 richieste al secondo. Ci teniamo MOLTO sotto: le
# richieste vere sono due (versione + sincronizzazione) più le immagini una
# alla volta, e sforare costa un'ora di blocco.
MIN_INTERVAL = 0.12


class YgoProError(Exception):
    """Errore parlante verso la GUI (rete, HTTP, JSON malformato)."""


class _RateLimiter:
    """Spaziatura minima fra richieste, condivisa da tutto il modulo.

    Stessa forma del limitatore del market_watch (vedi GOTCHA 13): lo slot si
    prenota sotto lock e si dorme FUORI dal lock, così più thread si accodano
    senza bloccarsi a vicenda."""

    def __init__(self, interval: float = MIN_INTERVAL) -> None:
        self.interval = interval
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_at)
            self._next_at = start + self.interval
        pausa = start - time.monotonic()
        if pausa > 0:
            time.sleep(pausa)


LIMITER = _RateLimiter()


def _get(path: str, params: dict | None = None, stream: bool = False):
    LIMITER.wait()
    try:
        response = SESSION.get(f"{BASE}/{path}", params=params or {},
                               timeout=TIMEOUT, stream=stream)
    except requests.RequestException as exc:
        raise YgoProError(f"Rete non raggiungibile: {exc}") from exc
    if response.status_code == 429:
        raise YgoProError("Troppe richieste: YGOPRODeck blocca per un'ora chi "
                          "supera il limite. Riprova più tardi.")
    if response.status_code >= 400:
        raise YgoProError(f"YGOPRODeck ha risposto {response.status_code}.")
    return response


def fetch_db_version() -> tuple[str, str]:
    """(versione, data ultimo aggiornamento) del database remoto.

    Una richiesta piccolissima (~180 ms misurati): serve per sapere se la
    copia locale è vecchia SENZA riscaricare 23 MB."""
    response = _get("checkDBVer.php")
    try:
        data = response.json()
        riga = data[0] if isinstance(data, list) else data
        return str(riga.get("database_version", "")), str(riga.get("last_update", ""))
    except (ValueError, AttributeError, IndexError, KeyError) as exc:
        raise YgoProError(f"Risposta inattesa da checkDBVer: {exc}") from exc


def fetch_all_cards(should_stop=None, progress=None, language: str = "") -> list:
    """Scarica TUTTE le carte (una sola richiesta, `misc=yes` per avere anche
    date, formati e "staple").

    Con `language` (it/fr/de/pt) l'API restituisce nomi e testi TRADOTTI, più
    `name_en` per ricollegarli. **Misurato il 2026-07-31:** in inglese 14.477
    carte / 23,6 MB, in italiano 11.599 / 17,2 MB — le 2.878 che mancano non
    sono mai uscite in italiano (in genere le più recenti e le OCG). Quindi
    l'inglese resta la base e l'italiano si sovrappone dov'è disponibile:
    il contrario perderebbe un quinto del database.

    Si legge a pezzi per poter avvisare del progresso e, soprattutto, per
    poter MOLLARE se l'utente chiude l'app: 23 MB sono pochi, ma su una linea
    lenta sono comunque secondi in cui la finestra non deve restare appesa."""
    params = {"misc": "yes"}
    if language:
        params["language"] = language
    response = _get("cardinfo.php", params, stream=True)
    atteso = int(response.headers.get("Content-Length") or 0)
    pezzi, scaricati = [], 0
    for chunk in response.iter_content(1 << 16):
        if should_stop is not None and should_stop():
            raise YgoProError("Sincronizzazione interrotta.")
        pezzi.append(chunk)
        scaricati += len(chunk)
        if progress is not None:
            progress(scaricati, atteso)
    try:
        payload = json.loads(b"".join(pezzi).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise YgoProError(f"Risposta non leggibile: {exc}") from exc
    carte = payload.get("data") if isinstance(payload, dict) else None
    if not carte:
        raise YgoProError("Il database è arrivato vuoto.")
    return carte


def parse_card(raw: dict) -> tuple[dict, list]:
    """Da una carta dell'API a un dizionario pronto per il DB, più le sue
    stampe.

    Torna un DIZIONARIO e non una tupla di proposito: la sincronizzazione lo
    completa in un secondo momento coi campi italiani, e farlo per indice
    numerico sarebbe una trappola alla prima colonna aggiunta.

    Parser DIFENSIVO come quello di CardTrader: l'API può aggiungere o
    togliere campi senza avvisare, e un `KeyError` a metà sincronizzazione
    butterebbe via 23 MB già scaricati."""
    misc = (raw.get("misc_info") or [{}])[0]
    ban = (raw.get("banlist_info") or {}) or {}
    immagini = raw.get("card_images") or [{}]
    prima = immagini[0] if immagini else {}
    carta = {
        "id": int(raw.get("id") or 0),
        "name": raw.get("name") or "",
        "name_it": "",
        "desc_it": "",
        "type": raw.get("type") or "",
        "frame_type": raw.get("frameType") or "",
        "desc": raw.get("desc") or "",
        "race": raw.get("race") or "",
        "attribute": raw.get("attribute") or "",
        "atk": raw.get("atk"),
        "def": raw.get("def"),
        "level": raw.get("level"),
        "linkval": raw.get("linkval"),
        "scale": raw.get("scale"),
        "archetype": raw.get("archetype") or "",
        "typeline": " / ".join(str(t) for t in (raw.get("typeline") or [])),
        "human_type": raw.get("humanReadableCardType") or "",
        "image_url": prima.get("image_url") or "",
        "image_small_url": prima.get("image_url_small") or "",
        "tcg_date": misc.get("tcg_date") or "",
        "ocg_date": misc.get("ocg_date") or "",
        "staple": 1 if str(misc.get("staple", "")).lower() == "yes" else 0,
        "ban_tcg": ban.get("ban_tcg") or "",
        "ban_ocg": ban.get("ban_ocg") or "",
        "ban_goat": ban.get("ban_goat") or "",
        "formats": json.dumps(misc.get("formats") or [], ensure_ascii=False),
        "art_count": len(immagini),
    }
    sets = [
        (carta["id"], s.get("set_name") or "", s.get("set_code") or "",
         s.get("set_rarity") or "")
        for s in (raw.get("card_sets") or [])
    ]
    return carta, sets


def search_blob(carta: dict) -> str:
    """Tutto il testo cercabile di una carta in UN campo, minuscolo: nome e
    testo dell'effetto, in italiano E in inglese.

    Serve a cercare *"distruggi"* come *"destroy"* con **una sola** `LIKE`
    invece di quattro. Non è però un'ottimizzazione: misurato sul database
    vero (14.477 carte), la ricerca passa da ~120 ms col solo inglese a
    ~190 ms con le due lingue — il testo da scorrere raddoppia, e nessun
    indice aiuta un `LIKE '%…%'`. Il tempo si recupera altrove (vedi
    `repository.search`: il conteggio totale si fa solo quando serve)."""
    pezzi = (carta.get("name"), carta.get("name_it"),
             carta.get("desc"), carta.get("desc_it"))
    return " ".join(p for p in pezzi if p).lower()
