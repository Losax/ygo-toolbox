"""Accesso al database della Collezione (tabelle `col_*`).

Tre tabelle, e ognuna risponde a una domanda diversa:

- `col_items`   — **cosa possiedo**: una riga per stampa *in un certo stato*
                  (condizione, lingua, prima edizione), con quante copie, cosa
                  l'ho pagata e in quale tasca del raccoglitore sta;
- `col_binders` — **i raccoglitori**: nome, formato della pagina (3×3, 4×3…)
                  e ordine nell'elenco;
- `col_slots`   — **chi sta in quale tasca**: una riga per TASCA, e una tasca
                  tiene UNA copia. Tre copie della stessa carta nel
                  raccoglitore sono tre righe qui, come in un raccoglitore
                  vero — non una tasca con scritto "×3";
- `col_prices`  — **quanto vale oggi**: l'ultimo prezzo visto per ogni stampa,
                  con la data. È una cache, non uno storico: la Collezione
                  risponde a "quanto vale adesso", e tenere un punto per ogni
                  controllo di 2.000 carte sarebbe un archivio che nessuno
                  guarda (lo storico per carta ce l'ha già il Market Watch).

## Perché le tasche stanno in una tabella a parte (v1.9.0)

All'inizio la posizione era due colonne di `col_items` (`binder_id`, `slot`):
una riga, una tasca. Funzionava finché una riga valeva una carta, ma una riga
vale **n copie**, e in un raccoglitore vero tre copie occupano tre tasche. Con
la posizione dentro l'oggetto non c'era modo di dirlo: restava la scritta "×3"
su una tasca sola.

Ora la tasca è una **cosa**, non un attributo: `col_slots(binder_id, slot,
item_id)` con chiave primaria `(binder_id, slot)` — che è anche la garanzia,
scritta nello schema invece che nel codice, che due carte non possano finire
nella stessa tasca. Le copie di una carta possono stare in parte nelle tasche e
in parte sfuse (succede quando il raccoglitore è pieno), e `quantity` meno le
tasche occupate dice quante ne restano fuori: l'interfaccia lo mostra invece di
arrotondare.

Le vecchie colonne `col_items.binder_id` / `slot` sono **morte**: la
migrazione le travasa in `col_slots` una volta sola e poi le azzera. Restano
nella tabella perché cancellare colonne a un database già in mano all'utente
vale meno del rischio; non vanno lette da nessuno.

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
        # Una riga per TASCA. La chiave primaria `(binder_id, slot)` è la
        # garanzia che due carte non finiscano nello stesso posto: scritta
        # nello schema, non affidata a un controllo nel codice.
        self.storage.execute(
            """
            CREATE TABLE IF NOT EXISTS col_slots (
                binder_id INTEGER NOT NULL,
                slot      INTEGER NOT NULL,
                item_id   INTEGER NOT NULL,
                PRIMARY KEY (binder_id, slot)
            )
            """
        )
        self.storage.execute(
            "CREATE INDEX IF NOT EXISTS idx_col_slots_item ON col_slots(item_id)")
        self._migra_tasche()

    def _migra_tasche(self) -> None:
        """Travasa le vecchie `col_items.binder_id`/`slot` in `col_slots`.

        Una volta sola, e **moltiplicando per le copie**: una riga da 3 copie
        che stava in una tasca ne occupa tre, perché è quello che vuol dire la
        nuova regola. Poi le vecchie colonne si azzerano, così nessuno può
        leggerle per sbaglio e trovarci una verità vecchia.
        """
        if self.get_setting("tasche_migrate"):
            return
        righe = self.storage.query(
            "SELECT id, quantity, binder_id, slot FROM col_items "
            "WHERE binder_id IS NOT NULL AND slot >= 0 ORDER BY binder_id, slot")
        occupate: dict[int, set] = {}
        for r in righe:
            binder = int(r["binder_id"])
            presi = occupate.setdefault(binder, set())
            posto = int(r["slot"])
            for _ in range(max(1, int(r["quantity"] or 1))):
                while posto in presi:
                    posto += 1
                presi.add(posto)
                self.storage.execute(
                    "INSERT OR IGNORE INTO col_slots (binder_id, slot, item_id) "
                    "VALUES (?,?,?)", (binder, posto, int(r["id"])))
        self.storage.execute(
            "UPDATE col_items SET binder_id = NULL, slot = -1 "
            "WHERE binder_id IS NOT NULL OR slot >= 0")
        self.set_setting("tasche_migrate", "1")

    # ------------------------------------------------------------ carte ---
    #: pezzi di query comuni: quante tasche occupa una carta, e dove
    _IN_TASCA = ("(SELECT COUNT(*) FROM col_slots s WHERE s.item_id = i.id)")
    _NOME_BINDER = ("(SELECT b.name FROM col_slots s "
                    " JOIN col_binders b ON b.id = s.binder_id "
                    " WHERE s.item_id = i.id LIMIT 1)")

    def list_items(self, provider: str, binder_id=TUTTI) -> list:
        """Le carte possedute, con il prezzo noto agganciato.

        `binder_id`: `TUTTI` = tutte; `None` = solo le copie **fuori** dalle
        tasche; un id = solo le copie dentro quel raccoglitore.

        Ogni riga porta `copie_viste`: quante copie contano **in questa
        vista**. Non è un sinonimo di `quantity` — una carta da 3 copie con 2
        nel raccoglitore ne mostra 2 lì e 1 fra le sfuse — ed è il numero che
        i conti devono usare, altrimenti le stesse copie verrebbero contate due
        volte.
        """
        # I parametri vanno nell'ordine in cui i `?` compaiono nel TESTO della
        # query, non nell'ordine in cui si pensano: qui `copie_viste` sta nella
        # SELECT, quindi il suo segnaposto viene prima di quello del WHERE.
        # Sbagliando l'ordine la query non trova niente e i conti vanno a zero
        # senza un errore — l'ha preso il controllo automatico, non l'occhio.
        if binder_id is TUTTI:
            viste = "i.quantity"
            dove = "i.provider = ?"
            parametri = [provider]
        elif binder_id is None:
            viste = f"(i.quantity - {self._IN_TASCA})"
            dove = f"i.provider = ? AND i.quantity > {self._IN_TASCA}"
            parametri = [provider]
        else:
            viste = ("(SELECT COUNT(*) FROM col_slots s "
                     " WHERE s.item_id = i.id AND s.binder_id = ?)")
            dove = ("i.provider = ? AND EXISTS (SELECT 1 FROM col_slots s "
                    " WHERE s.item_id = i.id AND s.binder_id = ?)")
            parametri = [int(binder_id), provider, int(binder_id)]
        return self.storage.query(
            f"SELECT i.*, p.price AS price, p.currency AS currency, "
            f"       p.checked_at AS checked_at, "
            f"       {self._NOME_BINDER} AS binder_name, "
            f"       {self._IN_TASCA} AS copie_in_tasca, "
            f"       {viste} AS copie_viste "
            f"FROM col_items i "
            f"LEFT JOIN col_prices p ON p.provider = i.provider "
            f"     AND p.ref_id = i.ref_id "
            f"WHERE {dove} "
            f"ORDER BY i.card_name COLLATE NOCASE, i.set_code, i.id",
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
                 first_edition=False, paid=None, note="") -> int:
        """Aggiunge copie, **fondendole** con una riga identica se c'è già.

        "Identica" vuol dire stessa stampa, stesso stato e pagata la stessa
        cifra: solo allora due righe sono davvero la stessa cosa e sommarle non
        perde niente. Due copie pagate 2 € e 12 € restano due righe, perché il
        prezzo d'acquisto è un dato che l'utente ha inserito a mano e nessuno
        ha il diritto di mediarlo.

        Dove stia la carta **non entra più** nel confronto: da quando le tasche
        sono una tabella a parte, la stessa carta in un raccoglitore e sul
        tavolo è una riga sola con due copie, una in tasca e una no.
        """
        quantity = max(1, int(quantity))
        gemella = self.storage.query(
            "SELECT id FROM col_items WHERE provider = ? AND ref_id = ? "
            "AND condition = ? AND language = ? AND first_edition = ? "
            "AND paid IS ? LIMIT 1",
            (provider, str(ref_id), condition, language, int(bool(first_edition)),
             paid))
        if gemella:
            self.storage.execute(
                "UPDATE col_items SET quantity = quantity + ? WHERE id = ?",
                (quantity, gemella[0]["id"]))
            return int(gemella[0]["id"])
        cur = self.storage.execute(
            "INSERT INTO col_items (provider, ref_id, card_name, detail, set_code,"
            " image_url, quantity, condition, language, first_edition, paid, note)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (provider, str(ref_id), card_name, detail, set_code, image_url,
             quantity, condition, language, int(bool(first_edition)), paid, note))
        return int(cur.lastrowid)

    #: campi che si possono cambiare dopo l'inserimento (tutto il resto è
    #: identità della riga e si cambia cancellando e riaggiungendo)
    MODIFICABILI = ("quantity", "condition", "language", "first_edition", "paid",
                    "note", "detail", "set_code", "image_url", "card_name",
                    "ref_id")

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
        """Via la carta e via le sue tasche: niente tasche orfane."""
        self.storage.execute("DELETE FROM col_slots WHERE item_id = ?",
                             (int(item_id),))
        self.storage.execute("DELETE FROM col_items WHERE id = ?", (int(item_id),))

    def set_quantity(self, item_id, quantity: int) -> None:
        """Cambia le copie; a zero la riga sparisce (possedere zero copie non
        è uno stato, è non possederla).

        Se le copie scendono sotto il numero di tasche occupate, le tasche in
        eccesso si **liberano partendo dall'ultima**: tre copie in tre tasche
        che diventano due devono lasciarne una vuota, non restare tre.
        """
        quantity = int(quantity)
        if quantity <= 0:
            self.remove_item(item_id)
            return
        self.storage.execute("UPDATE col_items SET quantity = ? WHERE id = ?",
                             (quantity, int(item_id)))
        in_tasca = self.copies_placed(item_id)
        if in_tasca > quantity:
            self.storage.execute(
                "DELETE FROM col_slots WHERE rowid IN ("
                "  SELECT rowid FROM col_slots WHERE item_id = ? "
                "  ORDER BY binder_id DESC, slot DESC LIMIT ?)",
                (int(item_id), in_tasca - quantity))

    # ----------------------------------------------------- raccoglitori ---
    def list_binders(self) -> list:
        """I raccoglitori, con quante righe e quante copie contengono."""
        return self.storage.query(
            "SELECT b.*, "
            " (SELECT COUNT(DISTINCT s.item_id) FROM col_slots s "
            "  WHERE s.binder_id = b.id) AS righe, "
            " (SELECT COUNT(*) FROM col_slots s WHERE s.binder_id = b.id) AS copie "
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
            self.storage.execute(
                "DELETE FROM col_items WHERE id IN "
                "(SELECT item_id FROM col_slots WHERE binder_id = ?)",
                (int(binder_id),))
        self.storage.execute("DELETE FROM col_slots WHERE binder_id = ?",
                             (int(binder_id),))
        self.storage.execute("DELETE FROM col_binders WHERE id = ?",
                             (int(binder_id),))

    def set_binder_positions(self, coppie) -> None:
        self.storage.executemany(
            "UPDATE col_binders SET position = ? WHERE id = ?",
            [(int(p), int(i)) for i, p in coppie])

    # ----------------------------------------------------------- tasche ---
    # Una tasca tiene UNA copia. Tutto quello che sta qui sotto ragiona per
    # copie, non per righe: è la differenza fra un raccoglitore e una lista.
    def slots_of(self, binder_id) -> dict:
        """`slot → riga della carta` per tutte le tasche piene di un raccoglitore."""
        righe = self.storage.query(
            "SELECT s.slot AS slot, i.*, p.price AS price, "
            "       p.currency AS currency, p.checked_at AS checked_at "
            "FROM col_slots s "
            "JOIN col_items i ON i.id = s.item_id "
            "LEFT JOIN col_prices p ON p.provider = i.provider "
            "     AND p.ref_id = i.ref_id "
            "WHERE s.binder_id = ? ORDER BY s.slot", (int(binder_id),))
        return {int(r["slot"]): r for r in righe}

    def item_at(self, binder_id, slot: int):
        righe = self.storage.query(
            "SELECT i.* FROM col_slots s JOIN col_items i ON i.id = s.item_id "
            "WHERE s.binder_id = ? AND s.slot = ? LIMIT 1",
            (int(binder_id), int(slot)))
        return righe[0] if righe else None

    def copies_placed(self, item_id, binder_id=None) -> int:
        """Quante copie di questa carta stanno in una tasca (in tutto, o qui)."""
        if binder_id is None:
            righe = self.storage.query(
                "SELECT COUNT(*) AS n FROM col_slots WHERE item_id = ?",
                (int(item_id),))
        else:
            righe = self.storage.query(
                "SELECT COUNT(*) AS n FROM col_slots "
                "WHERE item_id = ? AND binder_id = ?",
                (int(item_id), int(binder_id)))
        return int(righe[0]["n"]) if righe else 0

    def first_free_slot(self, binder_id, da: int = 0) -> int:
        """La prima tasca libera da `da` in poi (anche in mezzo alle pagine).

        Riempire i buchi lasciati da una carta tolta è ciò che ci si aspetta
        da un raccoglitore: l'alternativa — andare sempre in fondo — lascia
        pagine mezze vuote che poi si sistemano a mano.
        """
        usati = {int(r["slot"]) for r in self.storage.query(
            "SELECT slot FROM col_slots WHERE binder_id = ?", (int(binder_id),))}
        posto = max(0, int(da))
        while posto in usati:
            posto += 1
        return posto

    def place_item(self, item_id, binder_id, slot: int = 0) -> int:
        """Mette nel raccoglitore le copie ancora fuori, **una per tasca**.

        Parte dalla tasca indicata e prosegue con le libere successive: tre
        copie entrano in tre tasche, che è tutto il senso di questa richiesta.
        Se il raccoglitore finisce lo spazio ne entrano meno, e le altre
        restano sfuse — detto, non arrotondato. Torna quante ne ha messe.

        Una carta sta in **un** raccoglitore alla volta: portandola altrove,
        le tasche di prima si liberano.
        """
        item_id, binder_id = int(item_id), int(binder_id)
        riga = self.item(item_id)
        if riga is None:
            return 0
        self.storage.execute(
            "DELETE FROM col_slots WHERE item_id = ? AND binder_id <> ?",
            (item_id, binder_id))
        da_mettere = int(riga["quantity"] or 1) - self.copies_placed(item_id, binder_id)
        posto, messe = max(0, int(slot)), 0
        while messe < da_mettere:
            posto = self.first_free_slot(binder_id, posto)
            self.storage.execute(
                "INSERT OR IGNORE INTO col_slots (binder_id, slot, item_id) "
                "VALUES (?,?,?)", (binder_id, posto, item_id))
            posto += 1
            messe += 1
        return messe

    def move_slot(self, binder_id, da: int, a: int) -> None:
        """Sposta la copia da una tasca all'altra, **scambiando** con chi c'era.

        Lo scambio è l'unico comportamento che non perde niente: sovrascrivere
        farebbe sparire una carta senza dirlo, e rifiutare il gesto
        costringerebbe a svuotare la tasca a mano prima di ogni spostamento.
        """
        binder_id, da, a = int(binder_id), int(da), int(a)
        if da == a:
            return
        qui = self.storage.query(
            "SELECT item_id FROM col_slots WHERE binder_id = ? AND slot = ?",
            (binder_id, da))
        if not qui:
            return
        mio = int(qui[0]["item_id"])
        altro = self.storage.query(
            "SELECT item_id FROM col_slots WHERE binder_id = ? AND slot = ?",
            (binder_id, a))
        self.storage.execute(
            "DELETE FROM col_slots WHERE binder_id = ? AND slot IN (?, ?)",
            (binder_id, da, a))
        self.storage.execute(
            "INSERT INTO col_slots (binder_id, slot, item_id) VALUES (?,?,?)",
            (binder_id, a, mio))
        if altro:
            self.storage.execute(
                "INSERT INTO col_slots (binder_id, slot, item_id) VALUES (?,?,?)",
                (binder_id, da, int(altro[0]["item_id"])))

    def unplace_slot(self, binder_id, slot: int) -> None:
        """Svuota UNA tasca: quella copia torna sfusa (la carta resta)."""
        self.storage.execute(
            "DELETE FROM col_slots WHERE binder_id = ? AND slot = ?",
            (int(binder_id), int(slot)))

    def unplace_item(self, item_id) -> None:
        """Toglie dal raccoglitore **tutte** le copie di questa carta."""
        self.storage.execute("DELETE FROM col_slots WHERE item_id = ?",
                             (int(item_id),))

    def cleanup_slots(self) -> None:
        """Via le tasche che indicano carte o raccoglitori che non ci sono più,
        e quelle in eccesso rispetto alle copie possedute."""
        self.storage.execute(
            "DELETE FROM col_slots WHERE item_id NOT IN (SELECT id FROM col_items)")
        self.storage.execute(
            "DELETE FROM col_slots WHERE binder_id NOT IN "
            "(SELECT id FROM col_binders)")
        for r in self.storage.query(
                "SELECT s.item_id AS id, COUNT(*) AS n, i.quantity AS q "
                "FROM col_slots s JOIN col_items i ON i.id = s.item_id "
                "GROUP BY s.item_id HAVING n > q"):
            self.storage.execute(
                "DELETE FROM col_slots WHERE rowid IN ("
                "  SELECT rowid FROM col_slots WHERE item_id = ? "
                "  ORDER BY binder_id DESC, slot DESC LIMIT ?)",
                (int(r["id"]), int(r["n"]) - int(r["q"])))

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
            # `copie_viste`, non `quantity`: in un raccoglitore contano le copie
            # che stanno LÌ, e fra le sfuse quelle che non stanno da nessuna
            # parte. Con `quantity` le stesse copie verrebbero contate due volte.
            copie = int(r["copie_viste"] if "copie_viste" in r.keys()
                        else r["quantity"] or 0)
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
