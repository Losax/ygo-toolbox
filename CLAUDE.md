# YGO Toolbox — guida per Claude Code

Cassetta degli attrezzi **modulare** per Yu-Gi-Oh!, interfaccia desktop
PySide6/Qt. Si parla italiano in questo progetto.

## Come si lavora qui (leggere prima di toccare qualsiasi cosa)

**1. Ogni modifica è una VERSIONE RILASCIATA, non un commit.** È una richiesta
esplicita dell'utente ("deve essere tutto a pari, exe compreso"). Nessun passo
è opzionale, e va fatto SUBITO, non "alla fine della sessione":

1. alzare la versione in `core/version.py`, `version_info.txt` (sia
   `filevers/prodvers` sia le stringhe) e nell'intestazione di `LEGGIMI.txt`;
2. aggiornare **i due registri** (vedi punto 3);
3. `git commit` **e `git push`** — in locale non basta: l'utente guarda GitHub;
4. ricompilare l'**exe** e l'**installer**;
5. creare la **Release su GitHub** con l'installer allegato.

Il punto 5 non è cosmetico: è la Release, non il tag, che accende l'avviso di
aggiornamento dentro l'app (25 tag e 0 release facevano rispondere 404 all'API).
E l'utente **usa l'app installata**, non `python main.py`: un exe vecchio
significa che sta usando qualcosa di diverso da ciò che dicono i registri.

**2. Verificare, non supporre.** In questa sessione ogni volta che ho dato per
buono qualcosa senza guardare, era sbagliato. Quindi:
- smoke test dopo OGNI modifica al market_watch;
- lanciare l'exe e leggere `~/.ygo_toolbox/log.txt` (nell'exe windowed gli
  errori non compaiono a schermo: finiscono solo lì);
- per le modifiche all'interfaccia, **una schermata coi font veri** (finestra
  con `WA_DontShowOnScreen`, NON offscreen: vedi GOTCHA 12) e guardarla;
- per i dati, **misurare sul DB reale** invece di stimare (copiarlo prima).
Se in una schermata compare qualcosa che "non dovrebbe esserci", NON liquidarlo
come artefatto: due volte era un difetto vero (GOTCHA 14).

**3. I due registri vanno tenuti aggiornati a ogni versione.**
- `REGISTRO.md` = per l'utente. Tabella delle funzioni + **cronologia
  numerata**: i punti nuovi si aggiungono **IN FONDO, in ordine crescente**
  (inserendoli in cima la cronologia si legge al rovescio: è già capitato e ho
  dovuto riordinarla).
- `REGISTRO_TECNICO.md` = handoff tecnico: architettura, modello dati, 19
  **GOTCHAS** e le decisioni col loro *perché*. Quando scopri una trappola,
  scrivila lì con il sintomo, la causa e la cura — è la parte più utile del
  documento.

**4. Non inventare numeri.** Il filo conduttore di questa sessione: variazioni
percentuali calcolate su prezzi non confrontabili, totali che moltiplicavano
prezzi non ottenibili, colori assegnati a condizioni sconosciute. Quando un
dato non c'è, mostrare "—" o un grigio neutro; mai un valore plausibile.

## Comandi

```bash
# setup
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# avvio app
python main.py

# test (headless, senza rete) — eseguire SEMPRE dopo modifiche al market_watch
QT_QPA_PLATFORM=offscreen python tests/smoke_test.py
```

```powershell
# rilascio: versione in TRE posti (core/version.py, version_info.txt,
# intestazione di LEGGIMI.txt), poi
.venv\Scripts\pyinstaller --noconfirm ygo_toolbox.spec          # exe (chiudere l'app prima!)
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /DAppVersion=X.Y.Z installer.iss
& "$env:ProgramFiles\GitHub CLI\gh.exe" release create vX.Y.Z `
    "dist\YGO-Toolbox-Setup-vX.Y.Z.exe" --title "YGO Toolbox vX.Y.Z" --notes-file note.md --verify-tag
```
Verifica sempre l'exe lanciandolo e leggendo `~/.ygo_toolbox/log.txt`: nell'exe
windowed gli errori non compaiono a schermo, finiscono lì.

I dati utente (token, watchlist, storico, catalogo) stanno in `~/.ygo_toolbox/`,
FUORI dal repository. Se cambi lo schema delle tabelle durante lo sviluppo,
cancella `~/.ygo_toolbox/ygo_toolbox.db` (CREATE TABLE IF NOT EXISTS non migra
le tabelle esistenti).

## Architettura

- `core/` = motore: finestra (`app.py`), contratto moduli (`module_base.py`),
  scoperta automatica (`module_loader.py`), servizi condivisi (`context.py`:
  storage + notifier), SQLite (`storage.py`), tema (`theme.py`), animazioni
  (`anim.py`), traduzioni (`i18n.py`), controllo aggiornamenti (`updates.py`).
- Dettagli, decisioni e trappole stanno in **`REGISTRO_TECNICO.md`**: leggerlo
  prima di mettere le mani su market_watch, ha 19 GOTCHAS che spiegano *perché*
  il codice è com'è.
- `modules/<nome>/module.py` = punto di aggancio: una sottoclasse di
  `ToolModule` con `id`, `title`, `create_widget()`. Viene scoperta da sola al
  riavvio; non serve registrarla da nessuna parte.

## Regole importanti

- **DB solo dal thread della GUI.** Le chiamate di rete (lente) girano in
  `QThread` (vedi `modules/market_watch/workers.py`), NON toccano SQLite, e
  restituiscono i dati alla GUI via segnali; la scrittura su DB avviene lì.
- Prefissa le tabelle di un modulo (es. `mw_`) per non collidere con altri.
- Timer/thread di un modulo vanno fermati in `on_stop()`.
- **MAI raffiche di richieste verso CardTrader** (API e CDN immagini sono
  dietro Cloudflare: 429 e 403). Esistono già due freni, non aggirarli:
  `providers/cardtrader.LIMITER` per l'API e `search_model._img_slot` per le
  immagini. Gli URL che falliscono si ricordano, non si ritentano in loop.
- **Non confrontare prezzi presi con filtri diversi.** Ogni punto di
  `mw_price_history` porta la sua `filters_key`, e il confronto vive dentro il
  "tratto" corrente (`_run_start`): cambiare filtri = altro prodotto, non un
  crollo. Il prezzo si può ereditare, la percentuale no.
- **Tutto "a pari" a ogni modifica** (richiesta esplicita dell'utente):
  sorgente + commit e push + **exe ricompilato** + **installer** + **Release su
  GitHub** (è la Release, non il tag, ad accendere l'avviso di aggiornamento).
  L'utente usa l'app installata, non `python main.py`.

## Modulo card_db — "Database" (fonte: API YGOPRODeck)

- **Le loro regole decidono l'architettura**, e sono citate in cima a
  `api.py`: copia locale OBBLIGATORIA (*"download and store all data pulled
  from this API locally"*), immagini da scaricare **una volta sola** e
  ri-ospitare (altrimenti IP in blacklist), 20 richieste/s con **un'ora di
  blocco** a chi sfora. Quindi: la ricerca interroga SQLite, mai la rete; le
  immagini vanno su DISCO in `~/.ygo_toolbox/card_images/`, una alla volta e
  solo quelle visibili a schermo (tutte insieme sarebbero ~400 MB).
- Sincronizzazione = **due** richieste: inglese (base, 14.477 carte) +
  italiano (`language=it`, 11.599) sovrapposto per id. Mai il contrario: in
  italiano mancano 2.878 carte.
- Ricerca con **FTS5** (GOTCHA 17): 1 ms invece di 190. La query dell'utente
  va sempre passata da `fts_query`, che neutralizza gli operatori di FTS5.
- I moduli **non si importano fra loro**: il ponte verso il market_watch passa
  da `AppContext.open_module(id, payload)` + `handle_request` sul widget.

## Modulo market_watch (fonte: API ufficiale CardTrader)

- La fonte prezzi è un **provider intercambiabile**: `providers/base.py`
  (contratto `PriceProvider`) + `providers/cardtrader.py` (implementazione).
  Per aggiungere CardMarket ecc., basta una nuova classe lì.
- Il prezzo "minimo" si ricava da `/marketplace/products?blueprint_id=ID`.
- Il token CardTrader si gestisce in `config.py` (file `~/.ygo_toolbox/
  cardtrader_token.txt` o variabile d'ambiente `CARDTRADER_TOKEN`). NON
  scrivere mai token nel codice o nei commit.
- **VERIFICATO con token reale (2026-06-29):** forma del prezzo, struttura
  della risposta e game id Yu-Gi-Oh! (= 4) combaciano col parser difensivo.
  Dettagli delle forme reali in cima a `providers/cardtrader.py`.

## Distribuzione
Repo **pubblico**: https://github.com/Losax/ygo-toolbox — l'app si consegna
come **installer** (`dist\YGO-Toolbox-Setup-vX.Y.Z.exe`, per-utente, senza UAC)
allegato a una **Release**. Lo zip portatile non si produce più.

## Idee future già impostate
- ~~Grafico dello storico prezzi~~ — **fatto (v1.0.26)**: `history_chart.py`,
  doppio clic sulla riga. Linea a gradini, solo la corsa attuale dei filtri.
  Il grafico del totale di una **base** invece NON si può fare senza inventare
  numeri: il DB conserva il minimo per carta, non il costo reale delle copie a
  ogni controllo.
- Controllo in background anche ad app chiusa (oggi gira solo con app aperta).
- Companion mobile: da ridecidere (i primi tentativi via Telegram sono stati
  rimossi, vedi REGISTRO_TECNICO).
- **macOS: ACCANTONATO** dall'utente il 2026-07-30 — nessun Mac disponibile, e
  **niente lavoro preparatorio** finché non ce n'è uno. Analisi completa già
  nei TODO del registro tecnico: non rifarla.
- **Pixmap sfocate su schermi densi**: 21 pixmap disegnate a runtime senza
  `devicePixelRatio`. Difetto latente già su Windows con monitor 4K e scaling,
  non solo un problema Mac. Dettagli nei TODO del registro tecnico.
