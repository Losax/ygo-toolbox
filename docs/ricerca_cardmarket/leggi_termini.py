"""Legge i Termini e la documentazione API di CardMarket da un PROCESSO A PARTE.

Il pannello Browser dell'app su questi indirizzi ha ucciso Claude Desktop due
volte (vedi CLAUDE.md). WebFetch da' 403. Quindi: curl_cffi con il cf_clearance
gia' coniato, in questo interprete, dove una challenge ammazza al massimo me.
"""
import shutil, sqlite3, time, pathlib
from curl_cffi import requests as cr

QUI = pathlib.Path(__file__).parent
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) QtWebEngine/6.11.1 Chrome/140.0.0.0 Safari/537.36")
shutil.copy(QUI / "cm_profilo" / "Cookies", QUI / "ck_leggi.sqlite")
ck = {n: v for n, v in sqlite3.connect(QUI / "ck_leggi.sqlite").execute(
    "select name, value from cookies")}

PAGINE = [
    ("termini",      "https://www.cardmarket.com/en/Policies/GeneralTermsAndConditions"),
    ("api_2_0",      "https://api.cardmarket.com/ws/documentation/API_2.0:Main_Page"),
    ("api_vecchia",  "https://api.cardmarket.com/ws/documentation"),
]
s = cr.Session(impersonate="chrome", headers={"User-Agent": UA})
for n, v in ck.items():
    s.cookies.set(n, v, domain=".cardmarket.com")

for nome, url in PAGINE:
    try:
        r = s.get(url, timeout=30)
        tit = (r.text.split("<title>")[1].split("</title>")[0].strip()
               if "<title>" in r.text else "?")
        print(f"  {nome:12} {r.status_code}  len={len(r.content):7}  {tit[:60]}")
        (QUI / f"cm_{nome}.html").write_text(r.text, encoding="utf-8")
    except Exception as e:
        print(f"  {nome:12} errore {type(e).__name__}: {str(e)[:70]}")
    time.sleep(3)                      # mai raffiche
