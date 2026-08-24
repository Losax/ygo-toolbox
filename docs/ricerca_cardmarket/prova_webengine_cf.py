"""QtWebEngine passa la sfida di Cloudflare di CardMarket? E il cookie che
ottiene si puo' riusare con `requests`?

Sono le due domande che decidono l'architettura:
- se passa, un Chromium serve SOLO a ottenere il permesso, non a ogni prezzo;
- se il cookie si riusa, i controlli successivi restano richieste HTTP normali
  (leggere, veloci, con il freno che il progetto ha gia').

Una pagina sola, con la finestra nascosta (WA_DontShowOnScreen: layout vero,
nessun lampo a schermo).
"""
import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt  # noqa: E402
from PySide6.QtWebEngineCore import QWebEngineProfile  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

URL = ("https://www.cardmarket.com/en/YuGiOh/Products/Singles/"
       "Legend-of-Blue-Eyes-White-Dragon/Mystical-Elf-V1-Super-Rare")
PROFILO = Path(__file__).parent / "cm_profilo"

app = QApplication(sys.argv)

profilo = QWebEngineProfile("cardmarket", app)
profilo.setPersistentStoragePath(str(PROFILO))
profilo.setCachePath(str(PROFILO / "cache"))
profilo.setPersistentCookiesPolicy(
    QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
print("User-Agent del motore:")
print("  ", profilo.httpUserAgent())

biscotti = {}
def su_cookie(c):
    biscotti[bytes(c.name()).decode()] = (bytes(c.value()).decode(),
                                          c.domain(), c.isHttpOnly())
profilo.cookieStore().cookieAdded.connect(su_cookie)

vista = QWebEngineView()
vista.setPage(__import__("PySide6.QtWebEngineCore", fromlist=["QWebEnginePage"])
              .QWebEnginePage(profilo, vista))
vista.resize(1200, 900)
vista.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
vista.show()

esito = {"html": "", "fatto": False, "t": None}
t0 = time.monotonic()


def guarda():
    def ricevuto(html):
        trascorso = round(time.monotonic() - t0, 1)
        if "article-row" in html:
            esito.update(html=html, fatto=True, t=trascorso)
            print(f"\n[t+{trascorso}s] PASSATA: la pagina vera e' arrivata "
                  f"({html.count('article-row')} righe di offerte, {len(html)} caratteri)")
            app.quit()
        elif time.monotonic() - t0 > 45:
            esito.update(html=html, fatto=False, t=trascorso)
            titolo = (html.split("<title>")[1].split("</title>")[0].strip()
                      if "<title>" in html else "?")
            print(f"\n[t+{trascorso}s] NON passata. titolo='{titolo}' len={len(html)}")
            app.quit()
        else:
            titolo = (html.split("<title>")[1].split("</title>")[0].strip()[:40]
                      if "<title>" in html else "?")
            print(f"  t+{trascorso}s  '{titolo}'  len={len(html)}")
    vista.page().toHtml(ricevuto)


orologio = QTimer()
orologio.setInterval(3000)
orologio.timeout.connect(guarda)
vista.load(QUrl(URL))
orologio.start()
QTimer.singleShot(60000, app.quit)
app.exec()

print("\n--- cookie raccolti ---")
for nome, (val, dom, http_only) in sorted(biscotti.items()):
    print(f"  {nome:24} dominio={dom:22} httpOnly={http_only} valore={val[:28]}…")
chiave = "cf_clearance" in biscotti
print("cf_clearance presente:", chiave)

if esito["fatto"] and chiave:
    print("\n--- il cookie si riusa con requests? ---")
    import requests
    ck = {n: v for n, (v, _d, _h) in biscotti.items()}
    r = requests.get(URL, timeout=25, cookies=ck, headers={
        "User-Agent": profilo.httpUserAgent(),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    print("  status:", r.status_code, "| cf-mitigated:", r.headers.get("cf-mitigated"),
          "| article-row:", r.text.count("article-row"), "| len:", len(r.content))

if esito["fatto"]:
    fuori = Path(PROFILO).parent / "cm_pagina.html"
    fuori.write_text(esito["html"], encoding="utf-8")
    print("\nHTML salvato in", fuori)
