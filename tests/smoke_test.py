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
    # in tabella la condizione è la sigla; il nome intero sta nel tooltip
    assert widget3.table.item(0, 4).text() == "NM", "condizione non ricaricata al riavvio"
    assert widget3.table.item(0, 4).toolTip() == "Near Mint"
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
    print("[OK] Condizioni abbreviate: NM/LP/SP/MP/PL, sconosciute intatte.")

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

    widget.stop()
    storage.close()
    print("\nTutti i controlli superati.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
