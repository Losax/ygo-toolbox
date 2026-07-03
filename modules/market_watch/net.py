"""Sessione HTTP condivisa per i download di immagini.

Riusare una sola `requests.Session` mantiene vive le connessioni (keep-alive) e
un pool, evitando un handshake TLS per ogni immagine: è la differenza più grossa
quando si scaricano molte miniature dallo stesso host. La Session di requests è
sicura per GET concorrenti da più thread (urllib3 gestisce il pool).
"""
from __future__ import annotations

import requests

SESSION = requests.Session()
_adapter = requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=12)
SESSION.mount("https://", _adapter)
SESSION.mount("http://", _adapter)
