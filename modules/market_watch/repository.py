"""Accesso al database per il Market Watch.

Tabelle (tutte con prefisso mw_ per non collidere con altri moduli):
- mw_watchlist:     le carte seguite (provider + id + soglia di calo %);
                    `position` = ordinamento manuale, `folder_id` = cartella
                    (NULL = fuori dalle cartelle);
- mw_folders:       cartelle espandibili della watchlist (nome, posizione,
                    stato espansa/chiusa persistito);
- mw_price_history: storico del prezzo PIÙ BASSO a ogni controllo;
- mw_last_quote:    ULTIMO annuncio scelto per carta (JSON; '' = "Nessuna
                    copia"). Una riga per carta (upsert): non cresce mai, e
                    si cancella insieme alla carta → niente dati orfani;
- mw_catalog:       cache locale del catalogo (per cercare le carte per nome);
- mw_settings:      chiave/valore (filtri globali, ultimo controllo, …).

Va usato solo dal thread della GUI (vedi nota in core/storage.py).
"""
from __future__ import annotations

import sqlite3

from core.storage import Storage


class MarketWatchRepository:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self._init_schema()

    def _init_schema(self) -> None:
        self.storage.execute(
            """
            CREATE TABLE IF NOT EXISTS mw_watchlist (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                provider      TEXT    NOT NULL,
                ref_id        TEXT    NOT NULL,
                card_name     TEXT    NOT NULL,
                detail        TEXT    NOT NULL DEFAULT '',
                threshold_pct REAL    NOT NULL DEFAULT 0.0,
                filters       TEXT    NOT NULL DEFAULT '',
                added_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE(provider, ref_id)
            )
            """
        )
        self.storage.execute(
            """
            CREATE TABLE IF NOT EXISTS mw_price_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                provider    TEXT    NOT NULL,
                ref_id      TEXT    NOT NULL,
                price       REAL    NOT NULL,
                currency    TEXT    NOT NULL DEFAULT 'EUR',
                captured_at TEXT    NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        self.storage.execute(
            """
            CREATE TABLE IF NOT EXISTS mw_catalog (
                provider  TEXT NOT NULL,
                ref_id    TEXT NOT NULL,
                name      TEXT NOT NULL,
                detail    TEXT NOT NULL DEFAULT '',
                image_url TEXT NOT NULL DEFAULT '',
                set_code  TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (provider, ref_id)
            )
            """
        )
        self.storage.execute(
            "CREATE INDEX IF NOT EXISTS idx_mw_catalog_name ON mw_catalog(provider, name)"
        )
        self.storage.execute(
            """
            CREATE TABLE IF NOT EXISTS mw_settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self.storage.execute(
            """
            CREATE TABLE IF NOT EXISTS mw_last_quote (
                provider    TEXT NOT NULL,
                ref_id      TEXT NOT NULL,
                quote       TEXT NOT NULL DEFAULT '',
                captured_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (provider, ref_id)
            )
            """
        )
        # Migrazione per DB creati prima dell'aggiunta dell'anteprima:
        # CREATE TABLE IF NOT EXISTS non aggiorna le tabelle esistenti.
        for col in ("image_url", "set_code"):
            try:
                self.storage.execute(f"ALTER TABLE mw_catalog ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError:
                pass  # la colonna esiste già
        try:  # filtri per singola carta (override di quelli globali)
            self.storage.execute("ALTER TABLE mw_watchlist ADD COLUMN filters TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        self.storage.execute(
            """
            CREATE TABLE IF NOT EXISTS mw_folders (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT    NOT NULL,
                name     TEXT    NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                expanded INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        # ordinamento manuale + cartelle per la watchlist
        for col, decl in (("position", "INTEGER NOT NULL DEFAULT 0"),
                          ("folder_id", "INTEGER")):
            try:
                self.storage.execute(f"ALTER TABLE mw_watchlist ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass

    # --- watchlist ---
    def add_watch(self, provider, ref_id, card_name, detail, threshold_pct) -> None:
        self.storage.execute(
            "INSERT OR IGNORE INTO mw_watchlist "
            "(provider, ref_id, card_name, detail, threshold_pct, position) "
            "VALUES (?, ?, ?, ?, ?, "
            " (SELECT COALESCE(MAX(position), 0) + 1 FROM mw_watchlist WHERE provider = ?))",
            (provider, str(ref_id), card_name, detail, threshold_pct, provider),
        )

    def remove_watch(self, watch_id) -> tuple[str, str] | None:
        """Rimuove la carta E i suoi dati collegati (storico, ultimo annuncio):
        così il DB non accumula informazioni di carte non più seguite.
        Ritorna (provider, ref_id) della carta rimossa, o None se non c'era."""
        rows = self.storage.query(
            "SELECT provider, ref_id FROM mw_watchlist WHERE id = ?", (watch_id,)
        )
        self.storage.execute("DELETE FROM mw_watchlist WHERE id = ?", (watch_id,))
        if not rows:
            return None
        provider, ref_id = rows[0]["provider"], rows[0]["ref_id"]
        self.storage.execute(
            "DELETE FROM mw_price_history WHERE provider = ? AND ref_id = ?", (provider, ref_id)
        )
        self.storage.execute(
            "DELETE FROM mw_last_quote WHERE provider = ? AND ref_id = ?", (provider, ref_id)
        )
        return provider, ref_id

    def set_watch_filters(self, watch_id, filters_json: str) -> None:
        """Filtri della singola carta (JSON) o '' per usare i filtri globali."""
        self.storage.execute(
            "UPDATE mw_watchlist SET filters = ? WHERE id = ?", (filters_json, watch_id)
        )

    def list_watches(self) -> list:
        # position = ordinamento manuale (drag&drop); a parità (DB storici,
        # tutte 0) si ricade sull'ordine alfabetico di prima.
        return self.storage.query(
            "SELECT * FROM mw_watchlist ORDER BY position, card_name, detail")

    # --- cartelle della watchlist ---
    def list_folders(self, provider) -> list:
        return self.storage.query(
            "SELECT * FROM mw_folders WHERE provider = ? ORDER BY position, id", (provider,)
        )

    def add_folder(self, provider, name) -> int:
        cur = self.storage.execute(
            "INSERT INTO mw_folders (provider, name, position) VALUES (?, ?, "
            " (SELECT COALESCE(MAX(position), 0) + 1 FROM mw_folders WHERE provider = ?))",
            (provider, name, provider),
        )
        return cur.lastrowid

    def rename_folder(self, folder_id, name) -> None:
        self.storage.execute("UPDATE mw_folders SET name = ? WHERE id = ?", (name, folder_id))

    def set_folder_expanded(self, folder_id, expanded: bool) -> None:
        self.storage.execute(
            "UPDATE mw_folders SET expanded = ? WHERE id = ?", (1 if expanded else 0, folder_id)
        )

    def delete_folder(self, folder_id) -> None:
        """Elimina la cartella; le sue carte tornano fuori (folder_id NULL)."""
        self.storage.execute(
            "UPDATE mw_watchlist SET folder_id = NULL WHERE folder_id = ?", (folder_id,)
        )
        self.storage.execute("DELETE FROM mw_folders WHERE id = ?", (folder_id,))

    def set_folder_positions(self, pairs) -> None:
        """pairs: iterabile di (folder_id, position)."""
        self.storage.executemany(
            "UPDATE mw_folders SET position = ? WHERE id = ?",
            [(pos, fid) for fid, pos in pairs],
        )

    def set_watch_layout(self, triples) -> None:
        """triples: iterabile di (watch_id, folder_id|None, position) —
        riscrive collocazione e ordine dopo un drag&drop (normalizzati)."""
        self.storage.executemany(
            "UPDATE mw_watchlist SET folder_id = ?, position = ? WHERE id = ?",
            [(fid, pos, wid) for wid, fid, pos in triples],
        )

    # --- storico prezzi ---
    def record_price(self, provider, ref_id, price, currency) -> None:
        """Aggiunge un punto allo storico SOLO se il prezzo è cambiato rispetto
        all'ultimo registrato: lo storico è la serie dei CAMBI di prezzo.
        Così controlli ravvicinati (es. quello automatico all'avvio) non
        azzerano la Var.% né gonfiano la tabella con duplicati."""
        if self.last_price(provider, ref_id) == price:
            return
        self.storage.execute(
            "INSERT INTO mw_price_history (provider, ref_id, price, currency) VALUES (?, ?, ?, ?)",
            (provider, str(ref_id), price, currency),
        )

    def last_price(self, provider, ref_id) -> float | None:
        rows = self.storage.query(
            "SELECT price FROM mw_price_history WHERE provider = ? AND ref_id = ? "
            "ORDER BY captured_at DESC, id DESC LIMIT 1",
            (provider, str(ref_id)),
        )
        return rows[0]["price"] if rows else None

    def last_price_change(self, provider, ref_id) -> list[float]:
        """[ultimo prezzo, ultimo prezzo DIVERSO precedente] (o meno elementi
        se non c'è abbastanza storia). La Var.% si calcola sull'ultimo CAMBIO
        di prezzo, non sull'ultimo controllo: robusto anche sui DB vecchi che
        contengono controlli consecutivi con lo stesso prezzo."""
        rows = self.storage.query(
            "SELECT price FROM mw_price_history WHERE provider = ? AND ref_id = ? "
            "ORDER BY captured_at DESC, id DESC LIMIT 1",
            (provider, str(ref_id)),
        )
        if not rows:
            return []
        last = rows[0]["price"]
        prev = self.storage.query(
            "SELECT price FROM mw_price_history WHERE provider = ? AND ref_id = ? "
            "AND price != ? ORDER BY captured_at DESC, id DESC LIMIT 1",
            (provider, str(ref_id), last),
        )
        return [last, prev[0]["price"]] if prev else [last]

    # --- ultimo annuncio per carta (persistenza tra i riavvii) ---
    def set_last_quotes(self, provider, items) -> None:
        """items: iterabile di (ref_id, quote_json); '' = nessun annuncio
        conforme ai filtri ("Nessuna copia"). Upsert: una sola riga per carta."""
        self.storage.executemany(
            "INSERT OR REPLACE INTO mw_last_quote (provider, ref_id, quote, captured_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            [(provider, str(ref_id), quote_json) for ref_id, quote_json in items],
        )

    def load_last_quotes(self, provider) -> list:
        return self.storage.query(
            "SELECT ref_id, quote FROM mw_last_quote WHERE provider = ?", (provider,)
        )

    def delete_setting(self, key) -> None:
        self.storage.execute("DELETE FROM mw_settings WHERE key = ?", (key,))

    # --- igiene del DB (chiamate all'avvio: economiche e idempotenti) ---
    def cleanup_orphans(self, provider) -> None:
        """Elimina storico/ultimo annuncio di carte non più in watchlist
        (es. dati rimasti da versioni precedenti alla pulizia in remove_watch)."""
        for table in ("mw_price_history", "mw_last_quote"):
            self.storage.execute(
                f"DELETE FROM {table} WHERE provider = ? AND ref_id NOT IN "
                "(SELECT ref_id FROM mw_watchlist WHERE provider = ?)",
                (provider, provider),
            )

    def prune_history(self, days: int = 90) -> None:
        """Sfoltisce lo storico: oltre `days` giorni tiene solo il prezzo
        MINIMO di ogni giornata per carta (basta e avanza per un grafico).
        Con l'auto-controllo ogni 30 min lo storico passerebbe da ~48 a
        1 riga/giorno/carta per i dati vecchi."""
        cutoff = f"-{int(days)} days"
        self.storage.execute(
            "DELETE FROM mw_price_history WHERE captured_at < datetime('now', ?) "
            "AND id NOT IN (SELECT id FROM ("
            "    SELECT id, MIN(price) FROM mw_price_history "
            "    WHERE captured_at < datetime('now', ?) "
            "    GROUP BY provider, ref_id, date(captured_at)"
            "))",
            (cutoff, cutoff),
        )

    # --- catalogo (cache per la ricerca per nome) ---
    def replace_catalog(self, provider, rows) -> None:
        """rows: iterabile di (ref_id, name, detail, image_url, set_code)."""
        self.storage.execute("DELETE FROM mw_catalog WHERE provider = ?", (provider,))
        self.storage.executemany(
            "INSERT OR REPLACE INTO mw_catalog (provider, ref_id, name, detail, image_url, set_code) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(provider, str(r[0]), r[1], r[2],
              r[3] if len(r) > 3 else "", r[4] if len(r) > 4 else "") for r in rows],
        )

    def catalog_count(self, provider) -> int:
        rows = self.storage.query(
            "SELECT COUNT(*) AS n FROM mw_catalog WHERE provider = ?", (provider,)
        )
        return rows[0]["n"] if rows else 0

    def all_catalog(self, provider) -> list:
        """Tutto il catalogo (per la ricerca live in memoria), ordinato per nome."""
        return self.storage.query(
            "SELECT ref_id, name, detail, image_url, set_code FROM mw_catalog "
            "WHERE provider = ? ORDER BY name",
            (provider,),
        )

    def catalog_set_code(self, provider, ref_id) -> str | None:
        """Codice del set (es. 'LOB') dal catalogo; None/'' se non presente."""
        rows = self.storage.query(
            "SELECT set_code FROM mw_catalog WHERE provider = ? AND ref_id = ?",
            (provider, str(ref_id)),
        )
        return (rows[0]["set_code"] or "").upper() if rows else None

    def catalog_image(self, provider, ref_id) -> str | None:
        rows = self.storage.query(
            "SELECT image_url FROM mw_catalog WHERE provider = ? AND ref_id = ?",
            (provider, str(ref_id)),
        )
        return rows[0]["image_url"] if rows else None

    def search_catalog(self, provider, query, limit: int = 25) -> list:
        return self.storage.query(
            "SELECT ref_id, name, detail FROM mw_catalog "
            "WHERE provider = ? AND name LIKE ? ORDER BY name LIMIT ?",
            (provider, f"%{query}%", limit),
        )

    # --- impostazioni (chiave/valore) ---
    def get_setting(self, key, default=None):
        rows = self.storage.query("SELECT value FROM mw_settings WHERE key = ?", (key,))
        return rows[0]["value"] if rows else default

    def set_setting(self, key, value) -> None:
        self.storage.execute(
            "INSERT OR REPLACE INTO mw_settings (key, value) VALUES (?, ?)",
            (key, value),
        )

    def catalog_name(self, provider, ref_id) -> str | None:
        rows = self.storage.query(
            "SELECT name FROM mw_catalog WHERE provider = ? AND ref_id = ?",
            (provider, str(ref_id)),
        )
        return rows[0]["name"] if rows else None
