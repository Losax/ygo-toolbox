"""Gestione del token CardTrader.

Il token NON è scritto nel codice. Viene preso (in ordine):
1. dalla variabile d'ambiente CARDTRADER_TOKEN, se presente;
2. da un file locale in ~/.ygo_toolbox/cardtrader_token.txt.

Nota: il file è in chiaro nella tua home (con permessi 600 dove possibile).
Per un uso personale va bene; se ti serve più sicurezza, usa la variabile
d'ambiente o un keyring di sistema.
"""
from __future__ import annotations

import os
from pathlib import Path

TOKEN_ENV = "CARDTRADER_TOKEN"


def _token_path(data_dir: Path) -> Path:
    return Path(data_dir) / "cardtrader_token.txt"


def load_token(data_dir: Path) -> str | None:
    env = os.environ.get(TOKEN_ENV)
    if env and env.strip():
        return env.strip()
    path = _token_path(data_dir)
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        return value or None
    return None


def save_token(data_dir: Path, token: str) -> None:
    path = _token_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token.strip(), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
