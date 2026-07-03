# Registro tecnico — YGO Toolbox (handoff sviluppo)

_Aggiornato: 2026-07-03_

Riferimento schematico di architettura, decisioni, gotchas e comandi. Vedi anche
`CLAUDE.md` (regole) e `REGISTRO.md` (lato utente).

---

## 1. Architettura file

**core/** (motore generico, agnostico dai moduli)
| File | Ruolo |
|---|---|
| `app.py` | `MainWindow`: contesto condiviso, sidebar + `QStackedWidget`, scoperta/avvio moduli, dissolvenza di pagina, icona finestra/tray. **Scala UI**: `resizeEvent` → scala = larghezza/1040 (clamp 0.9–1.3, passi 0.05) → `theme.apply_scale` + `apply_scale(scale)` sui moduli che lo espongono. |
| `module_loader.py` | Scoperta automatica moduli via `pkgutil` (`<pkg>.module`). |
| `module_base.py` | Contratto `ToolModule` (`id`, `title`, `create_widget`, `on_start/stop`). |
| `context.py` | `AppContext` (storage, notifier, data_dir) + `Notifier` (tray/stdout). |
| `storage.py` | Wrapper SQLite (solo thread GUI). |
| `theme.py` | Tema: Fusion + `QPalette` scura + QSS. Costanti colore (ACCENT, POSITIVE, …) e `FONT_FAMILY` ("Inter", incorporato in `assets/fonts`, caricato con `QFontDatabase` in `apply_theme`; hinting `PreferNoHinting` per testo morbido; fallback Segoe UI). `build_qss(scale)` genera il QSS con le misure in px scalate; `apply_scale(app, scale)` lo ri-applica al volo. |
| `anim.py` | Effetti: `fade_in`, `drop_shadow`, `hover_glow`/`hover_lift` (event filter), `pulse_item`, `animate_collapse` (fisarmonica pannello). Flag globale `ENABLED` (`set_enabled`/`is_enabled`, da Opzioni → chiave `animations` nel dict display): con False gli helper saltano allo stato finale; le animazioni custom (cartelle, arrivo riga, smooth wheel, ToggleSwitch, AnimatedCombo, CardDialog) controllano `anim.is_enabled()` da sole. |
| `i18n.py` | Traduzioni leggere: ITALIANO = chiave e fallback (chiavi non mappate restano in italiano), dict `en` completo. `load_language()` all'avvio (PRIMA della UI, da main), scelta in `~/.ygo_toolbox/language.txt`, `tr("…")` ovunque nelle stringhe visibili; template con `.format()`. La lingua si applica al RIAVVIO (la UI si costruisce una volta). |

**modules/market_watch/**
| File | Ruolo |
|---|---|
| `module.py` | Punto di aggancio (`MarketWatchModule`). |
| `widget.py` | Tutta la UI + logica: ricerca live, watchlist, controlli prezzi, anteprima, Opzioni. |
| `repository.py` | Accesso DB (tabelle `mw_*`) + migrazioni + settings. |
| `providers/base.py` | Contratto `PriceProvider`, `CardRef`, `PriceQuote`, `ListingFilters`. |
| `providers/cardtrader.py` | Client HTTP + parsing + `fetch_catalog` (paginato) + filtri annunci + euristica "americana". |
| `workers.py` | `QThread`: `PriceFetchWorker`, `CatalogSyncWorker`, `ImageFetchWorker`. |
| `search_model.py` | `ThumbDelegate` (disegno voci popup: miniatura, testo, pill codice, hover animato) + download miniature. NB hover: scala ASIMMETRICA (y 1.07, x 1.018) — oltre i bordi della finestra popup non si può disegnare, con 1.06 anche in X la pill veniva tagliata al bordo. |
| `flags.py` | Bandierine paesi disegnate a runtime con QPainter (~38 paesi; strisce/croci/casi speciali, pill col codice come ripiego) + `country_name` per i tooltip. Cache per (codice, altezza). Zero asset, zero rete. |
| `rarity.py` | Badge rarità (pill con sigla community: UR, ScR, QCSR, … e colore/gradiente "foil"). Match per SOTTOSTRINGA dal più specifico al più generico ("rare" per ultimo!); sconosciute → iniziali su pill neutra. Cache per (nome, altezza). |
| `filters_dialog.py` | Dialoghi "in-app": `CardDialog` (base SENZA cornice di Windows: **Qt.Popup** + FramelessWindowHint + WA_TranslucentBackground → il clic fuori chiude da solo; `reject()` reindirizza ad `accept()` = **chiudere applica**, solo il pulsante Annulla scarta via `_cancel`; le QComboBox interne NON chiudono il popup). Card `QFrame#popover` con ombra; `open_near(anchor)` posiziona accanto al pulsante ed entra con **fade + scivolamento** — NB: `setWindowOpacity` è inaffidabile sulle finestre translucide di Windows → si usa `anim.fade_in` (effetto opacità annidato sopra l'ombra della card: widget diversi = lecito). `FiltersDialog` = solo filtri annunci (pulsante imbuto; per-carta con allow_global; lingua ≠ en spegne l'americana via `_on_language_changed`, MAI bloccare la combo). `DisplayDialog` = solo visualizzazione (pulsante Opzioni). `ToggleSwitch` = QCheckBox ridipinto a interruttore (pallino animato, traccia teal); freccette combo = PNG chevron generato da `theme._chevron_url` (cache in ~/.ygo_toolbox/cache — il QSS accetta solo url() per ::down-arrow). `AnimatedCombo` = tendina animata (fade sulla view + scivolamento) con menu ARROTONDATO: contenitore QComboBoxPrivateContainer reso translucido (flags Popup+Frameless+NoDropShadow, WA_TranslucentBackground) e trasparente con stylesheet a dichiarazione NUDA (il selettore di classe privata NON fa presa nei fogli di widget!) + stylesheet esplicito sulla view per ripristinarne il look; `setMaxVisibleItems(30)` per non far comparire i QComboBoxPrivateScroller (strisce-freccia squadrate sopra/sotto). Uscita card animata in `CardDialog.done()` (closeEvent con event.ignore() + reject, chiusura vera al finished; guardia `_exiting`). |
| `net.py` | `requests.Session` condivisa (keep-alive). |
| `config.py` | Token (file / env). |

**Altro:** `main.py` (entrypoint + icona app), `tests/smoke_test.py` (headless),
`ygo_toolbox.spec` (build; `datas` include `assets/fonts`, `version=` punta a
`version_info.txt`), `assets/icon.ico`, `assets/fonts/` (Inter + licenza OFL),
`core/version.py` (APP_VERSION — allineare a mano `version_info.txt`),
`LEGGIMI.txt` (guida per gli amici, va nello zip di distribuzione).
**Release:** build exe → test da profilo pulito (rinominare `~/.ygo_toolbox`,
lanciare, verificare benvenuto, ripristinare) → `Compress-Archive` di exe +
LEGGIMI in `dist\YGO Toolbox vX.Y.Z.zip`. Benvenuto: `WelcomeDialog`, flag
`welcomed` in mw_settings (marcato in silenzio se il token esiste già).

---

## 2. Modello dati (SQLite, prefisso `mw_`)

- `mw_watchlist(id, provider, ref_id, card_name, detail, threshold_pct, filters,
  added_at, position, folder_id)` — `filters` = JSON `ListingFilters` della
  singola carta (`''` = usa i globali); `position` = ordinamento manuale
  (drag&drop, a parità → alfabetico); `folder_id` = cartella (NULL = fuori).
- `mw_folders(id, provider, name, position, expanded)` — cartelle espandibili
  della watchlist; eliminandone una le carte tornano a folder_id NULL.
- `mw_price_history(id, provider, ref_id, price, currency, captured_at)` — storico
  del minimo, UNA riga per CAMBIO di prezzo (`record_price` scarta i controlli
  col prezzo invariato). La Var.% usa `last_price_change` = ultimo prezzo vs
  ultimo prezzo DIVERSO (robusto anche sui duplicati dei DB vecchi).
- `mw_catalog(provider, ref_id, name, detail, image_url, set_code)` — cache catalogo. `detail` = "rarità · espansione".
- `mw_last_quote(provider, ref_id PK, quote, captured_at)` — ULTIMO annuncio
  scelto per carta (JSON di `PriceQuote.to_dict()`; `''` = "Nessuna copia").
  **Upsert** a ogni controllo → 1 riga/carta, dimensione fissa; si cancella con
  la carta (`remove_watch`) + `cleanup_orphans` all'avvio. `prune_history(90)`
  sfoltisce lo storico vecchio al minimo giornaliero.
- `mw_settings(key, value)` — `filters` (JSON `ListingFilters` globali),
  `last_checked` (timestamp mostrato in colonna "Controllo"), `display`
  (JSON preferenze visualizzazione: `rarity_icons`, `set_codes`). La vecchia
  chiave `no_match` è migrata in `mw_last_quote` (righe con quote `''`) e rimossa.
  NB: le celle a badge (rarità, venditore) sono cell WIDGET → in vista normale
  la colonna Rarità con badge usa larghezza Fixed (ResizeToContents li ignora).

**Migrazioni:** `CREATE TABLE IF NOT EXISTS` NON aggiorna tabelle esistenti →
colonne aggiunte con `ALTER TABLE ADD COLUMN` in `_init_schema` (`mw_catalog`:
`image_url`, `set_code`; `mw_watchlist`: `filters`). Dopo aver aggiunto colonne
al catalogo serve **ri-sincronizzare**.

---

## 3. Provider CardTrader (verificato dal vivo)

- Game Yu-Gi-Oh! = **id 4** (trovato per nome in `/games`, che torna un dict).
- `/blueprints?expansion_id=..` è **paginato a 50/pagina** → `_all_blueprints`
  scorre le pagine (stop a pagina incompleta o senza id nuovi).
- Blueprint: `version` = **rarità**; `code` espansione = **codice set** (→ upper);
  `image.show.url` = immagine (host **www.cardtrader.com**).
- `/marketplace/products?blueprint_id=..` torna un **dict** {blueprint_id: [annunci]}.
  Prezzo in `price:{cents,currency}` e piatto `price_cents`.
- Per annuncio: `properties_hash` (`condition`, `yugioh_language`, `first_edition`,
  `yugioh_rarity`, …), `graded`, `on_vacation`, `description` (commento),
  `user` (`username`, `user_type` pro/normal, `country_code`, **`can_sell_via_hub`**
  = acquistabile con CardTrader Zero).

**Filtri** (`ListingFilters` in base.py, applicati in `lowest_price` via
`_listing_matches`): language, min_condition (scala `CONDITIONS`), first_edition,
zero_only (`can_sell_via_hub`), exclude_graded, pro_only, **american_only**.
Euristica USA (`_is_american_print`): lingua == "en" AND (country_code == "US"
OR regex `\b(usa|u.s.a.|american(o/a)|north american|(na|us) print)\b` sul commento;
confini di parola per non pescare "usato").

---

## 4. Decisioni chiave & GOTCHAS

1. **Cloudflare:** CardTrader (API + CDN immagini) è dietro Cloudflare. Raffiche
   → 403 "challenge" per IP (temporaneo). NON fare probing massivo. Il CDN
   immagini **rifiuta `QNetworkAccessManager`** anche con User-Agent browser →
   usare **`requests`** (in `QThread`/`QThreadPool`). Vedi memoria dedicata.
2. **Ricerca — performance:** un `QAbstractListModel` in Python come sorgente del
   `QCompleter` è **lentissimo** (il completer chiama `data()` ~47k volte/tasto →
   ~220ms). **NON** usare `UnfilteredPopupCompletion` su modello enorme (costruisce
   il popup su tutti i match → freeze di secondi). **Soluzione attuale:** ricerca
   "a token" fatta in Python su indice pre-calcolato (`_search_index`), **cappata a
   60** risultati con stop anticipato, che riempie un piccolo `QStringListModel`;
   completer in Unfiltered su quel modello piccolo. Debounce 90ms. Filtraggio
   1-2ms su query larghe.
3. **Miniature popup:** disegnate da `ThumbDelegate` **solo per le righe visibili**
   (`uniformItemSizes(True)` + tetto `MAX_INFLIGHT`). Senza `uniformItemSizes` il
   view misura ogni riga → migliaia di download simultanei → crash + Cloudflare.
4. **Un solo `QGraphicsEffect` per widget:** un widget con `drop_shadow`/hover NON
   può anche essere dissolto con `fade_in`. (Tabella: ombra statica, niente fade;
   il "vivo" arriva dal `pulse_item` sul prezzo.)
5. **PyInstaller + scoperta dinamica moduli:** `pkgutil.iter_modules` funziona in
   frozen SOLO se i moduli sono nel bundle. Vanno inclusi con
   `collect_submodules('modules'/'core')` **nello .spec**, e serve
   `sys.path.insert(0, SPECPATH)` nello spec perché trovi i NOSTRI pacchetti.
6. **Icona exe:** cambiare solo `assets/icon.ico` non invalida la cache di
   PyInstaller → ricompilare con **`--clean`** per re-incorporarla. La cache icone
   di Windows può mostrare la vecchia in Explorer (non è un bug).
7. **Console Windows cp1252:** lo smoke test forza UTF-8 su stdout/stderr per
   stampare `€`, `→`, ecc.
8. **Panoramica adattiva (usabile a QUALSIASI larghezza):** sotto lo schermo
   intero non si stringono solo le colonne: una **DENSITÀ** (1.0 → 0.65, scatti
   0.05, riferimento = rapporto spazio/colonne dello schermo intero ~0.8×scala)
   rimpicciolisce l'INTERA vista — font, altezza righe, miniature, badge,
   pulsanti (helper `_rp()` = `_sp()` × densità). Poi il fit colonne: minimi =
   header (grassetto) + contenuto tipico per Prezzo/Var. ("888.88 €");
   eccedenza recuperata comprimendo le colonne con margine; se non basta,
   **header ABBREVIATI** (Cond., Ling., Vend., Comm. — tooltip = nome intero).
   Riserva Commenti ~13% del viewport (min 84). Verificato coi font veri:
   nessuno scroll da 880 a 1920, densità 1.0 a schermo intero (invariato).
   `QTableWidgetItem` rende il testo multi-riga (`\n`) se la riga è alta; una
   `QIcon` impostata dopo l'inserimento rispetta l'`iconSize` del view.
9. **Viewport stantio durante il resize:** nei `resizeEvent` del widget i FIGLI
   (tabella) non sono ancora ri-layoutati → leggere lì `viewport().width()` dà
   il valore VECCHIO. Soluzione: `installEventFilter` sul **viewport della
   tabella** e ricalcolare il fit al suo `QEvent.Resize` (geometria definitiva).
10. **Scala UI:** un solo punto di verità (`MainWindow._update_ui_scale`),
    quantizzata a passi di 0.05 per non rigenerare il QSS a ogni pixel. Il QSS
    scala SOLO le misure in px (font/padding/raggi), non colori né bordi 1px.
    Nei moduli le dimensioni passano da `self._sp()/_sz()/_scaled_font()`.
11. **Animazioni su QTableWidgetItem = rischio CRASH nell'exe:** un re-render
    (es. massimizzare in Panoramica) DISTRUGGE gli item mentre le animazioni
    (pulse del prezzo, lampo di arrivo) sono a metà: toccarli solleva
    RuntimeError dentro uno slot. Da sorgente è solo un traceback; nell'exe
    WINDOWED (stderr = None) PySide abortisce il processo. Regola: ogni slot
    di animazione che tocca item deve avere try/except RuntimeError (vedi
    anim.pulse_item, _animate_row_arrival); inoltre main._ensure_streams
    dirotta stdout/stderr su ~/.ygo_toolbox/log.txt come rete di sicurezza.
    VARIANTE: con DeleteWhenStopped anche il riferimento Python all'animazione
    muore a fine corsa → richiamare .stop()/.state() al giro dopo esplode
    (bug "interruttori che non si spengono"). Per animazioni RIAVVIABILI
    (ToggleSwitch) usare UN oggetto persistente creato nel costruttore,
    senza DeleteWhenStopped.
12. **Font offscreen = tofu LARGO:** in `QT_QPA_PLATFORM=offscreen` mancano i
    font e ogni glifo è largo ~1em → `QFontMetrics` gonfia i minimi colonna e
    i test di fit mostrano scroll che sul desktop reale non c'è. Per verifiche
    di layout coi FONT VERI: piattaforma windows di default + finestra con
    `setAttribute(WA_DontShowOnScreen)` prima di `show()` — layout reale,
    niente flash a schermo.

---

## 5. Flussi principali

- **Ricerca:** `search_input.textEdited` → `_on_search_text` (reset selezione +
  debounce) → `_apply_search_filter` (token-AND su `_search_index`, cap 60) →
  `QStringListModel` → `QCompleter.complete()`. Selezione: `activated` →
  `_on_pick` (`_label_to_ref[label]` → `CardRef`).
- **Prezzi:** `check_now` costruisce job `(ref_id, filtri_effettivi)` con
  `_effective_filters(watch)` (filtri della carta se presenti, altrimenti i
  globali) → `PriceFetchWorker` → `lowest_price(card_id, filters)` (ritorna un
  `PriceQuote` arricchito: prezzo + campi strutturati condition/language/
  first_edition/zero, venditore, paese, commento, quantità) → `_on_prices`
  (scrive `mw_price_history`, notifica se calo ≥ soglia, salva
  `self._last_quotes` e **persiste tutto** con upsert in `mw_last_quote` +
  `last_checked` nei settings) → `_render_after_check` (+ `pulse_item`).
  Se `lowest_price` torna `None`, il ref va in `_no_match_refs` → riga "Nessuna
  copia" (riga con quote `''` in `mw_last_quote`). All'avvio il widget ricarica
  `_last_quotes`, `_no_match_refs` e `last_checked` dal DB (Panoramica piena
  subito) e ~2,5 s dopo parte `_startup_check` (check automatico silenzioso,
  solo se token + watchlist non vuota).
- **Filtri per carta:** icona impostazioni per riga → `_open_item_settings` →
  `FiltersDialog(allow_global=True)` → `repo.set_watch_filters` (`''` = globali).
- **Immagini:** anteprima grande via `ImageFetchWorker` (QImage decodificato fuori
  GUI); miniature del popup via `ThumbDelegate`; miniature di riga watchlist via
  `_row_icon`/`_on_row_thumb` (QThreadPool + `SESSION`, `_ThumbTask` con size). Cache per URL.
- **Filtri globali:** `open_options` → `FiltersDialog` → salva JSON in
  `mw_settings.filters` → `provider.filters` → ricontrollo.
- **Panoramica (`_toggle_overview`):** nasconde il pannello ricerca (animazione
  `anim.animate_collapse`) e delega a `_apply_responsive_sizing()` (righe,
  miniature, font, colonne — tutto già scalato con la UI). Tabella a **16
  colonne** modulari (0 Immagine, 1 Nome, 2 Rarità, 3 Set, 4 Condizione,
  5 Lingua, 6 1ª ed., 7 Zero, 8 Prezzo, 9 Var., 10 Soglia, 11 Controllo,
  12 Venditore, 13 Commenti, 14 Q.tà, 15 Azioni): Panoramica mostra 0-9 +
  12-15 (nasconde 10,11), normale mostra 0-3 + 8-11 + 15 (nasconde 4-7,12-14).
  Cella Venditore = widget (`_seller_cell`): username + `flags.flag_pixmap`
  del paese + badge `_make_pro_badge` per i PRO, sfondo trasparente.
- **Cartelle & drag&drop:** il modello visuale è `self._row_entries`
  (lista di `("folder", riga)` / `("watch", riga)`); `_render_after_check`
  costruisce cartelle → carte (se `expanded`) → carte fuori. Riga-cartella =
  item unico con `setSpan(row, 0, 1, 15)` — la colonna Azioni resta FUORI
  dallo span e ospita i pulsanti rinomina (matita)/elimina della cartella;
  etichetta = freccia + 📁/📂 + nome + n° carte + totale € (somma ultimi
  prezzi, esclusi i "Nessuna copia"). Ricordarsi `clearSpans()` a ogni render
  e di resettare le altezze riga. Il drop di Qt sposterebbe i singoli
  item rompendo span/cell widget → `_WatchTable.dropEvent` lo intercetta
  (`IgnoreAction`) ed emette `row_moved(da, a)`; `_on_row_moved` decide
  (carta→riordina/in cartella, cartella→riordina cartelle) e `_move_watch`
  riscrive il layout normalizzato (`set_watch_layout`). Toggle su
  `cellClicked` con **fisarmonica animata** (`_toggle_folder`:
  QVariantAnimation sulle altezze riga; in chiusura il re-render avviene al
  `finished`), CRUD cartelle nel menu contestuale. Dopo ogni spostamento
  `_flash_watch`/`_flash_folder` → `_animate_row_arrival` (altezza 45→100% +
  lampo ACCENT sui BackgroundRole, poi reset a None per non rompere la zebra;
  la riga cartella ripristina SURFACE_2).
- **Fluidità:** tabella con `ScrollPerPixel` (default = salto per riga, a
  scatti con righe alte); `_render_after_check` sospende gli update durante
  il rebuild (`setUpdatesEnabled`) → un solo repaint; la riscalatura del tema
  (`MainWindow`) è DIFFERITA con timer coalescente da 120 ms (rigenerare il
  QSS ri-stilizza tutti i widget: farlo a ogni scatto di drag = jank).
  **NIENTE QGraphicsEffect sulla tabella**: l'ombra sfumata ri-rasterizza e
  ri-sfoca l'intero widget a ogni frame di scroll (misurati ~6 ms/frame, fps
  dimezzati) — le ombre stanno solo su pannelli statici. Rotellina con
  **scroll animato** (`_smooth_wheel`: easing 150 ms, scatti accumulabili;
  i touchpad con pixelDelta restano al nativo).

---

## 6. Build / test

```bash
# dipendenze
pip install -r requirements.txt          # PySide6, requests (+ pyinstaller, pillow per build/icona)

# test headless
QT_QPA_PLATFORM=offscreen python tests/smoke_test.py

# eseguibile (onefile, windowed)
.venv\Scripts\pyinstaller --noconfirm ygo_toolbox.spec
# ...con cambio icona:
.venv\Scripts\pyinstaller --noconfirm --clean ygo_toolbox.spec
```

Verifica offscreen della GUI (utile in sviluppo): istanziare `MainWindow` con
`QT_QPA_PLATFORM=offscreen` e usare `widget.grab().save(png)` per un'anteprima
(il testo appare come tofu: mancano i font nell'offscreen, non è un bug).

---

## 7. Idee future / TODO

- Grafico dello storico prezzi (dati già in `mw_price_history`).
- Controllo in background anche ad app chiusa.
- Colonne Panoramica trascinabili/personalizzabili; nascondere colonne sotto una
  certa larghezza (oggi la Panoramica dà il meglio a schermo intero).
- Filtro per paese venditore; altre parole chiave per l'euristica "americana".
- Provider CardMarket (nuova classe in `providers/`).
- Quando un ref esce da "Nessuna copia", la variazione % è calcolata sull'ultimo
  prezzo storico (che può essere pre-filtri): eventualmente gestire il caso.

**Fatto il 2026-07-02/03:** cartelle "canoniche" (📁 + conteggio + totale € +
pulsanti rinomina/elimina) con fisarmonica animata; fluidità (ScrollPerPixel,
render senza flicker, scala differita, NIENTE effetti grafici sulla tabella,
rotellina animata); restyling (font Inter incorporato, raggi più morbidi,
zebra + separatori marcati); animazione di arrivo allo spostamento voci;
header a pulsanti-icona; impostazioni riorganizzate in CardDialog "in-app"
(imbuto = filtri accanto alla ricerca, Opzioni = solo visualizzazione,
clic fuori = chiudi e applica, entrata/uscita animate); ToggleSwitch al posto
delle checkbox; chevron per le combo; tendine arrotondate e animate
(AnimatedCombo); lingua sempre modificabile (americana si spegne da sola);
fix crash massimizzazione (animazioni su item distrutti) + log dell'exe in
~/.ygo_toolbox/log.txt; Var.% dall'ultimo CAMBIO di prezzo.

**Fatto il 2026-07-01/02 (oltre a quanto sopra):** scala UI responsive
(finestra → QSS + moduli), colonne Panoramica separate (Condizione/Lingua/
1ª ed./Zero), fit colonne senza scroll né header troncati, bandierine paese +
badge PRO in colonna Venditore (`flags.py`), persistenza `mw_last_quote`
(Panoramica piena al riavvio), unificazione/migrazione "no_match", pulizia
dati alla rimozione + orfani + sfoltimento storico >90 gg, controllo
automatico all'apertura.

**Fatto in precedenza:** "Nessuna copia" persistente, modalità Panoramica
(animata, colonne modulari, info annuncio venditore/commenti/quantità),
miniature di riga, filtri per singola carta.
