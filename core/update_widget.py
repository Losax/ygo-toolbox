"""Il piede dell'aggiornamento: il thread che controlla e scarica, e il
riquadro sotto il menu laterale che lo racconta.

**Perché sta nel core e non in un modulo.** Prima l'avviso viveva
nell'header del market_watch, ma l'app si apre sul Database (primo in ordine
alfabetico): l'avviso c'era, la Release c'era, e per nove versioni di fila non
è servito a niente. Qui sotto il menu laterale si vede da qualunque pagina.

**Come si comporta**, in una riga: trovata una versione nuova la scarica **da
sola**, in sottofondo, senza chiedere; a file pronto e verificato offre UN
pulsante, *Riavvia e aggiorna*.

Conseguenza da non dimenticare: il download non l'ha chiesto nessuno, quindi
se fallisce **non si dice niente** — resta l'avviso di prima con il link alla
pagina, e il motivo finisce in `~/.ygo_toolbox/log.txt`. L'unica cosa che
parla è un aggiornamento *chiesto* che non è andato a buon fine, e lo dice una
volta sola (vedi `updates.esito_precedente`).

Il chip del catalogo carte è giallo e dice anche lui "aggiornamento": si
distinguono per posto (piede vs header del modulo), forma (pulsante vs
etichetta), icona (`↑` programma, `↻` dati) e parole (versioni vs carte).
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import updates
from core.i18n import tr
from core.version import APP_VERSION

#: Quanto si aspetta che Setup dia segno di essere partito. Misurato il
#: 2026-08-22: il file di log compare a t+2 s con l'installer in cache, la
#: finestra a t+8 s a freddo (47 MB da scompattare). 30 s è margine, non attesa
#: prevista — e finché non scade **l'app non si chiude**.
AVVIO_MAX = 30.0
AVVIO_PASSO = 500   # ms fra un controllo e l'altro


class UpdateWorker(QThread):
    """Un giro solo, all'avvio: chiede qual è l'ultima release e — se c'è, se
    siamo congelati e se non è una versione già scartata — ne scarica
    l'installer.

    Un thread per tutto e **nessun ritentativo**: l'API di GitHub concede 60
    richieste l'ora da IP non autenticato, e riprovare su una rete che non va
    è solo un modo di consumarle.
    """

    trovata = Signal(object)          # Release
    avanzamento = Signal(int, int)    # byte fatti, totale (0 = sconosciuto)
    pronta = Signal(object, str)      # Release, percorso dell'installer
    fallita = Signal(object, str)     # Release, motivo (per il log, non per l'utente)

    def __init__(self, parent=None, url: str = "") -> None:
        super().__init__(parent)
        self._url = url
        self._stop = False

    def richiedi_stop(self) -> None:
        """Chiamata alla chiusura dell'app: il download si interrompe al
        blocco successivo e il pezzo scaricato viene cancellato."""
        self._stop = True

    def _annullato(self) -> bool:
        return self._stop

    def run(self) -> None:  # noqa: D102 (firma Qt)
        release = updates.fetch_latest(self._url)
        if self._stop or release is None:
            return
        if not updates.is_newer(release.version):
            return
        self.trovata.emit(release)
        if not updates.is_frozen():
            return      # `python main.py`: si avvisa, non si installa
        if not release.installabile or updates.scartata(release.version):
            return      # niente asset, o versione che ha già fallito una volta
        try:
            percorso = updates.scarica(
                release,
                on_progress=lambda fatti, tot: self.avanzamento.emit(fatti, tot),
                annullato=self._annullato,
            )
        except InterruptedError:
            return      # l'app si sta chiudendo: non è un guasto
        except Exception as errore:   # rete, proxy TLS, file corto, disco pieno
            self.fallita.emit(release, "%s: %s" % (type(errore).__name__, errore))
            return
        if not self._stop:
            self.pronta.emit(release, str(percorso))


class UpdateFooter(QWidget):
    """Il riquadro sotto il menu laterale. Invisibile finché non c'è nulla da
    dire, così non costa spazio nel caso normale.

    Riceve dalla finestra principale due funzioni, invece di conoscerla:
    - `occupato()` → una frase se c'è un lavoro lungo in corso (sincronizzazione
      catalogo, giro prezzi), altrimenti "". È l'unico momento in cui l'utente
      può perdere lavoro vero, e l'unico modale ammesso in tutto il flusso;
    - `chiudi()` → chiude l'app per bene (stop dei moduli, DB chiuso, tray via)
      invece di farsi ammazzare da `CloseApplications=force`, che resta la rete
      di sicurezza. Chiudersi bene costa **31 secondi in meno**: misurato, è il
      timeout che Inno aspetta prima di uccidere l'exe onefile.
    """

    def __init__(self, parent=None, occupato=None, chiudi=None) -> None:
        super().__init__(parent)
        self.setObjectName("updatefoot")
        self._occupato = occupato or (lambda: "")
        self._chiudi = chiudi or (lambda: None)
        self._worker: UpdateWorker | None = None
        self._release = None
        self._installer = ""
        self._proc = None
        self._log: Path | None = None
        self._t_avvio = 0.0
        #: Stato corrente. Serve a far dispacciare il clic del pulsante da UN
        #: solo slot: ricollegare `clicked` a ogni cambio di stato è il modo di
        #: ritrovarsi un pulsante che dice "Riavvia e aggiorna" e apre la
        #: cartella (accaduto: `_non_partita` rifaceva il connect, e un
        #: download riuscito DOPO ereditava il collegamento sbagliato).
        self._stato = ""

        colonna = QVBoxLayout(self)
        colonna.setContentsMargins(12, 10, 12, 12)
        colonna.setSpacing(6)
        self.testo = QLabel()
        self.testo.setObjectName("updatetext")
        self.testo.setWordWrap(True)
        self.dettaglio = QLabel()
        self.dettaglio.setObjectName("updatesub")
        self.dettaglio.setWordWrap(True)
        self.dettaglio.setVisible(False)
        colonna.addWidget(self.testo)
        colonna.addWidget(self.dettaglio)

        # I pulsanti UNO SOTTO L'ALTRO, non affiancati: la colonna è larga
        # 190px e affiancandoli "Riavvia e aggiorna" si leggeva "ia e agg"
        # (visto in una schermata coi font veri — la larghezza utile è 166px,
        # appena quella di un pulsante solo).
        pila = QVBoxLayout()
        pila.setContentsMargins(0, 0, 0, 0)
        pila.setSpacing(5)
        self.btn_azione = QPushButton()
        self.btn_azione.setObjectName("primary")
        self.btn_azione.setVisible(False)
        self.btn_azione.clicked.connect(self._azione_premuta)
        self.btn_altro = QPushButton()
        self.btn_altro.setVisible(False)
        self.btn_altro.clicked.connect(self._apri_pagina)
        pila.addWidget(self.btn_azione)
        pila.addWidget(self.btn_altro)
        colonna.addLayout(pila)

        self._timer = QTimer(self)
        self._timer.setInterval(AVVIO_PASSO)
        self._timer.timeout.connect(self._controlla_avvio)

        self.setVisible(False)

    # ---------------------------------------------------------------- avvio

    def controlla_esito_precedente(self) -> None:
        """Com'è finito l'aggiornamento lanciato l'ultima volta? Da chiamare
        una volta, all'avvio. `esito_precedente` consuma lo stato, quindi
        qualunque cosa dica la dice una volta sola."""
        esito = updates.esito_precedente()
        if esito == "fatto":
            self._mostra(tr("✓ Aggiornata alla {v}").format(v=APP_VERSION),
                         calmo=True)
        elif esito == "mancato":
            # L'utente ha premuto un pulsante e non è successo quel che
            # doveva: questo va detto. Ma senza modale e senza allarmi — e
            # quella versione non si riscarica più da sola.
            self._mostra(tr("L'aggiornamento non è andato a buon fine."),
                         dettaglio=tr("Sei ancora alla {v}.").format(v=APP_VERSION),
                         calmo=True, altro=tr("Apri la pagina"))

    def avvia_controllo(self, url: str = "") -> None:
        """Un solo controllo per avvio, in un thread. Silenzioso su tutto."""
        if self._worker is not None:
            return
        self._worker = UpdateWorker(self, url)
        self._worker.trovata.connect(self._on_trovata)
        self._worker.avanzamento.connect(self._on_avanzamento)
        self._worker.pronta.connect(self._on_pronta)
        self._worker.fallita.connect(self._on_fallita)
        self._worker.start()

    def stop(self) -> None:
        """Alla chiusura dell'app: il thread va fermato, altrimenti il processo
        esce con 0xC0000409 senza un rigo di errore (già visto, GOTCHA 21)."""
        self._timer.stop()
        if self._worker is not None and self._worker.isRunning():
            self._worker.richiedi_stop()
            self._worker.wait(3000)

    # -------------------------------------------------------------- risposte

    def _on_trovata(self, release) -> None:
        self._release = release
        if updates.is_frozen() and release.installabile \
                and not updates.scartata(release.version):
            # Il download parte da solo: qui si dice solo che sta arrivando.
            self._mostra(tr("↑ Versione {v}").format(v=release.version),
                         dettaglio=tr("La sto preparando…"),
                         altro=tr("Apri la pagina"))
        else:
            # Non congelata, senza installer, o già fallita: resta la via che
            # funziona da sempre. "Apri la pagina" non si toglie mai.
            self._mostra(tr("↑ Versione {v}").format(v=release.version),
                         dettaglio=tr("Hai la {v}.").format(v=APP_VERSION),
                         altro=tr("Apri la pagina"))

    def _on_avanzamento(self, fatti: int, totale: int) -> None:
        if self._release is None:
            return
        # Percentuale SOLO se il server ha detto quanto pesa. Su un totale
        # ignoto sarebbe un numero inventato, e qui non se ne inventano.
        if totale > 0:
            self.dettaglio.setText(tr("La sto preparando… {p}%").format(
                p=min(100, int(fatti * 100 / totale))))
        else:
            self.dettaglio.setText(tr("La sto preparando… {mb} MB").format(
                mb=fatti // (1024 * 1024)))
        self.dettaglio.setVisible(True)

    def _on_pronta(self, release, percorso: str) -> None:
        self._release = release
        self._installer = percorso
        self._mostra(tr("↑ Versione {v} pronta").format(v=release.version),
                     azione=tr("Riavvia e aggiorna"),
                     altro=tr("Apri la pagina"), stato="pronta",
                     # L'app sta per chiudersi da sola: va detto PRIMA del clic,
                     # non scoperto dopo.
                     suggerimento=tr("Chiude l'app, installa la {v} e la "
                                     "riapre. Meno di un minuto.")
                     .format(v=release.version))

    def _on_fallita(self, release, motivo: str) -> None:
        """Download fallito. **Non si dice niente**: non l'aveva chiesto
        nessuno. Torna l'avviso col link, e il perché va nel log."""
        print("[updates] download di %s non riuscito: %s"
              % (getattr(release, "version", "?"), motivo))
        if release is not None:
            self._mostra(tr("↑ Versione {v}").format(v=release.version),
                         dettaglio=tr("Hai la {v}.").format(v=APP_VERSION),
                         altro=tr("Apri la pagina"))

    # ------------------------------------------------------- il gesto vero

    def _riavvia_e_aggiorna(self) -> None:
        if self._release is None or not self._installer:
            return
        # Punto 7 del flusso: l'unico momento in cui si può perdere lavoro
        # vero (una sincronizzazione sono 4-5 minuti). Unico modale ammesso.
        motivo = ""
        try:
            motivo = self._occupato() or ""
        except Exception:
            motivo = ""
        if motivo:
            risposta = QMessageBox.question(
                self, tr("Aggiornare adesso?"),
                tr("È in corso {cosa}. Aggiornando adesso si interrompe.\n\n"
                   "Aggiornare comunque?").format(cosa=motivo),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if risposta != QMessageBox.StandardButton.Yes:
                return

        versione = self._release.version
        self._log = updates.log_path(versione)
        # Un log di un tentativo precedente farebbe credere subito che Setup
        # sia partito: va via PRIMA, altrimenti il controllo non controlla nulla.
        try:
            self._log.unlink(missing_ok=True)
        except OSError:
            pass
        updates.segna_attesa(versione)
        self._mostra(tr("Avvio dell'installazione…"), calmo=True)
        try:
            self._proc = updates.lancia_installer(
                Path(self._installer), updates.install_dir(), self._log)
        except Exception as errore:
            print("[updates] Setup non è partito: %s: %s"
                  % (type(errore).__name__, errore))
            self._non_partita()
            return
        self._t_avvio = time.monotonic()
        self._timer.start()

    def _controlla_avvio(self) -> None:
        """L'app NON si chiude finché Setup non ha dato segno di essere partito
        davvero. È la sola differenza fra "aggiornamento in corso" e
        "l'antivirus ha messo in quarantena il file e l'utente resta senza app
        e senza spiegazione".

        Il segno è **la comparsa del file di log**, non il processo vivo: nel
        guasto del GOTCHA 24 il processo era uscito con **0** in tre secondi.
        """
        if self._log is not None and updates.installer_partito(self._log):
            self._timer.stop()
            self._chiudi()
            return
        morto = self._proc is not None and self._proc.poll() is not None
        scaduto = time.monotonic() - self._t_avvio > AVVIO_MAX
        if morto or scaduto:
            self._timer.stop()
            print("[updates] Setup non ha dato segno di vita "
                  "(uscito=%s, scaduto=%s)" % (morto, scaduto))
            self._non_partita()

    def _non_partita(self) -> None:
        """Setup non è partito: **non ci si chiude**, e si offrono le due vie
        d'uscita. E si dimentica l'attesa, altrimenti al prossimo avvio si
        annuncerebbe un fallimento che non c'è stato."""
        stato = updates.load_state()
        stato.pop("attesa", None)
        updates.save_state(stato)
        self._mostra(tr("L'installazione non è partita."),
                     dettaglio=tr("Il file scaricato è in .ygo_toolbox\\updates."),
                     calmo=True, azione=tr("Apri la cartella"),
                     altro=tr("Apri la pagina"), stato="non_partita")

    # ------------------------------------------------------------- utilità

    def _azione_premuta(self) -> None:
        """Un solo slot per il pulsante primario, che dispaccia sullo stato.
        Vedi `self._stato`: ricollegare `clicked` a ogni cambio di stato lascia
        collegamenti vecchi attaccati al pulsante nuovo."""
        if self._stato == "pronta":
            self._riavvia_e_aggiorna()
        elif self._stato == "non_partita":
            self._apri_cartella()

    def _apri_pagina(self) -> None:
        pagina = getattr(self._release, "page", "")
        if pagina:
            QDesktopServices.openUrl(QUrl(pagina))

    def _apri_cartella(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(updates.UPDATES_DIR)))

    def _mostra(self, testo: str, dettaglio: str = "", calmo: bool = False,
                azione: str = "", altro: str = "", stato: str = "",
                suggerimento: str = "") -> None:
        """Unico punto che tocca il riquadro: uno stato, una chiamata."""
        self._stato = stato
        self.btn_azione.setToolTip(suggerimento)
        self.testo.setText(testo)
        self.testo.setProperty("state", "calmo" if calmo else "")
        self.testo.style().unpolish(self.testo)
        self.testo.style().polish(self.testo)
        self.dettaglio.setText(dettaglio)
        self.dettaglio.setVisible(bool(dettaglio))
        self.btn_azione.setText(azione)
        self.btn_azione.setVisible(bool(azione))
        self.btn_altro.setText(altro)
        self.btn_altro.setVisible(bool(altro))
        self.setVisible(True)
