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


#: La spaziatura fra le chiamate all'API, imparata dal limitatore durante
#: l'uso. Sta in un FILE e non nelle impostazioni di un modulo perché il
#: limitatore è **uno solo** per tutta l'app: con una copia per modulo, chi si
#: costruisce per ultimo sovrascriveva quella degli altri e la calibrazione di
#: una sessione intera finiva nel cestino a ogni avvio.
INTERVAL_FILE = "api_interval.txt"


def load_interval(data_dir: Path) -> float:
    """La spaziatura salvata, o 0 se non c'è (o non si legge)."""
    percorso = Path(data_dir) / INTERVAL_FILE
    try:
        return float(percorso.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0.0


def save_interval(data_dir: Path, secondi: float) -> None:
    try:
        percorso = Path(data_dir) / INTERVAL_FILE
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_text(f"{float(secondi):.3f}", encoding="utf-8")
    except OSError:
        pass          # una preferenza di comodo: se non si scrive, pazienza


def save_token(data_dir: Path, token: str) -> None:
    path = _token_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token.strip(), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
