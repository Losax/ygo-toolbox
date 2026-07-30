"""Accesso al database del modulo (tabelle `cdb_*`).

La copia locale di YGOPRODeck: 14.477 carte più i loro set. Le ricerche
girano QUI, non sulla rete — è quello che chiede la loro guida, ed è anche il
motivo per cui la ricerca è istantanea.

Le tabelle hanno il prefisso `cdb_` per non collidere con `mw_` del market
watch: il file SQLite è uno solo, condiviso da tutti i moduli.
"""
from __future__ import annotations

import sqlite3

from core.storage import Storage

from .api import search_blob

# Colonne di `cdb_cards`. L'ordine vale solo qui: le carte arrivano come
# DIZIONARI e la tupla la costruisce `replace_all`, così aggiungere una
# colonna non spacca nulla altrove.
CARD_COLUMNS = (
    "id", "name", "name_it", "type", "frame_type", "desc", "desc_it", "race",
    "attribute", "atk", "def", "level", "linkval", "scale", "archetype",
    "typeline", "human_type", "image_url", "image_small_url", "tcg_date",
    "ocg_date", "staple", "ban_tcg", "ban_ocg", "ban_goat", "formats",
    "art_count", "search",
)


class CardDbRepository:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self._init_schema()

    def _init_schema(self) -> None:
        self.storage.execute(
            "CREATE TABLE IF NOT EXISTS cdb_cards ("
            " id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_it TEXT,"
            " type TEXT, frame_type TEXT, desc TEXT, desc_it TEXT,"
            " race TEXT, attribute TEXT,"
            " atk INTEGER, def INTEGER, level INTEGER, linkval INTEGER, scale INTEGER,"
            " archetype TEXT, typeline TEXT, human_type TEXT,"
            " image_url TEXT, image_small_url TEXT, tcg_date TEXT, ocg_date TEXT,"
            " staple INTEGER DEFAULT 0, ban_tcg TEXT, ban_ocg TEXT, ban_goat TEXT,"
            " formats TEXT, art_count INTEGER DEFAULT 1, search TEXT)"
        )
        self.storage.execute(
            "CREATE INDEX IF NOT EXISTS cdb_cards_name ON cdb_cards(name)")
        # Indici sulle colonne dei filtri: una ricerca per solo attributo
        # (2.648 carte) passava da scansione completa a indice — misurato,
        # da 128 ms a pochi ms. Costano niente su 14.477 righe.
        for colonna in ("type", "race", "attribute", "archetype", "level"):
            self.storage.execute(
                f"CREATE INDEX IF NOT EXISTS cdb_cards_{colonna} "
                f'ON cdb_cards("{colonna}")')
        self.storage.execute(
            "CREATE TABLE IF NOT EXISTS cdb_sets ("
            " card_id INTEGER NOT NULL, set_name TEXT, set_code TEXT, rarity TEXT)"
        )
        self.storage.execute(
            "CREATE INDEX IF NOT EXISTS cdb_sets_card ON cdb_sets(card_id)")
        self.storage.execute(
            "CREATE TABLE IF NOT EXISTS cdb_meta (key TEXT PRIMARY KEY, value TEXT)")
        self.fts = self._init_fts()

    def _init_fts(self) -> bool:
        """Indice full-text sulla colonna `search` (FTS5, dentro SQLite: zero
        dipendenze nuove).

        **Misurato sul database vero**, 14.477 carte con testi nelle due
        lingue: `LIKE '%…%'` ~90 ms, FTS5 **1 ms** — novanta volte tanto,
        perché un LIKE con il jolly davanti non può usare nessun indice e si
        scorre 20 MB di testo a ogni tasto. Costa 0,5 s di costruzione e ~6 MB
        nel file.
        La semantica cambia in meglio: si cercano PAROLE (con prefisso), non
        sottostringhe. "ash" trova le 39 carte che cominciano per ash, non le
        215 che contengono quelle lettere in mezzo a una parola — "Flash
        Assailant" non è un risultato sensato per "ash".

        Se FTS5 mancasse (build di SQLite senza il modulo) NON è un errore: si
        torna al LIKE, più lento ma identico nei risultati utili."""
        try:
            self.storage.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS cdb_fts USING fts5("
                " search, content='cdb_cards', content_rowid='id',"
                " tokenize='unicode61 remove_diacritics 2')")
        except Exception:
            return False
        return True

    @staticmethod
    def fts_query(text: str) -> str:
        """Trasforma quello che ha scritto l'utente in una query FTS5 SICURA.

        Ogni parola va fra virgolette (le virgolette interne raddoppiate) e
        seguita da `*`: così gli operatori di FTS5 (AND, OR, NOT, NEAR, `:`,
        parentesi) restano testo invece di diventare sintassi — uno spazio o
        un due punti scritti per sbaglio non devono far esplodere la ricerca.
        Il `*` finale serve a cercare mentre si digita: "drag" trova "dragon".
        """
        parole = []
        for grezza in (text or "").lower().split():
            if not any(ch.isalnum() for ch in grezza):
                continue          # solo punteggiatura: FTS5 non la digerisce
            parole.append('"' + grezza.replace('"', '""') + '"*')
        return " ".join(parole)

    # --- sincronizzazione ---------------------------------------------------
    def replace_all(self, cards: list, sets: list) -> None:
        """Sostituisce l'intera copia locale, in UNA transazione.

        Tutto o niente: una sincronizzazione interrotta a metà lascerebbe un
        database mezzo vecchio e mezzo nuovo, che è peggio di uno vecchio.
        `cards` sono i dizionari di `api.parse_card` (già completati coi testi
        italiani): la colonna `search` si costruisce qui, una volta sola."""
        segnaposto = ", ".join("?" * len(CARD_COLUMNS))
        colonne = ", ".join(f'"{c}"' for c in CARD_COLUMNS)
        righe = []
        for carta in cards:
            carta = dict(carta)
            carta["search"] = search_blob(carta)
            righe.append(tuple(carta.get(c) for c in CARD_COLUMNS))
        conn = self.storage.conn
        with conn:                      # commit unico (o rollback se salta)
            conn.execute("DELETE FROM cdb_cards")
            conn.execute("DELETE FROM cdb_sets")
            conn.executemany(
                f"INSERT OR REPLACE INTO cdb_cards ({colonne}) VALUES ({segnaposto})",
                righe)
            conn.executemany(
                "INSERT INTO cdb_sets (card_id, set_name, set_code, rarity) "
                "VALUES (?, ?, ?, ?)", sets)
        if self.fts:
            # L'indice è "a contenuto esterno": legge da cdb_cards, quindi
            # dopo un rimpiazzo totale va ricostruito (0,5 s misurati).
            try:
                self.storage.execute("INSERT INTO cdb_fts(cdb_fts) VALUES('rebuild')")
            except Exception:
                self.fts = False

    def count_cards(self) -> int:
        rows = self.storage.query("SELECT COUNT(*) AS n FROM cdb_cards")
        return rows[0]["n"] if rows else 0

    def get_meta(self, key: str, default: str = "") -> str:
        rows = self.storage.query("SELECT value FROM cdb_meta WHERE key = ?", (key,))
        return rows[0]["value"] if rows else default

    def set_meta(self, key: str, value: str) -> None:
        self.storage.execute(
            "INSERT OR REPLACE INTO cdb_meta (key, value) VALUES (?, ?)",
            (key, str(value)))

    # --- valori possibili per i filtri (dai DATI, non da liste scritte a mano:
    #     una lista fissa invecchia al primo tipo di carta nuovo) -------------
    def distinct(self, column: str) -> list:
        if column not in {"type", "race", "attribute", "archetype", "frame_type"}:
            raise ValueError(f"colonna non ammessa: {column}")
        rows = self.storage.query(
            f'SELECT DISTINCT "{column}" AS v FROM cdb_cards '
            f'WHERE "{column}" IS NOT NULL AND "{column}" != "" ORDER BY v')
        return [r["v"] for r in rows]

    def levels(self) -> list:
        rows = self.storage.query(
            "SELECT DISTINCT level AS v FROM cdb_cards WHERE level IS NOT NULL "
            "ORDER BY v")
        return [r["v"] for r in rows]

    # --- ricerca ------------------------------------------------------------
    def search_page(self, text: str = "", filters: dict | None = None,
                    limit: int = 300) -> tuple[list, int]:
        """(righe, totale trovate). Da usare al posto di `search` +
        `count_matches`: chiede una riga IN PIÙ del limite e, se non arriva,
        il totale è già noto — niente seconda scansione.

        Non è un dettaglio: ogni scansione costa ~190 ms su 14.477 carte (il
        `LIKE '%…%'` sul testo delle due lingue non può usare indici), e
        farne due a ogni tasto si sentiva."""
        righe = self.search(text, filters, limit + 1)
        if len(righe) <= limit:
            return righe, len(righe)
        return righe[:limit], self.count_matches(text, filters)

    def search(self, text: str = "", filters: dict | None = None,
               limit: int = 300) -> list:
        """Ricerca locale. `filters` accetta: type, race, attribute, archetype,
        level, banlist ('tcg'|'ocg'|'goat'), staple.

        Il tetto a `limit` non è pigrizia: senza filtri la ricerca vuota
        prenderebbe 14.477 righe e la lista dovrebbe disegnarle tutte. Chi
        chiama sa quante ne sono state tagliate (vedi `search_page`)."""
        where, params = self._where(text, filters or {})
        sql = ("SELECT id, name, name_it, type, frame_type, race, attribute, "
               "atk, def, level, archetype, image_small_url, "
               "ban_tcg, ban_ocg, ban_goat FROM cdb_cards")
        if where:
            sql += " WHERE " + " AND ".join(where)
        # Prima i nomi che COMINCIANO per quello che hai scritto: cercando
        # "ash" ci si aspetta Ash Blossom in cima, non "Flash Assailant".
        # Vale per entrambe le lingue.
        if text.strip():
            inizio = f"{text.strip().lower()}%"
            sql += (" ORDER BY (lower(name) LIKE ? OR lower(name_it) LIKE ?) DESC,"
                    " name COLLATE NOCASE")
            params = params + (inizio, inizio)
        else:
            sql += " ORDER BY name COLLATE NOCASE"
        sql += " LIMIT ?"
        try:
            return self.storage.query(sql, params + (limit,))
        except sqlite3.OperationalError:
            # L'indice full-text ha rifiutato la query (indice corrotto,
            # sintassi imprevista): si scende al LIKE invece di lasciare la
            # ricerca rotta. Una volta sola: `fts` resta spento.
            if not self.fts:
                raise
            self.fts = False
            return self.search(text, filters, limit)

    def count_matches(self, text: str = "", filters: dict | None = None) -> int:
        where, params = self._where(text, filters or {})
        sql = "SELECT COUNT(*) AS n FROM cdb_cards"
        if where:
            sql += " WHERE " + " AND ".join(where)
        rows = self.storage.query(sql, params)
        return rows[0]["n"] if rows else 0

    def _where(self, text: str, filters: dict) -> tuple[list, tuple]:
        where: list = []
        params: list = []
        testo = (text or "").strip().lower()
        if testo:
            # La colonna `search` contiene nome e testo dell'effetto in
            # italiano E in inglese: si cerca "distruggi" come "destroy".
            # Con l'indice full-text va per parole (1 ms), altrimenti si
            # ripiega sul LIKE (~90 ms) — stessi risultati utili.
            query = self.fts_query(testo) if self.fts else ""
            if query:
                where.append("id IN (SELECT rowid FROM cdb_fts "
                             "WHERE cdb_fts MATCH ?)")
                params.append(query)
            else:
                where.append("search LIKE ?")
                params.append(f"%{testo}%")
        for colonna, chiave in (("type", "type"), ("race", "race"),
                                ("attribute", "attribute"),
                                ("archetype", "archetype")):
            valore = filters.get(chiave)
            if valore:
                where.append(f'"{colonna}" = ?')
                params.append(valore)
        if filters.get("level") is not None:
            where.append("level = ?")
            params.append(int(filters["level"]))
        banlist = filters.get("banlist")
        if banlist in ("tcg", "ocg", "goat"):
            where.append(f'ban_{banlist} != ""')
        elif banlist == "any":
            where.append('(ban_tcg != "" OR ban_ocg != "" OR ban_goat != "")')
        if filters.get("staple"):
            where.append("staple = 1")
        return where, tuple(params)

    def card(self, card_id: int):
        rows = self.storage.query("SELECT * FROM cdb_cards WHERE id = ?", (int(card_id),))
        return rows[0] if rows else None

    def sets_of(self, card_id: int) -> list:
        return self.storage.query(
            "SELECT set_name, set_code, rarity FROM cdb_sets WHERE card_id = ? "
            "ORDER BY set_code", (int(card_id),))
