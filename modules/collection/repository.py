"""Accesso al database della Collezione (tabelle `col_*`).

Tre tabelle, e ognuna risponde a una domanda diversa:

- `col_items`   — **cosa possiedo**: una riga per stampa *in un certo stato*
                  (condizione, lingua, prima edizione), con quante copie, cosa
                  l'ho pagata e in quale tasca del raccoglitore sta;
- `col_binders` — **i raccoglitori**: nome, formato della pagina (3×3, 4×3…)
                  e ordine nell'elenco;
- `col_prices`  — **quanto vale oggi**: l'ultimo prezzo visto per ogni stampa,
                  con la data. È una cache, non uno storico: la Collezione
                  risponde a "quanto vale adesso", e tenere un punto per ogni
                  controllo di 2.000 carte sarebbe un archivio che nessuno
                  guarda (lo storico per carta ce l'ha già il Market Watch).

Il prefisso `col_` tiene le tabelle separate da `mw_` e `cdb_`: il file SQLite
è uno solo, condiviso da tutti i moduli. Va usato solo dal thread della GUI
(vedi la nota in core/storage.py).
"""
from __future__ import annotations

from core.storage import Storage

#: Formati di pagina che esistono davvero in commercio. Il 3×3 è lo standard.
LAYOUTS = ((3, 3), (4, 3), (4, 2), (2, 2))

#: Valore usato da `list_items` per dire "non filtrare per raccoglitore":
#: `None` è già un filtro vero e proprio (= le carte fuori dai raccoglitori).
TUTTI = object()


class CollectionRepository:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self._init_schema()

    def _init_schema(self) -> None:
        self.storage.execute(
            """
            CREATE TABLE IF NOT EXISTS col_binders (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL,
                position   INTEGER NOT NULL DEFAULT 0,
                cols       INTEGER NOT NULL DEFAULT 3,
                rows       INTEGER NOT NULL DEFAULT 3,
                note       TEXT    NOT NULL DEFAULT '',
                created_at TEXT    NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        # `paid` è REAL **senza** NOT NULL e senza default: NULL vuol dire "non
        # so cosa l'ho pagata", 0.00 vuol dire "regalata". Sono due cose
        # diverse, e confonderle falserebbe il confronto con il valore — la
        # regola di questo progetto è mostrare "—", mai un numero plausibile.
        self.storage.execute(
            """
            CREATE TABLE IF NOT EXISTS col_items (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                provider      TEXT    NOT NULL,
                ref_id        TEXT    NOT NULL,
                card_name     TEXT    NOT NULL,
                detail        TEXT    NOT NULL DEFAULT '',
                set_code      TEXT    NOT NULL DEFAULT '',
                image_url     TEXT    NOT NULL DEFAULT '',
                quantity      INTEGER NOT NULL DEFAULT 1,
                condition     TEXT    NOT NULL DEFAULT '',
                language      TEXT    NOT NULL DEFAULT '',
                first_edition INTEGER NOT NULL DEFAULT 0,
                paid          REAL,
                note          TEXT    NOT NULL DEFAULT '',
                binder_id     INTEGER,
                slot          INTEGER NOT NULL DEFAULT -1,
                added_at      TEXT    NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        self.storage.execute(
            "CREATE INDEX IF NOT EXISTS idx_col_items_ref "
            "ON col_items(provider, ref_id)")
        self.storage.execute(
            "CREATE INDEX IF NOT EXISTS idx_col_items_binder "
            "ON col_items(binder_id, slot)")
        # `price` può essere NULL: vuol dire "controllata, ma nessuno la vende".
        # È un'informazione, non un buco — e senza questa distinzione una carta
        # introvabile sembrerebbe per sempre "mai controllata".
        self.storage.execute(
            """
            CREATE TABLE IF NOT EXISTS col_prices (
                provider   TEXT NOT NULL,
                ref_id     TEXT NOT NULL,
                price      REAL,
                currency   TEXT NOT NULL DEFAULT 'EUR',
                checked_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (provider, ref_id)
            )
            """
        )
        self.storage.execute(
            """
            CREATE TABLE IF NOT EXISTS col_settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

    # ------------------------------------------------------------ carte ---
    def list_items(self, provider: str, binder_id=TUTTI) -> list:
        """Le carte possedute, con il prezzo noto agganciato.

        `binder_id`: `TUTTI` = tutte; `None` = solo quelle fuori dai
        raccoglitori; un id = solo quelle di quel raccoglitore.
        """
        dove, parametri = "i.provider = ?", [provider]
        if binder_id is not TUTTI:
            if binder_id is None:
                dove += " AND i.binder_id IS NULL"
            else:
                dove += " AND i.binder_id = ?"
                parametri.append(int(binder_id))
        return self.storage.query(
            "SELECT i.*, p.price AS price, p.currency AS currency, "
            "       p.checked_at AS checked_at, b.name AS binder_name "
            "FROM col_items i "
            "LEFT JOIN col_prices p ON p.provider = i.provider AND p.ref_id = i.ref_id "
            "LEFT JOIN col_binders b ON b.id = i.binder_id "
            f"WHERE {dove} "
            "ORDER BY i.card_name COLLATE NOCASE, i.set_code, i.id",
            tuple(parametri))

    def item(self, item_id):
        righe = self.storage.query(
            "SELECT i.*, p.price AS price, p.currency AS currency, "
            "       p.checked_at AS checked_at "
            "FROM col_items i "
            "LEFT JOIN col_prices p ON p.provider = i.provider AND p.ref_id = i.ref_id "
            "WHERE i.id = ?", (int(item_id),))
        return righe[0] if righe else None

    def add_item(self, provider, ref_id, card_name, detail="", set_code="",
                 image_url="", quantity=1, condition="", language="",
                 first_edition=False, paid=None, note="", binder_id=None,
                 slot=-1) -> int:
        """Aggiunge copie, **fondendole** con una riga identica se c'è già.

        "Identica" vuol dire stessa stampa nello stesso stato, nello stesso
        posto e pagata la stessa cifra: solo allora due righe sono davvero la
        stessa cosa e sommarle non perde niente. Due copie pagate 2 € e 12 €
        restano due righe, perché il prezzo d'acquisto è un dato che l'utente
        ha inserito a mano e nessuno ha il diritto di mediarlo.
        """
        quantity = max(1, int(quantity))
        gemella = self.storage.query(
            "SELECT id, quantity FROM col_items WHERE provider = ? AND ref_id = ? "
            "AND condition = ? AND language = ? AND first_edition = ? "
            "AND paid IS ? AND binder_id IS ? AND slot = ? LIMIT 1",
            (provider, str(ref_id), condition, language, int(bool(first_edition)),
             paid, binder_id, int(slot)))
        if gemella:
            self.storage.execute(
                "UPDATE col_items SET quantity = quantity + ? WHERE id = ?",
                (quantity, gemella[0]["id"]))
            return int(gemella[0]["id"])
        cur = self.storage.execute(
            "INSERT INTO col_items (provider, ref_id, card_name, detail, set_code,"
            " image_url, quantity, condition, language, first_edition, paid, note,"
            " binder_id, slot) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (provider, str(ref_id), card_name, detail, set_code, image_url,
             quantity, condition, language, int(bool(first_edition)), paid,
             note, binder_id, int(slot)))
        return int(cur.lastrowid)

    #: campi che si possono cambiare dopo l'inserimento (tutto il resto è
    #: identità della riga e si cambia cancellando e riaggiungendo)
    MODIFICABILI = ("quantity", "condition", "language", "first_edition", "paid",
                    "note", "binder_id", "slot", "detail", "set_code",
                    "image_url", "card_name", "ref_id")

    def update_item(self, item_id, **campi) -> None:
        """Aggiorna solo i campi passati (gli altri restano come sono)."""
        pezzi, valori = [], []
        for chiave, valore in campi.items():
            if chiave not in self.MODIFICABILI:
                raise ValueError(f"campo non modificabile: {chiave}")
            pezzi.append(f"{chiave} = ?")
            valori.append(valore)
        if not pezzi:
            return
        valori.append(int(item_id))
        self.storage.execute(
            f"UPDATE col_items SET {', '.join(pezzi)} WHERE id = ?", tuple(valori))

    def remove_item(self, item_id) -> None:
        self.storage.execute("DELETE FROM col_items WHERE id = ?", (int(item_id),))

    def set_quantity(self, item_id, quantity: int) -> None:
        """Cambia le copie; a zero la riga sparisce (possedere zero copie non
        è uno stato, è non possederla)."""
        quantity = int(quantity)
        if quantity <= 0:
            self.remove_item(item_id)
            return
        self.storage.execute("UPDATE col_items SET quantity = ? WHERE id = ?",
                             (quantity, int(item_id)))

    # ----------------------------------------------------- raccoglitori ---
    def list_binders(self) -> list:
        """I raccoglitori, con quante righe e quante copie contengono."""
        return self.storage.query(
            "SELECT b.*, "
            " (SELECT COUNT(*) FROM col_items i WHERE i.binder_id = b.id) AS righe, "
            " (SELECT COALESCE(SUM(i.quantity), 0) FROM col_items i "
            "  WHERE i.binder_id = b.id) AS copie "
            "FROM col_binders b ORDER BY b.position, b.id")

    def binder(self, binder_id):
        righe = self.storage.query("SELECT * FROM col_binders WHERE id = ?",
                                   (int(binder_id),))
        return righe[0] if righe else None

    def add_binder(self, name: str, cols: int = 3, rows: int = 3,
                   note: str = "") -> int:
        posizione = self.storage.query(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM col_binders")[0]["p"]
        cur = self.storage.execute(
            "INSERT INTO col_binders (name, position, cols, rows, note) "
            "VALUES (?,?,?,?,?)",
            (name, posizione, max(1, int(cols)), max(1, int(rows)), note))
        return int(cur.lastrowid)

    def rename_binder(self, binder_id, name: str) -> None:
        self.storage.execute("UPDATE col_binders SET name = ? WHERE id = ?",
                             (name, int(binder_id)))

    def set_binder_layout(self, binder_id, cols: int, rows: int) -> None:
        """Cambia il formato della pagina.

        Le carte NON si spostano: la tasca `slot` è un numero assoluto dentro
        il raccoglitore, quindi cambiando formato si ridistribuiscono sulle
        pagine da sole, esattamente come travasando un raccoglitore vero.
        """
        self.storage.execute(
            "UPDATE col_binders SET cols = ?, rows = ? WHERE id = ?",
            (max(1, int(cols)), max(1, int(rows)), int(binder_id)))

    def delete_binder(self, binder_id, con_carte: bool = False) -> None:
        """Elimina un raccoglitore. Le carte escono (o spariscono con lui).

        Il valore predefinito è il meno distruttivo: buttare via il
        raccoglitore non vuol dire buttare via le carte.
        """
        if con_carte:
            self.storage.execute("DELETE FROM col_items WHERE binder_id = ?",
                                 (int(binder_id),))
        else:
            self.storage.execute(
                "UPDATE col_items SET binder_id = NULL, slot = -1 "
                "WHERE binder_id = ?", (int(binder_id),))
        self.storage.execute("DELETE FROM col_binders WHERE id = ?",
                             (int(binder_id),))

    def set_binder_positions(self, coppie) -> None:
        self.storage.executemany(
            "UPDATE col_binders SET position = ? WHERE id = ?",
            [(int(p), int(i)) for i, p in coppie])

    # --- tasche ---
    def item_at(self, binder_id, slot: int):
        righe = self.storage.query(
            "SELECT * FROM col_items WHERE binder_id = ? AND slot = ? LIMIT 1",
            (int(binder_id), int(slot)))
        return righe[0] if righe else None

    def place(self, item_id, binder_id, slot: int) -> None:
        """Mette una carta in una tasca precisa, **scambiando** con chi c'era.

        Lo scambio è l'unico comportamento che non perde niente: sovrascrivere
        farebbe sparire una carta dal raccoglitore senza dirlo, e rifiutare il
        gesto costringerebbe a svuotare la tasca a mano prima di ogni
        spostamento.
        """
        item_id = int(item_id)
        riga = self.item(item_id)
        if riga is None:
            return
        if binder_id is None:
            self.update_item(item_id, binder_id=None, slot=-1)
            return
        binder_id, slot = int(binder_id), int(slot)
        occupante = self.item_at(binder_id, slot)
        if occupante is not None and int(occupante["id"]) == item_id:
            return                      # già lì: niente da fare
        if occupante is not None:
            # chi c'era prende il posto (e il raccoglitore) di chi arriva
            partenza = riga["binder_id"]
            self.update_item(int(occupante["id"]),
                             binder_id=partenza,
                             slot=int(riga["slot"]) if partenza is not None else -1)
        self.update_item(item_id, binder_id=binder_id, slot=slot)

    def first_free_slot(self, binder_id) -> int:
        """La prima tasca libera del raccoglitore (anche in mezzo alle pagine).

        Riempire i buchi lasciati da una carta tolta è ciò che ci si aspetta
        da un raccoglitore: l'alternativa — andare sempre in fondo — lascia
        pagine mezze vuote che poi si sistemano a mano.
        """
        usati = {int(r["slot"]) for r in self.storage.query(
            "SELECT slot FROM col_items WHERE binder_id = ?", (int(binder_id),))
            if int(r["slot"]) >= 0}
        posto = 0
        while posto in usati:
            posto += 1
        return posto

    # ------------------------------------------------------------ prezzi ---
    def prices(self, provider: str) -> dict:
        """ref_id → (prezzo|None, valuta, quando). Solo le stampe controllate."""
        return {str(r["ref_id"]): (r["price"], r["currency"], r["checked_at"])
                for r in self.storage.query(
                    "SELECT ref_id, price, currency, checked_at FROM col_prices "
                    "WHERE provider = ?", (provider,))}

    def set_prices(self, provider: str, righe) -> None:
        """righe: iterabile di `(ref_id, prezzo|None, valuta, quando)`."""
        self.storage.executemany(
            "INSERT OR REPLACE INTO col_prices (provider, ref_id, price, currency,"
            " checked_at) VALUES (?,?,?,?,?)",
            [(provider, str(r[0]), r[1], r[2] or "EUR", r[3]) for r in righe])

    def refs_to_check(self, provider: str, prima_di: str = "") -> list[str]:
        """Le stampe possedute il cui prezzo manca o è più vecchio di `prima_di`.

        `prima_di` = data ISO; vuoto = solo quelle mai controllate. Le date si
        salvano in ISO proprio per questo: il confronto fra stringhe è anche
        il confronto fra istanti.
        """
        # `GROUP BY ref_id` e non `DISTINCT ref_id, card_name`: due righe
        # della stessa stampa con il nome scritto diversamente (il catalogo si
        # risincronizza, i nomi cambiano) sarebbero passate due volte, cioè due
        # richieste per la stessa carta.
        if prima_di:
            righe = self.storage.query(
                "SELECT i.ref_id, MIN(i.card_name) AS card_name FROM col_items i "
                "LEFT JOIN col_prices p ON p.provider = i.provider "
                "     AND p.ref_id = i.ref_id "
                "WHERE i.provider = ? AND (p.ref_id IS NULL OR p.checked_at < ?) "
                "GROUP BY i.ref_id ORDER BY card_name", (provider, prima_di))
        else:
            righe = self.storage.query(
                "SELECT i.ref_id, MIN(i.card_name) AS card_name FROM col_items i "
                "LEFT JOIN col_prices p ON p.provider = i.provider "
                "     AND p.ref_id = i.ref_id "
                "WHERE i.provider = ? AND p.ref_id IS NULL "
                "GROUP BY i.ref_id ORDER BY card_name", (provider,))
        return [str(r["ref_id"]) for r in righe]

    def all_refs(self, provider: str) -> list[str]:
        return [str(r["ref_id"]) for r in self.storage.query(
            "SELECT ref_id, MIN(card_name) AS card_name FROM col_items "
            "WHERE provider = ? GROUP BY ref_id ORDER BY card_name", (provider,))]

    def price_span(self, provider: str) -> tuple[str, str]:
        """`(il più vecchio, il più recente)` fra i controlli fatti.

        Serve **il minimo**, non il massimo: con il solo `MAX` bastava
        aggiornare una carta per far comparire la data di oggi accanto a un
        valore fatto di prezzi vecchi di mesi. Quando i due coincidono
        l'interfaccia mostra una data sola, che è il caso normale dopo un
        aggiornamento completo.
        """
        righe = self.storage.query(
            "SELECT MIN(checked_at) AS vecchio, MAX(checked_at) AS recente "
            "FROM col_prices WHERE provider = ?", (provider,))
        if not righe:
            return "", ""
        return (righe[0]["vecchio"] or ""), (righe[0]["recente"] or "")

    def last_check(self, provider: str) -> str:
        """Il controllo più recente (usato dove serve solo "c'è mai stato")."""
        return self.price_span(provider)[1]

    def cleanup_prices(self, provider: str) -> None:
        """Via i prezzi di stampe che non possiedo più: niente dati orfani."""
        self.storage.execute(
            "DELETE FROM col_prices WHERE provider = ? AND ref_id NOT IN "
            "(SELECT ref_id FROM col_items WHERE provider = ?)",
            (provider, provider))

    # ------------------------------------------------------------ conti ---
    def totals(self, provider: str, binder_id=TUTTI) -> dict:
        """I conti della collezione, tenendo separato ciò che non si sa.

        Perché tanti campi invece di un totale: un valore di 812 € su una
        collezione in cui 300 carte non hanno prezzo non è "il valore della
        collezione", è il valore *della parte che conosco*. Chi guarda deve
        poterlo capire senza chiederlo, quindi il conteggio di ciò che manca
        viaggia insieme al totale e l'interfaccia lo mostra sempre.

        `guadagno` confronta valore e spesa **solo sulle carte che hanno
        entrambi i dati**: sommare il valore di tutto e sottrarre la spesa di
        una parte darebbe un guadagno inventato.
        """
        righe = self.list_items(provider, binder_id)
        # "stampe" = stampe DIVERSE (ref_id), non righe: la stessa stampa in
        # due condizioni sono due righe ma una sola stampa, ed è il numero che
        # deve tornare con le "N richieste" del menu di aggiornamento.
        conti = {
            "copie": 0, "righe": len(righe),
            "stampe": len({str(r["ref_id"]) for r in righe}),
            "valore": 0.0, "copie_valutate": 0,
            "copie_senza_annuncio": 0, "copie_da_controllare": 0,
            "spesa": 0.0, "copie_con_spesa": 0,
            "valore_confrontabile": 0.0, "spesa_confrontabile": 0.0,
            "copie_confrontabili": 0, "valuta": "", "valute_miste": False,
        }
        valute = set()
        for r in righe:
            copie = int(r["quantity"] or 0)
            conti["copie"] += copie
            prezzo = r["price"]
            noto = prezzo is not None
            if noto:
                conti["valore"] += float(prezzo) * copie
                conti["copie_valutate"] += copie
                valute.add((r["currency"] or "EUR").upper())
                conti["valuta"] = conti["valuta"] or (r["currency"] or "EUR")
            elif r["checked_at"]:
                conti["copie_senza_annuncio"] += copie   # controllata: non la vende nessuno
            else:
                conti["copie_da_controllare"] += copie   # mai controllata
            speso = r["paid"]
            if speso is not None:
                conti["spesa"] += float(speso) * copie
                conti["copie_con_spesa"] += copie
                if noto:
                    conti["valore_confrontabile"] += float(prezzo) * copie
                    conti["spesa_confrontabile"] += float(speso) * copie
                    conti["copie_confrontabili"] += copie
        conti["guadagno"] = (conti["valore_confrontabile"]
                             - conti["spesa_confrontabile"])
        # Sommare euro e sterline dà un numero che non esiste. Non capita col
        # provider di oggi (CardTrader risponde in EUR), ma se capitasse il
        # totale non deve spacciarsi per una valuta sola: chi lo mostra lo dice.
        conti["valute_miste"] = len(valute) > 1
        return conti

    # ------------------------------------------------------ impostazioni ---
    def get_setting(self, key, default=None):
        righe = self.storage.query("SELECT value FROM col_settings WHERE key = ?",
                                   (key,))
        return righe[0]["value"] if righe else default

    def set_setting(self, key, value) -> None:
        self.storage.execute(
            "INSERT OR REPLACE INTO col_settings (key, value) VALUES (?, ?)",
            (key, str(value)))
