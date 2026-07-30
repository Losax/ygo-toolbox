# YGO Toolbox — guida per Claude Code

Cassetta degli attrezzi **modulare** per Yu-Gi-Oh!, interfaccia desktop
PySide6/Qt. Si parla italiano in questo progetto.

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
  prima di mettere le mani su market_watch, ha 14 GOTCHAS che spiegano *perché*
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
- Storico prezzi già salvato a ogni controllo → prossimo passo naturale: grafico.
- Controllo in background anche ad app chiusa (oggi gira solo con app aperta).
- Companion mobile: da ridecidere (i primi tentativi via Telegram sono stati
  rimossi, vedi REGISTRO_TECNICO).
