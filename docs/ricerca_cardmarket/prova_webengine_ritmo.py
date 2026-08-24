"""Quanto costa la SECONDA pagina, e la terza?

E' la domanda che decide se l'idea sta in piedi: se ogni carta della watchlist
costa 9 secondi di sfida Cloudflare, quaranta carte sono sei minuti. Se invece
la sfida si paga una volta e poi si naviga liberamente, il costo per carta e'
quello di una pagina normale.

Il profilo e' PERSISTENTE e riusa quello del giro precedente: quindi il primo
caricamento dice anche se il permesso sopravvive alla chiusura dell'app.
"""
import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

BASE = "https://www.cardmarket.com/en/YuGiOh/Products/Singles/Legend-of-Blue-Eyes-White-Dragon/"
PAGINE = ["Mystical-Elf-V1-Super-Rare", "Two-Pronged-Attack-V1-Rare", "Umi-V2-Common"]
PROFILO = Path(__file__).parent / "cm_profilo"

app = QApplication(sys.argv)
profilo = QWebEngineProfile("cardmarket", app)
profilo.setPersistentStoragePath(str(PROFILO))
profilo.setCachePath(str(PROFILO / "cache"))
profilo.setPersistentCookiesPolicy(
    QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)

vista = QWebEngineView()
vista.setPage(QWebEnginePage(profilo, vista))
vista.resize(1200, 900)
vista.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
vista.show()

stato = {"i": 0, "t0": 0.0, "sfide": 0}
esiti = []


def prossima():
    if stato["i"] >= len(PAGINE):
        app.quit()
        return
    stato["t0"] = time.monotonic()
    stato["sfide"] = 0
    vista.load(QUrl(BASE + PAGINE[stato["i"]]))
    QTimer.singleShot(700, controlla)


def controlla():
    def ricevuto(h):
        dt = time.monotonic() - stato["t0"]
        if "article-row" in h:
            esiti.append((PAGINE[stato["i"]], round(dt, 2), h.count("article-row"),
                          stato["sfide"]))
            print(f"  {PAGINE[stato['i']]:32} {dt:5.2f}s  "
                  f"{h.count('article-row'):3} offerte  sfide viste: {stato['sfide']}")
            stato["i"] += 1
            QTimer.singleShot(1200, prossima)      # un respiro fra le pagine
            return
        if "Just a moment" in h:
            stato["sfide"] += 1
        if dt > 40:
            esiti.append((PAGINE[stato["i"]], round(dt, 2), 0, stato["sfide"]))
            print(f"  {PAGINE[stato['i']]:32} SCADUTA dopo {dt:.0f}s")
            stato["i"] += 1
            QTimer.singleShot(500, prossima)
            return
        QTimer.singleShot(400, controlla)
    vista.page().toHtml(ricevuto)


print("carico tre pagine prodotto di seguito, stesso profilo:")
QTimer.singleShot(0, prossima)
QTimer.singleShot(150000, app.quit)
app.exec()

print("\n--- riepilogo ---")
for nome, dt, n, sfide in esiti:
    print(f"  {dt:5.2f}s  {n:3} offerte  sfida: {'si' if sfide else 'no'}  {nome}")
if esiti:
    tempi = [e[1] for e in esiti if e[2]]
    if tempi:
        print(f"\nprima pagina {tempi[0]:.2f}s | successive: "
              f"{', '.join(f'{t:.2f}s' for t in tempi[1:]) or '-'}")
