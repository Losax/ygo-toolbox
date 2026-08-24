"""La combinazione CHE FUNZIONA: cookie del motore + impronta TLS di Chrome.

Trovata il 2026-08-24 dopo che `requests` era stato respinto (403
`cf-mitigated: challenge`) anche con un `cf_clearance` nato due minuti prima:
non e' il biscotto a mancare, e' l'handshake TLS a tradire chi chiama.

Il cookie e' legato a DUE cose insieme, e sbagliarne una sola basta a cadere:
  - lo User-Agent ESATTO che l'ha ottenuto (quello di QtWebEngine, non quello
    che curl_cffi manda per conto suo);
  - il profilo TLS: "chrome" (l'ultimo) passa, "chrome131" no.

Prerequisito: aver girato prima `prova_webengine_cf.py`, che crea `cm_profilo/`
con il `cf_clearance` dentro. Serve `pip install curl_cffi`.
"""
import shutil
import sqlite3
import time
from pathlib import Path

from curl_cffi import requests as cr

# lo User-Agent del motore che ha ottenuto il cookie: cambiando versione di
# PySide6 cambia anche questo, e il cookie non vale piu'
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) QtWebEngine/6.11.1 Chrome/140.0.0.0 Safari/537.36")
URL = ("https://www.cardmarket.com/en/YuGiOh/Products/Singles/"
       "Legend-of-Blue-Eyes-White-Dragon/Mystical-Elf-V1-Super-Rare")
PROFILO = Path(__file__).parent / "cm_profilo"

copia = Path(__file__).parent / "cookies_copia.sqlite"
shutil.copy(PROFILO / "Cookies", copia)          # il motore lo tiene aperto
ck = {n: v for n, v in sqlite3.connect(copia).execute(
    "select name, value from cookies")}
print("cookie nel profilo:", sorted(ck))
assert "cf_clearance" in ck, "manca cf_clearance: girare prima la sonda WebEngine"

print("\n--- cosa serve davvero ---")
prove = [
    ("solo cf_clearance",       {"cf_clearance": ck["cf_clearance"]}, UA, "chrome"),
    ("senza cf_clearance",      {k: v for k, v in ck.items() if k != "cf_clearance"}, UA, "chrome"),
    ("UA sbagliato",            {"cf_clearance": ck["cf_clearance"]}, None, "chrome"),
    ("profilo TLS sbagliato",   {"cf_clearance": ck["cf_clearance"]}, UA, "chrome131"),
]
for etichetta, cookie, ua, imp in prove:
    intestazioni = {"User-Agent": ua} if ua else {}
    t0 = time.monotonic()
    r = cr.get(URL, impersonate=imp, cookies=cookie, headers=intestazioni,
               timeout=30)
    print(f"  {etichetta:22} status={r.status_code} "
          f"offerte={r.text.count('article-row'):3} "
          f"{time.monotonic() - t0:.2f}s")
    time.sleep(2)                                 # mai raffiche

print("\n--- la sessione si rinnova da sola? ---")
s = cr.Session(impersonate="chrome", headers={"User-Agent": UA})
s.cookies.set("cf_clearance", ck["cf_clearance"], domain=".cardmarket.com")
for giro in range(3):
    r = s.get(URL, timeout=30)
    print(f"  giro {giro + 1}: status={r.status_code} "
          f"offerte={r.text.count('article-row'):3} "
          f"cookie={sorted(s.cookies.keys())}")
    time.sleep(3)
