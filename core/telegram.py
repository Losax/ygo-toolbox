"""Canale di notifica Telegram (fase 1 del "companion" mobile).

Il PC con l'app aperta fa da "server": quando un controllo trova un calo di
prezzo, oltre alla notifica di sistema parte un messaggio Telegram. È tutto
traffico IN USCITA: niente VPN, niente porte aperte sul router — e sul
telefono le notifiche arrivano anche ad app chiusa (push di Telegram).

Setup (una volta, da Opzioni): crea un bot con @BotFather → ottieni il token;
apri la chat col bot e premi /start; incolla il token e premi "Collega".
L'app scopre la chat via getUpdates, salva in ~/.ygo_toolbox/telegram.json e
manda un messaggio di prova.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import requests

CONFIG_FILE = Path.home() / ".ygo_toolbox" / "telegram.json"
API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 10


def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(token: str, chat_id: int, username: str = "") -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps({"token": token, "chat_id": chat_id, "username": username}),
        encoding="utf-8",
    )


def is_configured() -> bool:
    cfg = load_config()
    return bool(cfg.get("token") and cfg.get("chat_id"))


def linked_name() -> str:
    return load_config().get("username", "")


def discover_chat(token: str) -> tuple[int, str] | None:
    """Trova la chat privata dell'utente col bot (richiede un /start recente).

    Ritorna (chat_id, nome) dall'ultimo messaggio privato, o None se il bot
    non ha ancora ricevuto nulla. Chiamata BLOCCANTE (usarla da un'azione
    utente, non da timer)."""
    resp = requests.get(API.format(token=token, method="getUpdates"),
                        params={"limit": 20}, timeout=TIMEOUT)
    resp.raise_for_status()
    for update in reversed(resp.json().get("result", [])):
        chat = (update.get("message") or {}).get("chat") or {}
        if chat.get("type") == "private" and chat.get("id"):
            return chat["id"], chat.get("username") or chat.get("first_name", "")
    return None


def send(text: str) -> None:
    """Invio ASINCRONO (thread usa-e-getta): mai bloccare la GUI.

    No-op se non configurato; gli errori finiscono nel log (la notifica
    desktop è comunque già partita)."""
    cfg = load_config()
    if not (cfg.get("token") and cfg.get("chat_id")):
        return

    def _post() -> None:
        try:
            requests.post(API.format(token=cfg["token"], method="sendMessage"),
                          json={"chat_id": cfg["chat_id"], "text": text},
                          timeout=TIMEOUT)
        except requests.RequestException as exc:
            print(f"[telegram] invio fallito: {exc}")

    threading.Thread(target=_post, daemon=True).start()
