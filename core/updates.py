"""Aggiornamento dell'app: scoprire che c'è una versione nuova, scaricarla e
installarla senza far fare niente all'utente.

Qui dentro NON c'è Qt: sono funzioni bloccanti e pure, così si possono provare
headless. La parte con thread, chip e pulsante sta in `core/update_widget.py`.

TRE REGOLE, tutte con un motivo:

- **silenzio sui guai.** Il controllo e il download partono da soli, non li ha
  chiesti nessuno: rete assente, proxy che ispeziona il TLS, indirizzo
  sbagliato, JSON incomprensibile non devono produrre un solo avviso. Le
  funzioni qui sollevano l'eccezione (serve a chi legge il log); è chi chiama a
  restare zitto. L'unica cosa che parla è un aggiornamento CHIESTO che non è
  andato a buon fine, e lo dice una volta sola.
- **si installa solo l'app congelata.** Con `python main.py` il pulsante non
  compare: installare sopra un'installazione che non è quella in esecuzione è
  il modo più rapido per non capire più niente.
- **l'asset si scegli per PATTERN, mai `assets[0]`.** L'ordine dipende da cosa
  è stato caricato per primo, e fra `gh release create` e la fine dell'upload
  c'è una finestra reale in cui la lista è incompleta.

E una trappola che è costata un'installazione fantasma, per esteso nel
REGISTRO_TECNICO (GOTCHA 24): la riga di comando di Setup si costruisce SOLO
con `subprocess.Popen(lista)`. Concatenando stringhe, `/DIR=C:\\…\\YGO Toolbox`
arriva senza virgolette, Inno lo tronca allo spazio, installa in `…\\YGO`, si
prende la chiave di disinstallazione di quella vera — e scrive nel log
"Installation process succeeded" uscendo con codice 0. Perciò:
**il codice di uscita non è una prova. La prova è la versione che si legge al
riavvio successivo.**

Sorgente: `LATEST_URL`, l'API delle release di GitHub (risponde solo se il
repository è PUBBLICO). In alternativa basta un JSON con `tag_name`,
`html_url` e `assets[]`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from core.version import APP_VERSION

#: Sorgente del controllo. La variabile d'ambiente `YGO_UPDATE_URL` la
#: sostituisce, e serve a UNA cosa: **collaudare l'aggiornamento dentro l'exe
#: installato** puntandolo a un JSON locale (`file:///…/release.json`) che
#: descrive una versione finta più nuova.
#:
#: Perché serve un gancio invece di provare "dal vivo": il pezzo più rischioso
#: del flusso è il `Popen` con `DEVNULL` fatto da un processo *windowed*
#: congelato (dove gli handle standard non sono validi e si prende `WinError 6`),
#: e quello si vede solo dall'exe installato. Senza questa riga, per provarlo
#: servirebbero due Release pubbliche di fila.
#: Non allarga la superficie d'attacco: chi può impostare le variabili
#: d'ambiente di questo utente può già sostituire direttamente l'exe.
LATEST_URL = (os.environ.get("YGO_UPDATE_URL", "").strip()
              or "https://api.github.com/repos/Losax/ygo-toolbox/releases/latest")
TIMEOUT = 8
#: Tetto a orologio per l'intero download. Il `timeout` di `urlopen` è
#: PER-LETTURA: un proxy che sgocciola un byte al secondo non lo fa scattare
#: mai, e senza questo il thread resterebbe appeso per sempre.
DOWNLOAD_DEADLINE = 900
CHUNK = 256 * 1024
_UA = "YGO-Toolbox-update-check"

#: Cartella di lavoro. NON `sys._MEIPASS` (il bootloader onefile la cancella
#: all'uscita), NON `{app}` (Setup la sta manipolando), NON la `{tmp}` di Inno
#: (cancellata a fine installazione).
UPDATES_DIR = Path.home() / ".ygo_toolbox" / "updates"
STATE_FILE = UPDATES_DIR / "stato.json"


# --------------------------------------------------------------------------
# confronto di versioni
# --------------------------------------------------------------------------

def parse_version(text: str) -> tuple:
    """ "v1.0.23" → (1, 0, 23). I pezzi non numerici si ignorano, così un
    "1.1.0-beta" non fa esplodere il confronto."""
    pezzi = []
    for parte in (text or "").strip().lstrip("vV").split("."):
        numero = ""
        for ch in parte:
            if not ch.isdigit():
                break
            numero += ch
        pezzi.append(int(numero) if numero else 0)
    return tuple(pezzi) or (0,)


def is_newer(candidate: str, current: str = APP_VERSION) -> bool:
    """True se `candidate` è una versione successiva a quella in uso.

    Confronto per NUMERI, non alfabetico: "1.0.9" < "1.0.23" (come stringhe
    sarebbe il contrario, ed è esattamente l'errore che ci si aspetta qui).
    Il confronto è `>` STRETTO: Inno non impedisce i downgrade, quindi non
    dobbiamo proporne noi."""
    a, b = parse_version(candidate), parse_version(current)
    lunghezza = max(len(a), len(b))
    a += (0,) * (lunghezza - len(a))
    b += (0,) * (lunghezza - len(b))
    return a > b


# --------------------------------------------------------------------------
# la release e il suo installer
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Release:
    """Quel che serve sapere di una release: la versione, la pagina per gli
    umani, e l'installer con nome e DIMENSIONE DICHIARATA (è quella che rende
    verificabile il download: senza, un file troncato passerebbe)."""
    version: str
    page: str
    asset_url: str = ""
    asset_name: str = ""
    asset_size: int = 0

    @property
    def installabile(self) -> bool:
        """C'è un installer da scaricare, e sappiamo quanto deve pesare."""
        return bool(self.asset_url and self.asset_name and self.asset_size > 0)


def _pick_asset(assets: object) -> dict | None:
    """L'installer, scelto per PATTERN: nome che contiene "setup", estensione
    `.exe`, upload FINITO (`state == "uploaded"`).

    Mai `assets[0]`: se un giorno alla Release si allega anche un changelog o
    uno zip, il primo elemento è quello che è stato caricato per primo."""
    if not isinstance(assets, list):
        return None
    for voce in assets:
        if not isinstance(voce, dict):
            continue
        nome = str(voce.get("name") or "")
        if (str(voce.get("state") or "") == "uploaded"
                and nome.lower().endswith(".exe")
                and "setup" in nome.lower()
                and voce.get("browser_download_url")):
            return voce
    return None


def fetch_latest(url: str = "") -> Release | None:
    """La release più recente, o None se non si sa.

    CHIAMATA BLOCCANTE: usarla in un thread (vedi `core/update_widget.py`).
    Non solleva: qui il silenzio è la regola, perché nessuno ha chiesto niente.
    """
    try:
        req = urllib.request.Request(url or LATEST_URL, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    if not isinstance(data, dict):
        return None
    versione = str(data.get("tag_name") or data.get("version") or "").strip()
    if not versione:
        return None
    pagina = str(data.get("html_url") or data.get("url") or "").strip()
    asset = _pick_asset(data.get("assets"))
    if asset is None:
        # Release senza installer allegato (o upload non ancora finito): si
        # avvisa comunque, ma con il solo link. Meglio un avviso che niente.
        return Release(version=versione.lstrip("vV"), page=pagina)
    try:
        peso = int(asset.get("size") or 0)
    except (TypeError, ValueError):
        peso = 0
    return Release(
        version=versione.lstrip("vV"),
        page=pagina,
        asset_url=str(asset.get("browser_download_url") or ""),
        asset_name=str(asset.get("name") or ""),
        asset_size=peso,
    )


# --------------------------------------------------------------------------
# download
# --------------------------------------------------------------------------

def is_frozen() -> bool:
    """True se stiamo girando dentro l'exe di PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    """La cartella dove SIAMO installati. `/DIR` va sempre da qui: con
    `PrivilegesRequiredOverridesAllowed=dialog` un percorso diverso può
    lasciare DUE installazioni, una per-utente e una per-macchina."""
    return Path(sys.executable).resolve().parent


def verifica_file(percorso: Path, peso_atteso: int) -> bool:
    """Il file scaricato è l'installer intero?

    Due controlli, entrambi necessari: i byte scritti devono essere ESATTAMENTE
    quelli dichiarati dalla release, e i primi due devono essere `MZ` (la firma
    di un eseguibile Windows). Il secondo smaschera il caso in cui il proxy
    aziendale restituisce una pagina di errore HTML con la lunghezza giusta per
    puro caso; il primo, il download troncato."""
    try:
        if percorso.stat().st_size != int(peso_atteso):
            return False
        with open(percorso, "rb") as f:
            return f.read(2) == b"MZ"
    except (OSError, TypeError, ValueError):
        return False


def scarica(release: Release, on_progress=None, annullato=None,
            deadline: float = DOWNLOAD_DEADLINE) -> Path:
    """Scarica l'installer in `UPDATES_DIR` e ne restituisce il percorso.

    BLOCCANTE, da usare in un thread. Solleva in caso di guaio (rete, file
    corto, firma sbagliata): chi chiama decide se tacere.

    - `on_progress(fatti, totale)`: `totale` è 0 quando il server non manda
      `Content-Length`. In quel caso la barra va INDETERMINATA — una
      percentuale su un totale ignoto è un numero inventato.
    - `annullato()`: se torna True si smette subito e si cancella il pezzo.

    **Niente `Range`, niente ripresa.** Riprendere dentro il file di un'altra
    release costruirebbe un ibrido che passa il controllo di dimensione.
    """
    if not release.installabile:
        raise ValueError("release senza installer da scaricare")
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    finale = UPDATES_DIR / release.asset_name
    if verifica_file(finale, release.asset_size):
        return finale                      # già scaricata in un giro precedente
    parziale = UPDATES_DIR / (release.asset_name + ".part")
    parziale.unlink(missing_ok=True)       # mai ereditare un pezzo altrui

    scaduta = time.monotonic() + max(30.0, float(deadline))
    req = urllib.request.Request(release.asset_url, headers={"User-Agent": _UA})
    fatti = 0
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            dichiarato = resp.headers.get("Content-Length")
            try:
                totale = int(dichiarato) if dichiarato else 0
            except (TypeError, ValueError):
                totale = 0
            with open(parziale, "wb") as out:
                while True:
                    if annullato is not None and annullato():
                        raise InterruptedError("download annullato")
                    if time.monotonic() > scaduta:
                        raise TimeoutError(
                            "download oltre il tempo massimo (%ds)" % int(deadline))
                    blocco = resp.read(CHUNK)
                    if not blocco:
                        break
                    out.write(blocco)
                    fatti += len(blocco)
                    if on_progress is not None:
                        on_progress(fatti, totale)
    except BaseException:
        parziale.unlink(missing_ok=True)
        raise

    if not verifica_file(parziale, release.asset_size):
        peso = parziale.stat().st_size if parziale.exists() else 0
        parziale.unlink(missing_ok=True)
        raise OSError("installer non valido: %d byte invece di %d"
                      % (peso, release.asset_size))
    os.replace(parziale, finale)           # atomico: o c'è intero o non c'è
    return finale


def pulisci_scaricati(tranne: str = "") -> None:
    """Via gli installer vecchi da `UPDATES_DIR` (48 MB l'uno).

    Si chiama quando un aggiornamento è andato a buon fine: da quel momento il
    file non serve più a nessuno. Silenziosa: se un file è bloccato, pazienza.
    """
    try:
        voci = list(UPDATES_DIR.glob("*.exe")) + list(UPDATES_DIR.glob("*.exe.part"))
    except OSError:
        return
    for voce in voci:
        if tranne and voce.name == tranne:
            continue
        try:
            voce.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------
# lancio dell'installer
# --------------------------------------------------------------------------

def log_path(versione: str) -> Path:
    """Il file di log di Inno per quella versione.

    Vale il suo peso: è quello che ha reso diagnosticabile in mezzo minuto
    l'installazione fantasma del GOTCHA 24. **La cartella va creata PRIMA**: se
    Setup non riesce a creare il file di log, aborta."""
    pulita = "".join(ch for ch in versione if ch.isalnum() or ch in "._-")
    return UPDATES_DIR / ("setup-%s.log" % (pulita or "x"))


def install_command(installer: Path, cartella: Path, log: Path) -> list[str]:
    """La riga di comando di Setup, come LISTA. Vedi il GOTCHA 24: costruirla
    come stringa è il modo di creare un'installazione fantasma.

    Scelte, ognuna con un perché:
    - `/SILENT` e **non** `/VERYSILENT`: con l'app chiusa, la barra di Inno è
      l'unica cosa a schermo che dice che il computer non si è piantato.
    - **niente `/SUPPRESSMSGBOXES`**: risponde *Annulla* al box
      Riprova/Annulla, cioè trasforma un file bloccato per mezzo secondo in
      un'installazione abortita CON L'EXE VECCHIO GIÀ RIMOSSO.
    - **niente `/CURRENTUSER` né `/ALLUSERS`**: con
      `PrivilegesRequiredOverridesAllowed=dialog` fanno *fallire* il setup.
    - `/NOCANCEL`: a copia iniziata non c'è un "indietro" — Inno non fa
      rollback.
    - nessun parametro nostro per il rilancio: ci pensa la voce `[Run]`
      dell'`.iss`, a cui è stato tolto `skipifsilent`.
    """
    return [
        str(installer), "/SILENT", "/NOCANCEL", "/NORESTART", "/SP-",
        "/DIR=" + str(cartella), "/LOG=" + str(log),
    ]


def lancia_installer(installer: Path, cartella: Path | None = None,
                     log: Path | None = None) -> subprocess.Popen:
    """Avvia Setup e restituisce il processo. Non attende: chi chiama controlla
    che sia partito davvero (vedi `installer_partito`).

    - **lista di argomenti, mai `shell=True`, mai un `.bat`** (GOTCHA 24);
    - `stdin/stdout/stderr=DEVNULL`: in app *windowed* gli handle standard non
      sono validi e senza questo si prende `WinError 6`;
    - `cwd` fuori da `{app}`, che Setup sta per toccare;
    - **non `os.startfile()`**: passa da `ShellExecute`, quindi da SmartScreen.
      `Popen` usa `CreateProcess` e no.
    """
    cartella = cartella or install_dir()
    log = log or log_path("x")
    log.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        install_command(installer, cartella, log),
        cwd=str(Path.home()),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def installer_partito(log: Path) -> bool:
    """Setup è davvero partito?

    Il segnale è **la comparsa del file di `/LOG`**, non una finestra e non il
    processo vivo. Misurato il 2026-08-22: il log appare a t+2 s con
    l'installer in cache, la finestra solo a t+8 s a freddo (il bootloader
    onefile deve prima scompattare 47 MB). E soprattutto: nell'installazione
    fantasma il processo era uscito con **0** dopo tre secondi, quindi
    "il processo è vivo" e "il processo è uscito bene" non dicono nulla."""
    try:
        return log.exists() and log.stat().st_size > 0
    except OSError:
        return False


# --------------------------------------------------------------------------
# memoria fra un avvio e l'altro
# --------------------------------------------------------------------------

def load_state() -> dict:
    """Lo stato fra due avvii, da un JSON accanto agli installer.

    Un file e non il DB: quando lo scriviamo l'app si sta chiudendo e lo
    storage è già chiuso, e al riavvio va letto prima che i moduli esistano.

    Chiavi:
    - `attesa`: la versione per cui abbiamo lanciato un installer. Al riavvio
      si confronta con quella in esecuzione: è l'unica prova che l'installazione
      sia avvenuta (vedi GOTCHA 24).
    - `annunciata`: versione per cui abbiamo GIÀ detto che è andata male, così
      lo si dice una volta sola.
    - `scartate`: versioni da non riscaricare più da sole. Senza questa lista,
      un aggiornamento che fallisce ricomincia a ogni avvio: 48 MB a giro, in
      sottofondo, per sempre.
    """
    try:
        dati = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dati if isinstance(dati, dict) else {}


def save_state(stato: dict) -> None:
    """Silenziosa: se non si può scrivere, il massimo danno è riproporre un
    aggiornamento già fatto."""
    try:
        UPDATES_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(stato, indent=2), encoding="utf-8")
    except OSError:
        pass


def segna_attesa(versione: str) -> None:
    """Prima di chiudersi: "sto per diventare la X". Al prossimo avvio si
    verifica, ed è l'unico controllo che dice la verità."""
    stato = load_state()
    stato["attesa"] = versione
    save_state(stato)


def scarta(versione: str) -> None:
    """Quella versione non si riscarica più da sola (resta il link)."""
    stato = load_state()
    scartate = [v for v in stato.get("scartate", []) if isinstance(v, str)]
    if versione not in scartate:
        scartate.append(versione)
    stato["scartate"] = scartate[-10:]
    save_state(stato)


def scartata(versione: str) -> bool:
    stato = load_state()
    return versione in [v for v in stato.get("scartate", []) if isinstance(v, str)]


def esito_precedente(corrente: str = APP_VERSION) -> str:
    """Com'è finito l'aggiornamento che avevamo lanciato? Consuma lo stato,
    quindi risponde una volta sola. Torna:

    - `""`      nessun aggiornamento in sospeso (il caso normale);
    - `"fatto"` la versione attesa è quella in esecuzione: si ripulisce tutto;
    - `"mancato"` l'installazione non è avvenuta. Va detto UNA volta, e quella
      versione non si riscarica più da sola.
    """
    stato = load_state()
    attesa = str(stato.get("attesa") or "").strip()
    if not attesa:
        return ""
    stato.pop("attesa", None)
    if not is_newer(attesa, corrente):
        # combacia (o siamo perfino più avanti): pulizia completa
        stato.pop("annunciata", None)
        save_state(stato)
        pulisci_scaricati()
        return "fatto"
    if stato.get("annunciata") == attesa:
        save_state(stato)
        return ""                          # già detto: non si ripete
    stato["annunciata"] = attesa
    scartate = [v for v in stato.get("scartate", []) if isinstance(v, str)]
    if attesa not in scartate:
        scartate.append(attesa)
    stato["scartate"] = scartate[-10:]
    save_state(stato)
    return "mancato"
