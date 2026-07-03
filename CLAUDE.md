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

I dati utente (token, watchlist, storico, catalogo) stanno in `~/.ygo_toolbox/`,
FUORI dal repository. Se cambi lo schema delle tabelle durante lo sviluppo,
cancella `~/.ygo_toolbox/ygo_toolbox.db` (CREATE TABLE IF NOT EXISTS non migra
le tabelle esistenti).

## Architettura

- `core/` = motore: finestra (`app.py`), contratto moduli (`module_base.py`),
  scoperta automatica (`module_loader.py`), servizi condivisi (`context.py`:
  storage + notifier), SQLite (`storage.py`).
- `modules/<nome>/module.py` = punto di aggancio: una sottoclasse di
  `ToolModule` con `id`, `title`, `create_widget()`. Viene scoperta da sola al
  riavvio; non serve registrarla da nessuna parte.

## Regole importanti

- **DB solo dal thread della GUI.** Le chiamate di rete (lente) girano in
  `QThread` (vedi `modules/market_watch/workers.py`), NON toccano SQLite, e
  restituiscono i dati alla GUI via segnali; la scrittura su DB avviene lì.
- Prefissa le tabelle di un modulo (es. `mw_`) per non collidere con altri.
- Timer/thread di un modulo vanno fermati in `on_stop()`.

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

## Idee future già impostate
- Storico prezzi già salvato a ogni controllo → prossimo passo naturale: grafico.
- Controllo in background anche ad app chiusa (oggi gira solo con app aperta).
