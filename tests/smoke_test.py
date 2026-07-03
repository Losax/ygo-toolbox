"""Smoke test headless (offscreen, niente rete) per la versione CardTrader.

Verifica con dati finti:
1. estrazione del prezzo più basso da /marketplace/products (forme diverse);
2. parsing del catalogo (games -> expansions -> blueprints);
3. logica di avviso quando compare un prezzo più basso oltre soglia.

Esegui:  QT_QPA_PLATFORM=offscreen python tests/smoke_test.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("CARDTRADER_TOKEN", None)  # assicura provider assente nel test
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# La console Windows usa cp1252 e va in errore sui caratteri non-latini (es. la
# freccia '→' nei messaggi): forziamo UTF-8 sull'output così il test gira ovunque.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from PySide6.QtWidgets import QApplication  # noqa: E402

from core.context import AppContext, Notifier  # noqa: E402
from core.storage import Storage  # noqa: E402
from modules.market_watch.providers.base import PriceQuote  # noqa: E402
from modules.market_watch.providers.cardtrader import (  # noqa: E402
    CardTraderProvider,
    fetch_catalog,
)
from modules.market_watch.widget import MarketWatchWidget  # noqa: E402


class RecordingNotifier(Notifier):
    def __init__(self):
        super().__init__(None)
        self.messages = []

    def notify(self, title, message):
        self.messages.append((title, message))


class FakeClient:
    """Finto client CardTrader: restituisce JSON canned, niente rete."""

    def games(self):
        return [{"id": 4, "name": "Yu-Gi-Oh!", "display_name": "Yu-Gi-Oh!"},
                {"id": 1, "name": "Magic"}]

    def expansions(self):
        return [{"id": 100, "game_id": 4, "name": "Legend of Blue Eyes", "code": "lob"},
                {"id": 200, "game_id": 1, "name": "Alpha (non YGO)", "code": "alp"}]

    def blueprints(self, expansion_id, page=None):
        assert expansion_id == 100  # solo l'espansione YGO va interrogata
        # Simulo la paginazione (50/pagina): pagina 1 piena, pagina 2 = coda.
        page1 = [{"id": 1000 + i, "name": f"Filler {i}"} for i in range(50)]
        page2 = [{"id": 555, "name": "Blue-Eyes White Dragon", "version": "Ultra Rare"},
                 {"id": 556, "name": "Dark Magician", "version": "Secret Rare"}]
        if page in (None, 1):
            return page1
        if page == 2:
            return page2
        return []

    def marketplace_products(self, blueprint_id):
        # mescolo le due forme di prezzo per testare il parser difensivo
        return [
            {"price": {"cents": 1500, "currency": "EUR"}, "properties_hash": {"condition": "Near Mint"}},
            {"price_cents": 990, "price_currency": "EUR", "properties_hash": {"condition": "Played"}},
            {"price": {"cents": 1200, "currency": "EUR"}, "properties_hash": {"condition": "Excellent"}},
        ]


def main() -> int:
    app = QApplication(sys.argv)  # noqa: F841
    tmp = Path(tempfile.mkdtemp())
    storage = Storage(tmp / "test.db")
    notifier = RecordingNotifier()
    ctx = AppContext(storage=storage, notifier=notifier, data_dir=tmp)

    widget = MarketWatchWidget(ctx)
    fake = FakeClient()
    provider = CardTraderProvider(fake, widget.repo)

    # 1) prezzo più basso = 9.90 (campo piatto, condizione "Played")
    quote = provider.lowest_price("555")
    assert quote is not None and abs(quote.amount - 9.90) < 1e-6, quote
    print(f"[OK] Prezzo più basso estratto: {quote.amount:.2f} {quote.currency} ({quote.detail})")

    # 2) catalogo: solo le carte YGO (espansione 100), seguendo la paginazione
    rows = fetch_catalog(fake)
    names = {r[1] for r in rows}
    # 50 filler (pagina 1) + 2 carte reali (pagina 2): la paginazione le prende tutte
    assert len(rows) == 52, f"attese 52 carte (50+2), trovate {len(rows)}"
    assert {"Blue-Eyes White Dragon", "Dark Magician"} <= names, names
    assert all(len(r) == 5 for r in rows), "le righe devono avere anche image_url e set_code"
    assert all(r[4] == "LOB" for r in rows), "codice set (maiuscolo) non catturato"
    print(f"[OK] Catalogo paginato: {len(rows)} carte (50 filler + 2), set_code='LOB'")
    widget.repo.replace_catalog("cardtrader", rows)
    cat = widget.repo.all_catalog("cardtrader")
    assert cat and all(r["set_code"] == "LOB" for r in cat), "set_code non persistito nel catalogo"
    found = provider.search_cards("magician")
    assert len(found) == 1 and found[0].id == "556"
    # la rarità (campo 'version' del blueprint) deve finire nel detail
    assert "Secret Rare" in found[0].detail, found[0].detail
    print(f"[OK] Ricerca 'magician' -> {found[0].name} (id {found[0].id}) [{found[0].detail}]")

    # 3) avviso su nuovo prezzo più basso oltre soglia
    widget.repo.add_watch("cardtrader", "555", "Blue-Eyes White Dragon", "LOB", threshold_pct=5.0)
    widget.repo.record_price("cardtrader", "555", 20.00, "EUR")  # prezzo di partenza
    widget._on_prices([{"ref_id": "555", "quote": PriceQuote(17.00, "EUR", "NM")}])  # -15%
    assert notifier.messages, "Nessuna notifica su calo oltre soglia!"
    print(f"[OK] Notifica calo: {notifier.messages[-1][1]}")

    before = len(notifier.messages)
    widget._on_prices([{"ref_id": "555", "quote": PriceQuote(16.90, "EUR", "NM")}])  # -0.6%, sotto soglia
    assert len(notifier.messages) == before, "Notifica scattata sotto soglia!"
    print("[OK] Calo sotto soglia: nessuna notifica (corretto).")

    before = len(notifier.messages)
    widget._on_prices([{"ref_id": "555", "quote": PriceQuote(25.00, "EUR", "NM")}])  # rialzo
    assert len(notifier.messages) == before, "Notifica scattata su rialzo!"
    print("[OK] Rialzo: nessuna notifica (corretto).")

    # nessun annuncio conforme ai filtri (quote None) → "Nessuna copia", niente notifica
    before = len(notifier.messages)
    widget._on_prices([{"ref_id": "555", "quote": None}])
    assert "555" in widget._no_match_refs
    assert len(notifier.messages) == before, "Notifica scattata senza copia!"
    assert widget.table.item(0, 8).text() == "Nessuna copia", widget.table.item(0, 8).text()  # col 8 = Prezzo
    # deve persistere: un nuovo widget sulla stessa storage ricarica lo stato
    # (ora da mw_last_quote: riga con quote vuota = "Nessuna copia")
    import json as _json  # noqa: E402
    assert any(r["ref_id"] == "555" and not r["quote"]
               for r in widget.repo.load_last_quotes("cardtrader"))
    widget2 = MarketWatchWidget(ctx)
    assert "555" in widget2._no_match_refs, "stato 'nessuna copia' non ricaricato"
    assert widget2.table.item(0, 8).text() == "Nessuna copia", "al riavvio torna il prezzo stantio!"
    widget2.stop()
    print("[OK] 'Nessuna copia' persiste al riavvio (niente più prezzo stantio).")

    # 3b) l'ultimo annuncio (venditore, condizione, …) persiste al riavvio
    rich = PriceQuote(12.00, "EUR", "NM · IT · Zero", seller="mario", seller_type="pro",
                      country="IT", comment="spedizione tracciata", quantity=2,
                      condition="Near Mint", language="IT", first_edition=True, zero=True)
    widget._on_prices([{"ref_id": "555", "quote": rich}])
    widget3 = MarketWatchWidget(ctx)
    q3 = widget3._last_quotes.get("555")
    assert q3 is not None and (q3.seller, q3.condition, q3.zero) == ("mario", "Near Mint", True), q3
    assert "555" not in widget3._no_match_refs
    assert widget3.table.item(0, 4).text() == "Near Mint", "condizione non ricaricata al riavvio"
    assert widget3.table.item(0, 8).text() == "12.00 €", widget3.table.item(0, 8).text()
    widget3.stop()
    print("[OK] Ultimo annuncio persistito: Panoramica piena anche dopo il riavvio.")

    # 3b-bis) controlli ripetuti con lo stesso prezzo: lo storico non cresce e
    # la Var.% resta calcolata sull'ultimo CAMBIO di prezzo (25.00 → 12.00)
    n0 = len(widget.repo.storage.query("SELECT id FROM mw_price_history WHERE ref_id = '555'"))
    widget._on_prices([{"ref_id": "555", "quote": PriceQuote(12.00, "EUR", "NM")}])  # identico
    n1 = len(widget.repo.storage.query("SELECT id FROM mw_price_history WHERE ref_id = '555'"))
    assert n1 == n0, "un controllo con prezzo identico non deve aggiungere righe"
    pair = widget.repo.last_price_change("cardtrader", "555")
    assert pair == [12.00, 25.00], pair
    print("[OK] Var.% dall'ultimo cambio di prezzo (i ricontrolli non la azzerano).")

    # 3c) rimozione carta = pulizia completa (storico + ultimo annuncio)
    watch_id = [w for w in widget.repo.list_watches() if w["ref_id"] == "555"][0]["id"]
    widget._remove(watch_id)
    assert not widget.repo.storage.query("SELECT 1 FROM mw_price_history WHERE ref_id = '555'")
    assert not widget.repo.storage.query("SELECT 1 FROM mw_last_quote WHERE ref_id = '555'")
    assert "555" not in widget._last_quotes
    print("[OK] Rimozione: storico e ultimo annuncio eliminati (niente dati orfani).")

    # 3c-bis) opzioni di visualizzazione: rarità come badge, set come codice
    from modules.market_watch.rarity import rarity_abbrev, rarity_pixmap  # noqa: E402
    assert rarity_abbrev("Quarter Century Secret Rare") == "QCSR"
    assert rarity_abbrev("Secret Rare") == "ScR"
    assert rarity_abbrev("Ultra Rare") == "UR"
    assert rarity_abbrev("Common") == "C"
    assert rarity_abbrev("Weird Foil") == "WF"          # sconosciuta → iniziali
    assert not rarity_pixmap("Starlight Rare", 18).isNull()
    widget.repo.add_watch("cardtrader", "555", "Blue-Eyes White Dragon",
                          "Ultra Rare · Legend of Blue Eyes", 5.0)
    widget.repo.set_setting("display", _json.dumps({"rarity_icons": True, "set_codes": True}))
    wdisp = MarketWatchWidget(ctx)
    assert wdisp.table.cellWidget(0, 2) is not None, "badge rarità non renderizzato"
    assert wdisp.table.cellWidget(0, 3) is not None, "pill del codice set non renderizzata"
    assert wdisp.table.item(0, 3).text() == "", "col Set deve mostrare la pill, non testo"
    wdisp.stop()
    # ripristina lo stato per i blocchi successivi (rimozione ecc.)
    widget.repo.set_setting("display", "{}")
    widget._display = {}
    print("[OK] Visualizzazione: badge rarità + codice set (LOB) attivabili dalle Opzioni.")

    # 3d) migrazione del vecchio formato "no_match" (mw_settings → mw_last_quote)
    widget.repo.add_watch("cardtrader", "777", "Legacy Card", "", 0.0)
    widget.repo.set_setting("no_match", _json.dumps(["777"]))
    wtmp = MarketWatchWidget(ctx)
    assert "777" in wtmp._no_match_refs, "vecchio no_match non migrato"
    assert not widget.repo.get_setting("no_match"), "chiave legacy non rimossa"
    wtmp.stop()
    print("[OK] Migrazione 'no_match' dal vecchio formato: trasparente.")

    # 3e) cartelle: creazione, spostamento dentro/fuori, collasso, eliminazione
    wid555 = [w for w in widget.repo.list_watches() if w["ref_id"] == "555"][0]["id"]
    fid = widget.repo.add_folder("cardtrader", "Draghi")
    widget._move_watch(wid555, fid)
    widget._reload_table()
    kinds = [k for k, _ in widget._row_entries]
    assert kinds[0] == "folder", widget._row_entries
    assert any(k == "watch" and p["ref_id"] == "555" and p["folder_id"] == fid
               for k, p in widget._row_entries), "carta non spostata nella cartella"
    widget.repo.set_folder_expanded(fid, False)
    widget._reload_table()
    assert not any(k == "watch" and p["ref_id"] == "555" for k, p in widget._row_entries), \
        "carta visibile con cartella chiusa"
    widget.repo.set_folder_expanded(fid, True)
    widget._move_watch(wid555, None)      # fuori dalla cartella
    widget._delete_folder({"id": fid})    # via la cartella (vuota)
    assert not widget.repo.list_folders("cardtrader")
    assert any(k == "watch" and p["ref_id"] == "555" and p["folder_id"] is None
               for k, p in widget._row_entries), "carta persa dopo l'eliminazione della cartella"
    print("[OK] Cartelle: sposta dentro/fuori, chiusa nasconde le carte, eliminazione sicura.")

    # 4) filtri annunci: lingua/condizione/Zero decidono quali annunci contano
    from modules.market_watch.providers.base import ListingFilters  # noqa: E402
    from modules.market_watch.providers.cardtrader import _listing_matches  # noqa: E402

    listings = [
        {"price": {"cents": 1000, "currency": "EUR"}, "graded": False,
         "properties_hash": {"condition": "Near Mint", "yugioh_language": "it", "first_edition": True},
         "user": {"can_sell_via_hub": True, "user_type": "pro"}},
        {"price": {"cents": 800, "currency": "EUR"}, "graded": False,
         "properties_hash": {"condition": "Played", "yugioh_language": "en", "first_edition": False},
         "user": {"can_sell_via_hub": False, "user_type": "normal"}},
    ]
    assert _listing_matches(listings[0], ListingFilters(language="it", min_condition="Near Mint"))
    assert not _listing_matches(listings[1], ListingFilters(language="it", min_condition="Near Mint"))
    assert _listing_matches(listings[0], ListingFilters(zero_only=True))
    assert not _listing_matches(listings[1], ListingFilters(zero_only=True))

    # stampa americana (euristica): inglese + (venditore US oppure commento USA/American)
    from modules.market_watch.providers.cardtrader import _is_american_print  # noqa: E402
    en = lambda **kw: {"properties_hash": {"yugioh_language": "en"}, **kw}
    assert _is_american_print(en(user={"country_code": "US"}))                       # venditore US
    assert _is_american_print(en(description="American 1st edition"))                 # commento
    assert _is_american_print(en(description="Carta USA, near mint"))                 # commento USA
    assert _is_american_print(en(description="NA print, ottime condizioni"))          # NA print
    assert _is_american_print(en(description="North American printing"))              # North American
    assert not _is_american_print(en(user={"country_code": "IT"}, description="usato, ottimo stato"))  # 'usato' != USA
    assert not _is_american_print(en(user={"country_code": "IT"}, description="banana split promo"))   # 'banana' != NA print
    assert not _is_american_print(en(user={"country_code": "IT"}, description=""))    # nessun segnale
    de = {"properties_hash": {"yugioh_language": "de"}, "user": {"country_code": "US"}}
    assert not _is_american_print(de)  # tedesca: non può essere americana anche se venditore US
    print("[OK] Stampa americana: US/commento riconosciuti, 'usato' e non-inglese esclusi")

    class FilterFakeClient:
        def marketplace_products(self, blueprint_id):
            return {str(blueprint_id): listings}

    no_filter = CardTraderProvider(FilterFakeClient(), widget.repo)
    assert abs(no_filter.lowest_price("999").amount - 8.00) < 1e-6  # vince l'inglese da 8.00
    only_it = CardTraderProvider(FilterFakeClient(), widget.repo, ListingFilters(language="it"))
    q = only_it.lowest_price("999")
    assert q is not None and abs(q.amount - 10.00) < 1e-6, q  # l'inglese è escluso → 10.00
    # campi strutturati dell'annuncio scelto (colonne separate in Panoramica)
    assert (q.condition, q.language, q.first_edition, q.zero) == ("Near Mint", "IT", True, True), q
    print(f"[OK] Filtri: senza filtro 8.00€, con 'solo IT' {q.amount:.2f}€ ({q.detail})")
    print(f"[OK] Campi separati: cond={q.condition}, lingua={q.language}, "
          f"1ª ed.={q.first_edition}, Zero={q.zero}")

    # 5) dialogo filtri: la lingua è sempre modificabile; se non è inglese,
    # l'americana si spegne da sola (non blocca più il cambio lingua)
    from modules.market_watch.filters_dialog import FiltersDialog  # noqa: E402
    dlg = FiltersDialog(ListingFilters(american_only=True))
    assert dlg.language.currentData() == "en", "americana attiva deve partire da Inglese"
    assert dlg.language.isEnabled(), "la lingua non deve più essere bloccata"
    dlg._select(dlg.language, "it")
    assert not dlg.american.isChecked(), "cambiando lingua l'americana deve spegnersi"
    assert dlg.result_filters().language == "it"
    print("[OK] Filtri: lingua sempre modificabile, americana si spegne da sola.")

    # 6) i18n: traduzioni presenti, fallback sicuro, cambio lingua
    from core import i18n  # noqa: E402
    assert i18n.tr("Nessuna copia") == "Nessuna copia"      # default: italiano
    i18n._current = "en"
    assert i18n.tr("Nessuna copia") == "No copies"
    assert i18n.tr("Catalogo · {n} carte").format(n=5) == "Catalog · 5 cards"
    assert i18n.tr("stringa non mappata") == "stringa non mappata"  # fallback
    i18n._current = "it"
    print("[OK] i18n: inglese tradotto, chiavi ignote restano in italiano.")

    widget.stop()
    storage.close()
    print("\nTutti i controlli superati.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
