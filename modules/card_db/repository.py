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

# --- vocabolario del GIOCO, non dell'API -----------------------------------
# L'API tiene tutto in due campi (`type` e `race`) che non corrispondono a
# come si chiamano le cose a Yu-Gi-Oh!. Qui si traduce:
#
#   API `type`  = una stringa composta ("Pendulum Effect Fusion Monster"),
#                 che dentro contiene DUE informazioni distinte: se la carta
#                 è un Mostro / una Magia / una Trappola, e — per i mostri —
#                 la CATEGORIA (Normale, Effetto, Fusione, Synchro, Xyz…).
#   API `race`  = per i mostri il **Tipo** (Drago, Guerriero…), per magie e
#                 trappole la **Proprietà** (Normale, Rapida, Counter…).
#                 "Razza" non esiste nel gioco.
#
# Nei dati ci sono anche 124 "Skill Card" e 106 "Token", che non sono nessuna
# delle tre: restano cercabili, semplicemente non hanno un filtro Carta.
CARD_KINDS = {"monster": "Monster", "spell": "Spell", "trap": "Trap"}

# Categorie di mostro, in ordine da giocatore: le due base, poi l'Extra Deck,
# poi le abilità. Si riconoscono per SOTTOSTRINGA dentro `type`.
MONSTER_CATEGORIES = (
    "Normal", "Effect", "Ritual", "Fusion", "Synchro", "Xyz", "Pendulum",
    "Link",
)

# Le ABILITÀ sono un'altra cosa dalla categoria, e vanno tenute separate come
# fa DuelingBook: un mostro è *Synchro* E *Tuner*, non "Synchro oppure Tuner".
# Mescolarle in una tendina sola impedirebbe di cercare proprio quella coppia.
MONSTER_ABILITIES = ("Tuner", "Flip", "Gemini", "Spirit", "Toon", "Union")

# Criteri di ordinamento: (chiave, espressione SQL). Chi non ha il dato va in
# FONDO in entrambi i versi — invertendo galleggerebbe in cima e la lista
# sembrerebbe ordinata per sbaglio (stessa regola del market_watch).
SORT_MODES = {
    "alpha": "name COLLATE NOCASE ASC",
    "atk": "(atk IS NULL) ASC, atk DESC, name COLLATE NOCASE ASC",
    "def": "(def IS NULL) ASC, def DESC, name COLLATE NOCASE ASC",
    "level": "(level IS NULL) ASC, level DESC, name COLLATE NOCASE ASC",
    "recent": "(tcg_date = '') ASC, tcg_date DESC, name COLLATE NOCASE ASC",
}

# Colonne di `cdb_cards`. L'ordine vale solo qui: le carte arrivano come
# DIZIONARI e la tupla la costruisce `replace_all`, così aggiungere una
# colonna non spacca nulla altrove.
CARD_COLUMNS = (
    "id", "name", "name_it", "type", "frame_type", "desc", "desc_it", "race",
    "attribute", "atk", "def", "level", "linkval", "scale", "archetype",
    "typeline", "human_type", "image_url", "image_small_url", "tcg_date",
    "ocg_date", "staple", "ban_tcg", "ban_ocg", "ban_goat", "formats",
    "art_count", "genesys", "search_name", "search_desc",
)
# Colonne indicizzate dal full-text, nell'ordine. Cambiarle richiede di
# ricostruire `cdb_fts` (lo fa `_init_fts` da sé, vedi lì).
FTS_COLUMNS = ("search_name", "search_desc")


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
            " formats TEXT, art_count INTEGER DEFAULT 1, genesys INTEGER,"
            " search_name TEXT, search_desc TEXT)"
        )
        # `CREATE TABLE IF NOT EXISTS` non aggiorna una tabella già esistente:
        # le colonne nuove vanno aggiunte a mano (regola del progetto).
        esistenti = {r["name"] for r in
                     self.storage.query("PRAGMA table_info(cdb_cards)")}
        nuove = [c for c, _t in (("genesys", "INTEGER"),
                                 ("search_name", "TEXT"),
                                 ("search_desc", "TEXT"))
                 if c not in esistenti]
        for colonna in nuove:
            tipo = "INTEGER" if colonna == "genesys" else "TEXT"
            self.storage.execute(
                f"ALTER TABLE cdb_cards ADD COLUMN {colonna} {tipo}")
        if {"search_name", "search_desc"} & set(nuove) and "search" in esistenti:
            # Nome e testo si cercavano in un campo solo. I due nuovi si
            # ricavano dalle colonne che ci sono GIÀ: nessuna
            # risincronizzazione da 65 MB per una separazione di campi.
            self.storage.execute(
                "UPDATE cdb_cards SET"
                " search_name = lower(name || ' ' || COALESCE(name_it, '')),"
                " search_desc = lower(COALESCE(\"desc\", '') || ' ' "
                "               || COALESCE(desc_it, ''))")
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
        # Date di uscita dei set: stanno in un endpoint a parte
        # (`cardsets.php`), non nei dati delle carte. Servono a ordinare le
        # ristampe cronologicamente.
        self.storage.execute(
            "CREATE TABLE IF NOT EXISTS cdb_setinfo ("
            " set_name TEXT PRIMARY KEY, set_code TEXT, tcg_date TEXT)")
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
        colonne = ", ".join(FTS_COLUMNS)
        try:
            # Se l'indice esiste con colonne DIVERSE (è successo separando
            # nome e testo) va rifatto: un indice che non corrisponde alle
            # colonne è peggio di nessun indice.
            attuali = tuple(r["name"] for r in
                            self.storage.query("PRAGMA table_info(cdb_fts)"))
            if attuali and attuali != FTS_COLUMNS:
                self.storage.execute("DROP TABLE cdb_fts")
                attuali = ()
            self.storage.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS cdb_fts USING fts5("
                f" {colonne}, content='cdb_cards', content_rowid='id',"
                f" tokenize='unicode61 remove_diacritics 2')")
            if not attuali and self.count_cards():
                self.storage.execute(
                    "INSERT INTO cdb_fts(cdb_fts) VALUES('rebuild')")
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
            carta["search_name"] = search_blob(carta, ("name", "name_it"))
            carta["search_desc"] = search_blob(carta, ("desc", "desc_it"))
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

    def races(self, card: str = "") -> list:
        """I valori del campo che il gioco chiama **Tipo** per i mostri
        (Drago, Guerriero, Mago…) e **Proprietà** per magie e trappole
        (Normale, Rapida, Continua, Counter…).

        L'API li mette tutti in una colonna sola (`race`), ma sono due
        vocabolari diversi che non si incontrano mai: filtrare per "card"
        evita di offrire "Counter" a chi sta cercando un mostro."""
        sql = ('SELECT DISTINCT race AS v FROM cdb_cards '
               'WHERE race IS NOT NULL AND race != ""')
        params: tuple = ()
        if card in CARD_KINDS:
            sql += " AND type LIKE ?"
            params = (f"%{CARD_KINDS[card]}%",)
        return [r["v"] for r in self.storage.query(sql + " ORDER BY v", params)]

    def categories(self) -> list:
        """Le categorie di mostro PRESENTI nei dati, nell'ordine in cui le
        elenca un giocatore (non alfabetico: prima le due base, poi l'Extra
        Deck)."""
        tipi = " ".join(self.distinct("type")).lower()
        return [c for c in MONSTER_CATEGORIES if c.lower() in tipi]

    def abilities(self) -> list:
        tipi = " ".join(self.distinct("type")).lower()
        return [a for a in MONSTER_ABILITIES if a.lower() in tipi]

    def levels(self) -> list:
        rows = self.storage.query(
            "SELECT DISTINCT level AS v FROM cdb_cards WHERE level IS NOT NULL "
            "ORDER BY v")
        return [r["v"] for r in rows]

    # --- ricerca ------------------------------------------------------------
    def search_page(self, filters: dict | None = None, order: str = "alpha",
                    page: int = 0, per_page: int = 100) -> tuple[list, int]:
        """(righe della pagina, totale trovate).

        Si pagina invece di tagliare a 300 come prima: con un tetto secco i
        risultati oltre il trecentesimo erano **irraggiungibili**, e chi cerca
        "Drago" senza altri filtri ne ha 800."""
        filtri = filters or {}
        totale = self.count_matches(filtri)
        righe = self.search(filtri, order, per_page, page * per_page)
        return righe, totale

    def search(self, filters: dict | None = None, order: str = "alpha",
               limit: int = 100, offset: int = 0) -> list:
        """Ricerca locale. `filters` accetta: name, desc, card, category,
        ability, race, attribute, archetype, level_min/level_max,
        atk_min/atk_max, def_min/def_max, banlist, staple."""
        where, params = self._where(filters or {})
        sql = ("SELECT id, name, name_it, type, frame_type, race, attribute, "
               "atk, def, level, archetype, image_small_url, "
               "ban_tcg, ban_ocg, ban_goat FROM cdb_cards")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY " + SORT_MODES.get(order, SORT_MODES["alpha"])
        sql += " LIMIT ? OFFSET ?"
        try:
            return self.storage.query(sql, params + (limit, max(0, offset)))
        except sqlite3.OperationalError:
            # L'indice full-text ha rifiutato la query (indice corrotto,
            # sintassi imprevista): si scende al LIKE invece di lasciare la
            # ricerca rotta. Una volta sola: `fts` resta spento.
            if not self.fts:
                raise
            self.fts = False
            return self.search(filters, order, limit, offset)

    def count_matches(self, filters: dict | None = None) -> int:
        where, params = self._where(filters or {})
        sql = "SELECT COUNT(*) AS n FROM cdb_cards"
        if where:
            sql += " WHERE " + " AND ".join(where)
        try:
            rows = self.storage.query(sql, params)
        except sqlite3.OperationalError:
            if not self.fts:
                raise
            self.fts = False
            return self.count_matches(filters)
        return rows[0]["n"] if rows else 0

    def _where(self, filters: dict) -> tuple[list, tuple]:
        where: list = []
        params: list = []
        # NOME e TESTO si cercano separatamente, come su DuelingBook: chi
        # cerca "dragon" nel nome non vuole le centinaia di carte che
        # nominano un drago nel proprio effetto. Con l'indice full-text si
        # filtra per colonna, altrimenti si ripiega sul LIKE.
        pezzi_fts, pezzi_like = [], []
        for chiave, colonna in (("name", "search_name"), ("desc", "search_desc")):
            testo = (filters.get(chiave) or "").strip().lower()
            if not testo:
                continue
            query = self.fts_query(testo) if self.fts else ""
            if query:
                pezzi_fts.append(f"{colonna} : ({query})")
            else:
                pezzi_like.append((colonna, testo))
        if pezzi_fts:
            where.append("id IN (SELECT rowid FROM cdb_fts WHERE cdb_fts MATCH ?)")
            params.append(" AND ".join(pezzi_fts))
        for colonna, testo in pezzi_like:
            where.append(f"{colonna} LIKE ?")
            params.append(f"%{testo}%")
        # Mostro / Magia / Trappola: sta dentro la stringa `type`
        # ("Effect Monster", "Spell Card"…). Verificato che non ci siano
        # equivoci: nessun mostro ha "Spell" nel proprio `type` (lo
        # "Spellcaster" sta in `race`, che è un altro campo).
        kind = filters.get("card")
        if kind in CARD_KINDS:
            where.append("type LIKE ?")
            params.append(f"%{CARD_KINDS[kind]}%")
        # Categoria e abilità sono ENTRAMBE dentro `type` ma sono cose
        # diverse: un mostro è Synchro E Tuner insieme, quindi si sommano.
        for chiave in ("category", "ability"):
            valore = filters.get(chiave)
            if valore:
                where.append("type LIKE ?")
                params.append(f"%{valore}%")
        for colonna, chiave in (("race", "race"), ("attribute", "attribute"),
                                ("archetype", "archetype")):
            valore = filters.get(chiave)
            if valore:
                where.append(f'"{colonna}" = ?')
                params.append(valore)
        # Intervalli (Livello/Rango, ATK, DEF): estremi INCLUSI, e ognuno
        # indipendente — si può dare solo il minimo o solo il massimo.
        for colonna in ("level", "atk", "def"):
            for suffisso, segno in (("_min", ">="), ("_max", "<=")):
                valore = filters.get(colonna + suffisso)
                if valore is None:
                    continue
                where.append(f'"{colonna}" {segno} ?')
                params.append(int(valore))
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

    def replace_setinfo(self, righe: list) -> None:
        """(nome, codice, data) di ogni set. Si aggancia per NOME: misurato,
        combacia su 1.023 set su 1.028, mentre per prefisso di codice sarebbe
        638 su 657."""
        conn = self.storage.conn
        with conn:
            conn.execute("DELETE FROM cdb_setinfo")
            conn.executemany(
                "INSERT OR REPLACE INTO cdb_setinfo (set_name, set_code, tcg_date) "
                "VALUES (?, ?, ?)", righe)

    def has_genesys(self) -> bool:
        """La copia locale contiene i punti Genesys? Serve a distinguere
        "questa carta vale 0 punti" da "il dato non l'abbiamo scaricato" —
        due cose diverse che a schermo si scriverebbero uguale."""
        rows = self.storage.query(
            "SELECT 1 FROM cdb_cards WHERE genesys IS NOT NULL LIMIT 1")
        return bool(rows)

    def has_setinfo(self) -> bool:
        rows = self.storage.query("SELECT 1 FROM cdb_setinfo LIMIT 1")
        return bool(rows)

    def sets_of(self, card_id: int) -> list:
        """Le stampe di una carta, in ordine CRONOLOGICO di uscita del set.

        La data arriva da `cdb_setinfo` (endpoint a parte). Chi non ce l'ha
        — 5 set su 1.028, più tutto l'archivio finché non si risincronizza —
        finisce IN FONDO invece che in cima: una data mancante non deve
        spacciarsi per "uscito prima di tutti"."""
        # ATTENZIONE: nell'ORDER BY si ripete il COALESCE invece di usare
        # l'alias `tcg_date`. Con l'alias, SQLite lega il nome alla COLONNA
        # della tabella (che nel LEFT JOIN senza corrispondenza è NULL):
        # `NULL = ''` vale NULL, e i NULL in ASC finiscono per PRIMI — cioè i
        # set senza data comparivano in cima come se fossero i più vecchi.
        # Visto dal vivo, non ipotizzato.
        return self.storage.query(
            "SELECT s.set_name, s.set_code, s.rarity, "
            "       COALESCE(i.set_code, '') AS set_short, "
            "       COALESCE(i.tcg_date, '') AS tcg_date "
            "FROM cdb_sets s LEFT JOIN cdb_setinfo i ON i.set_name = s.set_name "
            "WHERE s.card_id = ? "
            "ORDER BY (COALESCE(i.tcg_date, '') = '') ASC, "
            "         COALESCE(i.tcg_date, '') ASC, s.set_code ASC",
            (int(card_id),))
