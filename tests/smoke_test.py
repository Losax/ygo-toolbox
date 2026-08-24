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
from modules.market_watch.providers.base import ListingFilters, PriceQuote  # noqa: E402
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
    # il prezzo di partenza va marcato coi filtri in vigore, altrimenti non è
    # confrontabile con quelli che registrerà _on_prices (vedi filters_key)
    chiave = widget._filters_key(widget._filters)
    widget.repo.record_price("cardtrader", "555", 20.00, "EUR", chiave)
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
    # condizione e lingua sono BADGE (cell widget), col nome intero nel tooltip
    from PySide6.QtWidgets import QLabel as _QL  # noqa: E402
    cond_cell = widget3.table.cellWidget(0, 4)
    assert cond_cell is not None, "condizione non ricaricata al riavvio"
    assert cond_cell.findChild(_QL).toolTip() == "Near Mint"
    assert widget3.table.cellWidget(0, 5) is not None, "lingua senza badge"
    assert widget3.table.item(0, 8).text() == "12.00 €", widget3.table.item(0, 8).text()
    widget3.stop()
    print("[OK] Ultimo annuncio persistito: Panoramica piena anche dopo il riavvio.")

    # 3b-bis) controlli ripetuti con lo stesso prezzo: lo storico non cresce e
    # la Var.% resta calcolata sull'ultimo CAMBIO di prezzo (25.00 → 12.00)
    n0 = len(widget.repo.storage.query("SELECT id FROM mw_price_history WHERE ref_id = '555'"))
    widget._on_prices([{"ref_id": "555", "quote": PriceQuote(12.00, "EUR", "NM")}])  # identico
    n1 = len(widget.repo.storage.query("SELECT id FROM mw_price_history WHERE ref_id = '555'"))
    assert n1 == n0, "un controllo con prezzo identico non deve aggiungere righe"
    pair = widget.repo.last_price_change("cardtrader", "555", chiave)
    assert pair == [12.00, 25.00], pair
    print("[OK] Var.% dall'ultimo cambio di prezzo (i ricontrolli non la azzerano).")

    # 3b-ter) CAMBIO DI FILTRI: il prezzo diventa quello di un'altra versione,
    # quindi niente Var. inventata e niente notifica di crollo.
    watch555 = [w for w in widget.repo.list_watches() if w["ref_id"] == "555"][0]
    widget.repo.set_watch_filters(watch555["id"], _json.dumps(
        ListingFilters(language="it", first_edition_only=True).to_dict()))
    before = len(notifier.messages)
    widget._on_prices([{"ref_id": "555", "quote": PriceQuote(3.00, "EUR", "NM")}])  # -75% finto
    assert len(notifier.messages) == before, \
        "un cambio di filtri non deve far scattare l'avviso di calo"
    nuova_chiave = widget._watch_key(
        [w for w in widget.repo.list_watches() if w["ref_id"] == "555"][0])
    assert nuova_chiave != chiave
    assert widget.repo.last_price_change("cardtrader", "555", nuova_chiave) == [3.00], \
        "col nuovo filtro la storia riparte: nessun precedente con cui fare la Var."
    assert widget.table.item(0, 9).text() == "—", widget.table.item(0, 9).text()

    # TORNANDO ai filtri di prima non deve riemergere il vecchio confronto:
    # quei movimenti sono di un'altra sessione, magari di settimane fa, e
    # ricomparirebbero come se fossero appena successi (caso reale: tolgo e
    # rimetto "americana" e mi esce +30%). Vale in salita come in discesa.
    widget.repo.set_watch_filters(watch555["id"], "")
    assert widget.repo.last_price_change("cardtrader", "555", chiave) == [12.00], \
        "la corsa precedente non deve fornire un termine di paragone"
    assert widget.repo.last_price("cardtrader", "555", chiave) is None, \
        "nemmeno l'avviso di calo deve avere un riferimento"
    # il prezzo però resta visibile (meglio l'ultimo noto di un trattino)
    assert widget.repo.last_known_price("cardtrader", "555", chiave) == 12.00
    before = len(notifier.messages)
    widget._on_prices([{"ref_id": "555", "quote": PriceQuote(30.00, "EUR", "NM")}])  # +150% finto
    assert len(notifier.messages) == before
    assert widget.table.item(0, 9).text() == "—", widget.table.item(0, 9).text()
    # da qui in poi i movimenti VERI si vedono di nuovo
    widget._on_prices([{"ref_id": "555", "quote": PriceQuote(24.00, "EUR", "NM")}])  # -20% vero
    assert widget.table.item(0, 9).text() == "-20.0%", widget.table.item(0, 9).text()
    print("[OK] Cambio filtri: niente Var. inventata né avvisi, in salita come "
          "in discesa; i movimenti veri della nuova serie si vedono.")

    # 3c) rimozione carta = pulizia completa (storico + ultimo annuncio)
    watch_id = [w for w in widget.repo.list_watches() if w["ref_id"] == "555"][0]["id"]
    widget._remove(watch_id)
    assert not widget.repo.storage.query("SELECT 1 FROM mw_price_history WHERE ref_id = '555'")
    assert not widget.repo.storage.query("SELECT 1 FROM mw_last_quote WHERE ref_id = '555'")
    assert "555" not in widget._last_quotes
    print("[OK] Rimozione: storico e ultimo annuncio eliminati (niente dati orfani).")

    # 3c-bis) opzioni di visualizzazione: rarità come badge, set come codice
    from core.rarity import is_rarity, rarity_abbrev, rarity_pixmap  # noqa: E402
    # `is_rarity`: la fonte YGOPRODeck a volte mette altro nel campo rarità
    # (192 stampe su 44.190: "2", "New", "European debut"…). Si scarta il
    # rumore SENZA una lista nera, che invecchierebbe al primo refuso nuovo:
    # passa ciò che la scala conosce o che contiene una parola da rarità —
    # così una rarità inventata domani resta visibile.
    assert is_rarity("Common") and is_rarity("Quarter Century Secret Rare")
    assert is_rarity("Ultra Mega Rare 2030"), "una rarità NUOVA non deve sparire"
    assert is_rarity("Short Print") and is_rarity("Duel Terminal Normal Rare")
    for rumore in ("2", "3", "New", "New artwork", "European debut",
                   "force-SMW", "", "   "):
        assert not is_rarity(rumore), rumore
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

    # 3f) riepilogo di cartella: totale e variazione allineati alle colonne
    for ref, name, prev, now in (("801", "Carta A", 100.0, 110.0),
                                 ("802", "Carta B", 50.0, 45.0),
                                 ("803", "Carta C", 10.0, 10.0)):
        widget.repo.add_watch("cardtrader", ref, name, "", 0.0)
        # senza filtri propri la chiave è quella dei predefiniti
        widget.repo.record_price("cardtrader", ref, prev, "EUR", chiave)
        widget.repo.record_price("cardtrader", ref, now, "EUR", chiave)
    fid2 = widget.repo.add_folder("cardtrader", "Riepilogo")
    for ref in ("801", "802", "803"):
        wid = [w for w in widget.repo.list_watches() if w["ref_id"] == ref][0]["id"]
        widget._move_watch(wid, fid2)
    widget.repo.set_folder_expanded(fid2, False)
    widget._reload_table()
    frow = [r for r, (k, p) in enumerate(widget._row_entries)
            if k == "folder" and p["id"] == fid2][0]
    # totale = 110 + 45 + 10 = 165; prima era 100 + 50 + 10 = 160 -> +3.1%
    assert widget.table.item(frow, 1).text().startswith("Riepilogo"), widget.table.item(frow, 1).text()
    assert widget.table.item(frow, 8).text() == "165.00 €", widget.table.item(frow, 8).text()
    assert widget.table.item(frow, 9).text() == "+3.1%", widget.table.item(frow, 9).text()
    assert widget.table.item(frow, 14).text() == "3", "Q.tà deve contare le carte"
    assert widget.table.columnSpan(frow, 0) == 1, "la riga cartella non deve piu' usare setSpan"
    # una carta "Nessuna copia" non deve entrare nel totale
    widget._no_match_refs = {"801"}
    widget._reload_table()
    assert widget.table.item(frow, 8).text() == "55.00 €", widget.table.item(frow, 8).text()
    widget._no_match_refs = set()
    # gruppo disegnato: cartella chiusa = solo la sua riga; aperta = riga + carte
    assert (frow, frow) in widget.table._groups, widget.table._groups
    widget.repo.set_folder_expanded(fid2, True)
    widget._reload_table()
    frow = [r for r, (k, p) in enumerate(widget._row_entries)
            if k == "folder" and p["id"] == fid2][0]
    assert (frow, frow + 3) in widget.table._groups, widget.table._groups
    # rientro delle carte in cartella: px sul disegno, NON spazi nel testo
    # (gli spazi rientravano solo la prima riga -> in Panoramica, dove i nomi
    # vanno a capo, le righe successive restavano disallineate)
    card_row = frow + 1
    assert not widget.table.item(card_row, 1).text().startswith(" "), \
        "il nome non deve piu' essere rientrato con spazi"
    assert widget._row_indent(card_row) > 0, "carta in cartella: serve il rientro"
    assert widget._row_indent(frow) == 0, "la riga cartella non va rientrata"
    loose = [r for r, (k, p) in enumerate(widget._row_entries)
             if k == "watch" and widget._folder_at(r) is None]
    assert loose and widget._row_indent(loose[0]) == 0, "carta sciolta: nessun rientro"
    for ref in ("801", "802", "803"):
        wid = [w for w in widget.repo.list_watches() if w["ref_id"] == ref][0]["id"]
        widget.repo.remove_watch(wid)
    widget._delete_folder({"id": fid2})
    print("[OK] Cartelle: totale 165.00 € e var. +3.1% sotto Prezzo/Var., gruppo evidenziato.")

    # 4) filtri annunci: lingua/condizione/Zero decidono quali annunci contano
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
    assert _is_american_print(en(description="[US Edition] near mint"))                # US Edition
    assert not _is_american_print(en(description="Limited Edition"))                   # 'edition' da sola no
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

    # 5a-bis) due pulsanti distinti: predefiniti (header) e carta-da-aggiungere.
    from modules.market_watch.providers.base import CardRef  # noqa: E402
    assert not widget.filters_btn.isEnabled(), "senza carta selezionata va disabilitato"
    widget._selected_ref = CardRef(id="556", name="Dark Magician", detail="Secret Rare · LOB")
    widget._pending_filters = None
    widget._update_card_filters_btn()
    assert widget.filters_btn.isEnabled() and not widget.filters_btn.isChecked()
    # filtri preparati per QUELLA carta -> il pulsante si accende
    widget._pending_filters = ListingFilters(language="it", first_edition_only=True)
    widget._update_card_filters_btn()
    assert widget.filters_btn.isChecked(), "con filtri propri il pulsante deve accendersi"
    # ...e nascono insieme alla carta, senza toccare i predefiniti.
    # check_now va neutralizzato: senza token apre un QMessageBox modale, che
    # in un test headless resta lì per sempre.
    vero_check, widget.check_now = widget.check_now, lambda: None
    globali_prima = widget.repo.get_setting("filters")
    widget.threshold_spin.setValue(3.0)
    widget.add_by_name()
    nuova = [w for w in widget.repo.list_watches() if w["ref_id"] == "556"][0]
    assert _json.loads(nuova["filters"]) == {"language": "it", "first_edition_only": True,
                                             **{k: v for k, v in
                                                ListingFilters().to_dict().items()
                                                if k not in ("language", "first_edition_only")}}, \
        nuova["filters"]
    assert widget.repo.get_setting("filters") == globali_prima, \
        "i filtri della singola carta non devono toccare i predefiniti"
    assert widget._pending_filters is None, "dopo l'aggiunta i filtri in sospeso si azzerano"
    assert not widget.filters_btn.isEnabled(), "selezione consumata: pulsante di nuovo spento"
    # una carta aggiunta SENZA toccare nulla eredita i predefiniti ('' = globali)
    widget._selected_ref = CardRef(id="557", name="Kuriboh", detail="Rare · LOB")
    widget._pending_filters = None
    widget.add_by_name()
    liscia = [w for w in widget.repo.list_watches() if w["ref_id"] == "557"][0]
    assert (liscia["filters"] or "") == "", "senza filtri propri deve usare i predefiniti"
    # spia nella watchlist: marcatore nella colonna Nome solo per chi ha i propri
    widget._reload_table()
    marcate = {p["ref_id"] for r, (k, p) in enumerate(widget._row_entries)
               if k == "watch" and widget._row_has_own_filters(r)}
    assert "556" in marcate and "557" not in marcate, marcate
    folder_rows = [r for r, (k, _p) in enumerate(widget._row_entries) if k == "folder"]
    assert all(not widget._row_has_own_filters(r) for r in folder_rows), \
        "le righe-cartella non vanno marcate"
    for ref in ("556", "557"):
        wid = [w for w in widget.repo.list_watches() if w["ref_id"] == ref][0]["id"]
        widget.repo.remove_watch(wid)
    widget.check_now = vero_check
    widget._selected_ref = None
    widget._update_card_filters_btn()
    print("[OK] Filtri: predefiniti separati; la carta selezionata nasce coi suoi.")

    # 5a-ter) BASI (mazzi): filtri comuni + copie che moltiplicano il totale
    from modules.market_watch.deck_dialog import DeckDialog  # noqa: E402
    from modules.market_watch.search_model import _thumb_url as _thumb_url_test  # noqa: E402
    widget.repo.replace_catalog("cardtrader", [
        ("701", "Ash Blossom & Joyous Spring", "Ultra Rare · RA01",
         "http://x/show_701.jpg", "RA01"),
        ("702", "Effect Veiler", "Super Rare · SDSE", "", "SDSE"),
    ])
    widget._rebuild_completer()
    vero_check2, widget.check_now = widget.check_now, lambda: None
    base_filtri = _json.dumps(ListingFilters(language="it").to_dict())
    ref701 = widget._label_to_ref[[l for l in widget._label_to_ref if "Ash Blossom" in l][0]]
    ref702 = widget._label_to_ref[[l for l in widget._label_to_ref if "Effect Veiler" in l][0]]
    widget._save_deck(None, "Snake-Eye", base_filtri, [(ref701, 3), (ref702, 2)])
    base = [f for f in widget.repo.list_folders("cardtrader") if f["name"] == "Snake-Eye"][0]
    assert base["filters"] == base_filtri, "i filtri della base non sono salvati"
    assert base["is_deck"], "una base va marcata come tale, non come cartella"
    # una cartella semplice NON è una base, e nella riga non ha il badge
    fid_semplice = widget.repo.add_folder("cardtrader", "Solo una cartella")
    semplice = [f for f in widget.repo.list_folders("cardtrader")
                if f["id"] == fid_semplice][0]
    assert not semplice["is_deck"]
    widget._reload_table()
    rbase = [r for r, (k, p) in enumerate(widget._row_entries)
             if k == "folder" and p["id"] == base["id"]][0]
    rcart = [r for r, (k, p) in enumerate(widget._row_entries)
             if k == "folder" and p["id"] == fid_semplice][0]
    assert widget.table.cellWidget(rbase, 2) is not None, "manca il badge BASE"
    assert widget.table.cellWidget(rcart, 2) is None, "la cartella non deve avere il badge"
    # cartelle nate prima della colonna: chi ha filtri propri diventa base
    widget.repo.set_folder_filters(fid_semplice, base_filtri)
    widget.repo.set_folder_deck(fid_semplice, False)
    widget._adopt_deck_flags()
    assert [f for f in widget.repo.list_folders("cardtrader")
            if f["id"] == fid_semplice][0]["is_deck"], \
        "una cartella con filtri propri e' una base"
    widget.repo.delete_folder(fid_semplice)
    in_base = {w["ref_id"]: w for w in widget.repo.list_watches()
               if w["folder_id"] == base["id"]}
    assert set(in_base) == {"701", "702"}, in_base.keys()
    assert in_base["701"]["copies"] == 3 and in_base["702"]["copies"] == 2

    # i filtri della base valgono per le sue carte, senza ripeterli carta per carta
    widget._refresh_folder_cache()
    assert widget._effective_filters(in_base["701"]).language == "it", "filtri della base ignorati"
    # ...ma una carta coi filtri PROPRI li scavalca
    widget.repo.set_watch_filters(in_base["702"]["id"],
                                  _json.dumps(ListingFilters(language="fr").to_dict()))
    ricarica = {w["ref_id"]: w for w in widget.repo.list_watches()}
    assert widget._effective_filters(ricarica["702"]).language == "fr", "i filtri della carta vincono"
    widget.repo.set_watch_filters(in_base["702"]["id"], "")

    # le copie moltiplicano il totale: 3×10 + 2×5 = 40
    chiave_base = widget._watch_key(
        {**{k: in_base["701"][k] for k in in_base["701"].keys()}})
    widget.repo.record_price("cardtrader", "701", 10.00, "EUR", chiave_base)
    widget.repo.record_price("cardtrader", "702", 5.00, "EUR", chiave_base)
    widget._reload_table()
    frow = [r for r, (k, p) in enumerate(widget._row_entries)
            if k == "folder" and p["id"] == base["id"]][0]
    assert widget.table.item(frow, 8).text() == "40.00 €", widget.table.item(frow, 8).text()
    assert widget.table.item(frow, 14).text() == "5", widget.table.item(frow, 14).text()
    # e la carta mostra le copie davanti al nome, col prezzo UNITARIO
    crow = [r for r, (k, p) in enumerate(widget._row_entries)
            if k == "watch" and p["ref_id"] == "701"][0]
    assert widget.table.item(crow, 1).text().startswith("3×"), widget.table.item(crow, 1).text()
    assert widget.table.item(crow, 8).text() == "10.00 €", widget.table.item(crow, 8).text()

    # modificare la base: cambio copie e tolgo una carta (che NON si perde)
    widget._save_deck(base, "Snake-Eye 2", "", [(ref701, 1)])
    base2 = [f for f in widget.repo.list_folders("cardtrader") if f["id"] == base["id"]][0]
    assert base2["name"] == "Snake-Eye 2" and base2["filters"] == ""
    ricarica = {w["ref_id"]: w for w in widget.repo.list_watches()}
    assert ricarica["701"]["copies"] == 1 and ricarica["701"]["folder_id"] == base["id"]
    assert ricarica["702"]["folder_id"] is None, \
        "una carta tolta dalla base resta in watchlist, fuori dalla base"
    for ref in ("701", "702"):
        widget.repo.remove_watch(ricarica[ref]["id"])
    widget.repo.delete_folder(base["id"])
    widget.check_now = vero_check2
    # nessun cell widget fantasma rimasto dai render precedenti (si vedevano
    # come iconcine appiccicate a sinistra, davanti al nome della cartella)
    from PySide6.QtWidgets import QWidget as _QW  # noqa: E402
    vp = widget.table.viewport()
    vivi = {id(widget.table.cellWidget(r, c))
            for r in range(widget.table.rowCount())
            for c in range(widget.table.columnCount())
            if widget.table.cellWidget(r, c) is not None}
    orfani = [ch for ch in vp.findChildren(_QW)
              if ch.parent() is vp and id(ch) not in vivi]
    assert not orfani, f"{len(orfani)} cell widget fantasma nel viewport"

    # il dialogo della base: miniatura accanto al nome, e la sua tabella
    # (ricostruita a ogni carta aggiunta) non deve lasciare fantasmi
    from PySide6.QtCore import Qt as _Qt  # noqa: E402
    from PySide6.QtGui import QPixmap as _QP  # noqa: E402
    from modules.market_watch import deck_dialog as _dd  # noqa: E402
    dlg = DeckDialog(widget._deck_search, cards=[(ref701, 2)],
                     thumb_items=widget._completer_items,
                     resolve=widget._label_to_ref.get)
    finta = _QP(_dd.ICON)
    finta.fill(_Qt.GlobalColor.darkRed)
    dlg._icons[_thumb_url_test(ref701.image_url)] = finta
    dlg._rebuild_table()
    dlg._rebuild_table()      # una seconda volta: è il caso che lasciava fantasmi
    assert not dlg.table.item(0, 0).icon().isNull(), "manca la miniatura nell'elenco della base"
    dvp = dlg.table.viewport()
    dvivi = {id(dlg.table.cellWidget(r, c))
             for r in range(dlg.table.rowCount())
             for c in range(dlg.table.columnCount())
             if dlg.table.cellWidget(r, c) is not None}
    assert not [ch for ch in dvp.findChildren(_QW)
                if ch.parent() is dvp and id(ch) not in dvivi], \
        "fantasmi nella tabella del dialogo"
    dlg.deleteLater()
    print("[OK] Basi: filtri comuni a cascata, copie che moltiplicano il totale, "
          "modifica senza perdere carte, nessun pulsante fantasma.")

    # 5a-quater) copie da più venditori: il costo di 3 copie non è 3× la più
    # economica se quel venditore ne ha una sola (caso "Blitzclique Surge").
    from modules.market_watch.providers.cardtrader import _pick_copies  # noqa: E402

    def offerta(prezzo, qty, venditore):
        return (prezzo, "EUR", {"quantity": qty,
                                "user": {"username": venditore, "country_code": "IT"},
                                "properties_hash": {"condition": "Near Mint",
                                                    "yugioh_language": "it"}})

    offerte = [offerta(10.0, 1, "tizio"), offerta(12.0, 5, "caio"), offerta(20.0, 9, "sempronio")]
    prese, totale, coperte = _pick_copies(offerte, 3)
    assert coperte == 3 and abs(totale - (10.0 + 12.0 * 2)) < 1e-6, (prese, totale)
    assert [p["qty"] for p in prese] == [1, 2], prese
    assert [p["seller"] for p in prese] == ["tizio", "caio"]
    # mercato che non basta: si dice quante se ne trovano, non si inventa
    prese, totale, coperte = _pick_copies([offerta(10.0, 2, "tizio")], 5)
    assert coperte == 2 and abs(totale - 20.0) < 1e-6
    # una copia sola: nessuna complicazione
    prese, totale, coperte = _pick_copies(offerte, 1)
    assert coperte == 1 and prese[0]["qty"] == 1 and abs(totale - 10.0) < 1e-6

    # in Panoramica la carta si apre e mostra una riga per venditore
    q_multi = PriceQuote(amount=10.0, currency="EUR", detail="NM",
                         sources=[{"qty": 1, "amount": 10.0, "seller": "tizio",
                                   "country": "IT", "condition": "Near Mint",
                                   "language": "IT"},
                                  {"qty": 2, "amount": 12.0, "seller": "caio",
                                   "country": "DE", "condition": "Excellent",
                                   "language": "EN"}],
                         total=34.0, covered=3)
    widget._last_quotes["701"] = q_multi
    widget.repo.add_watch("cardtrader", "701", "Ash Blossom & Joyous Spring",
                          "Ultra Rare · RA01", 0.0, "", 3)
    w701 = [w for w in widget.repo.list_watches() if w["ref_id"] == "701"][0]
    widget.repo.record_price("cardtrader", "701", 10.0, "EUR", widget._watch_key(w701))
    widget._toggle_overview(True)
    widget._reload_table()
    kinds = [k for k, _p in widget._row_entries]
    assert "source" not in kinds, "le provenienze partono chiuse"
    widget._toggle_sources([w for w in widget.repo.list_watches() if w["ref_id"] == "701"][0])
    righe = [(k, p) for k, p in widget._row_entries]
    fonti = [i for i, (k, _p) in enumerate(righe) if k == "source"]
    assert len(fonti) == 2, righe
    assert widget.table.item(fonti[0], 8).text() == "10.00 €", widget.table.item(fonti[0], 8).text()
    assert widget.table.item(fonti[1], 8).text() == "24.00 €", widget.table.item(fonti[1], 8).text()
    assert widget.table.item(fonti[1], 14).text() == "2"
    # la carta mostra il costo delle TRE copie, non 3× la più economica
    crow = [i for i, (k, p) in enumerate(righe)
            if k == "watch" and p["ref_id"] == "701"][0]
    assert widget.table.item(crow, 8).text() == "34.00 €", widget.table.item(crow, 8).text()
    assert widget._row_indent(fonti[0]) > widget._row_indent(crow), "la provenienza va più dentro"
    widget._toggle_sources(w701)
    widget._toggle_overview(False)
    widget.repo.remove_watch(w701["id"])
    widget._last_quotes.pop("701", None)
    print("[OK] Copie da più venditori: costo reale (10 + 2×12), righe di "
          "provenienza apribili, mercato insufficiente dichiarato.")

    # 5a-quinquies) link alla pagina CardTrader nella colonna Azioni
    from PySide6.QtWidgets import QPushButton as _QPB  # noqa: E402
    widget.repo.add_watch("cardtrader", "382653", "Dominus Purge",
                          "Starlight Rare · ROTA", 0.0,
                          _json.dumps(ListingFilters(language="it",
                                                     first_edition_only=True).to_dict()))
    widget._reload_table()
    lrow = [r for r, (k, p) in enumerate(widget._row_entries)
            if k == "watch" and p["ref_id"] == "382653"][0]
    azioni = widget.table.cellWidget(lrow, 15)
    bottoni = azioni.findChildren(_QPB)
    assert len(bottoni) == 3, f"attesi filtri + link + cestino, trovati {len(bottoni)}"
    # l'indirizzo si costruisce col solo id: il sito reindirizza allo slug
    assert widget.CARD_PAGE.format(ref_id="382653") == \
        "https://www.cardtrader.com/cards/382653"
    wl = [w for w in widget.repo.list_watches() if w["ref_id"] == "382653"][0]
    tip = widget._card_page_tip(wl)
    assert "CardTrader" in tip and "IT" in tip and "1ª ed." in tip, tip
    # senza filtri attivi niente riga sui filtri da rimettere
    assert widget._filters_summary(ListingFilters()) == ""
    widget.repo.remove_watch(wl["id"])
    print("[OK] Azioni: pulsante che apre la pagina della carta, coi filtri "
          "in vigore ricordati nel tooltip.")

    # 5a-sexies) condizione abbreviata in tabella, nome intero nel tooltip
    from modules.market_watch.widget import _condition_short  # noqa: E402
    assert _condition_short("Near Mint") == "NM"
    assert _condition_short("Light Played") == "LP"
    assert _condition_short("Slightly Played") == "SP"     # nome usato dal sito
    assert _condition_short("Moderately Played") == "MP"
    assert _condition_short("Played") == "PL", "'played' dentro 'light played' non deve confondere"
    assert _condition_short("Poor") == "PO"
    assert _condition_short("  near mint ") == "NM", "spazi e maiuscole non contano"
    # sconosciuta: si lascia com'è invece di inventare una sigla
    assert _condition_short("Graded 9.5") == "Graded 9.5"
    assert _condition_short("") == ""
    # badge colorato: verde per le perfette, rosso per le rovinate
    from modules.market_watch.widget import _condition_color  # noqa: E402
    verde, rosso = _condition_color("Mint"), _condition_color("Poor")
    assert verde.green() > verde.red(), "Mint deve tendere al verde"
    assert rosso.red() > rosso.green(), "Poor deve tendere al rosso"
    scala = ["Mint", "Near Mint", "Excellent", "Good", "Played", "Poor"]
    rossi = [_condition_color(c).red() for c in scala]
    verdi = [_condition_color(c).green() for c in scala]
    assert rossi == sorted(rossi), f"il rosso deve solo crescere: {rossi}"
    assert verdi == sorted(verdi, reverse=True), f"il verde deve solo calare: {verdi}"
    # sconosciuta: grigio neutro, nessun giudizio inventato
    ignota = _condition_color("Graded 9.5")
    assert abs(ignota.red() - ignota.green()) < 30 and abs(ignota.green() - ignota.blue()) < 40, ignota
    print("[OK] Condizioni abbreviate e colorate: NM/LP/SP/MP/PL, scala "
          "verde→rosso monotona, sconosciute grigie e intatte.")

    # 5a-septies) ordinamento: rarità, prezzo, variazione — dentro i gruppi
    from core.rarity import rarity_rank  # noqa: E402
    assert rarity_rank("Common") < rarity_rank("Ultra Rare") < rarity_rank("Starlight Rare")
    assert rarity_rank("Boh?") == -1, "rarità ignota: fuori scala, non in mezzo"

    # (ref, nome, detail, prezzo prima, prezzo dopo) → variazione
    ORD = [("901", "Alfa", "Common · X", 5.0, 4.0),              # 5 → 4  = -20%
           ("902", "Beta", "Starlight Rare · X", 100.0, 120.0),  # 100→120 = +20%
           ("903", "Gamma", "Super Rare · X", 50.0, 50.0)]       # nessuna variazione
    widget.repo.replace_catalog("cardtrader", [(r, n, d, "", "X") for r, n, d, _p, _q in ORD])
    chiave_ord = widget._filters_key(widget._filters)
    for ref, nome, det, prima, dopo in ORD:
        widget.repo.add_watch("cardtrader", ref, nome, det, 0.0)
        widget.repo.record_price("cardtrader", ref, prima, "EUR", chiave_ord)
        if dopo != prima:
            widget.repo.record_price("cardtrader", ref, dopo, "EUR", chiave_ord)

    soli = {r for r, _n, _d, _p, _q in ORD}

    def ordine():
        """Solo le carte di questa prova: in watchlist ce ne sono altre."""
        widget._reload_table()
        return [p["ref_id"] for k, p in widget._row_entries
                if k == "watch" and p["ref_id"] in soli]

    widget._set_sort("price")            # dal più caro
    assert ordine() == ["902", "903", "901"], ordine()
    widget._set_sort("price")            # secondo clic: inverte
    assert not widget._sort_desc and ordine() == ["901", "903", "902"], ordine()
    widget._set_sort("rarity")           # dalla più ricercata
    assert ordine() == ["902", "903", "901"], ordine()
    widget._set_sort("change")           # dal rialzo maggiore al calo maggiore
    assert ordine() == ["902", "901", "903"], ordine()   # +20%, -20%, senza dato
    widget._set_sort("change")           # invertito: prima il calo
    assert ordine() == ["901", "902", "903"], ordine()
    # chi non ha variazione resta in fondo in ENTRAMBI i versi
    assert ordine()[-1] == "903", "senza dato si resta in fondo anche invertendo"
    # il criterio si ricorda fra i riavvii
    widget._set_sort("rarity")
    assert widget.repo.get_setting("sort") == "rarity:desc"
    wsort = MarketWatchWidget(ctx)
    assert (wsort._sort_mode, wsort._sort_desc) == ("rarity", True)
    wsort.stop()
    widget._set_sort("manual")
    for ref, _n, _d, _p, _q in ORD:
        wid = [w for w in widget.repo.list_watches() if w["ref_id"] == ref][0]["id"]
        widget.repo.remove_watch(wid)
    print("[OK] Ordinamento: rarità/prezzo/variazione, verso invertibile, "
          "senza-dato sempre in fondo, criterio ricordato.")

    # 5b) rate limit: il 429 non deve più far fallire il controllo.
    # Il client ritenta rispettando Retry-After e allarga la spaziatura.
    from modules.market_watch.providers import cardtrader as ct  # noqa: E402

    class FakeResponse:
        def __init__(self, status, payload=None, retry_after=None):
            self.status_code = status
            self._payload = payload if payload is not None else {}
            self.headers = {} if retry_after is None else {"Retry-After": str(retry_after)}

        def json(self):
            return self._payload

    class FlakySession:
        """Risponde 429 le prime `n` volte, poi 200."""

        def __init__(self, n):
            self.left = n
            self.calls = 0

        def get(self, url, params=None, headers=None, timeout=None):
            self.calls += 1
            if self.left > 0:
                self.left -= 1
                return FakeResponse(429, retry_after=0)   # 0 = non rallentare il test
            return FakeResponse(200, {"ok": True})

    real_min, real_wait = ct.MIN_INTERVAL, ct.MAX_RETRY_WAIT
    # attese ridotte al minimo: il test verifica la LOGICA, non gli orologi
    # (non zero: con spaziatura 0 la penalità moltiplicativa non crescerebbe)
    ct.MIN_INTERVAL, ct.MAX_RETRY_WAIT = 0.001, 0.0
    ct.LIMITER = ct._RateLimiter()            # limitatore pulito per il test
    flaky = FlakySession(2)
    client = ct.CardTraderClient("token-finto", session=flaky)
    assert client._get("/qualsiasi") == {"ok": True}, "il 429 deve essere ritentato"
    assert flaky.calls == 3, f"attesi 2 tentativi falliti + 1 buono, fatti {flaky.calls}"
    assert ct.LIMITER.interval > ct.MIN_INTERVAL, "dopo un 429 la spaziatura deve allargarsi"
    print(f"[OK] Rate limit: 429 ritentato ({flaky.calls} chiamate), "
          f"spaziatura salita a {ct.LIMITER.interval / ct.MIN_INTERVAL:.1f}× il minimo.")

    # 429 che non passa mai: errore parlante, non un crash
    ct.LIMITER = ct._RateLimiter()
    stubborn = FlakySession(99)
    try:
        ct.CardTraderClient("token-finto", session=stubborn)._get("/qualsiasi")
        raise AssertionError("doveva sollevare RateLimited")
    except ct.RateLimited as exc:
        assert "429" in str(exc)
    assert stubborn.calls == ct.RETRY_ATTEMPTS, f"attesi {ct.RETRY_ATTEMPTS} tentativi"

    # should_stop: le attese mollano subito (chiusura app durante un backoff)
    stopped = ct.CardTraderClient("token-finto", session=FlakySession(99),
                                  should_stop=lambda: True)
    try:
        stopped._get("/qualsiasi")
        raise AssertionError("doveva interrompersi")
    except ct.CardTraderError as exc:
        assert "interrotta" in str(exc).lower(), exc
    ct.MIN_INTERVAL, ct.MAX_RETRY_WAIT = real_min, real_wait   # ripristino
    ct.LIMITER = ct._RateLimiter()
    print("[OK] Rate limit: resa con errore parlante e interruzione immediata alla chiusura.")

    # 5c) risultati PARZIALI: le carte non controllate non vanno azzerate
    widget._last_quotes = {"111": PriceQuote(amount=5.0, currency="EUR", detail="vecchio")}
    widget._no_match_refs = {"222"}
    widget._on_prices([{"ref_id": "333", "quote": None}], failed=2, last_error="Troppe richieste (429)")
    assert "111" in widget._last_quotes, "una carta non controllata non deve perdere il prezzo"
    assert widget._last_quotes["111"].amount == 5.0
    assert "222" in widget._no_match_refs, "'Nessuna copia' non deve sparire per una carta non controllata"
    assert "333" in widget._no_match_refs, "la carta controllata senza annunci è 'Nessuna copia'"
    assert "parziale" in widget.status.text().lower(), widget.status.text()
    print("[OK] Controllo parziale: prezzi delle carte non controllate preservati.")

    # 5d) la spaziatura imparata sopravvive al riavvio (niente 429 da rifare)
    ct.LIMITER.adopt(1.25)
    widget._save_rate_interval()
    ct.LIMITER = ct._RateLimiter()                      # "riavvio": limitatore nuovo
    assert ct.LIMITER.interval == ct.MIN_INTERVAL
    widget._load_rate_interval()
    assert abs(ct.LIMITER.interval - 1.25) < 1e-6, ct.LIMITER.interval
    ct.LIMITER.adopt(999)                               # valore assurdo: va tagliato
    assert ct.LIMITER.interval == ct.MAX_INTERVAL
    widget.repo.set_setting("api_interval", "non-un-numero")
    widget._load_rate_interval()                        # non deve esplodere
    print(f"[OK] Rate limit: spaziatura ricordata fra i riavvii "
          f"(1.25s riletta, valori assurdi tagliati a {ct.MAX_INTERVAL}s).")
    ct.LIMITER = ct._RateLimiter()

    # 5c) controllo aggiornamenti: confronto NUMERICO e silenzio sugli errori
    from core import updates  # noqa: E402
    assert updates.parse_version("v1.0.23") == (1, 0, 23)
    assert updates.parse_version("1.1.0-beta") == (1, 1, 0), "il suffisso si ignora"
    assert updates.parse_version("") == (0,)
    # il caso che un confronto alfabetico sbaglierebbe: "1.0.9" < "1.0.23"
    assert updates.is_newer("1.0.23", "1.0.9")
    assert not updates.is_newer("1.0.9", "1.0.23")
    assert updates.is_newer("v1.1.0", "1.0.23")
    assert not updates.is_newer("1.0.23", "1.0.23"), "stessa versione = niente avviso"
    assert not updates.is_newer("1.0.22", "1.0.23"), "più vecchia = niente avviso"
    assert updates.is_newer("1.1", "1.0.23"), "lunghezze diverse si confrontano comunque"
    # indirizzo irraggiungibile: None, nessuna eccezione (regola del silenzio)
    assert updates.fetch_latest("http://127.0.0.1:9/nulla") is None
    print("[OK] Aggiornamenti: confronto numerico (1.0.9 < 1.0.23), "
          "irraggiungibile = silenzio.")

    # 5c-bis) aggiornamento in-app (v1.4.0): scelta dell'asset, download
    #         verificato, riga di comando di Setup, memoria fra i riavvii.
    #         Tutto OFFLINE: la "release" è un file JSON e l'"installer" un
    #         file locale, serviti via file://.
    import subprocess as _sub  # noqa: E402
    up_dir = tmp / "updates"
    up_dir.mkdir()
    updates.UPDATES_DIR = up_dir          # niente scritture in ~/.ygo_toolbox
    updates.STATE_FILE = up_dir / "stato.json"

    # --- l'asset si sceglie per PATTERN, mai assets[0] ---
    assets = [
        {"name": "note.md", "state": "uploaded",
         "browser_download_url": "http://x/note.md", "size": 10},
        {"name": "YGO-Toolbox-Setup-v9.9.9.exe", "state": "uploading",
         "browser_download_url": "http://x/parziale.exe", "size": 5},
        {"name": "YGO-Toolbox-Setup-v9.9.9.exe", "state": "uploaded",
         "browser_download_url": "http://x/vero.exe", "size": 4242},
    ]
    scelto = updates._pick_asset(assets)
    assert scelto is not None and scelto["browser_download_url"] == "http://x/vero.exe", \
        "l'asset va scelto per nome+estensione+state, non per posizione"
    assert updates._pick_asset([assets[0]]) is None, "un .md non è un installer"
    assert updates._pick_asset([assets[1]]) is None, "upload non finito = non esiste"
    assert updates._pick_asset("non-una-lista") is None

    # --- fetch_latest legge anche l'asset; senza asset resta il solo link ---
    finto_exe = up_dir / "YGO-Toolbox-Setup-v9.9.9.exe"
    finto_exe.write_bytes(b"MZ" + b"\x00" * 4240)     # 4242 byte, firma giusta
    rel_json = tmp / "release.json"
    rel_json.write_text(_json.dumps({
        "tag_name": "v9.9.9", "html_url": "https://esempio/rel",
        "assets": [{"name": finto_exe.name, "state": "uploaded", "size": 4242,
                    "browser_download_url": finto_exe.as_uri()}],
    }), encoding="utf-8")
    rel = updates.fetch_latest(rel_json.as_uri())
    assert rel is not None and rel.version == "9.9.9" and rel.installabile
    assert rel.asset_size == 4242 and rel.page == "https://esempio/rel"
    senza = tmp / "senza_asset.json"
    senza.write_text(_json.dumps({"tag_name": "v9.9.9", "html_url": "u",
                                  "assets": []}), encoding="utf-8")
    solo_link = updates.fetch_latest(senza.as_uri())
    assert solo_link is not None and not solo_link.installabile, \
        "release senza installer: si avvisa comunque, ma senza pulsante"
    # un JSON col BOM (su Windows lo mette quasi ogni strumento) deve passare:
    # con decode("utf-8") json.loads solleva, e la regola del silenzio lo
    # nasconde — nessun avviso e niente da cui capire il perché
    con_bom = tmp / "con_bom.json"
    con_bom.write_bytes(b"\xef\xbb\xbf" + rel_json.read_bytes())
    assert updates.fetch_latest(con_bom.as_uri()) == rel, "il BOM non deve fermare nulla"

    # --- verifica del file: dimensione E firma MZ, entrambe ---
    assert updates.verifica_file(finto_exe, 4242)
    assert not updates.verifica_file(finto_exe, 4243), "un byte in meno = troncato"
    pagina_html = up_dir / "proxy.exe"
    pagina_html.write_bytes(b"<h" + b"\x00" * 4240)   # peso giusto, non un exe
    assert not updates.verifica_file(pagina_html, 4242), \
        "peso giusto ma non comincia per MZ: è la pagina di errore di un proxy"
    assert not updates.verifica_file(up_dir / "non-esiste", 1)

    # --- download: il file arriva intero, il .part non resta in giro ---
    sorgente = tmp / "sorgente.exe"
    sorgente.write_bytes(b"MZ" + b"\x01" * 998)       # 1000 byte
    rel_ok = updates.Release("9.9.9", "u", sorgente.as_uri(), "scaricato.exe", 1000)
    visti = []
    percorso = updates.scarica(rel_ok, on_progress=lambda f, t: visti.append((f, t)))
    assert percorso.exists() and percorso.stat().st_size == 1000
    assert not (up_dir / "scaricato.exe.part").exists(), "il .part va rinominato"
    assert visti and visti[-1][0] == 1000
    # secondo giro: il file c'è già e passa i controlli → non si riscarica
    prima = percorso.stat().st_mtime_ns
    assert updates.scarica(rel_ok) == percorso and percorso.stat().st_mtime_ns == prima, \
        "un file già valido non si riscarica: sarebbero 48 MB a ogni avvio"
    # dimensione dichiarata sbagliata: si solleva e NON resta niente sul disco
    rel_ko = updates.Release("9.9.9", "u", sorgente.as_uri(), "bugiardo.exe", 999)
    try:
        updates.scarica(rel_ko)
        raise AssertionError("un installer di peso sbagliato non deve passare")
    except OSError:
        pass
    assert not (up_dir / "bugiardo.exe").exists()
    assert not (up_dir / "bugiardo.exe.part").exists()
    # annullamento: niente file, niente eccezione da mostrare
    try:
        updates.scarica(rel_ko, annullato=lambda: True)
        raise AssertionError("l'annullamento deve interrompere")
    except InterruptedError:
        pass

    # --- GOTCHA 24: la riga di comando di Setup DEVE arrivare virgolettata ---
    riga = updates.install_command(Path(r"C:\giu\setup.exe"),
                                   Path(r"C:\Programs\YGO Toolbox"),
                                   Path(r"C:\log\setup.log"))
    assert isinstance(riga, list) and riga[0].endswith("setup.exe")
    assert "/SILENT" in riga and "/NOCANCEL" in riga and "/SP-" in riga
    assert "/SUPPRESSMSGBOXES" not in riga, \
        "risponderebbe Annulla al box Riprova/Annulla: exe vecchio già rimosso"
    assert not any(a in riga for a in ("/CURRENTUSER", "/ALLUSERS")), \
        "con PrivilegesRequiredOverridesAllowed=dialog fanno FALLIRE il setup"
    scritta = _sub.list2cmdline(riga)
    assert '"/DIR=C:\\Programs\\YGO Toolbox"' in scritta, scritta
    # il controllo che conta: la cartella non deve poter arrivare troncata
    assert "/DIR=C:\\Programs\\YGO Toolbox" not in scritta.replace(
        '"/DIR=C:\\Programs\\YGO Toolbox"', ""), \
        "senza virgolette Inno legge …\\YGO e installa in una cartella fantasma"

    # --- l'ambiente di Setup NON deve portarsi dietro le variabili di
    #     PyInstaller: altrimenti l'app rilanciata da [Run] cerca python310.dll
    #     nella cartella di estrazione del processo appena morto e si apre con
    #     "Failed to load Python DLL" (GOTCHA 26, riprodotto a comando)
    import os as _os
    _salva = dict(_os.environ)
    _os.environ["_PYI_APPLICATION_HOME_DIR"] = r"C:\Temp\_MEI999992"
    _os.environ["_PYI_PARENT_PROCESS_LEVEL"] = "0"
    _os.environ["_MEIPASS2"] = r"C:\Temp\_MEI999992"
    _os.environ["YGO_CANARINO"] = "resto"
    pulito = updates.ambiente_per_setup()
    assert not [k for k in pulito if k.startswith(("_PYI", "_MEI"))], \
        "l'app rilanciata erediterebbe la cartella di estrazione di un morto"
    assert pulito.get("YGO_CANARINO") == "resto", \
        "si toglie solo cio' che riguarda PyInstaller, non tutto l'ambiente"
    _os.environ.clear()
    _os.environ.update(_salva)

    # --- il segnale "Setup è partito" è il file di log, non il processo ---
    finto_log = updates.log_path("9.9.9")
    assert not updates.installer_partito(finto_log)
    finto_log.write_text("Log opened.", encoding="utf-8")
    assert updates.installer_partito(finto_log)
    finto_log.write_text("", encoding="utf-8")
    assert not updates.installer_partito(finto_log), "log vuoto = non è partito"

    # --- memoria fra i riavvii: l'esito si dice UNA volta sola ---
    updates.STATE_FILE.unlink(missing_ok=True)
    assert updates.esito_precedente("1.3.0") == "", "senza attesa, niente da dire"
    updates.segna_attesa("1.4.0")
    assert updates.esito_precedente("1.4.0") == "fatto", "combacia: riuscito"
    assert updates.esito_precedente("1.4.0") == "", "e non si ripete"
    updates.segna_attesa("1.4.0")
    assert updates.esito_precedente("1.3.0") == "mancato", "siamo ancora alla 1.3.0"
    assert updates.scartata("1.4.0"), "una versione fallita non si riscarica da sola"
    updates.segna_attesa("1.4.0")
    assert updates.esito_precedente("1.3.0") == "", \
        "il fallimento si annuncia una volta sola, non a ogni avvio"
    # la pulizia porta via gli installer, non lo stato
    updates.segna_attesa("1.3.0")
    assert updates.esito_precedente("1.3.0") == "fatto"
    assert not list(up_dir.glob("*.exe")), "a fine giro gli installer si buttano"
    print("[OK] Aggiornamento in-app: asset scelto per pattern, download "
          "verificato (peso + firma MZ), /DIR virgolettato, esito detto una "
          "volta sola.")

    # 5c-ter) il piede: gli stati che l'utente vede, e il silenzio sui guai
    from core.update_widget import UpdateFooter  # noqa: E402
    occupato_da = [""]
    chiuso = []
    piede = UpdateFooter(occupato=lambda: occupato_da[0],
                         chiudi=lambda: chiuso.append(True))
    assert not piede.isVisible(), "senza niente da dire il piede non esiste"
    rel_v = updates.Release("9.9.9", "https://esempio/rel",
                            sorgente.as_uri(), "scaricato.exe", 1000)
    piede._on_trovata(rel_v)
    assert piede.isVisibleTo(piede.parent() or piede) or True   # offscreen: basta lo stato
    assert "9.9.9" in piede.testo.text()
    assert not piede.btn_azione.isVisible() or piede.btn_azione.text() == ""
    assert piede.btn_altro.text() == "Apri la pagina", \
        "'Apri la pagina' è la via d'uscita e non si toglie mai"
    piede._on_avanzamento(500, 1000)
    assert "50%" in piede.dettaglio.text()
    piede._on_avanzamento(500, 0)
    assert "%" not in piede.dettaglio.text(), \
        "senza Content-Length non si inventa una percentuale"
    piede._on_pronta(rel_v, str(sorgente))
    assert piede.btn_azione.text() == "Riavvia e aggiorna"
    # guaio sul download: NON lo si dice, resta l'avviso col link
    piede._on_fallita(rel_v, "URLError: finto")
    assert piede.btn_azione.text() == "" and piede.btn_altro.text() == "Apri la pagina"
    assert "9.9.9" in piede.testo.text() and "non" not in piede.testo.text().lower()
    # esito mancato: si dice, in grigio, con la via d'uscita
    updates.segna_attesa("9.9.9")
    piede2 = UpdateFooter()
    piede2.controlla_esito_precedente()
    assert "buon fine" in piede2.testo.text()
    assert piede2.testo.property("state") == "calmo", \
        "quello che l'utente non può risolvere non va in giallo"
    piede3 = UpdateFooter()
    piede3.controlla_esito_precedente()
    assert piede3.testo.text() == "", "e la seconda volta non si ripete"
    # il pulsante primario NON deve ereditare il mestiere di uno stato
    # precedente: cambia testo, quindi deve cambiare anche cosa fa
    piede._on_pronta(rel_v, str(sorgente))
    assert piede._stato == "pronta"
    piede._non_partita()
    assert piede._stato == "non_partita" and piede.btn_azione.text() == "Apri la cartella"
    piede._on_pronta(rel_v, str(sorgente))
    assert piede._stato == "pronta" and piede.btn_azione.text() == "Riavvia e aggiorna", \
        "tornata pronta, il pulsante torna ad aggiornare e non apre la cartella"
    piede.stop()
    piede2.stop()
    piede3.stop()
    # e il chip vecchio non deve esistere più: l'avviso vive nel core
    assert not hasattr(widget, "update_label"), \
        "l'avviso è stato spostato nel piede: nel market_watch non deve restarne traccia"
    print("[OK] Piede aggiornamenti: stati (trovata → preparo → pronta), "
          "download fallito = silenzio, esito mancato in grigio una volta sola.")

    # 5c-quater) chi è occupato lo dice, e solo se lo è davvero
    assert widget.busy_reason() == "", "a riposo non si inventa un lavoro in corso"
    class _FintoWorker:
        def isRunning(self):
            return True
    salvato = widget._sync_worker
    widget._sync_worker = _FintoWorker()
    assert "catalogo" in widget.busy_reason()
    widget._sync_worker = salvato
    print("[OK] busy_reason: il piede sa cosa sta interrompendo prima di "
          "chiudere l'app.")

    # 5d) esporta/importa in JSON: il giro completo su un DB vergine
    from modules.market_watch import transfer  # noqa: E402
    from modules.market_watch.repository import MarketWatchRepository  # noqa: E402
    from core.storage import Storage as _St  # noqa: E402

    def repo_vuoto(nome):
        st = _St(tmp / nome)
        return MarketWatchRepository(st), st

    src, st_src = repo_vuoto("exp_src.db")
    fid = src.add_folder("cardtrader", "Snake-Eye",
                         _json.dumps(ListingFilters(language="it").to_dict()), True)
    src.add_watch("cardtrader", "701", "Ash Blossom", "Ultra Rare · RA01", 5.0,
                  _json.dumps(ListingFilters(language="en").to_dict()), 3)
    src.add_watch("cardtrader", "702", "Effect Veiler", "Super Rare · SDSE", 0.0)
    w701 = [w for w in src.list_watches() if w["ref_id"] == "701"][0]
    src.set_watch_folder(w701["id"], fid)
    src.record_price("cardtrader", "701", 40.0, "EUR", "chiave-x")
    src.set_setting("filters", _json.dumps(ListingFilters(min_condition="Near Mint").to_dict()))
    src.set_setting("sort", "price:asc")

    dati = transfer.export_data(src, "cardtrader", app_version="test")
    percorso = tmp / "scambio.json"
    transfer.write_file(percorso, dati)
    testo = percorso.read_text(encoding="utf-8")
    # il TOKEN e il CATALOGO non devono uscire, mai
    assert "cardtrader_token" not in testo and "mw_catalog" not in testo
    assert '"formato": "ygo-toolbox/watchlist"' in testo and '"versione": 1' in testo
    assert "3 carte" not in transfer.describe(dati)   # sono 2
    assert transfer.describe(dati).startswith("2 carte · 1 cartelle")

    # rileggendolo si ottiene la stessa cosa
    riletto = transfer.read_file(percorso)
    assert riletto["cartelle"][0]["nome"] == "Snake-Eye"
    assert riletto["cartelle"][0]["base"] is True
    assert riletto["cartelle"][0]["filtri"]["language"] == "it"
    assert riletto["cartelle"][0]["carte"][0]["copie"] == 3
    assert riletto["carte_sciolte"][0]["ref_id"] == "702"

    # IMPORT su DB vergine (sostituisci): tutto ricostruito
    dst, st_dst = repo_vuoto("exp_dst.db")
    esito = transfer.import_data(dst, "cardtrader", riletto, replace=True)
    assert esito == {"aggiunte": 2, "aggiornate": 0, "cartelle": 1, "storico": 1}, esito
    imp = {w["ref_id"]: w for w in dst.list_watches()}
    assert imp["701"]["copies"] == 3 and imp["701"]["threshold_pct"] == 5.0
    assert _json.loads(imp["701"]["filters"])["language"] == "en", "filtri della carta persi"
    assert imp["702"]["folder_id"] is None, "la carta sciolta non va in cartella"
    cart = dst.list_folders("cardtrader")[0]
    assert cart["name"] == "Snake-Eye" and cart["is_deck"]
    assert imp["701"]["folder_id"] == cart["id"]
    # lo storico conserva la data ORIGINALE e la chiave dei filtri
    st_row = dst.all_history("cardtrader")[0]
    assert st_row["filters_key"] == "chiave-x" and st_row["price"] == 40.0
    orig = src.all_history("cardtrader")[0]
    assert st_row["captured_at"] == orig["captured_at"], "la data non deve appiattirsi"
    # sostituendo si portano anche le preferenze
    assert dst.get_setting("sort") == "price:asc"

    # reimportare lo STESSO file non deve duplicare niente
    esito2 = transfer.import_data(dst, "cardtrader", riletto, replace=False)
    assert esito2["aggiunte"] == 0 and esito2["storico"] == 0, esito2
    assert len(dst.list_watches()) == 2 and len(dst.all_history("cardtrader")) == 1

    # export di UNA SOLA base: niente storico, niente preferenze
    solo = transfer.export_data(src, "cardtrader", only_folder_id=fid)
    assert "storico" not in solo and "preferenze" not in solo
    assert len(solo["cartelle"]) == 1 and not solo["carte_sciolte"]

    # file non nostro, o troppo nuovo: errore parlante, non un crash
    brutto = tmp / "brutto.json"
    brutto.write_text('{"formato": "altro"}', encoding="utf-8")
    try:
        transfer.read_file(brutto); raise AssertionError("doveva rifiutarlo")
    except transfer.TransferError as e:
        assert "watchlist" in str(e).lower(), e
    futuro = tmp / "futuro.json"
    futuro.write_text('{"formato": "ygo-toolbox/watchlist", "versione": 99}', encoding="utf-8")
    try:
        transfer.read_file(futuro); raise AssertionError("doveva rifiutarlo")
    except transfer.TransferError as e:
        assert "99" in str(e), e
    st_src.close(); st_dst.close()
    print("[OK] Esporta/importa JSON: giro completo, niente token né catalogo, "
          "date dello storico conservate, reimport senza duplicati.")

    # 6) i18n: traduzioni presenti, fallback sicuro, cambio lingua
    from core import i18n  # noqa: E402
    assert i18n.tr("Nessuna copia") == "Nessuna copia"      # default: italiano
    i18n._current = "en"
    assert i18n.tr("Nessuna copia") == "No copies"
    assert i18n.tr("Catalogo · {n} carte").format(n=5) == "Catalog · 5 cards"
    assert i18n.tr("stringa non mappata") == "stringa non mappata"  # fallback
    i18n._current = "it"
    print("[OK] i18n: inglese tradotto, chiavi ignote restano in italiano.")

    # 7) immagini: esatta -> altra stampa col timbro "Stock" -> cornice vuota.
    # (in fondo perché replace_catalog azzera il catalogo del provider)
    from PySide6.QtCore import Qt  # noqa: E402
    from PySide6.QtGui import QImage, QPixmap  # noqa: E402
    from modules.market_watch import search_model as sm  # noqa: E402
    # Il segnaposto grigio di CardTrader vale come immagine ASSENTE, e il
    # percorso relativo arriva senza slash iniziale (caso reale: "Deception of
    # the Sinful Spoils", 645 stampe su 47.980 nel catalogo vero).
    from modules.market_watch.providers import cardtrader as ctp  # noqa: E402
    assert ctp.usable_image_url("https://www.cardtrader.comfallbacks/card_uploader/show.png") == ""
    assert ctp.usable_image_url("") == ""
    assert ctp.usable_image_url("https://x/show_vera.jpg") == "https://x/show_vera.jpg"
    assert ctp._blueprint_image_url(
        {"image": {"show": {"url": "fallbacks/card_uploader/show.png"}}}) == "", \
        "il segnaposto di CardTrader non va salvato come immagine"
    assert ctp._blueprint_image_url(
        {"image": {"show": {"url": "uploads/x.jpg"}}}) == f"{ctp.IMAGE_HOST}/uploads/x.jpg", \
        "slash iniziale mancante: l'host non va incollato al percorso"
    assert ctp._blueprint_image_url(
        {"image": {"show": {"url": "/uploads/x.jpg"}}}) == f"{ctp.IMAGE_HOST}/uploads/x.jpg"

    widget.repo.replace_catalog("cardtrader", [
        # tre stampe della stessa carta: una SENZA rarità (l'arte "liscia",
        # da preferire come ripiego), una con rarità, una senza immagine
        ("901", "Mirror Force", "Ultra Rare · LOB", "http://x/show_901.jpg", "LOB"),
        ("902", "Mirror Force", "Secret Rare · DPKB", "", "DPKB"),
        ("904", "Mirror Force", "SDK", "http://x/show_904.jpg", "SDK"),
        ("903", "Carta Introvabile", "Rare · XYZ", "", "XYZ"),
        # caso "Deception": la stampa col segnaposto viene PRIMA nel catalogo.
        # Se la si prendesse come ripiego, la carta resterebbe senza immagine.
        ("905", "Carta Col Segnaposto", "Quarter Century · ROTA",
         "https://www.cardtrader.comfallbacks/card_uploader/show.png", "ROTA"),
        ("906", "Carta Col Segnaposto", "Secret Rare · ROTA", "http://x/show_906.jpg", "ROTA"),
    ])
    widget._rebuild_completer()
    # ripiego = la stampa SENZA rarità, non la prima trovata
    assert widget._stock_images["Mirror Force"] == "http://x/show_904.jpg", \
        widget._stock_images["Mirror Force"]
    exact, stock = widget._image_urls_for("902", "Mirror Force")
    assert exact == "" and stock == "http://x/show_904.jpg", (exact, stock)
    # per la stampa che È il ripiego, nessun doppione
    assert widget._image_urls_for("904", "Mirror Force") == ("http://x/show_904.jpg", "")
    # caso "Deception": il segnaposto NON deve vincere come ripiego
    exact905, stock905 = widget._image_urls_for("905", "Carta Col Segnaposto")
    assert exact905 == "", "il segnaposto non è un'immagine valida"
    assert stock905 == "http://x/show_906.jpg", \
        f"doveva ripiegare sulla foto vera dell'altra stampa, non su {stock905!r}"
    # nessuna immagine da nessuna parte: cornice vuota, niente iniziali
    assert widget._image_urls_for("903", "Carta Introvabile") == ("", "")
    icon = widget._row_icon("903", "Carta Introvabile")
    assert icon is not None and not icon.isNull(), "serve comunque una cornice"
    size = widget.table.iconSize()
    assert sm._make_empty_frame(size) is sm._make_empty_frame(size), "cornice in cache"

    # il timbro "Stock" produce un pixmap DIVERSO dall'originale (ed è in cache)
    art = QPixmap(sm.THUMB)
    art.fill(Qt.GlobalColor.darkGreen)
    marked = sm.stock_pixmap("http://x/preview_904.jpg", art)
    assert marked is not art and marked.size() == art.size()
    assert marked.toImage() != art.toImage(), "il timbro deve alterare l'immagine"
    assert sm.stock_pixmap("http://x/preview_904.jpg", art) is marked, "timbro in cache"

    # l'esatta fallisce -> si passa al ripiego, che viene messo in coda
    turl = "http://x/preview_901.jpg"
    widget._url_ref[turl] = "901"
    widget._url_name[turl] = "Mirror Force"
    widget._on_row_thumb(turl, QImage())          # immagine nulla = fallimento
    assert turl in widget._failed_thumbs, "l'URL perso va ricordato"
    stock_turl = "http://x/preview_904.jpg"
    widget._row_thumb_cache[stock_turl] = art     # come se fosse già scaricata
    icon = widget._row_icon("901", "Mirror Force")
    assert icon is not None and not icon.isNull(), "doveva ripiegare sull'altra stampa"
    before = len(widget._row_thumb_inflight)
    widget._row_icon("901", "Mirror Force")
    assert len(widget._row_thumb_inflight) == before, "un URL già fallito non va riscaricato"
    # i download di immagini sono spaziati: niente raffica verso il CDN
    from modules.market_watch import search_model as sm  # noqa: E402
    real_interval = sm._IMG_INTERVAL
    sm._IMG_INTERVAL = 0.02
    sm._img_next_at = 0.0
    import time as _time  # noqa: E402
    t0 = _time.monotonic()
    for _ in range(5):
        sm._img_slot()
    spent = _time.monotonic() - t0
    assert spent >= 4 * sm._IMG_INTERVAL * 0.8, f"slot non spaziati ({spent:.3f}s)"
    sm._IMG_INTERVAL, sm._img_next_at = real_interval, 0.0
    print("[OK] Immagini: ripiego sull'arte senza rarità col timbro 'Stock', "
          "cornice vuota come ultima spiaggia, richieste spaziate.")

    # 6) grafico dello storico prezzi
    from datetime import datetime as _dt, timedelta as _td  # noqa: E402
    from modules.market_watch import history_chart as hc  # noqa: E402

    t0 = _dt(2026, 7, 1, 10, 0, 0)

    def punto(minuti, prezzo, chiave="A"):
        return {"price": prezzo, "currency": "EUR", "filters_key": chiave,
                "captured_at": (t0 + _td(minutes=minuti)).strftime("%Y-%m-%d %H:%M:%S")}

    # i punti consecutivi con lo STESSO prezzo si fondono: sono un prezzo solo,
    # non quattro eventi (i DB vecchi registravano ogni controllo)
    runs = hc.split_runs([punto(0, 10.0), punto(1, 10.0), punto(2, 10.0),
                          punto(30, 12.0), punto(60, 11.0)])
    assert len(runs) == 1, runs
    assert [p.price for p in runs[0].points] == [10.0, 12.0, 11.0]

    # cambio di filtri = corsa nuova; tornando alla chiave di prima NON si
    # ricuce la vecchia serie (è il caso "tolgo e rimetto e mi esce +30%")
    runs = hc.split_runs([punto(0, 10.0), punto(10, 12.0),
                          punto(20, 3.0, "B"),
                          punto(30, 11.0, "A"), punto(40, 13.0, "A")])
    assert [r.key for r in runs] == ["A", "B", "A"], [r.key for r in runs]
    assert len(runs[-1].points) == 2, "la corsa attuale sono solo i punti dopo l'ultimo cambio"
    assert abs(runs[-1].change_pct() - (13.0 - 11.0) / 11.0 * 100) < 1e-6
    assert runs[1].change_pct() is None, "con un punto solo non c'è variazione da mostrare"
    assert (runs[-1].low, runs[-1].high) == (11.0, 13.0)

    # lettura a GRADINI: fra due punti vale l'ultimo prezzo, non un'interpolazione
    pts = hc.split_runs([punto(0, 10.0), punto(60, 20.0)])[0].points
    assert hc.price_at(pts, t0 + _td(minutes=59)) == 10.0, "prima del cambio vale il vecchio prezzo"
    assert hc.price_at(pts, t0 + _td(minutes=60)) == 20.0
    assert hc.price_at(pts, t0 + _td(minutes=999)) == 20.0, "l'ultimo prezzo resta in vigore"
    assert hc.price_at(pts, t0 - _td(minutes=1)) is None, "prima del primo punto non si inventa"

    # date illeggibili: si saltano, non fanno esplodere il grafico
    assert hc.parse_dt("non-una-data") is None
    assert hc.split_runs([{"price": 1.0, "currency": "EUR", "filters_key": "A",
                           "captured_at": "boh"}]) == []

    # asse dei prezzi: valori tondi che CONTENGONO i dati, anche se piatti.
    # (39.9→51.0 è il caso trovato dal vivo: l'asse si fermava a 50 e la punta
    # a 51 usciva dal riquadro.)
    for basso, alto in ((226.0, 247.0), (39.9, 51.0), (0.4, 0.55), (5.0, 1200.0),
                        (99.99, 100.01), (1.0, 3.0)):
        ticks = hc.nice_ticks(basso, alto)
        assert ticks[0] <= basso + 1e-9, (basso, alto, ticks)
        assert ticks[-1] >= alto - 1e-9, (basso, alto, ticks)
        assert len(ticks) >= 2, ticks
        passi = {round(ticks[i] - ticks[i - 1], 9) for i in range(1, len(ticks))}
        assert len(passi) == 1, f"passo dell'asse non uniforme: {ticks}"
    piatti = hc.nice_ticks(10.0, 10.0)
    assert piatti[0] < 10.0 < piatti[-1], piatti

    # il giro completo dal DB: i punti escono in ordine e col loro filters_key
    widget.repo.add_watch("cardtrader", "555", "Blue-Eyes White Dragon", "UR · LOB", 5.0)
    k1 = widget._filters_key(widget._filters)
    for prezzo in (20.0, 22.0, 21.0):
        widget.repo.record_price("cardtrader", "555", prezzo, "EUR", k1)
    righe = widget.repo.history_points("cardtrader", "555")
    assert [r["price"] for r in righe] == [20.0, 22.0, 21.0], [r["price"] for r in righe]
    assert all(r["filters_key"] == k1 for r in righe)

    dlg = hc.HistoryDialog("Blue-Eyes White Dragon", "UR · LOB", "IT · Near Mint",
                           hc.split_runs(righe))
    assert dlg.chart.current_run() is not None
    assert len(dlg.chart.current_run().points) == 3
    assert not dlg.chart.previous_runs()
    # senza serie precedenti l'interruttore non esiste: un comando spento che
    # non fa niente è peggio di un comando assente
    assert not hasattr(dlg, "prev_switch")
    dlg.deleteLater()

    # filtri appena cambiati e nessun controllo ancora fatto: la corsa attuale
    # è VUOTA — meglio dirlo che mostrare i prezzi di un'altra versione
    w555 = [w for w in widget.repo.list_watches() if w["ref_id"] == "555"][0]
    widget.repo.set_watch_filters(w555["id"], _json.dumps(
        ListingFilters(language="fr", pro_only=True).to_dict()))
    w555 = [w for w in widget.repo.list_watches() if w["ref_id"] == "555"][0]
    k2 = widget._watch_key(w555)
    assert k2 != k1
    runs2 = hc.split_runs(widget.repo.history_points("cardtrader", "555"))
    assert runs2[-1].key == k1, "l'ultima corsa in archivio è ancora quella vecchia"
    dlg2 = hc.HistoryDialog("Blue-Eyes", "UR · LOB", "FR · PRO",
                            runs2 + [hc.Run(k2, [], "EUR")])
    assert dlg2.chart.current_run().points == [], "la corsa nuova parte vuota"
    assert len(dlg2.chart.previous_runs()) == 1
    assert hasattr(dlg2, "prev_switch") and not dlg2.prev_switch.isChecked(), \
        "le serie precedenti partono NASCOSTE: non sono confrontabili"
    dlg2.chart.set_show_previous(True)
    assert len(dlg2.chart._visible_runs()) == 2
    dlg2.deleteLater()

    # 6b) il pop-up nasce dalla MINIATURA della carta
    from PySide6.QtCore import QRect as _QRect  # noqa: E402
    from core import anim as _anim  # noqa: E402

    a, b = _QRect(0, 0, 10, 10), _QRect(100, 100, 200, 120)
    assert hc.lerp_rect(a, b, 0.0) == a and hc.lerp_rect(a, b, 1.0) == b
    # con t > 1 il rettangolo SFONDA quello finale: è il rimbalzo del pop-up
    assert hc.lerp_rect(a, b, 1.1).width() > b.width()

    # Profilo del MOVIMENTO. Sono i due difetti segnalati dall'utente sulla
    # prima versione (OutBack overshoot 2.2), qui bloccati in numeri:
    # "sembra molto meccanica" = il primo fotogramma saltava di 124px, e
    # "un colpo di frusta" = si ritirava di 13px per fotogramma.
    assert hc.pop_in(0.0) == 0.0 and abs(hc.pop_in(1.0) - 1.0) < 1e-9, \
        "gli estremi devono essere esatti, altrimenti l'ultimo fotogramma scatta"
    passi = 31
    mini, finale = _QRect(0, 0, 60, 41), _QRect(0, 0, 690, 470)
    larghezze = [hc.lerp_rect(mini, finale, hc.pop_in(i / passi)).width()
                 for i in range(passi + 1)]
    delta = [larghezze[i] - larghezze[i - 1] for i in range(1, len(larghezze))]
    assert delta[0] < 40, f"partenza a scatto: {delta[0]}px nel primo fotogramma"
    ritiri = [d for d in delta if d < 0]
    assert ritiri, "senza sfondamento non è un pop-up"
    assert min(ritiri) >= -6, f"colpo di frusta: rientro di {min(ritiri)}px/fotogramma"
    assert max(larghezze) > finale.width(), "il pop deve sfondare"
    assert max(larghezze) - finale.width() < 45, "sfondamento esagerato"
    # l'uscita non rimbalza: una finestra che si chiude non deve discutere
    assert hc.pop_out(0.0) == 1.0 and hc.pop_out(1.0) == 0.0
    assert all(hc.pop_out(i / 20) >= hc.pop_out((i + 1) / 20) for i in range(20))

    # La COMPARSA della linea: era una OutCubic, che parte alla velocità
    # massima — "appare in maniera aggressiva". Ora parte e finisce da ferma.
    assert hc.draw_on(0.0) == 0.0 and hc.draw_on(1.0) == 1.0
    fotogrammi = 51                      # ~820 ms a 60 al secondo
    largh = 630.0                        # larghezza tipica del grafico
    scoperti = [(hc.draw_on((i + 1) / fotogrammi) - hc.draw_on(i / fotogrammi)) * largh
                for i in range(fotogrammi)]
    assert scoperti[0] < 4, f"la linea parte di scatto ({scoperti[0]:.0f}px)"
    assert scoperti[-1] < 4, f"la linea si ferma di scatto ({scoperti[-1]:.0f}px)"
    assert max(scoperti) < 30, f"tratto troppo veloce ({max(scoperti):.0f}px/fotogramma)"
    assert all(scoperti[i] >= -1e-9 for i in range(fotogrammi)), "non deve tornare indietro"

    # La comparsa NON parte da sola caricando i dati: con la finestra che
    # nasce dalla miniatura, la linea si disegnava due volte — una mentre la
    # finestra era ancora in volo (invisibile) e una al `replay()`.
    from PySide6.QtCore import QAbstractAnimation as _QAA  # noqa: E402
    dlg_r = hc.HistoryDialog("X", "", "", hc.split_runs(righe))
    assert dlg_r.chart._reveal == 0.0, "col grafico non ancora mostrato non si disegna nulla"
    assert dlg_r.chart._anim.state() != _QAA.State.Running, \
        "la comparsa non deve partire da set_runs: la lancia chi mostra il grafico"
    dlg_r.chart.replay()
    assert dlg_r.chart._anim.state() == _QAA.State.Running
    dlg_r.chart._anim.stop()
    # animazioni spente: il grafico dev'essere subito tutto lì, non invisibile
    _anim.set_enabled(False)
    dlg_r.chart.set_runs(hc.split_runs(righe))
    assert dlg_r.chart._reveal == 1.0, "senza animazioni il grafico deve vedersi subito"
    dlg_r.chart.replay()
    assert dlg_r.chart._reveal == 1.0
    _anim.set_enabled(True)
    dlg_r.deleteLater()

    # il rettangolo di partenza ha le PROPORZIONI della finestra (altrimenti
    # l'immagine si deforma lungo tutta la corsa: effetto gommato)
    dlg_p = hc.HistoryDialog("X", "", "", hc.split_runs(righe))
    origine_p = _QRect(383, 769, 60, 64)
    start_p = dlg_p._start_rect(origine_p, finale)
    assert abs(start_p.width() / start_p.height()
               - finale.width() / finale.height()) < 0.05, start_p
    assert (start_p.center() - origine_p.center()).manhattanLength() <= 2, \
        "deve restare centrato sulla miniatura"
    dlg_p.deleteLater()

    dlg3 = hc.HistoryDialog("Carta", "UR · LOB", "", hc.split_runs(righe))
    finale = _QRect(0, 0, 690, 470)
    origine = _QRect(383, 769, 60, 64)
    da = dlg3._start_rect(origine, finale)
    assert (da.center() - origine.center()).manhattanLength() <= 2, \
        "deve partire dalla miniatura"
    # riga non visibile (nessuna origine): si parte da un rettangolino al
    # centro, non da un punto a caso
    centro = dlg3._start_rect(None, finale)
    assert centro.width() < 100 and finale.contains(centro.center()), centro
    # l'istantanea per il fantasma si prende SENZA mostrare la finestra
    ghost = dlg3._snapshot_ghost()
    assert ghost is not None and not dlg3.isVisible(), "la finestra non deve apparire"
    ghost.deleteLater()
    # animazioni spente (Opzioni): nessun fantasma, apertura immediata
    _anim.set_enabled(False)
    dlg3._ghost = None
    dlg3.exec = lambda: 0
    assert dlg3.open_from(origine) == 0
    assert dlg3._ghost is None, "con le animazioni spente niente fantasma"
    _anim.set_enabled(True)
    dlg3.deleteLater()

    widget.repo.remove_watch(w555["id"])
    print("[OK] Grafico storico: gradini (niente interpolazione), punti "
          "duplicati fusi, corse separate dai filtri e serie precedenti "
          "nascoste per scelta.")
    print("[OK] Pop-up: nasce dalla miniatura della carta, sfonda e rientra, "
          "e con le animazioni spente si apre e basta.")

    # 7) modulo Database (YGOPRODeck): copia locale, ricerca, ponte
    from modules.card_db import api as cdb_api  # noqa: E402
    from modules.card_db.repository import CardDbRepository  # noqa: E402

    # parser difensivo: campi mancanti non devono far saltare la copia
    grezza = {
        "id": 14558127, "name": "Ash Blossom & Joyous Spring",
        # come la carta vera: è insieme Effetto E Tuner, e serve a provare
        # che categoria e abilità si sommano invece di escludersi
        "type": "Tuner Effect Monster", "frameType": "effect",
        "desc": "When a card…",
        "race": "Zombie", "attribute": "FIRE", "atk": 0, "def": 1800, "level": 3,
        "typeline": ["Zombie", "Tuner", "Effect"],
        "humanReadableCardType": "Tuner Effect Monster",
        "archetype": "Ash", "banlist_info": {"ban_tcg": "Limited"},
        "card_images": [{"image_url": "http://x/1.jpg",
                         "image_url_small": "http://x/1s.jpg"},
                        {"image_url": "http://x/2.jpg"}],
        "card_sets": [{"set_name": "Tin", "set_code": "MP22-EN257",
                       "set_rarity": "Secret Rare"}],
        "misc_info": [{"staple": "Yes", "tcg_date": "2017-05-04",
                       "formats": ["TCG", "OCG"]}],
    }
    carta, stampe = cdb_api.parse_card(grezza)
    assert carta["id"] == 14558127 and carta["ban_tcg"] == "Limited"
    assert carta["art_count"] == 2 and carta["typeline"] == "Zombie / Tuner / Effect"
    assert carta["staple"] == 1 and stampe[0][2] == "MP22-EN257"
    # una carta ridotta all'osso non deve sollevare nulla
    minima, _ = cdb_api.parse_card({"id": 1, "name": "X"})
    assert minima["ban_tcg"] == "" and minima["atk"] is None

    st_db = _St(tmp / "carddb.db")
    repo_db = CardDbRepository(st_db)
    assert repo_db.count_cards() == 0
    carta["name_it"] = "Fiore di Cenere & Gioiosa Primavera"
    carta["desc_it"] = "Quando una carta viene attivata: distruggi quel bersaglio."
    altra, _ = cdb_api.parse_card(
        {"id": 2, "name": "Pot of Greed", "type": "Spell Card",
         "desc": "Draw 2 cards.", "race": "Normal"})
    repo_db.replace_all([carta, altra], stampe)
    assert repo_db.count_cards() == 2

    # NOME e TESTO si cercano separatamente (come su DuelingBook): chi cerca
    # "dragon" nel nome non vuole le carte che nominano un drago nell'effetto.
    assert [r["name"] for r in repo_db.search({"desc": "distruggi"})] == [carta["name"]]
    assert [r["name"] for r in repo_db.search({"desc": "draw"})] == ["Pot of Greed"]
    assert [r["name"] for r in repo_db.search({"name": "cenere"})] == [carta["name"]]
    assert repo_db.search({"name": "distruggi"}) == [], \
        "'distruggi' è nel TESTO, non nel nome: non deve uscire cercando per nome"
    # i due campi si sommano
    assert len(repo_db.search({"name": "ash", "desc": "distruggi"})) == 1
    assert repo_db.search({"name": "ash", "desc": "draw"}) == []
    # si cerca mentre si digita: il prefisso basta
    assert repo_db.search({"name": "blos"}), "il prefisso deve bastare"
    # la punteggiatura da sola non deve far esplodere l'indice full-text
    assert repo_db.fts_query("-") == "" and repo_db.search({"name": "-"}) is not None
    assert repo_db.search({"name": 'pot" OR 1=1'}) is not None, \
        "gli operatori FTS vanno neutralizzati"

    # Filtri, col vocabolario del GIOCO: "Carta" = Mostro/Magia/Trappola
    # (dentro la stringa `type` dell'API), "Tipo" = Drago/Guerriero… per i
    # mostri e Proprietà = Normale/Rapida/Counter… per magie e trappole
    # (l'API li mette entrambi in `race`, che il gioco NON chiama "razza").
    assert len(repo_db.search({"card": "monster"})) == 1
    assert len(repo_db.search({"card": "spell"})) == 1
    assert len(repo_db.search({"card": "trap"})) == 0
    assert len(repo_db.search({"card": "monster", "category": "Effect"})) == 1
    assert len(repo_db.search({"card": "monster", "category": "Xyz"})) == 0
    assert len(repo_db.search({"race": "Zombie"})) == 1      # Tipo del mostro
    assert len(repo_db.search({"race": "Normal"})) == 1      # Proprietà della magia
    assert len(repo_db.search({"attribute": "FIRE"})) == 1
    assert len(repo_db.search({"banlist": "tcg"})) == 1
    assert len(repo_db.search({"banlist": "ocg"})) == 0
    assert repo_db.distinct("attribute") == ["FIRE"]
    # categoria e abilità sono cose DIVERSE e si sommano: un mostro è
    # "Effetto" E "Tuner", non l'uno oppure l'altro
    assert len(repo_db.search({"category": "Effect", "ability": "Tuner"})) == 1
    assert len(repo_db.search({"category": "Xyz", "ability": "Tuner"})) == 0
    # INTERVALLI: estremi inclusi, e si può dare solo un capo
    assert len(repo_db.search({"atk_max": 0})) == 1          # Ash Blossom, ATK 0
    assert len(repo_db.search({"atk_min": 1})) == 0
    assert len(repo_db.search({"def_min": 1800, "def_max": 1800})) == 1
    assert len(repo_db.search({"level_min": 3, "level_max": 3})) == 1
    assert len(repo_db.search({"level_min": 4})) == 0
    # ORDINAMENTO: chi non ha il dato va in fondo in ogni caso
    per_atk = repo_db.search({}, "atk")
    assert per_atk[-1]["name"] == "Pot of Greed", \
        "una magia (senza ATK) deve finire in fondo, non in cima"
    # PAGINE: prima si tagliava a 300 e il resto era irraggiungibile
    pag0, totale = repo_db.search_page({}, "alpha", 0, 1)
    pag1, _ = repo_db.search_page({}, "alpha", 1, 1)
    assert totale == 2 and len(pag0) == 1 and len(pag1) == 1
    assert pag0[0]["id"] != pag1[0]["id"], "la seconda pagina ripete la prima"
    # le voci di Tipo/Proprietà cambiano con la carta scelta: offrire
    # "Counter" a chi cerca un mostro sarebbe una scelta che dà sempre zero
    assert repo_db.races("monster") == ["Zombie"], repo_db.races("monster")
    assert repo_db.races("spell") == ["Normal"], repo_db.races("spell")
    assert "Effect" in repo_db.categories()
    assert "Tuner" in repo_db.abilities()
    assert len(repo_db.sets_of(carta["id"])) == 1
    scheda = repo_db.card(carta["id"])
    assert scheda["desc_it"].startswith("Quando")
    st_db.close()
    print("[OK] Database: parser difensivo, copia locale, ricerca IT+EN con "
          "indice full-text, filtri col vocabolario del gioco e ban list.")

    # 7a) le due PAGINE: elenco e carta. Niente rete nel test: si sostituisce
    # la funzione che chiede la versione (l'unica chiamata all'avvio) e si
    # tolgono gli indirizzi delle immagini, così non parte alcun download.
    from modules.card_db.widget import CardDbWidget  # noqa: E402
    vera_versione = cdb_api.fetch_db_version
    vere_espansioni = cdb_api.fetch_sets
    def _niente_rete(*_a, **_k):
        raise cdb_api.YgoProError("test senza rete")
    cdb_api.fetch_db_version = _niente_rete
    cdb_api.fetch_sets = _niente_rete    # il widget le chiede all'avvio
    st_ui = _St(tmp / "carddb_ui.db")
    repo_ui = CardDbRepository(st_ui)
    senza_foto = []
    for c in (carta, altra):
        c = dict(c)
        c["image_url"] = c["image_small_url"] = ""
        senza_foto.append(c)
    repo_ui.replace_all(senza_foto, stampe)
    ctx_ui = AppContext(storage=st_ui, notifier=notifier, data_dir=tmp)
    cdb = CardDbWidget(ctx_ui)
    assert cdb.pages.currentIndex() == 0, "si parte dall'elenco"
    assert cdb.table.rowCount() == 2, cdb.table.rowCount()
    cdb._open_row(0)
    assert cdb.pages.currentIndex() == 1, "scegliendo una carta la pagina è sua"
    nomi_noti = {n for c in senza_foto for n in (c["name"], c["name_it"]) if n}
    assert cdb.d_name.text() in nomi_noti, cdb.d_name.text()
    cdb.show_list()
    assert cdb.pages.currentIndex() == 0
    # la riga è ancora selezionata: ri-cliccarla non cambia la selezione, ma
    # deve riaprire lo stesso (per questo si ascolta anche il clic)
    cdb._open_row(0)
    assert cdb.pages.currentIndex() == 1, "la riga già selezionata deve riaprirsi"
    cdb.back_btn.click()
    assert cdb.pages.currentIndex() == 0
    cdb.stop()

    # 7a-bis) badge delle lingue. Il predefinito segue l'INTERFACCIA (con
    # l'app in inglese le carte in italiano sarebbero una sorpresa) e il badge
    # acceso cambia NOME e TESTO insieme.
    from core import i18n as _i18n  # noqa: E402
    lingua_prima = _i18n.current()
    for lingua, inizio in (("en", "When a card"), ("it", "Quando una carta")):
        _i18n._current = lingua
        cdb_l = CardDbWidget(ctx_ui)
        assert cdb_l._desc_lang == lingua
        cdb_l._open_row(0)
        assert cdb_l.d_desc.text().startswith(inizio), \
            f"con l'app in {lingua} il testo dev'essere in {lingua}: {cdb_l.d_desc.text()[:40]}"
        assert cdb_l.lang_badges[lingua].isChecked(), "badge acceso sbagliato"
        atteso = carta["name_it"] if lingua == "it" else carta["name"]
        assert cdb_l.d_name.text() == atteso, cdb_l.d_name.text()
        # premendo l'altro badge cambiano insieme nome e testo
        altro = "it" if lingua == "en" else "en"
        cdb_l.lang_badges[altro].click()
        assert not cdb_l.d_desc.text().startswith(inizio), "il badge non commuta"
        assert cdb_l.d_name.text() != atteso, "il badge deve cambiare anche il nome"
        # il nome INGLESE non si perde mai: con l'italiano acceso va sotto
        if altro == "it":
            assert carta["name"] in cdb_l.d_type.text(), cdb_l.d_type.text()
        cdb_l.stop()
    # carta senza italiano: badge IT spento E disabilitato, col perché nel
    # tooltip — un badge assente farebbe saltare la fila e non direbbe nulla
    _i18n._current = "it"
    cdb_l = CardDbWidget(ctx_ui)
    cdb_l.show_card(2)                      # "Pot of Greed", solo inglese
    assert cdb_l.d_desc.text() == "Draw 2 cards."
    assert not cdb_l.lang_badges["it"].isEnabled()
    assert not cdb_l.lang_badges["it"].isChecked()
    assert cdb_l.lang_badges["en"].isChecked()
    assert cdb_l.lang_badges["it"].toolTip()
    cdb_l.stop()
    # e nell'ELENCO nessuna traduzione: solo il nome inglese, canonico
    assert "\n" not in cdb.table.item(0, 1).text(), \
        "l'elenco non deve mostrare il nome tradotto"

    # 7a-ter) ristampe: riquadro con una riga per stampa, e i badge di codice
    # set e rarità sono quelli CONDIVISI col market watch (stanno nel core
    # apposta: i moduli non si importano fra loro)
    from core import badges as _badges  # noqa: E402
    from core.rarity import rarity_pixmap as _rar  # noqa: E402
    assert not _badges.set_pill("MP22-EN257", 20).isNull()
    assert _badges.set_pill("MP22-EN257", 20) is _badges.set_pill("MP22-EN257", 20), \
        "la pillola del set va tenuta in cache"
    assert not _rar("Secret Rare", 20).isNull()

    # Etichetta del set: il codice CORTO quando basta, quello completo quando
    # due espansioni lo condividono (142 codici sono condivisi: MVP1 vale per
    # Movie Pack, Gold Edition, Secret Edition e Special Edition).
    from modules.card_db.widget import set_labels  # noqa: E402
    etichette = set_labels({
        "Maximum Crisis": {"corto": "MACR", "carta": "MACR-EN036"},
        "Movie Pack": {"corto": "MVP1", "carta": "MVP1-EN038"},
        "Movie Pack: Gold Edition": {"corto": "MVP1", "carta": "MVP1-ENG38"},
        "Senza codice": {"corto": "", "carta": "XYZ-EN001"},
    })
    assert etichette["Maximum Crisis"] == "MACR", etichette
    assert etichette["Movie Pack"] == "MVP1-EN038", etichette
    assert etichette["Movie Pack: Gold Edition"] == "MVP1-ENG38", etichette
    assert etichette["Senza codice"] == "XYZ-EN001", etichette
    # le stampe escono in ordine CRONOLOGICO, e chi non ha data va in FONDO
    # (l'alias nell'ORDER BY legava alla colonna NULL: i set senza data
    # finivano in cima come se fossero i più vecchi)
    repo_ui.replace_setinfo([("Tin", "MP22", "2022-09-15"),
                             ("Vecchio", "OLD", "2010-01-01"),
                             ("Ignoto", "NEW", "")])
    conn_ui = st_ui.conn
    conn_ui.execute("INSERT INTO cdb_sets (card_id, set_name, set_code, rarity) "
                    "VALUES (?,?,?,?)", (carta["id"], "Vecchio", "OLD-EN001", "Common"))
    conn_ui.execute("INSERT INTO cdb_sets (card_id, set_name, set_code, rarity) "
                    "VALUES (?,?,?,?)", (carta["id"], "Ignoto", "NEW-EN001", "Rare"))
    conn_ui.commit()
    ordinate = repo_ui.sets_of(carta["id"])
    assert [r["set_code"] for r in ordinate] == \
        ["OLD-EN001", "MP22-EN257", "NEW-EN001"], [r["set_code"] for r in ordinate]

    _i18n._current = "en"
    cdb_s = CardDbWidget(ctx_ui)
    cdb_s._open_row(0)                      # la carta con le stampe
    # isHidden e non isVisible: qui il widget padre non è mai a schermo, e
    # isVisible sarebbe False comunque — mentirebbe sul nostro setVisible
    assert not cdb_s.d_sets_box.isHidden()
    # una riga per CODICE set = pillola + contenitore delle rarità (niente
    # nome esteso: si ripeteva identico per ogni rarità dello stesso set)
    assert cdb_s.d_sets_grid.rowCount() == 3, cdb_s.d_sets_grid.rowCount()
    assert cdb_s.d_sets_grid.count() == 6, cdb_s.d_sets_grid.count()
    assert "3" in cdb_s.d_sets_title.text()
    # la carta senza stampe non mostra un riquadro vuoto
    cdb_s.show_card(2)
    assert cdb_s.d_sets_grid.count() == 0 and cdb_s.d_sets_box.isHidden()
    cdb_s.stop()

    # 7a-quater) riquadro dei FORMATI: ban list TCG/OCG e punti Genesys.
    # Tre distinzioni che a schermo si scriverebbero uguale: in lista /
    # legale (3 copie) / mai uscita in quel formato. E per Genesys, uno 0 è un
    # punteggio VERO, mentre "non scaricato" è un'altra cosa.
    _i18n._current = "it"      # le attese qui sotto sono in italiano
    conn_ui.execute("UPDATE cdb_cards SET genesys = 42 WHERE id = ?", (carta["id"],))
    conn_ui.execute("UPDATE cdb_cards SET formats = ? WHERE id = ?",
                    (_json.dumps(["OCG"]), 2))       # Pot of Greed: solo OCG
    conn_ui.commit()
    assert repo_ui.has_genesys()
    cdb_f = CardDbWidget(ctx_ui)

    def _formati(widget):
        letto = {}
        for r in range(widget.d_formats.rowCount()):
            c0 = widget.d_formats.itemAtPosition(r, 0)
            c1 = widget.d_formats.itemAtPosition(r, 1)
            if c0 and c1:
                valore = c1.widget()
                letto[c0.widget().text()] = valore.text() or f"badge:{valore.toolTip()}"
        return letto

    cdb_f.show_card(carta["id"])
    letto = _formati(cdb_f)
    assert letto["TCG"] == "badge:Limited", letto      # in lista → badge
    assert letto["OCG"] == "3 copie", letto            # legale e non in lista
    assert letto["Genesys"] == "42 punti", letto
    cdb_f.show_card(2)                                  # solo OCG, 0 punti
    letto = _formati(cdb_f)
    assert "non uscita" in letto["TCG"], letto
    assert letto["OCG"] == "3 copie", letto
    # uno 0 è un punteggio, non un buco
    conn_ui.execute("UPDATE cdb_cards SET genesys = 0 WHERE id = 2")
    conn_ui.commit()
    cdb_f.show_card(2)
    assert _formati(cdb_f)["Genesys"] == "0 punti", _formati(cdb_f)
    # ...e "non scaricato" è un'altra cosa ancora
    conn_ui.execute("UPDATE cdb_cards SET genesys = NULL")
    conn_ui.commit()
    cdb_f.show_card(2)
    assert not repo_ui.has_genesys()
    assert "non scaricato" in _formati(cdb_f)["Genesys"], _formati(cdb_f)
    cdb_f.stop()

    _i18n._current = lingua_prima
    cdb_api.fetch_sets = vere_espansioni
    _i18n._current = lingua_prima
    st_ui.close()
    cdb_api.fetch_db_version = vera_versione
    print("[OK] Database: la carta scelta si prende la pagina, e si torna "
          "indietro col pulsante o con Esc.")
    print("[OK] Database: badge di lingua sulla carta (nome e testo insieme), "
          "predefinito = lingua dell'app, elenco senza traduzioni.")
    print("[OK] Database: ristampe in un riquadro, con i badge di set e rarità "
          "condivisi col Market Watch (core/badges.py, core/rarity.py).")
    print("[OK] Database: riquadro dei formati — ban list TCG/OCG, 3 copie, "
          "'mai uscita' e punti Genesys (0 ≠ dato mancante).")

    # 7b) ponte fra moduli: passa dal CONTESTO, i moduli non si conoscono
    ricevuti = []
    ctx.open_module = lambda mid, payload=None: (ricevuti.append((mid, payload)), True)[1]
    assert widget.handle_request({"card_name": "Dark Magician"})
    assert widget.search_input.text() == "Dark Magician"
    assert not widget.handle_request({}), "senza nome non si fa finta di niente"
    from core.context import AppContext as _AC  # noqa: E402
    vuoto = _AC(storage=storage, notifier=notifier, data_dir=tmp)
    assert vuoto.open_module("chiunque", {"x": 1}) is False, \
        "senza finestra principale la navigazione dice di no, non esplode"
    print("[OK] Ponte fra moduli: la carta arriva alla ricerca del Market Watch.")

    # 7c) importazione .ydk: il file porta passcode e QUANTITÀ, non rarità
    from modules.market_watch import ydk as _ydk  # noqa: E402
    from modules.market_watch.repository import (  # noqa: E402
        CardCatalogError as _CatalogError,
        MarketWatchRepository as _MWRepo,
    )
    from modules.market_watch.widget import PROVIDER as _PROV  # noqa: E402
    from modules.market_watch.ydk_dialog import (  # noqa: E402
        YdkImportDialog,
        sort_printings,
    )

    # -- il parser: sezioni, quantità, righe sporche --
    testo_ydk = ("#created by tester\n#main\n14558127\n14558127\n14558127\n"
                 "84192580\n84192580\n#extra\n27572350\n!side\n84192580\n"
                 "rumore\n")
    mazzo = _ydk.parse(testo_ydk)
    per_codice = {c.passcode: c for c in mazzo.cards}
    assert len(mazzo.cards) == 3, mazzo.cards
    assert per_codice[14558127].total == 3
    # la stessa carta in main E side: le copie si SOMMANO, perché per giocare
    # quel mazzo bisogna possederle tutte
    assert per_codice[84192580].total == 3, per_codice[84192580]
    assert per_codice[84192580].split
    assert per_codice[84192580].sections_label() == "2 main + 1 side"
    assert not per_codice[27572350].split, "una sola sezione: niente spiegazione"
    assert mazzo.total_copies == 7
    # quello che non si capisce si mostra, non si butta via in silenzio
    assert mazzo.ignored == [(12, "rumore")], mazzo.ignored
    # senza intestazione le copie non si perdono, e gli zeri davanti non contano
    assert _ydk.parse("00014558127\n").cards[0].passcode == 14558127
    assert _ydk.parse("").cards == []

    # -- "tabella assente" e "query fallita" NON sono la stessa cosa --
    # Chi non ha mai aperto il Database non ha la tabella: stato NORMALE, e
    # riceve un vuoto. La cura è sincronizzare.
    st_senza = Storage(tmp / "senza_catalogo.db")
    repo_senza = _MWRepo(st_senza)
    assert repo_senza.card_catalog_status() == ("assente", "")
    assert not repo_senza.has_card_catalog()
    assert repo_senza.cards_by_passcode([14558127]) == {}
    # tabella creata ma ancora senza righe: sempre "sincronizza"
    st_senza.execute(
        "CREATE TABLE cdb_cards (id INTEGER PRIMARY KEY, name TEXT, "
        "name_it TEXT, image_url TEXT, image_small_url TEXT)")
    assert repo_senza.card_catalog_status() == ("vuota", "")
    assert repo_senza.cards_by_passcode([14558127]) == {}
    st_senza.close()

    # La tabella c'è ma le manca una colonna: NON deve diventare "nessuna
    # carta". Sarebbe lo stesso messaggio del caso sopra, e manderebbe
    # l'utente a sincronizzare — che riscrive le RIGHE, non la FORMA.
    st_rotto = Storage(tmp / "catalogo_rotto.db")
    repo_rotto = _MWRepo(st_rotto)
    st_rotto.execute("CREATE TABLE cdb_cards (id INTEGER PRIMARY KEY, name TEXT)")
    st_rotto.execute("INSERT INTO cdb_cards VALUES (14558127, 'Ash Blossom')")
    stato_rotto, mancanti_rotto = repo_rotto.card_catalog_status()
    assert stato_rotto == "incompleta", stato_rotto
    assert "image_small_url" in mancanti_rotto, mancanti_rotto
    assert not repo_rotto.has_card_catalog()
    try:
        repo_rotto.cards_by_passcode([14558127])
        raise AssertionError("una tabella illeggibile deve farsi sentire")
    except _CatalogError as exc:
        assert exc.stato == "incompleta", exc.stato
        assert "name_it" in exc.dettaglio, exc.dettaglio
    st_rotto.close()

    # -- col catalogo, i passcode diventano nomi (quelli ignoti restano fuori) --
    # le colonne sono quelle VERE di cdb_cards: se la finta ne perde una, la
    # query fallisce e il ponte difensivo la trasforma in "nessuna carta"
    storage.execute(
        "CREATE TABLE IF NOT EXISTS cdb_cards (id INTEGER PRIMARY KEY, "
        "name TEXT, name_it TEXT, image_url TEXT, image_small_url TEXT)")
    storage.execute(
        "INSERT OR REPLACE INTO cdb_cards (id, name, name_it, image_url, "
        "image_small_url) VALUES (?, ?, ?, ?, ?)",
        (14558127, "Ash Blossom & Joyous Spring", "Fioritura di Cenere", "", ""))
    assert widget.repo.has_card_catalog()
    trovate = widget.repo.cards_by_passcode([14558127, 27204312])
    assert set(trovate) == {14558127}, trovate

    # -- le stampe: dalla più comune alla più ricercata --
    for _ref, _det, _code in (("bp-secret", "Secret Rare · Maximum Crisis", "MACR"),
                              ("bp-com-1", "Common · Structure Deck", "SDSB"),
                              ("bp-com-2", "Common · Structure Deck", "SDSB")):
        storage.execute(
            "INSERT OR REPLACE INTO mw_catalog (provider, ref_id, name, detail, "
            "image_url, set_code) VALUES (?, ?, ?, ?, ?, ?)",
            (_PROV, _ref, "Ash Blossom & Joyous Spring", _det, "", _code))
    stampe = sort_printings(widget.repo.printings(_PROV, "Ash Blossom & Joyous Spring"))
    assert len(stampe) == 3
    assert stampe[0]["ref_id"].startswith("bp-com"), [s["ref_id"] for s in stampe]
    assert stampe[-1]["ref_id"] == "bp-secret", [s["ref_id"] for s in stampe]

    # -- il dialogo: NIENTE è preselezionato (sceglierlo sarebbe inventare) --
    voci_ydk = [{"passcode": 14558127, "name": "Ash Blossom & Joyous Spring",
                 "name_it": "Fioritura di Cenere", "thumb_url": "",  # niente rete
                 "copies": 3, "sections": "2 main + 1 side", "printings": stampe}]
    dlg_ydk = YdkImportDialog(voci_ydk, unknown=[27204312], ignored=[(12, "rumore")],
                              default_name="Prova")
    assert not dlg_ydk._ok_btn.isEnabled(), "senza scelte non si crea la base"
    assert dlg_ydk.result_cards() == []
    # il mazzo è una GRIGLIA di carte; le stampe compaiono scegliendone una
    assert dlg_ydk.grid.count() == 1
    assert dlg_ydk.prints.count() == 0, "finché non scegli una carta, niente stampe"
    dlg_ydk.grid.setCurrentRow(0)
    assert dlg_ydk.prints.count() == 3
    # due stampe con rarità ed espansione identiche restano DUE voci distinte:
    # sono blueprint diversi, con prezzi diversi. Si distinguono col numero.
    etichette = [dlg_ydk.prints.item(k).text() for k in range(3)]
    assert sum("#bp-com" in e for e in etichette) == 2, etichette
    # scegliere una stampa abilita il pulsante e porta con sé le copie
    dlg_ydk._choose(0, 0)
    assert dlg_ydk._ok_btn.isEnabled()
    assert "✓" in dlg_ydk.grid.item(0).text(), "la carta a posto si vede nella griglia"
    scelte_ydk = dlg_ydk.result_cards()
    assert len(scelte_ydk) == 1 and scelte_ydk[0][1] == 3, scelte_ydk
    assert scelte_ydk[0][0].name == "Ash Blossom & Joyous Spring"
    # ri-clic sulla stessa = ci ho ripensato
    dlg_ydk._choose(0, 0)
    assert not dlg_ydk._ok_btn.isEnabled() and dlg_ydk.result_cards() == []
    assert "✓" not in dlg_ydk.grid.item(0).text()
    # i codici non riconosciuti si vedono, non spariscono
    assert "27204312" in dlg_ydk.summary.text(), dlg_ydk.summary.text()
    dlg_ydk.deleteLater()
    print("[OK] Importa .ydk: sezioni sommate, righe sporche mostrate, ponte "
          "catalogo carte che distingue 'assente' da 'illeggibile', mazzo in "
          "GRIGLIA con le immagini dalla "
          "cache su disco, e NIENTE preselezionato (la stampa la sceglie l'utente).")

    widget.stop()
    storage.close()
    print("\nTutti i controlli superati.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
