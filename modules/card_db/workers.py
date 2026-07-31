"""Thread del modulo Database.

Regola del progetto: la rete sta nei thread, il DB solo nel thread della GUI.
Qui si scarica e si *analizza* (che su 14.477 carte non è gratis), poi le
righe già pronte tornano alla GUI con un segnale ed è lei a scriverle.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from . import api


class VersionWorker(QThread):
    """Chiede la versione del database remoto: una richiesta piccolissima.

    Serve a sapere se la copia locale è vecchia senza riscaricare 23 MB. Se
    fallisce **tace**: è un controllo che l'utente non ha chiesto, e un errore
    per una cosa che non ha chiesto è solo fastidio (stessa regola del
    controllo aggiornamenti dell'app)."""

    done = Signal(str, str)     # versione, ultimo aggiornamento

    def run(self) -> None:  # noqa: D102
        try:
            versione, quando = api.fetch_db_version()
        except api.YgoProError:
            return
        self.done.emit(versione, quando)


class SetsWorker(QThread):
    """Solo l'elenco dei set con le date (170 KB).

    Serve a chi ha già scaricato il database prima che le date esistessero:
    invece di chiedergli di risincronizzare 24 MB, si prende il pezzo che
    manca. Se fallisce **tace**: l'ordine delle ristampe resta quello per
    codice, che è comunque un ordine."""

    done = Signal(list)

    def run(self) -> None:  # noqa: D102
        try:
            righe = api.fetch_sets()
        except api.YgoProError:
            return
        if righe:
            self.done.emit(righe)


class SyncWorker(QThread):
    """Scarica l'intero database e lo prepara per l'inserimento.

    Emette `progress` durante lo scaricamento e poi durante l'analisi: sono
    due fasi entrambe percepibili, e una barra che si ferma a metà senza
    spiegazione sembra un blocco."""

    progress = Signal(str, int, int)          # fase, fatto, totale
    # carte, stampe, elenco set (con le date), versione, data
    finished_ok = Signal(list, list, list, str, str)
    failed = Signal(str)

    def run(self) -> None:  # noqa: D102
        try:
            versione, quando = "", ""
            try:
                versione, quando = api.fetch_db_version()
            except api.YgoProError:
                pass          # la versione è un di più: non ferma la copia
            grezze = api.fetch_all_cards(
                should_stop=self.isInterruptionRequested,
                progress=lambda fatto, tot: self.progress.emit("download", fatto, tot))
            carte, sets = [], []
            totale = len(grezze)
            per_id: dict = {}
            for indice, raw in enumerate(grezze):
                if self.isInterruptionRequested():
                    return
                try:
                    carta, righe_set = api.parse_card(raw)
                except (TypeError, ValueError, AttributeError):
                    continue          # una carta storta non butta via le altre
                if not carta["id"]:
                    continue
                carte.append(carta)
                per_id[carta["id"]] = carta
                sets.extend(righe_set)
                if indice % 500 == 0:
                    self.progress.emit("analisi", indice, totale)

            # --- seconda passata: i testi ITALIANI si sovrappongono a quelli
            # inglesi dove esistono (11.599 su 14.477). Se questa richiesta
            # fallisce NON si butta via il lavoro: si resta in inglese, che è
            # esattamente com'era prima.
            if not self.isInterruptionRequested():
                try:
                    self.progress.emit("italiano", 0, 0)
                    for raw in api.fetch_all_cards(
                            should_stop=self.isInterruptionRequested,
                            progress=lambda f, t: self.progress.emit("italiano", f, t),
                            language="it"):
                        carta = per_id.get(int(raw.get("id") or 0))
                        if carta is None:
                            continue      # esiste in italiano ma non in inglese
                        carta["name_it"] = raw.get("name") or ""
                        carta["desc_it"] = raw.get("desc") or ""
                except api.YgoProError:
                    pass

            # --- terza richiesta, piccola (170 KB): le DATE dei set, che nei
            # dati delle carte non ci sono. Se manca, le ristampe restano in
            # ordine di codice invece che cronologico: si perde l'ordine, non
            # il database.
            setinfo: list = []
            if not self.isInterruptionRequested():
                try:
                    setinfo = api.fetch_sets()
                except api.YgoProError:
                    pass
        except api.YgoProError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:      # imprevisto: parlante, non un crash muto
            self.failed.emit(f"Errore inatteso: {exc}")
            return
        if not carte:
            self.failed.emit("Nessuna carta valida nella risposta.")
            return
        self.finished_ok.emit(carte, sets, setinfo, versione, quando)
