"""Piccolo wrapper su SQLite condiviso da tutti i moduli.

Regola importante: questa connessione va usata SOLO dal thread della GUI.
Le operazioni di rete (lente) vanno fatte in un thread separato che NON
tocca il database; i risultati tornano alla GUI tramite segnali Qt e solo
lì si scrive su disco. Così evitiamo i problemi di SQLite multi-thread.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


class Storage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        cur = self._conn.execute(sql, params)
        self._conn.commit()
        return cur

    def executemany(self, sql: str, seq_of_params) -> sqlite3.Cursor:
        cur = self._conn.executemany(sql, seq_of_params)
        self._conn.commit()
        return cur

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        self._conn.close()
