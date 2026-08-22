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

> ### ⚠ ECCEZIONE VALIDA UNA VOLTA SOLA — poi CANCELLARE questo riquadro
> Chiesta dall'utente il 2026-08-22: **al PROSSIMO rilascio (e solo a quello)
> NON installare la nuova versione su questa macchina.** Vuole provare da sé
> il pulsante *Riavvia e aggiorna* della v1.4.0, e per farlo la sua
> installazione deve restare INDIETRO rispetto a GitHub.
>
> Quindi, quella volta: versione nei tre posti, registri, commit e push, exe e
> installer ricompilati e **Release pubblicata** — tutto normale. Salta **solo**
> l'installazione dell'installer sulla macchina.
> La Release va fatta comunque: senza, l'app non vede niente e il test non
> esiste. La verifica "lancia l'exe e leggi `~/.ygo_toolbox/log.txt`" si fa su
> `dist\YGO Toolbox.exe` (che è già la versione nuova, quindi non si offre di
> aggiornarsi) — **non** cliccare mai il pulsante di aggiornamento lì: `/DIR`
> nasce da `sys.executable` e installerebbe dentro `dist\`.
>
> Stato al momento della richiesta: sulla macchina è installata la **1.3.9**,
> un numero mai esistito pubblicamente, costruito solo per stare sotto la
> 1.4.0. Se l'utente intanto premesse il pulsante si ritroverebbe alla 1.4.0, e
> va bene: qualunque rilascio successivo resta più nuovo di entrambe.
>
> **Appena questa eccezione è stata usata, cancella il riquadro** e torna alla
> regola dei cinque passi: l'utente usa l'app installata, e lasciarla indietro
> più di un giro è esattamente il guaio che l'aggiornamento in-app risolve.

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
- `REGISTRO_TECNICO.md` = handoff tecnico: architettura, modello dati, 26
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
  (`anim.py`), traduzioni (`i18n.py`), aggiornamento dell'app (`updates.py` =
  motore senza Qt, `update_widget.py` = thread + piede sotto il menu).
- Dettagli, decisioni e trappole stanno in **`REGISTRO_TECNICO.md`**: leggerlo
  prima di mettere le mani su market_watch, ha 26 GOTCHAS che spiegano *perché*
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
- Sincronizzazione = **quattro** richieste: inglese (base, 14.477 carte) +
  italiano (`language=it`, 11.599) sovrapposto per id — mai il contrario, in
  italiano mancano 2.878 carte — + `format=genesys` per i punti (altri 24 MB:
  il campo non esiste nella risposta normale) + `cardsets.php` per le date dei
  set (170 KB, agganciate per NOME).
- Ricerca con **FTS5** (GOTCHA 17): 1 ms invece di 190. La query dell'utente
  va sempre passata da `fts_query`, che neutralizza gli operatori di FTS5.
- I moduli **non si importano fra loro**: il ponte verso il market_watch passa
  da `AppContext.open_module(id, payload)` + `handle_request` sul widget.
- **I campi dell'API NON sono il vocabolario del gioco** (GOTCHA 23): `race` è
  il **Tipo** del mostro (Drago…) o la **Proprietà** di magia/trappola
  (Rapida, Counter…) — "razza" non esiste; `type` è una stringa composta che
  contiene sia la **Carta** (Mostro/Magia/Trappola) sia la **Categoria**
  (Xyz, Link, Synchro…). La traduzione sta in cima a `repository.py`.

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

**Aggiornamento in-app: FATTO e collaudato (v1.4.0, 2026-08-22).** L'app
scarica da sola in sottofondo e un pulsante nel piede sotto il menu chiude,
installa e riapre. Come funziona: `REGISTRO_TECNICO.md` §5, "Aggiornamento
in-app"; misure, trappole e ricetta del collaudo in §7.
**Per ricollaudarlo dopo averci messo le mani** (e va ricollaudato: il difetto
peggiore — GOTCHA 26 — si vedeva SOLO facendo il giro intero dall'app
installata): non servono due Release. Si punta l'app installata a un
`release.json` locale con `YGO_UPDATE_URL`, si compila un installer finto più
nuovo con `ISCC /DAppVersion=X.Y.Z /O<cartella>`, e si preme il pulsante **per
coordinate** — UIAutomation non legge i widget Qt di questa app. Gli script
`collaudo_giro.ps1` / `foto_e_clic.ps1` sono descritti in §7.
Due punti ancora aperti che possono lasciare l'app non funzionante, entrambi
fuori dal nostro codice: l'antivirus sull'exe onefile non firmato (`upx=True`
nello spec è il profilo con più falsi positivi in circolazione) e una copia
interrotta a metà, perché **Inno non fa rollback**.

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
