"""Catalogo delle STAMPE (blueprint) in sola lettura, condiviso fra i moduli.

Il catalogo di CardTrader — una riga per ogni *stampa* di ogni carta, con la
sua rarità, la sua espansione e il suo `ref_id` — è ciò che permette di
chiedere un prezzo. Lo scarica il Market Watch (è un'operazione da qualche
minuto, vedi `fetch_catalog`), ma da quando esiste la Collezione a leggerlo
sono in due.

**La tabella si chiama ancora `mw_catalog`.** Il nome è storico e resta:
rinominarla vorrebbe dire una migrazione su un database già in mano agli
utenti per guadagnare due lettere. Chi la CREA e la riempie è il Market Watch;
qui si legge soltanto — come `core/card_catalog.py` fa con `cdb_cards`.
"""
from __future__ import annotations

import sqlite3

from core.storage import Storage


def sincronizzato(storage: Storage, provider: str) -> bool:
    """C'è un catalogo utilizzabile? (tabella presente E con righe)

    Difensivo come il ponte verso il Database: chi non ha mai aperto il Market
    Watch non ha la tabella, e quello è uno stato normale — va invitato a
    sincronizzare, non fatto esplodere.
    """
    try:
        return count(storage, provider) > 0
    except sqlite3.Error:
        return False


def count(storage: Storage, provider: str) -> int:
    if not storage.query("SELECT name FROM sqlite_master "
                         "WHERE type='table' AND name='mw_catalog'"):
        return 0
    righe = storage.query(
        "SELECT COUNT(*) AS n FROM mw_catalog WHERE provider = ?", (provider,))
    return righe[0]["n"] if righe else 0


def search_names(storage: Storage, provider: str, query: str,
                 limit: int = 30) -> list[str]:
    """I NOMI di carta che contengono `query`, senza ripetizioni.

    Una carta ha decine di stampe: cercando per nome si vuole la carta, e le
    stampe si scelgono dopo. Prima i nomi che *iniziano* con quello che si sta
    scrivendo — è quasi sempre quello che si cerca.
    """
    if not query.strip() or not count(storage, provider):
        return []
    q = query.strip()
    righe = storage.query(
        "SELECT DISTINCT name FROM mw_catalog "
        "WHERE provider = ? AND name LIKE ? "
        "ORDER BY (name LIKE ?) DESC, name LIMIT ?",
        (provider, f"%{q}%", f"{q}%", int(limit)))
    return [r["name"] for r in righe]


def printings(storage: Storage, provider: str, name: str) -> list:
    """Tutte le stampe di una carta, per NOME esatto, ordinate per espansione."""
    if not count(storage, provider):
        return []
    return storage.query(
        "SELECT ref_id, name, detail, image_url, set_code FROM mw_catalog "
        "WHERE provider = ? AND name = ? ORDER BY set_code, detail",
        (provider, name))


def by_ref(storage: Storage, provider: str, ref_id: str):
    """La riga di catalogo di UNA stampa, o None se il catalogo non la conosce."""
    if not count(storage, provider):
        return None
    righe = storage.query(
        "SELECT ref_id, name, detail, image_url, set_code FROM mw_catalog "
        "WHERE provider = ? AND ref_id = ?", (provider, str(ref_id)))
    return righe[0] if righe else None


def search_rows(storage: Storage, provider: str, query: str, limit: int = 25) -> list:
    """Stampe il cui NOME contiene `query` (per la ricerca del provider)."""
    if not count(storage, provider):
        return []
    return storage.query(
        "SELECT ref_id, name, detail FROM mw_catalog "
        "WHERE provider = ? AND name LIKE ? ORDER BY name LIMIT ?",
        (provider, f"%{query}%", int(limit)))
