# Registro tecnico — YGO Toolbox (handoff sviluppo)

_Aggiornato: 2026-07-30_

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
| `updates.py` | Controllo aggiornamenti. `LATEST_URL` = API release di GitHub: risponde solo se il repo è pubblico **e c'è almeno una Release pubblicata** (i tag non contano); altrimenti 404 e il controllo tace (è la regola: **silenzio su qualunque problema** — un errore per un controllo che l'utente non ha chiesto è solo fastidio). In alternativa basta un JSON pubblico con `tag_name`/`html_url`. `is_newer` confronta per NUMERI, non alfabeticamente: "1.0.9" < "1.0.23", che alfabeticamente sarebbe il contrario. Mai scaricamento automatico: si avvisa e si apre la pagina. `check_async` gira in un thread daemon; il risultato torna alla GUI via **segnale Qt** (`MarketWatchWidget._update_found`), mai chiamando la UI dal thread. |
| `badges.py` | Pillole condivise: `pill(testo, altezza, ink, bg)` e `set_pill(codice)` (fondo scuro, sigla teal). Stavano nel market_watch; dalla v1.1.5 sono nel core perché le usa anche il Database — e i moduli **non si importano fra loro**. Un vocabolario visivo comune va in un posto comune. |
| `rarity.py` | Badge rarità (sigla community UR/ScR/QCSR… + colori foil), `rarity_rank` per l'ordinamento e **`is_rarity`** (v1.1.7): YGOPRODeck mette a volte altro in quel campo — 192 stampe su 44.190 con "2", "3", "New", "European debut", "force-SMW". Il filtro NON è una lista nera (invecchierebbe al primo refuso nuovo): passa ciò che la scala conosce **o** che contiene una parola da rarità (`rare`, `common`, `short print`, `duel terminal`), così una rarità inventata domani resta visibile. Verificato su tutti i 48 valori distinti del DB: scartati gli 8 sbagliati, zero rarità vere perse. Spostato da `modules/market_watch/` al core nella v1.1.5, stesso motivo. Match per SOTTOSTRINGA dal più specifico al più generico ("rare" per ultimo!). |
| `i18n.py` | Traduzioni leggere: ITALIANO = chiave e fallback (chiavi non mappate restano in italiano), dict `en` completo. `load_language()` all'avvio (PRIMA della UI, da main), scelta in `~/.ygo_toolbox/language.txt`, `tr("…")` ovunque nelle stringhe visibili; template con `.format()`. La lingua si applica al RIAVVIO (la UI si costruisce una volta). |

**modules/market_watch/**
| File | Ruolo |
|---|---|
| `module.py` | Punto di aggancio (`MarketWatchModule`). |
| `widget.py` | Tutta la UI + logica: ricerca live, watchlist, controlli prezzi, anteprima, Opzioni. |
| `repository.py` | Accesso DB (tabelle `mw_*`) + migrazioni + settings. |
| `providers/base.py` | Contratto `PriceProvider`, `CardRef`, `PriceQuote`, `ListingFilters`. |
| `providers/cardtrader.py` | Client HTTP + parsing + `fetch_catalog` (paginato) + filtri annunci + euristica "americana" + **rate limit** (`LIMITER`, vedi GOTCHA 13). |
| `workers.py` | `QThread`: `PriceFetchWorker` (una carta alla volta, tollerante agli errori, segnale `progress`), `CatalogSyncWorker`, `ImageFetchWorker`. |
| `search_model.py` | `ThumbDelegate` (disegno voci popup: miniatura, testo, pill codice, hover animato) + download miniature. NB hover: scala ASIMMETRICA (y 1.07, x 1.018) — oltre i bordi della finestra popup non si può disegnare, con 1.06 anche in X la pill veniva tagliata al bordo. |
| `flags.py` | Bandierine paesi disegnate a runtime con QPainter (~38 paesi; strisce/croci/casi speciali, pill col codice come ripiego) + `country_name` per i tooltip. Cache per (codice, altezza). Zero asset, zero rete. |
| *(in `widget.py`)* `_make_condition_pill` / `_make_language_pill` | Badge di condizione e lingua (`_pill` è la forma comune, la stessa di rarità e codice set). Colore della condizione: `_CONDITION_RANK` (0 = perfetta, 1 = rovinata) → interpolazione verde→giallo→rosso. È un DIZIONARIO, non `indice/len`: le scale dell'API e del sito hanno lunghezze diverse, e un indice darebbe alla stessa condizione posizioni diverse nelle due. Testo colorato su fondo dello stesso colore all'alpha 38: colorare tutto il fondo darebbe cinque macchie accese per riga. La lingua resta NEUTRA di proposito (il colore lì accanto porta già un giudizio). Sconosciuta → grigio e nome intero. Sono cell WIDGET: colonne 4/5 devono avere larghezza dichiarata, `ResizeToContents` li ignora. |
| *(in `widget.py`)* `_condition_short` | Sigle delle condizioni (NM, LP, SP, MP, …). Match **ESATTO** sul nome intero: "played" è dentro "light played" e "slightly played", un match per sottostringa le ridurrebbe tutte a PL (l'opposto di `rarity.py`, dove il match parziale serve). La mappa contiene sia i nomi dell'API sia quelli del sito, che NON coincidono. Sconosciuta → si lascia il nome com'è, mai una sigla inventata. Nome intero nel tooltip; colonna Condizione scesa da 110 a 70 px. |
| *(rarità)* | Spostato in **`core/rarity.py`** nella v1.1.5: lo usa anche il Database. |
| `deck_dialog.py` | `DeckDialog`: compone/modifica una **base** (mazzo) — nome, filtri comuni, carte e copie. **NON è una `CardDialog`**: quelle sono `Qt.Popup` e si chiudono al primo clic fuori, il che va bene per due interruttori ma è pessimo per un modulo dove si compongono venti carte. Qui serve una finestra modale normale. La ricerca non è riscritta né imitata: stesso indice "a token" (`_deck_search`) e soprattutto **lo stesso `ThumbDelegate`** su un `QCompleter` proprio — miniature, hover animato e pill del set arrivano da lì. Il widget passa `thumb_items` (le stesse voci di `set_cards`) e `resolve=_label_to_ref.get`. NB: il popup del completer è una finestra a parte, quindi non compare in un `grab()` del dialogo — per verificarlo va catturato `completer.popup()`. Copie e pulsante "togli" stanno nella STESSA cella (con una colonna a parte, la barra di scorrimento verticale la spingeva fuori dal bordo). **Numero delle copie illeggibile:** il QSS del tema dà ai campi 8px di padding sopra e sotto; in una cella bassa al testo restavano ~8px e del "3" si vedeva la fascia centrale — sembrava un carattere minuscolo, non un numero tagliato. Cura: righe da 52px imposte **riga per riga** (`setDefaultSectionSize` NON ridimensiona le righe già create), spinbox con altezza minima 34 e un QSS locale che riduce il padding. Diagnosi: lo stesso spinbox reso da solo, in un QHBoxLayout e in una cella — solo nella cella era alto 26px. |
| `filters_dialog.py` | Dialoghi "in-app": `CardDialog` (base SENZA cornice di Windows: **Qt.Popup** + FramelessWindowHint + WA_TranslucentBackground → il clic fuori chiude da solo; `reject()` reindirizza ad `accept()` = **chiudere applica**, solo il pulsante Annulla scarta via `_cancel`; le QComboBox interne NON chiudono il popup). Card `QFrame#popover` con ombra; `open_near(anchor)` posiziona accanto al pulsante ed entra con **fade + scivolamento** — NB: `setWindowOpacity` è inaffidabile sulle finestre translucide di Windows → si usa `anim.fade_in` (effetto opacità annidato sopra l'ombra della card: widget diversi = lecito). `FiltersDialog` = solo filtri annunci, con tre chiamanti (predefiniti dall'imbuto in header, carta-in-arrivo e per-riga entrambi con `allow_global`; lingua ≠ en spegne l'americana via `_on_language_changed`, MAI bloccare la combo). `DisplayDialog` = solo visualizzazione (pulsante Opzioni). `ToggleSwitch` = QCheckBox ridipinto a interruttore (pallino animato, traccia teal); freccette combo = PNG chevron generato da `theme._chevron_url` (cache in ~/.ygo_toolbox/cache — il QSS accetta solo url() per ::down-arrow). `AnimatedCombo` = tendina animata (fade sulla view + scivolamento) con menu ARROTONDATO: contenitore QComboBoxPrivateContainer reso translucido (flags Popup+Frameless+NoDropShadow, WA_TranslucentBackground) e trasparente con stylesheet a dichiarazione NUDA (il selettore di classe privata NON fa presa nei fogli di widget!) + stylesheet esplicito sulla view per ripristinarne il look; `setMaxVisibleItems(30)` per non far comparire i QComboBoxPrivateScroller (strisce-freccia squadrate sopra/sotto). Uscita card animata in `CardDialog.done()` (closeEvent con event.ignore() + reject, chiusura vera al finished; guardia `_exiting`). |
| `history_chart.py` | Grafico dello storico prezzi: logica pura (`split_runs`, `collapse`, `nice_ticks`, `price_at`, dataclass `Run`) + `PriceChart` (QWidget dipinto con QPainter) + `HistoryDialog`. La logica sta fuori da Qt apposta: lo smoke test la prova senza aprire finestre. **Non è una `CardDialog`** (Qt.Popup = si chiude al primo clic fuori): è una finestra che si guarda e si sorvola col mouse. Si disegna in un QWidget, NON in un pixmap → la densità dello schermo la gestisce Qt e il grafico resta nitido (non aumenta il debito dei 21 pixmap disegnati a mano). |
| `transfer.py` | Esporta/importa la watchlist in **JSON leggibile** (`formato: ygo-toolbox/watchlist`, `versione`). Niente Qt dentro: logica pura, testabile. **JSON e non CSV** perché i dati sono gerarchici (cartelle→carte, e entrambe portano un *oggetto* filtri): in CSV servirebbero più file collegati da id, meno comprensibili per un amico, non più. Chiavi in italiano: il file lo legge una persona. **NON si esportano MAI il token** (è una credenziale, e il file nasce per essere passato) **né il catalogo** (47.980 righe riscaricabili). Storico e preferenze entrano nel backup e restano fuori dall'export di una singola base: la regola la applica `export_data` da sé (`include_history=None` = "decidi tu"), non la memoria del chiamante. Import: `replace=False` aggiorna le carte già presenti con quanto dice il file (ignorarne pezzi in silenzio sarebbe peggio) e non duplica lo storico; `replace=True` svuota prima ed è l'unico caso in cui applica le preferenze. Lo storico si reinserisce con `add_history_row`, che conserva la data ORIGINALE — `record_price` timbrerebbe `now` e appiattirebbe la storia sul giorno dell'import. |
| `net.py` | `requests.Session` condivisa (keep-alive). |
| `config.py` | Token (file / env). |

**modules/card_db/** (modulo **Database**, fonte YGOPRODeck — v1.1.0)
| File | Ruolo |
|---|---|
| `module.py` | Punto di aggancio (`CardDbModule`, id `card_db`, titolo "Database"). |
| `api.py` | Client HTTP + parser difensivo + `search_blob`. In cima ci sono le **regole di YGOPRODeck citate testualmente**: sono loro a dettare l'architettura (copia locale obbligatoria, immagini da ri-ospitare, 20 richieste/s con un'ora di blocco a chi sfora). |
| `repository.py` | Tabelle `cdb_*` + ricerca + **indice full-text FTS5**. |
| `images.py` | Cache immagini **su DISCO** (`~/.ygo_toolbox/card_images/`), download spaziati, URL falliti ricordati. |
| `workers.py` | `VersionWorker` (controllo versione, silenzioso se fallisce) e `SyncWorker` (scarica inglese + italiano, analizza, consegna righe pronte alla GUI). |
| `widget.py` | UI: ricerca + filtri, elenco con miniature, scheda a lato, ponte verso il market_watch. |

**Numeri misurati sul vivo (2026-07-31), da non ri-stimare:**
14.477 carte / 23,6 MB in inglese; 11.599 / 17,2 MB in italiano (le 2.878 che
mancano non sono mai uscite in italiano); 44.190 stampe; 651 archetipi, 86
razze, 29 tipi, 315 carte in ban list; sincronizzazione ~4 s di rete+analisi e
~2 s di scrittura; file SQLite **38,5 MB** con l'indice full-text; immagini
14.642 (~27 KB la piccola, ~400 MB tutte insieme → non si scaricano in blocco).

**Altro:** `main.py` (entrypoint + icona app), `tests/smoke_test.py` (headless),
`ygo_toolbox.spec` (build; `datas` include `assets/fonts`, `version=` punta a
`version_info.txt`), `assets/icon.ico`, `assets/fonts/` (Inter + licenza OFL),
`core/version.py` (APP_VERSION — allineare a mano `version_info.txt`),
`LEGGIMI.txt` (guida per gli amici, va nello zip di distribuzione).
**Release:** alzare la versione in **TRE** posti (`core/version.py`,
`version_info.txt` — sia `filevers/prodvers` sia le stringhe — e l'intestazione
di `LEGGIMI.txt`; nell'installer NO, la legge da fuori) → build exe → test da
profilo pulito (rinominare `~/.ygo_toolbox`, lanciare, verificare benvenuto,
ripristinare) → **installer**:
```
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /DAppVersion=X.Y.Z installer.iss
```
→ `dist\YGO-Toolbox-Setup-vX.Y.Z.exe` (~46 MB), l'artefatto da consegnare
(nome SENZA spazi: GitHub li sostituisce con punti negli allegati di Release).
Infine la **Release**, che è ciò che accende il controllo aggiornamenti:
```
gh release create vX.Y.Z "dist\YGO-Toolbox-Setup-vX.Y.Z.exe" \
  --title "YGO Toolbox vX.Y.Z" --notes-file note.md --verify-tag
```
(`gh` sta in `C:\Program Files\GitHub CLI\gh.exe`, non è nel PATH di questa
sessione. NB: in PowerShell `--json a,b -q '…'` viene sbriciolato — usare
`--json` da solo e poi `ConvertFrom-Json`.)
**`installer.iss` (Inno Setup 6), scelte deliberate:**
- `PrivilegesRequired=lowest` → installazione PER UTENTE in
  `%LocalAppData%\Programs`, **nessun UAC**. Un cartello d'allarme in meno.
- SmartScreen: compare **una volta sull'installer**, non sull'app installata —
  i file scritti da un installer non ereditano il marchio "scaricato da
  internet" che invece si propaga all'exe estratto da uno zip. L'installer
  quindi RIDUCE gli avvisi, non li aggiunge.
- `AppId` è un GUID FISSO: cambiarlo farebbe accumulare una voce diversa fra i
  programmi installati a ogni versione.
- **App aperta durante l'operazione** (il caso normale: si aggiorna senza
  chiudere): `CloseApplications=force` basta per l'INSTALLAZIONE, NON per la
  disinstallazione — verificato dal vivo, i processi restavano vivi e l'exe da
  44 MB rimaneva orfano. Serve anche `[UninstallRun]` con `taskkill /F /IM`,
  che gira prima della rimozione dei file. L'eseguibile "onefile" di
  PyInstaller sopravvive alla chiusura della finestra e tiene il file bloccato.
- `~/.ygo_toolbox` non si tocca: verificato che watchlist, catalogo e token
  restano identici dopo aggiornamento E disinstallazione.
Lo zip portatile non si produce più: un solo artefatto da spiegare. Se servisse,
`Compress-Archive` di exe + LEGGIMI.
Benvenuto: `WelcomeDialog`, flag `welcomed` in mw_settings (marcato in silenzio
se il token esiste già).
**REGOLA (richiesta esplicita 2026-07-28): a ogni modifica tutto resta "a
pari"** — sorgente, commit+push su GitHub **e l'exe in `dist\`** ricompilato.
Niente exe che resta indietro rispetto al codice.
**Git/GitHub:** repo **PUBBLICO** su https://github.com/Losax/ygo-toolbox
(verificato via API il 2026-07-29; la nota "privato" di luglio era superata).
**I tag NON bastano al controllo aggiornamenti:** `releases/latest` guarda le
*Release pubblicate*, non i tag — con 0 release e 25 tag rispondeva 404 e il
controllo taceva. Dalla **v1.0.24 la Release esiste** e il controllo funziona
(verificato: `fetch_latest()` → `('v1.0.24', url)`). Ogni versione nuova vuole
la sua Release, altrimenti l'avviso resta muto.
Attenzione: `latest` **ignora bozze e prerelease** — va pubblicata come release
normale, o si torna al 404.
(branch `main`; .gitignore esclude build/dist/db/token/.claude; screenshot
del README in `docs/`). Committare e pushare a fine sessione.

---

## 2. Modello dati (SQLite, prefisso `mw_`)

- `mw_watchlist(id, provider, ref_id, card_name, detail, threshold_pct, filters,
  added_at, position, folder_id)` — `filters` = JSON `ListingFilters` della
  singola carta (`''` = usa i globali); `position` = ordinamento manuale
  (drag&drop, a parità → alfabetico); `folder_id` = cartella (NULL = fuori).
- `mw_folders(id, provider, name, position, expanded, filters)` — cartelle
  espandibili della watchlist; eliminandone una le carte tornano a folder_id
  NULL. `filters` = JSON `ListingFilters` validi per TUTTE le carte contenute
  ('' = usa i predefiniti). `is_deck` = **base (mazzo)** invece di cartella
  semplice: cambia icona (carte a ventaglio, la stessa del pulsante che le crea)
  e aggiunge il badge "BASE" in colonna 2. Serve un flag ESPLICITO perché una
  base coi filtri predefiniti e una copia per carta sarebbe indistinguibile
  da una cartella. Lo mette `_save_deck` (anche modificando una cartella
  esistente: passare dall'editor la promuove) e, una tantum per i DB
  precedenti, `_adopt_deck_flags` — filtri propri o carte in più copie sono
  dati che una cartella semplice non avrebbe motivo di avere.
- `mw_watchlist.copies` — quante copie della carta (default 1). Moltiplica il
  prezzo nei totali di base; il prezzo mostrato sulla riga resta UNITARIO,
  col numero di copie davanti al nome ("3× Ash Blossom").
- `mw_price_history(id, provider, ref_id, price, currency, filters_key, captured_at)` —
  storico del minimo, UNA riga per CAMBIO di prezzo (`record_price` scarta i
  controlli col prezzo invariato). La Var.% usa `last_price_change` = ultimo
  prezzo vs ultimo prezzo DIVERSO (robusto anche sui duplicati dei DB vecchi).
  **`filters_key` = con quali filtri è stato rilevato quel prezzo**
  (`_filters_key` = JSON dei filtri effettivi a chiavi ordinate). Prezzi presi
  con filtri diversi NON sono confrontabili: sono lingua/condizione/stampa
  diverse, cioè un altro prodotto. `last_price`, `last_price_change` e
  `record_price` filtrano per chiave (`None` = tutta la storia, per lo
  sfoltimento); `prune_history` raggruppa anche per `filters_key`, altrimenti
  due serie della stessa carta si mangerebbero a vicenda.
  **Non basta la chiave: conta anche il TRATTO** (`_run_start`). Togliere un
  filtro e rimetterlo riportava la chiave di prima, e con essa il confronto
  con punti di settimane addietro: un movimento vecchio che sembrava appena
  avvenuto (dal vivo su *Dominus Purge*: +30%). `_run_start` trova
  `MAX(id)` fra i punti con chiave DIVERSA — quello è il taglio, e il
  confronto usa solo i punti successivi. Senza interruzioni il taglio è 0 e il
  comportamento è identico a prima.
  `last_price` (riferimento dell'avviso) e `last_price_change` (Var.) usano il
  taglio; `last_known_price` NO, perché serve a MOSTRARE un prezzo: meglio
  l'ultimo noto che un trattino mentre il ricontrollo è in corso. Regola:
  **il prezzo si può ereditare, la percentuale no.**
  **Migrazione (`adopt_history_key`):** i punti nati prima della colonna hanno
  chiave `''`. All'avvio `_adopt_history_keys` li assegna ai filtri correnti
  **solo per le carte che usano i predefiniti**: se una carta ha filtri PROPRI
  vuol dire che glieli hanno messi, e i prezzi precedenti sono verosimilmente
  di prima — adottarli riproporrebbe il confronto fasullo. Quelle ripartono
  pulite; la vecchia serie resta comunque nel DB, marcata `''`.
- `mw_catalog(provider, ref_id, name, detail, image_url, set_code)` — cache catalogo. `detail` = "rarità · espansione".
- `mw_last_quote(provider, ref_id PK, quote, captured_at)` — ULTIMO annuncio
  scelto per carta (JSON di `PriceQuote.to_dict()`; `''` = "Nessuna copia").
  **Upsert** a ogni controllo → 1 riga/carta, dimensione fissa; si cancella con
  la carta (`remove_watch`) + `cleanup_orphans` all'avvio. `prune_history(90)`
  sfoltisce lo storico vecchio al minimo giornaliero.
- `mw_settings(key, value)` — `filters` (JSON `ListingFilters` globali),
  `last_checked` (timestamp mostrato in colonna "Controllo"), `display`
  (JSON preferenze visualizzazione: `rarity_icons`, `set_codes`),
  `api_interval` (spaziatura anti-429 imparata, vedi GOTCHA 13). La vecchia
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
  `image.show.url` = immagine (host **www.cardtrader.com**). **Due trappole,
  entrambe viste dal vivo il 2026-07-28:**
  1. per le stampe senza foto l'API NON lascia il campo vuoto, restituisce il
     proprio segnaposto grigio `fallbacks/card_uploader/show.png` — 645 stampe
     su 47.980. Vale come immagine assente (`usable_image_url`), altrimenti si
     scarica un rettangolo grigio buono per qualsiasi carta invece di ripiegare
     sull'arte vera di un'altra stampa;
  2. quel percorso arriva **senza slash iniziale**: concatenandolo all'host
     usciva `https://www.cardtrader.comfallbacks/…`, un host inesistente.
     `_blueprint_image_url` ora normalizza lo slash.
  Il filtro si applica anche in **lettura** (widget), non solo in scrittura:
  i cataloghi già scaricati contengono quegli URL e non deve servire una
  risincronizzata da 5 minuti per rimetterli a posto.
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
OR regex `\b(usa|u.s.a.|american(o/a)|north american|(na|us) print/edition)\b` sul commento;
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
    **Ricaduta trovata il 2026-07-28** (nel log di un exe vero): `_smooth_wheel`
    ricreava l'animazione a ogni scatto con DeleteWhenStopped e ne conservava
    il riferimento in `self._scroll_anim`. Il `prev.stop()` era protetto da
    try/except, ma la riga PRIMA — `prev.state()` — no: bastava uno scatto dato
    dopo la fine dell'animazione precedente per sollevare RuntimeError a ogni
    rotellina. Ora l'animazione è UNA sola, creata in `__init__` e riavviata
    (niente DeleteWhenStopped) — che è esattamente la cura già scritta qui
    sopra. Morale: quando si applica questa regola, coprire TUTTI gli accessi
    all'oggetto, non solo `stop()`.
12. **Font offscreen = tofu LARGO:** in `QT_QPA_PLATFORM=offscreen` mancano i
    font e ogni glifo è largo ~1em → `QFontMetrics` gonfia i minimi colonna e
    i test di fit mostrano scroll che sul desktop reale non c'è. Per verifiche
    di layout coi FONT VERI: piattaforma windows di default + finestra con
    `setAttribute(WA_DontShowOnScreen)` prima di `show()` — layout reale,
    niente flash a schermo.
13. **Rate limit dell'API (429) — il controllo watchlist è una RAFFICA.**
    `lowest_price` fa UNA chiamata `/marketplace/products` per carta: con
    qualche decina di carte in watchlist le richieste partivano attaccate e
    CardTrader rispondeva 429. Peggio: il `try/except` avvolgeva TUTTO il ciclo
    del worker, quindi un 429 a metà buttava via anche le carte già scaricate.
    Difese, in ordine di importanza:
    - `LIMITER` (`_RateLimiter` modulo-level, condiviso da tutti i client: il
      limite è per token/IP) **spazia** le chiamate. `wait()` prenota lo slot
      sotto lock e dorme FUORI dal lock, così più thread si accodano senza
      bloccarsi. Spaziatura **adattiva**: `penalize()` ×2.5 a ogni 429 (tetto
      `MAX_INTERVAL`), `relax()` ×0.92 a ogni risposta pulita (pavimento
      `MIN_INTERVAL` = 0.15s). Il limite documentato non lo conosciamo: per
      questo si tara da sola invece di inseguire un numero fisso.
    - `_get` **ritenta** il 429 (`RETRY_ATTEMPTS`) rispettando `Retry-After`
      quando è un numero, altrimenti backoff 2/4/8s. Solo alla resa alza
      `RateLimited` (sottoclasse di `CardTraderError`: chi cattura la base
      continua a funzionare).
    - `PriceFetchWorker` va **carta per carta**: un fallimento non abortisce
      il giro, ci si arrende dopo `MAX_CONSECUTIVE_FAILURES`=3 di fila
      consegnando comunque il parziale via `finished_ok(results, failed,
      last_error)`. `failed` secco solo se non è passato NIENTE.
    - La spaziatura imparata è **persistita** in `mw_settings.api_interval`
      (`_load_rate_interval`/`_save_rate_interval` nel widget: il provider
      resta puro, il DB lo tocca solo la GUI) — senza, ogni avvio ripartirebbe
      a 0.15s e si riprenderebbe gli stessi 429.
    - **ATTENZIONE ai parziali:** `_on_prices` ora AGGIORNA `_last_quotes` e
      `_no_match_refs` solo per i ref presenti in `results`. Riassegnarli in
      blocco (com'era) trasformerebbe ogni carta non controllata in
      "Nessuna copia", cancellandone il prezzo. Stesso motivo per cui
      `set_last_quotes` riceve solo i controllati.
    - Le attese sono **interrompibili** (`_sleep` a fettine da 100 ms +
      `client.should_stop`, che i worker legano a
      `isInterruptionRequested`; `widget.stop()` chiama `requestInterruption()`
      PRIMA di `wait(2000)`). Senza, chiudere l'app durante un backoff da 8s
      lasciava il thread appeso.
    - Corollario: i vecchi `time.sleep(0.1)` in `fetch_catalog`/`_all_blueprints`
      sono stati tolti — la spaziatura la mette il LIMITER, averla in due posti
      significa solo rallentare due volte.
14. **Cell widget FANTASMA nella tabella.** Sostituendo o togliendo un cell
    widget, Qt non sempre lo distrugge subito: resta figlio del viewport e
    continua a essere disegnato dov'era. I primi render avvengono prima che le
    colonne abbiano la larghezza definitiva, quindi i pulsanti Azioni di
    allora restavano incollati a SINISTRA — due iconcine davanti al nome della
    cartella, apparse con le basi ma presenti da prima. Diagnosi: confrontare
    i figli di `viewport()` con l'insieme dei `cellWidget(r, c)` vivi (le
    posizioni erano corrette, i widget in più no). Cura:
    `search_model.sweep_orphan_cell_widgets(table)`, chiamata in coda a ogni
    `_render_after_check` E in `DeckDialog._rebuild_table` (che si rifà a ogni
    carta aggiunta: senza, i vecchi spinbox restavano disegnati sopra le
    righe). Sta in `search_model` proprio perché serve a due tabelle diverse.
    Morale: quando in una schermata compare qualcosa che "non dovrebbe
    esserci", non liquidarlo come artefatto del `grab()` — si conta.

---

17. **`LIKE '%…%'` non è una ricerca: FTS5 sì.** Nel modulo Database la
    ricerca copre nome e testo dell'effetto in DUE lingue, cioè ~20 MB di
    testo. Col `LIKE` costava **~90 ms in inglese e ~190 ms con le due
    lingue** — nessun indice può aiutare un jolly iniziale, si scorre tutto.
    Con **FTS5** (dentro SQLite, zero dipendenze nuove): **1 ms**, novanta
    volte tanto, al prezzo di 0,5 s di costruzione e ~6 MB nel file.
    Cambia anche la SEMANTICA, in meglio: si cercano parole con prefisso, non
    sottostringhe — "ash" dà le 39 carte che cominciano per ash invece di 215
    che contengono quelle lettere ovunque ("Flash Assailant" non è un
    risultato sensato). Due cautele: la query dell'utente va **neutralizzata**
    (`fts_query` mette ogni parola fra virgolette e aggiunge `*`, così AND/OR/
    NEAR/`:` restano testo e non sintassi), e se FTS5 mancasse si **ripiega
    sul LIKE** invece di lasciare la ricerca rotta.
    Corollario misurato: i filtri senza testo (es. solo attributo, 2.648
    carte) erano a 128 ms per scansione completa → indici sulle colonne
    filtrate, ~27 ms.
18. **Il padding del QSS mangia l'ICONA, non solo il testo** (v1.1.1). Nel
    modulo Database le miniature dell'elenco si vedevano mozzate sopra e
    sotto. `QTableWidget::item` ha `padding: 8px 10px` più un bordo da 1px:
    in una riga da 78 px a un'icona da 70 ne restano 61, e Qt la TAGLIA
    invece di rimpicciolirla. Cura: l'altezza della riga si calcola dalla
    costante (`THUMB.height() + ROW_PADDING`), non a occhio. È lo stesso
    inciampo del "numero delle copie illeggibile" nel `deck_dialog` — lì era
    uno spinbox, qui un'icona: quando qualcosa appare tagliato in una cella,
    il primo sospettato è il padding del tema.
    Corollario (stessa versione): copiare `_CardArt` dal modulo del grafico
    portandosi dietro `QSizePolicy.Ignored` è stato un errore. Là l'altezza la
    dà il layout; qui è imposta da `setFixedHeight`, e con `Ignored` il layout
    piazzava le etichette successive come se l'immagine fosse alta la metà —
    la carta finiva **disegnata sopra il nome**. Verticale `Fixed`.
    Morale: una politica di dimensionamento non si copia senza il contesto che
    la giustifica.
19. **Un'animazione, un'API e una ricerca si misurano; un numero scritto a
    memoria è un numero inventato.** Nel commento di `search_blob` avevo
    scritto "la ricerca scende a ~35 ms" PRIMA di misurare: la misura vera
    diceva l'opposto (da 120 a 190 ms, perché il testo raddoppia). Il numero
    plausibile in un commento è una trappola per chi legge dopo, esattamente
    come un prezzo plausibile in tabella.

---

## 5. Flussi principali

- **Ricerca:** `search_input.textEdited` → `_on_search_text` (reset selezione +
  debounce) → `_apply_search_filter` (token-AND su `_search_index`, cap 60) →
  `QStringListModel` → `QCompleter.complete()`. Selezione: `activated` →
  `_on_pick` (`_label_to_ref[label]` → `CardRef`).
- **Prezzi:** `check_now` costruisce job `(ref_id, filtri_effettivi)` con
  `_effective_filters(watch)` (filtri della carta se presenti, altrimenti i
  globali) → `PriceFetchWorker` (carta per carta, chiamate spaziate dal
  `LIMITER`, `progress(fatte, totali)` → barra di stato "… 12/40"; i
  fallimenti non abortiscono il giro, vedi GOTCHA 13) →
  `lowest_price(card_id, filters)` (ritorna un
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
- **Pagina della carta sul sito** (`_open_card_page`): basta
  `https://www.cardtrader.com/cards/<blueprint_id>` — il sito reindirizza allo
  slug completo (verificato dal vivo 2026-07-29: `/cards/382653` →
  `/it/cards/382653-dominus-purge-…`). Quindi NON serve salvare lo `slug` in
  catalogo né risincronizzare, anche se l'API lo espone.
  **I filtri NON si possono passare nel link.** Ispezionata la pagina: il
  pannello filtri è un form che fa **POST a `/it/cards/<id>/filter.json`** e
  l'URL non cambia mai; mettendo i `q[...]` in query string restano lì
  ignorati (checkbox non spuntate, risultati invariati). Nomi dei campi, per
  memoria: `q[terms][properties_hash.yugioh_language.keyword][]` (en/fr/it/de/
  es/pt), `q[terms][properties_hash.condition.keyword][]`,
  `q[term][properties_hash.first_edition]`, `q[term][user.can_sell_via_hub]`,
  `q[term][graded]`. **Attenzione:** la scala delle condizioni del SITO
  (Mint, Near Mint, Slightly/Moderately Played, Played, Poor) NON coincide con
  quella che usiamo dall'API (`CONDITIONS`: … Excellent, Good, Light Played …).
  Al posto dei filtri nel link, il tooltip elenca quelli in vigore.
- **Immagini:** anteprima grande via `ImageFetchWorker` (QImage decodificato fuori
  GUI); miniature del popup via `ThumbDelegate`; miniature di riga watchlist via
  `_row_icon`/`_on_row_thumb` (QThreadPool + `SESSION`, `_ThumbTask` con size). Cache per URL.
  **Scala di ripieghi, uguale nei tre punti (riga, popup, anteprima):**
  1. immagine della **stampa esatta**;
  2. immagine di **un'altra stampa della stessa carta**, col timbro "Stock" —
     `self._stock_images` (nome → url) è costruito in `_rebuild_completer`,
     che il catalogo lo sta già scorrendo tutto: zero query aggiuntive. Si
     preferisce una stampa **senza rarità** (`detail` senza " · " = arte
     "liscia"), altrimenti una qualsiasi. Il ripiego si scarica **solo dopo**
     che l'esatta è fallita, altrimenti sarebbero due richieste per carta.
     Timbro = `stock_pixmap(url, pm)` in `search_model.py`: copia col testo in
     diagonale (ombra scura + testo chiaro, così regge sia sulle arti scure
     sia su quelle chiare), cache per (url, w, h) — l'originale in cache resta
     pulito, perché lo stesso url è l'immagine ESATTA di un'altra stampa.
  3. `_make_empty_frame(size)` — cornice tratteggiata, ultima spiaggia.
     (Una prima versione ci metteva le iniziali della carta: scartata su
     richiesta, faceva più rumore del buco che copriva.)
  **Attenzione:** `_rebuild_completer` (che costruisce `_stock_images`) è
  differito con un `singleShot`, quindi la tabella viene disegnata una prima
  volta SENZA ripieghi: per questo finisce con `_refresh_row_icons()`, altrimenti
  le carte che dipendono dal ripiego resterebbero con la cornice vuota.
  **Attenzione:** `_on_row_thumb` ricalcola le icone di TUTTE le righe
  (`_refresh_row_icons`), non solo di quella "proprietaria" dell'url: un
  ripiego è condiviso da più stampe della stessa carta, e un fallimento fa
  scattare il ripiego anche su righe diverse. Il nome carta serve per
  risalire al ripiego: sta nell'item della colonna 0 come `UserRole + 1`.
  **Gli URL falliti si RICORDANO** (`_failed_thumbs`, `_failed_images`,
  `ThumbDelegate._failed`): senza, ogni ridisegno rilanciava lo stesso download
  perso — esattamente la raffica che fa scattare l'anti-bot di Cloudflare
  (GOTCHA 1). Si azzerano in `check_now`, che è il gesto "aggiorna tutto":
  altrimenti un 403 temporaneo lascerebbe il segnaposto fino al riavvio.
  **Download spaziati** (`_img_slot`, `_IMG_INTERVAL` = 80 ms, in
  `search_model.py`): `_ThumbTask` è il collo di bottiglia di TUTTE le
  miniature (righe + popup), e 6 thread che partivano insieme erano la raffica
  che faceva rispondere 403 al CDN. Misurato sul catalogo reale (2026-07-28):
  **0 stampe su 47.980 senza image_url** → il "non trova l'immagine" NON era
  un URL mancante ma il download che falliva; il ripiego stock resta come rete
  di sicurezza, la spaziatura è la cura vera.
- **Filtri, TRE porte d'ingresso allo stesso `FiltersDialog`:**
  1. `open_default_filters` (imbuto nell'**header**) → filtri PREDEFINITI →
     JSON in `mw_settings.filters` → `provider.filters` → ricontrollo.
  2. `open_card_filters` (sliders accanto alla **ricerca**) → filtri della sola
     carta SELEZIONATA ma non ancora aggiunta. La riga non esiste ancora, non
     c'è niente su cui scrivere: restano in `self._pending_filters` (None =
     userà i predefiniti) e `add_by_name` li passa ad `add_watch(...,
     filters_json)` — così **nascono con la carta** e già il primo controllo
     li rispetta. `_pending_filters` si azzera a ogni cambio di selezione
     (`_on_pick`, `_on_search_text`) e dopo l'aggiunta: erano per QUELLA carta.
     Il pulsante è `setCheckable(True)` solo per avere il teal del `:checked`
     come spia "questa carta ha filtri suoi" — lo stato lo riscrive sempre
     `_update_card_filters_btn()` dopo il dialogo, anche su Annulla, altrimenti
     resterebbe acceso per il toggle automatico del clic.
  3. `_open_item_settings` (sliders sulla **riga**) → `repo.set_watch_filters`.
  4. `_edit_deck_filters`, dentro `DeckDialog` → `mw_folders.filters`, validi per
     tutte le carte della base.
  **Cascata** (`_effective_filters`): carta → **base/cartella** → predefiniti.
  Le cartelle si leggono una volta per render (`_refresh_folder_cache`), non
  una query per carta: `_effective_filters` gira per ogni carta a ogni
  render E a ogni controllo.
  Icona: **imbuto = predefiniti**, **sliders = filtri di una carta** (riga e
  carta-in-arrivo: stesso mestiere, stesso glifo). Accanto alla ricerca sta
  anche il pulsante **basi** (carte impilate): comporre una base è un gesto di
  ricerca, non un'impostazione dell'app, e nell'header stonava. Opzioni è passata da
  sliders a **ingranaggio** (`_make_gear_icon`) proprio per liberare gli
  sliders: header con cinque glifi tutti diversi (chiave, frecce, imbuto,
  ingranaggio, griglia).
- **Panoramica (`_toggle_overview`):** nasconde il pannello ricerca (animazione
  `anim.animate_collapse`) e delega a `_apply_responsive_sizing()` (righe,
  miniature, font, colonne — tutto già scalato con la UI). Tabella a **16
  colonne** modulari (0 Immagine, 1 Nome, 2 Rarità, 3 Set, 4 Condizione,
  5 Lingua, 6 1ª ed., 7 Zero, 8 Prezzo, 9 Var., 10 Soglia, 11 Controllo,
  12 Venditore, 13 Commenti, 14 Q.tà, 15 Azioni): Panoramica mostra 0-9 +
  12-15 (nasconde 10,11), normale mostra 0-3 + 8-11 + 15 (nasconde 4-7,12-14).
  Cella Venditore = widget (`_seller_cell`): username + `flags.flag_pixmap`
  del paese + badge `_make_pro_badge` per i PRO, sfondo trasparente.
- **Copie multiple (basi):** `lowest_price(card_id, filters, copies)` — con
  `copies` > 1 non basta l'annuncio più economico, quel venditore potrebbe
  averne UNO solo e moltiplicare il suo prezzo darebbe un totale non
  ottenibile (visto dal vivo su *Blitzclique Surge*). `_pick_copies` scorre gli
  annunci dal più economico prendendo le quantità disponibili finché le copie
  sono coperte; nessuna richiesta in più, gli annunci sono già tutti lì.
  Riempie `PriceQuote.sources` (una voce per venditore), `total` e `covered`
  (< copies = il mercato non basta, e va detto invece di fingere un totale).
  **`amount` resta il prezzo della copia più economica**: è quello che finisce
  nello storico, quindi la Var.% continua a misurare la carta e non la lista
  della spesa. Da qui la regola nel totale di base: `totale` = costo reale,
  `ora`/`prima` = prezzi unitari × copie per la variazione — DUE accumulatori
  separati, mescolarli darebbe una percentuale fra unità di misura diverse.
  In tabella: terzo tipo di riga `("source", (watch, src))` in `_row_entries`,
  visibile solo in Panoramica (servono le colonne) e solo per le carte aperte
  (`_open_sources`, per ref_id, in memoria). L'interruttore è la cella Q.tà
  (`3 ▸`), che è la colonna che parla di copie ed è larga quanto basta.
  Attenzione: `_folder_at` e `_row_indent` devono riconoscere il nuovo tipo —
  il payload è una TUPLA, non una riga di DB, e `payload["folder_id"]`
  esploderebbe.
- **Grafico dello storico** (`history_chart.py`; ingressi: doppio clic sulla
  riga → `_on_cell_double_clicked`, e tasto destro → *Storico prezzi…*, entrambi
  in `_open_history`). Nessuna richiesta di rete: i dati sono già in
  `mw_price_history`, `repo.history_points` li restituisce TUTTI (chiave
  compresa) e `split_runs` li spezza in **corse**, cioè blocchi consecutivi con
  la stessa `filters_key` — la stessa definizione che `_run_start` calcola con
  `MAX(id)` fra i punti di chiave diversa. L'ultima corsa è quella attuale.
  Decisioni, tutte figlie di "non inventare numeri":
  - **linea a GRADINI, non interpolata**: lo storico registra i *cambi* di
    prezzo, quindi fra due punti il prezzo è rimasto quello; una diagonale
    disegnerebbe una discesa graduale mai avvenuta (dal vivo su *The Bystial
    Lubellion*: fermo a 200,54 € per 18 giorni, poi -18% il 24/07);
  - **la linea arriva a `now`**: l'ultimo prezzo è ancora quello in vigore;
  - **solo la corsa attuale in pieno colore**; le precedenti sono un altro
    prodotto e stanno dietro un `ToggleSwitch` che compare SOLO se esistono
    (un comando spento che non fa niente è peggio di un comando assente), rese
    smorzate e separate da una tratteggiata. I riquadri di riepilogo parlano
    solo della corsa attuale, e il tooltip lo dice: con le serie vecchie a
    schermo, "Minimo" si leggerebbe come il minimo del grafico;
  - **punti consecutivi con lo stesso prezzo fusi** (`collapse`): i DB nati
    prima di `record_price` ne hanno a raffica (visti 4 identici in 15 secondi);
  - **asse dei prezzi non zero-based** (226→246 € sarebbe piatto), ma i valori
    sono sempre etichettati.
  Se i filtri sono appena cambiati e non c'è ancora stato un controllo,
  `_open_history` aggiunge una `Run` VUOTA con la chiave corrente: la finestra
  dice "nessun prezzo con questi filtri" invece di spacciare la serie
  precedente per quella attuale.
  I **pallini si disegnano anche sulle corse smorzate**: una serie di pochi
  punti ravvicinati, su un asse di settimane, si schiaccia in un tratto
  verticale che senza pallini sembra un difetto di disegno (visto su *Dominus
  Purge*) invece che "qui ci sono state alcune rilevazioni".
  L'animazione di comparsa è **UNA** `QVariantAnimation` creata nel costruttore
  e riavviata, senza `DeleteWhenStopped` (GOTCHA 11).
  **Pop-up dalla miniatura (`open_from`/`done`, v1.0.27).** La finestra cresce
  dal rettangolo della miniatura nella riga (`widget._thumb_rect_on_screen`:
  `visualItemRect` della colonna 0 → coordinate schermo; None se la riga è
  fuori dal viewport → si parte da un rettangolino al centro, meglio che
  sbucare da un punto sbagliato). Entrata con `OutBack` (overshoot 2.2):
  misurato, sfonda di **97px su 690** e rientra — il "pop" chiesto
  esplicitamente. Uscita simmetrica con `InCubic`, la finestra si ritira nella
  stessa miniatura.
  **NON si anima la geometria della finestra vera**: a 60px il layout non ci
  sta (e Qt comunque non scende sotto il minimo dei figli). Si anima
  `_ZoomGhost`, una finestra `Tool` translucida e trasparente agli eventi che
  disegna un'**istantanea** presa con `WA_DontShowOnScreen` (stessa tecnica del
  GOTCHA 12: layout vero, nessun lampo a schermo) scalata dentro un rettangolo
  interpolato da `lerp_rect` — che accetta `t > 1` proprio per lasciar passare
  lo sfondamento dell'easing. L'attesa è un `QEventLoop` annidato dentro
  `open_from`: `exec()` bloccherebbe comunque il chiamante, e così
  l'animazione resta un dettaglio delle due funzioni invece di spargersi in
  callback.
  L'istantanea si prende col grafico ANCORA VUOTO e `chart.replay()` fa
  ripartire la comparsa della linea quando la finestra è atterrata: altrimenti
  si disegnava durante il volo, cioè dove nessuno la vede.
  Senza cornice nativa servono due cose che dava Windows: la **✕** e il
  **trascinamento dall'intestazione** (`mousePressEvent` sopra
  `_drag_height`). Il clic fuori NON chiude: è un `Qt.Dialog`, non un
  `Qt.Popup` come le `CardDialog`.
  **GOTCHA 15 — un'animazione si DEBUGGA in pixel al fotogramma.** La prima
  versione (OutBack overshoot 2.2, 400 ms) fu giudicata "meccanica" e con "un
  colpo di frusta" alla fine. Primo riflesso: sono frame persi. **Misurato:
  62 fps, 0,4 ms di disegno per fotogramma — le prestazioni non c'entravano
  niente.** Il difetto stava nella FORMA del movimento, e si vede stampando i
  Δpx per fotogramma:
  - `+124 +109 +96 …` → il primo fotogramma copriva 124 px dei 630 totali: la
    finestra non si vedeva partire (= "meccanica");
  - `… -12 -13 -12 -11 …` → 11 fotogrammi di RITIRO a 812 px/s (= "colpo di
    frusta"). Tutte le `OutBack` fanno così: l'overshoot rientra veloce.
  Cura: la forma non è più una `QEasingCurve` ma una **funzione pura**
  (`pop_in`/`pop_out`), con l'animazione Qt lasciata LINEARE. Così il profilo
  si prova senza aprire finestre — ed è com'è stato trovato il difetto e come
  lo bloccano ora i test. `pop_in` = molla smorzata `1-e^(-5.5t)cos(4.6t)` con
  tempo deformato `t^1.6` (derivata nulla in 0 = niente teletrasporto) e
  correzione lineare perché `f(1)` sia ESATTO (senza, l'ultimo fotogramma
  scatta di qualche px proprio mentre l'occhio si posa). Risultato misurato:
  primo fotogramma +14 px, sfondamento +27 px, rientro peggiore -4 px che
  decade a -1.
  Altri tre punti dello stesso difetto, tutti "di forma" e non di velocità:
  - **deformazione**: il rettangolo di partenza aveva le proporzioni della
    miniatura (0,94) e quello finale della finestra (1,47) → l'istantanea si
    stirava per tutta la corsa. Ora `_start_rect` impone le proporzioni della
    finestra, centrate sulla miniatura;
  - **scambio**: `ghost.hide()` prima di `exec()` lasciava un fotogramma di
    vuoto (e lasciava vedere l'eventuale animazione di comparsa di Windows).
    Ora `self.show()` → `processEvents()` → `ghost.hide()`: la finestra vera è
    già sotto quando il fantasma se ne va. Stessa cosa al contrario in `done`;
  - **collisione di animazioni**: `chart.replay()` partiva nell'istante in cui
    la finestra si assestava, sommando due movimenti. Ora è ritardato di
    140 ms e la comparsa della linea dura 820 ms.
  **Corollario (v1.0.29), stessa lezione applicata alla COMPARSA DELLA
  LINEA.** Anche lì "aggressiva, veloce", e anche lì due difetti di forma:
  - `OutCubic` parte alla velocità massima → il primo fotogramma scopriva
    **48 px** dei 630 e poi rallentava fino a 4 fotogrammi fermi in coda. Ora
    la forma è `draw_on` (smootherstep, derivata nulla ai DUE estremi) su
    animazione lineare: primo fotogramma 1 px, punta 23, ultimo 1;
  - il `setClipRect` era una **tendina dal bordo NETTO**: un bordo verticale
    duro che corre si legge come una sciabolata, indipendentemente dalla
    velocità. Ora `_paint_series_appearing` disegna le corse su un `QPixmap`
    (col `devicePixelRatio` del monitor) e lo smeriglia con una maschera
    orizzontale in `CompositionMode_DestinationIn`: linea, area e pallini
    sfumano insieme. Costa un pixmap per fotogramma, ma SOLO durante la
    comparsa — a `_reveal >= 1` si disegna diretto sul widget.
  **DUE comparse invece di una (v1.0.30).** `set_runs` faceva partire la
  comparsa da sé, nel costruttore: con la finestra che nasce dalla miniatura
  quella corsa girava **mentre il dialogo era ancora nascosto** (in volo c'è
  solo l'istantanea), all'atterraggio se ne vedeva la coda e 140 ms dopo
  `replay()` la faceva ripartire da zero — il tratto si disegnava due volte.
  Ora `set_runs` carica i dati e basta (`_reveal = 0`, o `1` se le animazioni
  sono spente: senza quel ramo il grafico resterebbe invisibile per sempre) e
  la comparsa la lancia **solo chi mostra il grafico**: `open_from` con un
  `singleShot(140)` dopo l'atterraggio, o `singleShot(0)` quando non c'è
  transizione. Regola generale: **un'animazione non si avvia dove si caricano
  i dati**, ma dove si sa che il widget è visibile.
  Verificato registrando tutti i valori di `_reveal` dall'apertura: una sola
  salita 0→1, nessun ritorno indietro, inizio a 786 ms (la finestra atterra a
  ~500). Il test lo blocca dall'altro capo: dopo `set_runs` l'animazione NON
  dev'essere in corsa.
  **Immagine della carta (v1.0.31).** `_CardArt` a sinistra del grafico
  (finestra passata a 870×565). **Zero richieste in più verso CardTrader**
  (GOTCHA 1): `widget._history_art` pesca dalle cache già piene — prima
  `_img_cache` (l'anteprima grande, che la SELEZIONE della riga ha già
  scaricato), poi `_row_thumb_cache` (la miniatura, sgranata ma presente
  perché la riga è a schermo). Se la grande manca davvero si chiama
  `_show_image`, cioè **la stessa singola richiesta** che parte selezionando
  la riga, e solo se non ce n'è già una in volo; quando arriva,
  `_on_image_done` la passa alla finestra aperta (`_history_dlg`) via
  `image_arrived`. Stessa scala di ripieghi del resto dell'app, timbro
  "Stock" compreso.
  `_CardArt` ha politica verticale `Ignored` e riscala l'ORIGINALE a ogni
  resize: il `sizeHint` di una QLabel è il suo pixmap, lasciarlo decidere
  darebbe un rimpallo layout→pixmap→layout, e riscalare un pixmap già ridotto
  lo impasta. Niente `objectName("preview")`: la carta non riempie mai tutta
  l'altezza e la cornice lascerebbe due bande vuote — meglio l'arte che
  galleggia con la sua ombra.
- **GOTCHA 16 — l'asse deve CONTENERE i dati.** `nice_ticks` chiudeva il ciclo
  con `value < hi + step/2`: con massimo 51,00 € e passo 5 l'ultimo tick era
  50 e **la punta della serie veniva disegnata fuori dal riquadro** (vista in
  una schermata di prova: la linea usciva sopra la griglia). Ora si continua
  finché `value < hi` e si aggiunge comunque il tick successivo, quindi
  l'ultimo è sempre ≥ del massimo. Il test prova sei intervalli diversi
  (compreso il caso reale 39,9→51,0) verificando che gli estremi contengano i
  dati e che il passo resti uniforme. Ennesima conferma della regola: le
  schermate si guardano, e quello che "non dovrebbe esserci" quasi sempre c'è
  per un motivo.
- **Modulo Database — sincronizzazione:** `SyncWorker` fa **due** richieste
  (inglese con `misc=yes`, poi italiano con `language=it`) e sovrappone i
  testi tradotti a quelli inglesi *per id*. L'inglese resta la base: partire
  dall'italiano perderebbe 2.878 carte che in italiano non esistono. Se la
  seconda richiesta fallisce non si butta via la prima — si resta in inglese.
  Il worker consegna **dizionari** (non tuple): la seconda passata li
  completa per chiave, e per indice numerico sarebbe una trappola alla prima
  colonna aggiunta. La scrittura su DB avviene nella GUI, in **una
  transazione** (`replace_all`): una sincronizzazione interrotta a metà
  lascerebbe un archivio mezzo vecchio e mezzo nuovo, peggio di uno vecchio.
- **Modulo Database — due PAGINE** (`QStackedWidget`, v1.1.2): pagina 0 =
  ricerca + filtri + elenco, pagina 1 = la carta a tutta larghezza. Non è un
  pannello laterale: scegliendo una carta la pagina diventa sua, e l'elenco
  riprende tutta la larghezza quando si torna. Si torna con il pulsante o con
  **Esc** (`keyPressEvent`).
  Due trappole già inciampate:
  - si ascolta **anche `cellClicked`**, non solo `itemSelectionChanged`:
    tornando all'elenco la riga di prima è ancora selezionata, e ri-cliccarla
    non cambia la selezione — senza il clic la carta non si riaprirebbe più;
  - `_load_visible_thumbs` esce subito se la pagina attiva non è l'elenco:
    con la carta aperta non c'è nessuna miniatura da scaricare, e il timer
    continuerebbe a girare.
  Attenzione nelle verifiche: la pagina entra con `anim.fade_in`, quindi una
  schermata catturata subito dopo il cambio pagina esce **vuota** — non è un
  difetto del layout (ci sono cascato: sembrava una pagina che non si
  disegnava, era la dissolvenza a metà).
- **Lingua del testo carta** (v1.1.3): il predefinito è `i18n.current()`, non
  l'italiano fisso — con l'app in inglese le carte in italiano erano una
  sorpresa. `_desc_lang` vive nel widget e la scelta manuale RESTA mentre si
  sfogliano le carte (azzerarla a ogni scheda costringerebbe a ri-premere il
  pulsante ogni volta). L'interruttore mostra la lingua di DESTINAZIONE e
  compare solo dove `desc_it` esiste: dove manca (2.878 carte) si mostra
  l'inglese e l'etichetta lo dichiara, invece di far sembrare una scelta
  quello che è un buco nei dati.
  **Badge di lingua (v1.1.4)**: la scelta è passata da un interruttore
  accanto al testo a una fila di **badge** (`LANGUAGES`, oggi `en`/`it`) in
  cima alla pagina della carta, perché è un comando di PAGINA — cambia nome
  e testo insieme, non solo l'effetto. Tutto passa da `_refresh_desc`: un
  solo posto in cui la lingua decide cosa si legge (prima nome e sottotitolo
  li scriveva anche `show_card`, e sarebbero andati fuori sincrono al primo
  clic sul badge). Il nome inglese non sparisce mai: con l'italiano acceso
  scende nella riga del tipo.
  Dove la traduzione manca il badge è **disabilitato, non nascosto**:
  nasconderlo farebbe ballare la fila e non direbbe nulla, spento dichiara
  "questa carta in italiano non c'è" (tooltip). È l'eccezione alla regola
  "un comando che non fa niente si toglie": qui il comando spento è
  un'informazione.
  Aggiungere una lingua = una voce in `LANGUAGES`, due colonne e un download
  in più nel `SyncWorker` (l'API dà anche fr, de, pt).
  Nell'ELENCO invece nessuna traduzione: solo il nome inglese, canonico. La
  ricerca continua a coprire entrambe le lingue (colonna `search`), quindi si
  cerca "cenere" e si trova Ash Blossom anche se in lista si legge l'inglese.
- **GOTCHA 23 — i campi dell'API NON sono il vocabolario del gioco** (v1.2.1).
  I filtri erano stati costruiti sui nomi dei campi YGOPRODeck, e due erano
  inesistenti a Yu-Gi-Oh!. La traduzione giusta sta in cima a
  `repository.py` (`CARD_KINDS`, `MONSTER_CATEGORIES`):
  - API `race` → per i MOSTRI è il **Tipo** (Dragon, Warrior…, 26 valori), per
    magie e trappole è la **Proprietà** (Normal, Quick-Play, Continuous,
    Field, Equip, Ritual / Normal, Continuous, Counter). "Razza" non esiste.
    Sono due vocabolari che non si incontrano mai: `repo.races(card)` offre
    solo quelli giusti, altrimenti si propone "Counter" a chi cerca un mostro.
  - API `type` → una stringa composta ("Pendulum Effect Fusion Monster") che
    contiene DUE informazioni: la **Carta** (Mostro/Magia/Trappola, per
    sottostringa — verificato che nessun mostro contenga "Spell" nel `type`:
    lo "Spellcaster" sta in `race`) e la **Categoria** del mostro.
  - Attributo, Livello/Rango e Categoria valgono SOLO per i mostri: con Magia
    o Trappola si disabilitano **e si azzerano**. Lasciarli attivi ma
    invisibili darebbe zero risultati senza dire perché.
  Contati sul DB: 9.308 mostri + 2.864 magie + 2.075 trappole = 14.247; le
  230 mancanti sono 124 Skill Card e 106 Token, che non sono nessuna delle
  tre e restano raggiungibili senza filtro Carta.
- **Riquadro dei formati** (`_fill_formats`, v1.2.0): ban list TCG/OCG +
  punti Genesys, dove prima c'erano badge sciolti accanto al tipo. Distingue
  **tre** stati che a schermo si scriverebbero uguale: in lista (badge),
  legale e non in lista (*3 copie*, che è la regola), **mai uscita in quel
  formato** (dal campo `formats` della fonte — senza, si farebbe credere che
  se ne possano giocare tre). Per Genesys, `0` è un punteggio VERO (13.762
  carte su 14.477) mentre `NULL` è "non scaricato": `repo.has_genesys()`
  distingue i due casi, altrimenti si scriverebbe la stessa cosa.
  **`genesys_points` costa 24 MB.** Verificato: NON compare nella risposta
  normale, nemmeno con `misc=yes` — arriva solo con `format=genesys`, e quel
  filtro non filtra nulla (restituisce comunque tutte le 14.477 carte). È una
  quarta richiesta piena nel `SyncWorker`; se fallisce, il resto della copia
  resta valido. Colonna `genesys` aggiunta con `ALTER TABLE` in `_init_schema`
  (i DB esistenti non la avrebbero: `CREATE TABLE IF NOT EXISTS` non migra).
- **Ristampe** (`_fill_sets`, v1.1.5): riquadro con bordo (`QGridLayout` in un
  `QFrame`), una riga per stampa = `badges.set_pill` + nome + `rarity_pixmap`,
  col nome intero della rarità nel tooltip (le sigle sono convenzioni della
  community, non ovvie). **Nessun taglio**: prima se ne mostravano 12 con "…",
  ma una staple esce in decine di set e quello è esattamente il dato che si
  cerca — la pagina scorre. Il riquadro si NASCONDE se non ci sono stampe,
  invece di restare lì vuoto. Le righe si ricostruiscono a ogni carta
  (`takeAt` + `deleteLater`): un `QGridLayout` non si svuota da solo.
  **v1.1.6 — raggruppate per CODICE e ordinate:** niente nome esteso (si
  ripeteva identico per ogni rarità dello stesso set: *RA01-EN016* otto volte;
  ora sta nel tooltip col la data). Una riga per codice, rarità accanto:
  34 stampe → 21 righe su *Ash Blossom*. Ordine **cronologico** per data del
  set, poi rarità crescente (`rarity_rank`); senza data → in fondo, rarità
  fuori scala → in fondo alla riga.
  Le DATE non stanno nei dati delle carte: arrivano da `cardsets.php`
  (1.028 set, 170 KB) in `cdb_setinfo`, agganciate per **nome** — misurato,
  1.023 su 1.028, mentre per prefisso di codice sarebbe 638 su 657. Chi ha
  già l'archivio non deve risincronizzare: `_ensure_setinfo` si prende il
  pezzo mancante all'avvio (`SetsWorker`, silenzioso se fallisce).
  **GOTCHA 20 — alias di colonna nell'ORDER BY.** `SELECT COALESCE(i.x,'') AS
  x … ORDER BY (x = '')` NON usa l'alias: SQLite lega il nome alla colonna
  della tabella, che nel LEFT JOIN senza corrispondenza è **NULL**; `NULL=''`
  vale NULL e i NULL in ASC vengono per PRIMI. Risultato: i set senza data in
  cima, come se fossero i più vecchi. Cura: ripetere l'espressione
  (`ORDER BY (COALESCE(i.x,'')='')`), non fidarsi dell'alias.
  **v1.1.8 — badge del SET, non della carta.** Si mostra `MACR`, non
  `MACR-EN036`. Il codice del set arriva da `cdb_setinfo` (`set_short`), col
  prefisso del codice carta come ripiego. **Il codice del set NON identifica
  il set**: misurato, 142 codici sono condivisi da più espansioni (`MVP1` =
  Movie Pack + Gold/Secret/Special Edition; `JUMP` = 70 promo). Quindi:
  raggruppare per **nome** (per codice fonderebbe prodotti diversi) ed
  etichettare con `set_labels` = *il codice più corto che resta univoco in
  quella carta* — corto se unico, completo se due edizioni lo condividono.
  `set_labels` è una funzione PURA, provata dai test senza aprire finestre.
  **GOTCHA 22 — `takeAt` non stacca il widget dal genitore.** Svuotando un
  layout con `takeAt` + `deleteLater`, i widget restano FIGLI e Qt continua a
  disegnarli dov'erano: passando da una carta all'altra si vedeva il badge
  della ban list precedente sopra le statistiche nuove. Peggio: `deleteLater`
  non viene processato da un semplice `processEvents`, quindi nelle verifiche
  a schermate il fantasma resta per sempre. Cura: `setParent(None)` SUBITO
  (helper `_svuota`), `deleteLater` solo per la memoria. È la stessa famiglia
  del GOTCHA 14 del market_watch.
  **GOTCHA 21 — un thread nuovo va aggiunto a `stop()`.** `SetsWorker` non era
  nella lista dei thread da fermare: i test passavano tutti ma il processo
  usciva con **0xC0000409** (fail-fast di Windows) senza un rigo di errore,
  perché il thread sopravviveva al widget. Si vede SOLO guardando il codice di
  uscita, non l'output: "tutti i controlli superati" era stampato lo stesso.
- **Ponte fra moduli** (`AppContext.open_module`, v1.1.0): i moduli **non si
  importano fra loro**, si chiamano per `id` attraverso il contesto. La
  `MainWindow` porta in primo piano il modulo e gli passa il messaggio se
  espone `handle_request`. Il predefinito torna `False` (test headless o
  contesti senza finestra): chi chiama lo dice all'utente invece di
  esplodere. Oggi lo usa il Database per mandare una carta al Market Watch:
  passa il **nome**, non un id — YGOPRODeck ragiona per carta, CardTrader per
  STAMPA (rarità + espansione, prezzi diversissimi), e scegliere la stampa al
  posto dell'utente sarebbe inventare.
- **Ordinamento** (`_SORT_MODES`, `_set_sort`, `_sorted_cards`): pulsantini
  sopra la tabella, criterio + verso in `mw_settings.sort` (`"price:desc"`).
  **Non** sono intestazioni cliccabili di proposito: l'ordinamento agisce
  DENTRO ogni gruppo (cartella/base) e fra le carte sciolte, mentre cliccare
  l'header suggerirebbe un riordino globale, che scioglierebbe i gruppi.
  Le chiavi di ordinamento sono tuple `(senza_dato, valore)`: chi non ha il
  dato finisce in fondo in ENTRAMBI i versi (invertendo, galleggerebbe in cima
  e la lista sembrerebbe ordinata per errore). Rarità: `rarity.rarity_rank`
  (scala CONVENZIONALE per SIGLA — vedi la nota in `rarity.py`: `_STYLES` è
  ordinato per specificità del match, non per pregio, usarlo per ordinare
  darebbe una classifica senza senso).
  **Effetto collaterale utile:** prezzo e variazione di ogni carta si calcolano
  ora UNA volta per render (dict `metrics`) e li riusano riepilogo delle basi,
  ordinamento e righe; prima ogni pezzo interrogava il DB per conto suo.
  Il drag&drop continua a scrivere le posizioni: si rivedono passando a
  *Manuale*.
- **Cartelle & drag&drop:** il modello visuale è `self._row_entries`
  (lista di `("folder", riga)` / `("watch", riga)` / `("source", …)`); `_render_after_check`
  costruisce cartelle → carte (se `expanded`) → carte fuori. **Riga-cartella
  allineata alle colonne** (`_set_folder_row`): NIENTE `setSpan` — prima era un
  unico item spalmato su 0-14 con nome/conteggio/totale nella stessa stringa,
  scollegato dalle intestazioni. Ora: 0 = icona cartella
  (`_make_folder_icon`, disegnata a runtime con chevron, cache per
  (aperta, dimensione) — via le emoji 📁/📂, che cambiano faccia per sistema e
  ignorano il tema), 1 = nome in grassetto (+ "· N carte" SOLO in vista
  normale: in Panoramica la colonna è stretta e il conteggio ha già casa in
  Q.tà, appenderlo troncava il nome), 8 = totale €, 9 = **variazione del
  totale**, 14 = numero di carte, 15 = pulsanti rinomina/elimina. Tutte le
  celle 0-14 portano lo sfondo `SURFACE_2` (la fascia). `clearSpans()` resta a
  ogni render per i layout ereditati dalle versioni con lo span, e vanno
  resettate le altezze riga.
  **Var. di cartella:** somma dei prezzi di ADESSO vs somma dei prezzi di
  PRIMA (`last_price_change`), non media delle percentuali — così una carta da
  200 € pesa quanto vale, coerente col totale accanto. Le carte senza storico
  precedente entrano identiche in entrambe le somme (non falsano il segno); i
  "Nessuna copia" sono esclusi da entrambe.
  **Confine dei gruppi:** `_WatchTable.set_groups([(prima, ultima)])` +
  `paintEvent` che, DOPO il disegno base, traccia una barra verticale d'accento
  lungo il gruppo e una riga di chiusura sotto l'ultima carta. Serviva perché
  coi soli sfondi non si capiva dove finisse una cartella e ricominciassero le
  carte sciolte. Si disegna sopra, quindi solo decorazioni che non coprono
  testo (x < ~3px e 1px di linea); gli sfondi restano sugli item. I gruppi si
  ricalcolano in `_do_render` e il disegno segue da solo la fisarmonica
  (legge `rowViewportPosition`/`rowHeight` a ogni frame).
  **Colonna Nome = `_IndentDelegate`** (`setItemDelegateForColumn(1, …)`), che
  fa due cose:
  - *rientro* delle carte in cartella spostando il RECT, NON con spazi nel
    testo: gli spazi rientrano solo la PRIMA riga, e in Panoramica i nomi vanno
    a capo, lasciando le successive disallineate;
  - *marcatore "filtri propri"* (`_make_mini_funnel`, teal) PRIMA del nome, per
    le righe con `mw_watchlist.filters` valorizzato. La colonnina del marcatore
    è riservata su TUTTE le righe: metterlo in fondo alla cella lo allontanava
    dal nome (la colonna è larga), e riservare lo spazio solo dove serve
    disallineava i nomi.
  Attenzione: spostando il rect **lo sfondo va dipinto a parte sul rect pieno**
  (`CE_ItemViewItem` con testo e icona svuotati) prima del contenuto, altrimenti
  a sinistra resta una striscia scoperta — si vedeva come una linea verticale
  lungo la colonna Nome. `sizeHint` sottrae rientro e colonnina, così il ritorno
  a capo usa la larghezza reale.
  La stessa informazione la dà anche il pulsante filtri della riga
  (`_settings_icon_custom`, teal invece di grigio): il marcatore serve a
  scorrere l'elenco, il pulsante è il comando.
  Il drop di Qt sposterebbe i singoli
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

- **Compatibilità macOS: ACCANTONATA il 2026-07-30** (decisione dell'utente:
  nessun Mac disponibile, riprendere quando ce n'è uno — e *niente lavoro
  preparatorio* nel frattempo). Analisi già fatta, non rifarla:
  - **il codice è quasi pronto**: cercando `winreg|os.startfile|windll|C:\|
    sys.platform|AppData` in `core/` e `modules/` c'è UN solo riferimento a
    Windows, l'icona `.ico` in `main.py`. I dati stanno in `Path.home()`, che
    su macOS va bene.
  - **serve fisicamente un Mac**: PyInstaller non compila per un sistema
    diverso da quello su cui gira. Non ci sono scorciatoie.
  - **Gatekeeper è più duro di SmartScreen**: app non firmata = quarantena e
    *Impostazioni → Privacy e sicurezza → Apri comunque*, e sui chip Apple può
    dare "app danneggiata". Per farlo bene: Apple Developer Program 99 $/anno
    con firma + notarizzazione (su Windows il certificato l'avevamo scartato).
  - da fare quando si riprende: `.icns`, ramo Mac nello spec con `BUNDLE`
    (saltando `version=version_info.txt`, risorsa Windows), `.dmg` o zip al
    posto di Inno, e **verificare le notifiche** (su Mac la tray è nella barra
    dei menu: `supportsMessages()` potrebbe dire False e gli avvisi di calo
    finirebbero solo nel log).
  - via a costo zero per uno-due amici smanettoni: far girare l'app dai
    sorgenti (`pip install -r requirements.txt`, `python main.py`).
- **Schermi ad alta densità: pixmap sfocate.** Disegniamo 21 pixmap a runtime
  (bandierine, badge, icone header, segnaposto, timbro "Stock") **senza gestire
  `devicePixelRatio`**: su Retina — ma anche su un 4K Windows con scaling al
  150% — vengono ingrandite dal sistema e si vedono morbide. Difetto LATENTE
  già oggi, non solo un problema Mac; l'utente non l'ha notato perché il suo
  schermo è al 100%. Si risolve in un punto solo se si passa da un helper
  comune invece di toccare i 21 siti.
- ~~Grafico dello storico prezzi~~ — **fatto il 2026-07-30 (v1.0.26)**, vedi
  `history_chart.py` e il flusso qui sopra. Restano possibili: grafico del
  totale di una BASE (oggi NON si può senza inventare numeri — il DB conserva
  il minimo per carta, non il costo reale delle copie a ogni controllo, che
  dipende dagli annunci di quel momento), zoom/selezione di un intervallo,
  esportazione del grafico come immagine.
- Controllo in background anche ad app chiusa.
- **Companion mobile: DA RIDECIDERE (in pausa dal 2026-07-28).** La prima
  versione (bot Telegram: `core/telegram.py` + aggancio in `Notifier.notify` +
  UI di collegamento in `DisplayDialog`) è stata **rimossa** perché la
  direzione non è ancora decisa — meglio niente che mezza soluzione. Per
  ripescarla: `git show 12f68bf` (commit "Notifiche Telegram sul telefono").
  Alternative sul tavolo per quando si riprenderà: bot Telegram con comandi
  (/lista, /soglia), web UI in LAN, app/PWA, oppure push da un servizio in
  cloud (che però toglie il vincolo "PC acceso").
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
