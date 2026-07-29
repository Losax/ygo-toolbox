"""Controllo aggiornamenti: c'è una versione più nuova?

L'app viene consegnata a mano, quindi chi la usa non ha modo di sapere che è
uscita una versione nuova. Qui si chiede a un indirizzo pubblico qual è
l'ultima e si confronta con la propria.

DUE REGOLE, entrambe deliberate:
- **silenzio in caso di problemi.** Rete assente, indirizzo sbagliato, risposta
  incomprensibile: non si dice niente all'utente. Un avviso di errore per un
  controllo che lui non ha chiesto è solo fastidio;
- **niente scaricamento automatico.** Si mostra che c'è una versione nuova e si
  apre la pagina; il file lo prende lui. Un aggiornamento che si installa da
  solo, non firmato, è esattamente ciò che non si vuole far fare a un amico.

Sorgente: `LATEST_URL`. Di default l'API delle release di GitHub, che risponde
solo se il repository è PUBBLICO — con repo privato la chiamata dà 404 e il
controllo resta zitto (vedi la regola sopra). In alternativa basta un file
JSON pubblico qualsiasi con dentro `{"tag_name": "v1.2.3", "html_url": "…"}`.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from core.version import APP_VERSION

LATEST_URL = "https://api.github.com/repos/Losax/ygo-toolbox/releases/latest"
TIMEOUT = 8
_UA = "YGO-Toolbox-update-check"


def parse_version(text: str) -> tuple:
    """"v1.0.23" → (1, 0, 23). I pezzi non numerici si ignorano, così un
    "1.1.0-beta" non fa esplodere il confronto."""
    pezzi = []
    for parte in (text or "").strip().lstrip("vV").split("."):
        numero = ""
        for ch in parte:
            if not ch.isdigit():
                break
            numero += ch
        pezzi.append(int(numero) if numero else 0)
    return tuple(pezzi) or (0,)


def is_newer(candidate: str, current: str = APP_VERSION) -> bool:
    """True se `candidate` è una versione successiva a quella in uso.

    Confronto per NUMERI, non alfabetico: "1.0.9" < "1.0.23" (come stringhe
    sarebbe il contrario, ed è esattamente l'errore che ci si aspetta qui)."""
    a, b = parse_version(candidate), parse_version(current)
    lunghezza = max(len(a), len(b))
    a += (0,) * (lunghezza - len(a))
    b += (0,) * (lunghezza - len(b))
    return a > b


def fetch_latest(url: str = "") -> tuple[str, str] | None:
    """(versione, pagina) dell'ultima release, o None se non si sa.

    CHIAMATA BLOCCANTE: usarla in un thread (vedi `check_async`)."""
    try:
        req = urllib.request.Request(url or LATEST_URL, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    if not isinstance(data, dict):
        return None
    versione = str(data.get("tag_name") or data.get("version") or "").strip()
    if not versione:
        return None
    pagina = str(data.get("html_url") or data.get("url") or "").strip()
    return versione, pagina


def check_async(callback, url: str = "") -> None:
    """Controlla in un thread usa-e-getta e chiama `callback(versione, pagina)`
    SOLO se ce n'è una più nuova. Il callback tocca la GUI, quindi chi lo passa
    deve farlo arrivare al thread principale (nell'app: un segnale Qt)."""
    def lavora() -> None:
        risultato = fetch_latest(url)
        if risultato and is_newer(risultato[0]):
            callback(risultato[0], risultato[1])

    threading.Thread(target=lavora, daemon=True).start()
