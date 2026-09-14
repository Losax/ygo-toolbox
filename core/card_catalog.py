"""Ponte in SOLA LETTURA verso il catalogo carte del modulo Database.

Il file SQLite è uno solo, ma i moduli **non si importano fra loro**: quando
al Market Watch serve tradurre i *passcode* di un `.ydk` in nomi, o alla
Collezione serve l'immagine di una carta, l'unica tabella che lo sa è
`cdb_cards`, che appartiene al Database. Prima questo codice stava dentro
`market_watch/repository.py`; da quando serve a due moduli sta qui, come
`card_images.py`, `badges.py` e `rarity.py`.

Le regole di questo ponte, che sono anche il motivo per cui è un file a parte:

- **si legge, non si scrive mai.** Il proprietario della tabella resta il
  Database: duplicare 14.000 righe sotto un altro prefisso significherebbe una
  seconda sincronizzazione da tenere allineata;
- **tutto difensivo.** Chi non ha mai aperto il Database non ha la tabella, e
  quello è uno stato NORMALE: deve ricevere un invito a sincronizzare, non un
  errore SQL;
- **"assente" e "illeggibile" non sono la stessa cosa** (v1.6.0). Finivano
  entrambi in un `return {}`, e l'utente si sentiva consigliare di
  sincronizzare anche quando il problema era la FORMA della tabella, che una
  sincronizzazione non tocca: un giro a vuoto. Un difetto invisibile che manda
  dalla parte sbagliata è peggio di un errore parlante.
"""
from __future__ import annotations

import sqlite3

from core.storage import Storage

#: Colonne che servono a chi usa il ponte. Se una manca, la query fallisce
#: TUTTA: meglio dirlo per nome che restituire "nessuna carta".
CARD_COLUMNS = ("id", "name", "name_it", "image_url", "image_small_url")

#: SQLite ha un tetto ai parametri di una query: le liste si leggono a blocchi.
BLOCCO = 400


class CardCatalogError(RuntimeError):
    """Il catalogo carte c'è, ma non si riesce a leggerlo.

    Si solleva **solo** quando la tabella esiste: non averla mai sincronizzata
    è uno stato normale, non un errore, e chi chiama riceve un dizionario
    vuoto. Porta con sé `stato` e `dettaglio` (le colonne mancanti, o il
    messaggio di SQLite) perché l'interfaccia possa dire cosa fare davvero
    invece di consigliare a caso.
    """

    def __init__(self, stato: str, dettaglio: str = "") -> None:
        super().__init__(f"{stato}: {dettaglio}" if dettaglio else stato)
        self.stato = stato
        self.dettaglio = dettaglio


def status(storage: Storage) -> tuple[str, str]:
    """Stato del catalogo carte: `(stato, dettaglio)`.

    Stati: `assente` (mai sincronizzato), `vuota` (tabella senza righe),
    `incompleta` (mancano colonne — il dettaglio le elenca), `illeggibile`
    (SQLite si lamenta; il dettaglio è il suo messaggio), `ok`.
    """
    try:
        if not storage.query("SELECT name FROM sqlite_master "
                             "WHERE type='table' AND name='cdb_cards'"):
            return "assente", ""
        presenti = {r["name"] for r in storage.query("PRAGMA table_info(cdb_cards)")}
        mancanti = [c for c in CARD_COLUMNS if c not in presenti]
        if mancanti:
            return "incompleta", ", ".join(mancanti)
        if not storage.query("SELECT 1 AS uno FROM cdb_cards LIMIT 1"):
            return "vuota", ""
        return "ok", ""
    except sqlite3.Error as exc:
        return "illeggibile", str(exc)


def available(storage: Storage) -> bool:
    """C'è il catalogo carte del Database, ed è utilizzabile?"""
    return status(storage)[0] == "ok"


def _leggibile(storage: Storage) -> bool:
    """True se vale la pena interrogare; solleva se la tabella c'è ma è rotta."""
    stato, dettaglio = status(storage)
    if stato in ("assente", "vuota"):
        return False      # stati NORMALI: non c'è ancora niente da leggere
    if stato != "ok":
        raise CardCatalogError(stato, dettaglio)   # la tabella c'è ma non si legge
    return True


def _a_blocchi(storage: Storage, colonna: str, valori: list) -> list:
    righe: list = []
    for i in range(0, len(valori), BLOCCO):
        blocco = valori[i:i + BLOCCO]
        segni = ",".join("?" * len(blocco))
        try:
            righe.extend(storage.query(
                f"SELECT id, name, name_it, image_url, image_small_url "
                f"FROM cdb_cards WHERE {colonna} IN ({segni})", tuple(blocco)))
        except sqlite3.Error as exc:
            raise CardCatalogError("illeggibile", str(exc)) from exc
    return righe


def by_passcode(storage: Storage, codes) -> dict:
    """passcode → riga del catalogo carte, per i codici trovati.

    I codici assenti semplicemente non compaiono nel risultato: è un dato
    mancante, e chi chiama lo mostra come tale invece di inventare una carta.
    Non tutti i passcode sono in `cdb_cards`: le **arti alternative** hanno un
    passcode proprio che lì non è indicizzato (la tabella tiene un id per
    carta), quindi un `.ydk` che le usa lascia qualche riga non riconosciuta.
    """
    codici = [int(c) for c in codes]
    if not codici or not _leggibile(storage):
        return {}
    return {int(r["id"]): r for r in _a_blocchi(storage, "id", codici)}


def by_name(storage: Storage, names) -> dict:
    """nome inglese → riga del catalogo carte, per i nomi trovati.

    Serve alla Collezione: il catalogo dei prezzi conosce le stampe per NOME,
    e l'immagine della carta sta nel Database. Il confronto è per nome esatto —
    entrambe le fonti usano il nome inglese ufficiale — e chi non si trova
    resta fuori: una miniatura mancante è meglio dell'immagine di un'altra
    carta scelta per somiglianza.
    """
    nomi = [str(n) for n in dict.fromkeys(names) if n]
    if not nomi or not _leggibile(storage):
        return {}
    return {str(r["name"]): r for r in _a_blocchi(storage, "name", nomi)}
