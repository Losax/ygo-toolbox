"""Il permesso di Cloudflare vale anche fuori da Chromium?

E' LA domanda architetturale: se cf_clearance si riusa con `requests`, il
Chromium serve una volta sola (prendere il permesso) e i controlli restano
richieste HTTP leggere. Se non si riusa, ogni prezzo costa un Chromium.

Il cookie e' appena stato preso dal motore: stesso IP, stesso minuto. L'unica
cosa che cambia e' CHI fa la richiesta (requests/OpenSSL invece di Chromium).
"""
import shutil, sqlite3, sys, pathlib, datetime
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) QtWebEngine/6.11.1 Chrome/140.0.0.0 Safari/537.36")
URL = ("https://www.cardmarket.com/en/YuGiOh/Products/Singles/"
       "Legend-of-Blue-Eyes-White-Dragon/Mystical-Elf-V1-Super-Rare")

src = pathlib.Path("cm_profilo/Cookies")
tmp = pathlib.Path("cookies_ora.sqlite")
shutil.copy(src, tmp)
c = sqlite3.connect(tmp)
ck, eta = {}, {}
for nome, val, host, creato in c.execute(
        "select name, value, host_key, creation_utc from cookies"):
    ck[nome] = val
    if creato:
        eta[nome] = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=creato)

print("cookie nel profilo (e quando sono nati):")
for n, v in ck.items():
    print(f"  {n:16} len={len(v):4}  nato={eta.get(n, '?')}")
print("\ncf_clearance presente:", "cf_clearance" in ck)

s = requests.Session()
r = s.get(URL, timeout=30, cookies=ck, headers={
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
})
print("\n--- requests, CON il cookie fresco del motore ---")
print("  status:", r.status_code)
print("  cf-mitigated:", r.headers.get("cf-mitigated"))
print("  server:", r.headers.get("server"), "| cf-ray:", r.headers.get("cf-ray"))
print("  righe di offerte:", r.text.count("article-row"), "| len:", len(r.content))
tit = r.text.split("<title>")[1].split("</title>")[0].strip() if "<title>" in r.text else "?"
print("  titolo:", tit[:70])
esito = "PASSA (il cookie si riusa)" if r.text.count("article-row") else "RESPINTO (il cookie non basta)"
print("\nESITO:", esito)
pathlib.Path("riuso_dump.html").write_text(r.text[:20000], encoding="utf-8")
