"""Esporta e importa la watchlist in un file JSON leggibile.

SQLite è un buon motore e un pessimo formato di scambio: è binario, ha uno
schema con migrazioni e per aprirlo serve uno strumento. Qui si passa da un
file di testo che chiunque può aprire, leggere e all'occorrenza correggere.

DECISIONI, tutte deliberate:
- **JSON, non CSV.** I dati sono gerarchici: le basi contengono carte, e sia le
  basi sia le carte portano un *oggetto* di filtri. In CSV servirebbero più file
  collegati da id — per un amico è meno comprensibile, non più.
- **Chiavi in italiano.** Questo file lo legge una persona, non una macchina.
- **Il TOKEN non si esporta MAI.** È una credenziale, e il file è nato per
  essere passato a qualcuno.
- **Il catalogo non si esporta.** 47.980 righe che si riscaricano in 4 minuti:
  renderebbe il file cento volte più grosso senza aggiungere niente di tuo.
- **`versione` in cima**, così i file di oggi resteranno leggibili domani.
"""
from __future__ import annotations

import json
from datetime import datetime

FORMATO = "ygo-toolbox/watchlist"
VERSIONE = 1


# --------------------------------------------------------------------------- #
# Esportazione
# --------------------------------------------------------------------------- #
def _filtri(raw: str):
    """La stringa JSON dei filtri come oggetto; None = "usa il livello sopra"."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _carta(watch) -> dict:
    return {
        "ref_id": str(watch["ref_id"]),
        "nome": watch["card_name"],
        "dettaglio": watch["detail"] or "",
        "copie": watch["copies"] if "copies" in watch.keys() else 1,
        "soglia": watch["threshold_pct"],
        "filtri": _filtri(watch["filters"] if "filters" in watch.keys() else ""),
    }


def export_data(repo, provider: str, app_version: str = "",
                only_folder_id=None, include_history: bool | None = None) -> dict:
    """Il contenuto da salvare su file.

    `only_folder_id` esporta UNA sola base (il caso "passo il mazzo a un
    amico"); senza, esporta tutto.

    Lo storico prezzi entra nei backup e resta fuori dalle condivisioni (per
    l'amico è ingombro privo di senso: i suoi filtri sono altri). La regola la
    applica questa funzione da sé — `include_history=None` significa "decidi
    tu" — invece di affidarla alla memoria di chi la chiama."""
    if include_history is None:
        include_history = only_folder_id is None
    watches = [w for w in repo.list_watches() if w["provider"] == provider]
    folders = repo.list_folders(provider)
    if only_folder_id is not None:
        folders = [f for f in folders if f["id"] == only_folder_id]
        watches = [w for w in watches if w["folder_id"] == only_folder_id]

    per_cartella: dict = {}
    sciolte = []
    for w in watches:
        fid = w["folder_id"] if "folder_id" in w.keys() else None
        if fid is None:
            sciolte.append(_carta(w))
        else:
            per_cartella.setdefault(fid, []).append(_carta(w))

    contenuto = ["cartelle", "carte"]
    dati: dict = {
        "formato": FORMATO,
        "versione": VERSIONE,
        "esportato": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "app": app_version,
        "cartelle": [{
            "nome": f["name"],
            "base": bool(f["is_deck"]) if "is_deck" in f.keys() else False,
            "aperta": bool(f["expanded"]),
            "filtri": _filtri(f["filters"] if "filters" in f.keys() else ""),
            "carte": per_cartella.get(f["id"], []),
        } for f in folders],
        "carte_sciolte": sciolte,
    }
    if only_folder_id is None:
        # Le preferenze hanno senso in un backup, non in una condivisione:
        # ricevere un mazzo non deve cambiare i filtri di chi lo riceve.
        dati["preferenze"] = {
            "filtri_predefiniti": _filtri(repo.get_setting("filters", "") or ""),
            "visualizzazione": _filtri(repo.get_setting("display", "") or ""),
            "ordinamento": repo.get_setting("sort", "") or "",
        }
        contenuto.append("preferenze")
    if include_history:
        refs = {c["ref_id"] for c in sciolte} | {
            c["ref_id"] for lista in per_cartella.values() for c in lista}
        dati["storico"] = [{
            "ref_id": str(r["ref_id"]),
            "prezzo": r["price"],
            "valuta": r["currency"],
            "quando": r["captured_at"],
            "filtri_chiave": r["filters_key"] if "filters_key" in r.keys() else "",
        } for r in repo.all_history(provider) if str(r["ref_id"]) in refs]
        contenuto.append("storico")
    dati["contenuto"] = contenuto
    return dati


def write_file(path, dati: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(dati, fh, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# Importazione
# --------------------------------------------------------------------------- #
class TransferError(Exception):
    """File non utilizzabile, con un motivo da mostrare all'utente."""


def read_file(path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            dati = json.load(fh)
    except (OSError, ValueError) as exc:
        raise TransferError(f"File illeggibile: {exc}") from exc
    if not isinstance(dati, dict) or dati.get("formato") != FORMATO:
        raise TransferError("Non è un file di watchlist di YGO Toolbox.")
    versione = dati.get("versione")
    if not isinstance(versione, int) or versione > VERSIONE:
        raise TransferError(
            f"Il file è della versione {versione}, questa app arriva alla {VERSIONE}: "
            "aggiorna l'app.")
    return dati


def describe(dati: dict) -> str:
    """Una riga che dice cosa c'è nel file, da mostrare PRIMA di importarlo."""
    cartelle = dati.get("cartelle") or []
    carte = len(dati.get("carte_sciolte") or [])
    for c in cartelle:
        carte += len(c.get("carte") or [])
    pezzi = [f"{carte} carte", f"{len(cartelle)} cartelle/basi"]
    if dati.get("storico"):
        pezzi.append(f"{len(dati['storico'])} punti di storico")
    if dati.get("preferenze"):
        pezzi.append("preferenze")
    return " · ".join(pezzi)


def _json_or_empty(oggetto) -> str:
    return json.dumps(oggetto) if oggetto else ""


def import_data(repo, provider: str, dati: dict, replace: bool = False) -> dict:
    """Scrive nel DB il contenuto del file. Ritorna un resoconto.

    `replace=False` (aggiungi): non si tocca ciò che c'è; le carte già presenti
    vengono AGGIORNATE con quanto dice il file (copie, soglia, filtri) e
    spostate nella sua cartella — il file è ciò che hai chiesto di importare,
    ignorarne dei pezzi in silenzio sarebbe peggio.
    `replace=True` (sostituisci): watchlist e cartelle vengono svuotate prima.
    Le preferenze si applicano SOLO sostituendo: ricevere un mazzo non deve
    cambiare i filtri di chi lo riceve."""
    resoconto = {"aggiunte": 0, "aggiornate": 0, "cartelle": 0, "storico": 0}

    if replace:
        for w in [w for w in repo.list_watches() if w["provider"] == provider]:
            repo.remove_watch(w["id"])
        for f in repo.list_folders(provider):
            repo.delete_folder(f["id"])

    esistenti = {str(w["ref_id"]): w for w in repo.list_watches()
                 if w["provider"] == provider}
    per_nome = {f["name"]: f["id"] for f in repo.list_folders(provider)}

    def metti_carta(carta: dict, folder_id) -> None:
        ref = str(carta.get("ref_id") or "").strip()
        if not ref:
            return
        filtri = _json_or_empty(carta.get("filtri"))
        copie = max(1, int(carta.get("copie") or 1))
        soglia = float(carta.get("soglia") or 0.0)
        vecchia = esistenti.get(ref)
        if vecchia is None:
            repo.add_watch(provider, ref, carta.get("nome") or ref,
                           carta.get("dettaglio") or "", soglia, filtri, copie)
            nuova = [w for w in repo.list_watches()
                     if w["provider"] == provider and str(w["ref_id"]) == ref]
            if not nuova:
                return
            esistenti[ref] = nuova[0]
            resoconto["aggiunte"] += 1
        else:
            repo.set_watch_copies(vecchia["id"], copie)
            repo.set_watch_filters(vecchia["id"], filtri)
            repo.set_watch_threshold(vecchia["id"], soglia)
            resoconto["aggiornate"] += 1
        if folder_id is not None:
            repo.set_watch_folder(esistenti[ref]["id"], folder_id)

    for cartella in dati.get("cartelle") or []:
        nome = (cartella.get("nome") or "").strip() or "Importata"
        fid = per_nome.get(nome)
        if fid is None:
            fid = repo.add_folder(provider, nome,
                                  _json_or_empty(cartella.get("filtri")),
                                  bool(cartella.get("base")))
            per_nome[nome] = fid
            resoconto["cartelle"] += 1
        for carta in cartella.get("carte") or []:
            metti_carta(carta, fid)
    for carta in dati.get("carte_sciolte") or []:
        metti_carta(carta, None)

    # Storico: solo i punti di carte che ora esistono, senza duplicare quelli
    # già presenti (importare due volte lo stesso file non deve gonfiarlo).
    if dati.get("storico"):
        gia = {(str(r["ref_id"]), r["captured_at"], r["price"])
               for r in repo.all_history(provider)}
        for punto in dati["storico"]:
            ref = str(punto.get("ref_id") or "")
            if ref not in esistenti:
                continue
            chiave = (ref, punto.get("quando"), punto.get("prezzo"))
            if chiave in gia:
                continue
            repo.add_history_row(provider, ref, punto.get("prezzo"),
                                 punto.get("valuta") or "EUR",
                                 punto.get("filtri_chiave") or "",
                                 punto.get("quando"))
            gia.add(chiave)
            resoconto["storico"] += 1

    prefs = dati.get("preferenze") or {}
    if replace and prefs:
        if prefs.get("filtri_predefiniti"):
            repo.set_setting("filters", json.dumps(prefs["filtri_predefiniti"]))
        if prefs.get("visualizzazione"):
            repo.set_setting("display", json.dumps(prefs["visualizzazione"]))
        if prefs.get("ordinamento"):
            repo.set_setting("sort", prefs["ordinamento"])
    return resoconto
