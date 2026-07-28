"""Traduzioni dell'interfaccia (leggere: dizionario, niente file .qm).

L'ITALIANO è la lingua di sviluppo: le stringhe italiane sono le CHIAVI e
anche il fallback (una chiave non tradotta resta in italiano, mai vuota).
La lingua scelta sta in ~/.ygo_toolbox/language.txt e si applica al
riavvio (la UI è costruita una volta all'avvio).

Uso: ``from core.i18n import tr`` e poi ``tr("Testo italiano")`` — per i
template ``tr("Catalogo · {n} carte").format(n=...)``.
"""
from __future__ import annotations

from pathlib import Path

LANG_FILE = Path.home() / ".ygo_toolbox" / "language.txt"
LANGUAGES = [("Italiano", "it"), ("English", "en")]

_current = "it"


def load_language() -> None:
    """Da chiamare all'avvio, PRIMA di costruire la UI."""
    global _current
    try:
        code = LANG_FILE.read_text(encoding="utf-8").strip().lower()
        if code in {c for _, c in LANGUAGES}:
            _current = code
    except OSError:
        pass


def set_language(code: str) -> None:
    global _current
    _current = code
    try:
        LANG_FILE.parent.mkdir(parents=True, exist_ok=True)
        LANG_FILE.write_text(code, encoding="utf-8")
    except OSError:
        pass


def current() -> str:
    return _current


def tr(text: str) -> str:
    if _current == "it":
        return text
    return _TRANSLATIONS.get(_current, {}).get(text, text)


_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        # header / chips
        "Prezzo più basso su CardTrader": "Lowest price on CardTrader",
        "● Token attivo": "● Token active",
        "○ Token mancante": "○ Token missing",
        "Catalogo · {n} carte": "Catalog · {n} cards",
        "Catalogo vuoto": "Catalog empty",
        "Token CardTrader (imposta/cambia)": "CardTrader token (set/change)",
        "Sincronizza il catalogo Yu-Gi-Oh! (~4-5 minuti, una tantum)":
            "Sync the Yu-Gi-Oh! catalog (~4-5 minutes, one-time)",
        "Opzioni di visualizzazione della watchlist": "Watchlist display options",
        "Panoramica: nasconde la ricerca e allarga la watchlist":
            "Overview: hides the search and expands the watchlist",
        "Torna alla ricerca": "Back to search",
        # ricerca
        "🔍  Scrivi il nome della carta (in inglese)…": "🔍  Type the card name…",
        "Sincronizza prima il catalogo per cercare le carte":
            "Sync the catalog first to search cards",
        "Filtri degli annunci (lingua, condizione, Zero, …)":
            "Listing filters (language, condition, Zero, …)",
        "Nessuna carta selezionata": "No card selected",
        "Avvisa al calo di": "Alert on drop of",
        "Avvisa quando il prezzo cala almeno di questa percentuale (0 = qualsiasi calo)":
            "Alert when the price drops at least this much (0 = any drop)",
        "Aggiungi alla watchlist": "Add to watchlist",
        "Nessuna\nanteprima": "No\npreview",
        "Caricamento…": "Loading…",
        "Immagine non\ndisponibile": "Image not\navailable",
        # tabella
        "Nome": "Name", "Rarità": "Rarity", "Set": "Set",
        "Condizione": "Condition", "Lingua": "Language",
        "1ª ed.": "1st ed.", "Zero": "Zero", "Prezzo": "Price",
        "Var.": "Chg.", "Soglia": "Threshold", "Controllo": "Checked",
        "Venditore": "Seller", "Commenti": "Comments", "Q.tà": "Qty",
        "Cond.": "Cond.", "Ling.": "Lang.", "Vend.": "Seller", "Comm.": "Comm.",
        "Nessuna copia": "No copies",
        "Nessun annuncio soddisfa i filtri impostati (Opzioni).":
            "No listing matches the current filters.",
        "Filtri di questa carta": "Filters for this card",
        " (personalizzati)": " (custom)",
        "Rimuovi dalla watchlist": "Remove from watchlist",
        "Venditore professionale (PRO)": "Professional seller (PRO)",
        # cartelle
        "{n} carte": "{n} cards", "1 carta": "1 card", "vuota": "empty",
        "Clic per aprire/chiudere · trascina qui le carte per spostarle dentro":
            "Click to open/close · drag cards here to move them inside",
        "Rinomina cartella": "Rename folder",
        "Elimina cartella (le carte tornano fuori)":
            "Delete folder (cards move back out)",
        "Sposta nella cartella": "Move to folder",
        "(Fuori dalle cartelle)": "(Out of folders)",
        "Nuova cartella…": "New folder…",
        "Rinomina cartella…": "Rename folder…",
        "Nuova cartella": "New folder",
        "Nome della cartella:": "Folder name:",
        "Nuovo nome:": "New name:",
        # footer / stati
        "Controlla ora": "Check now",
        "Auto ogni": "Auto every",
        " min": " min",
        "Pronto.": "Ready.",
        "Sincronizzazione catalogo… (può richiedere qualche minuto)":
            "Syncing catalog… (may take a few minutes)",
        "Sincronizzazione catalogo… espansione {done}/{total}":
            "Syncing catalog… set {done}/{total}",
        "Catalogo aggiornato: {n} carte.": "Catalog updated: {n} cards.",
        "Token salvato.": "Token saved.",
        "Token mancante": "Token missing",
        "Imposta prima il token CardTrader.": "Set the CardTrader token first.",
        "Token CardTrader": "CardTrader token",
        "Incolla qui il tuo token (Bearer) di CardTrader:":
            "Paste your CardTrader (Bearer) token here:",
        "Filtri aggiornati: ricontrollo i prezzi…": "Filters updated: re-checking prices…",
        "Filtri rimossi.": "Filters cleared.",
        "Visualizzazione aggiornata.": "Display updated.",
        "Controllo prezzi su CardTrader…": "Checking prices on CardTrader…",
        "Controllo automatico all'avvio…": "Automatic check on startup…",
        "Ultimo controllo: {when}.": "Last check: {when}.",
        "Watchlist vuota.": "Watchlist is empty.",
        "Errore: {msg}": "Error: {msg}",
        "Aggiunta: {name}. Recupero prezzo iniziale…":
            "Added: {name}. Fetching initial price…",
        "Filtri aggiornati per {name}. Ricontrollo…":
            "Filters updated for {name}. Re-checking…",
        "Lingua salvata: riavvia l'app per applicarla.":
            "Language saved: restart the app to apply it.",
        # notifiche
        "Nuovo prezzo più basso su CardTrader": "New lowest price on CardTrader",
        # dialogo filtri
        "Filtri degli annunci": "Listing filters",
        "Considera solo gli annunci che rispettano questi criteri quando "
        "calcolo il prezzo più basso da seguire.":
            "Only consider listings matching these criteria when computing "
            "the lowest price to track.",
        "Usa i filtri globali": "Use global filters",
        "Condizione minima": "Minimum condition",
        "Qualsiasi": "Any",
        "Italiano": "Italian", "Inglese": "English", "Tedesco": "German",
        "Francese": "French", "Spagnolo": "Spanish", "Portoghese": "Portuguese",
        "Giapponese": "Japanese", "Coreano": "Korean", "Cinese": "Chinese",
        "Solo prima edizione": "First edition only",
        "Solo acquistabili con CardTrader Zero": "CardTrader Zero only",
        "Escludi carte graded": "Exclude graded cards",
        "Solo venditori PRO": "PRO sellers only",
        "Solo stampa americana (USA)": "American (USA) print only",
        "Criterio non ufficiale: carta in INGLESE e (venditore americano "
        "oppure commento che cita USA/American). Forza la lingua su Inglese.":
            "Unofficial heuristic: ENGLISH card and (American seller or a "
            "comment mentioning USA/American). Forces language to English.",
        "Filtri · {name}": "Filters · {name}",
        # dialogo visualizzazione
        "Visualizzazione della watchlist": "Watchlist display",
        "Come mostrare rarità e set nelle righe della watchlist.":
            "How to show rarity and set in the watchlist rows.",
        "Rarità come icona (badge colorato)": "Rarity as icon (colored badge)",
        "Mostra la sigla della rarità (UR, ScR, QCSR, …) su un badge "
        "colorato come la foil; il nome completo resta nel tooltip.":
            "Shows the rarity code (UR, ScR, QCSR, …) on a badge colored "
            "like its foil; the full name stays in the tooltip.",
        "Set come codice (es. LOB) invece del nome": "Set as code (e.g. LOB) instead of name",
        "Lingua dell'app": "App language",
        "Animazioni dell'interfaccia": "Interface animations",
        "Dissolvenze, scivolamenti e transizioni; disattivale se preferisci "
        "un'interfaccia immediata.":
            "Fades, slides and transitions; turn them off if you prefer an "
            "instant interface.",
        "La nuova lingua si applica al prossimo avvio.":
            "The new language applies at the next startup.",
        # benvenuto (primo avvio)
        "Benvenuto in YGO Toolbox!": "Welcome to YGO Toolbox!",
        "Per iniziare servono due passi:\n\n"
        "1.  Imposta il tuo token CardTrader — pulsante con la CHIAVE in "
        "alto a destra. Il token si crea gratis su cardtrader.com, nella "
        "sezione API del tuo profilo.\n\n"
        "2.  Sincronizza il catalogo — pulsante con le FRECCE circolari "
        "(~5 minuti, serve solo la prima volta).\n\n"
        "Poi cerca una carta, scegli la soglia di avviso e aggiungila alla "
        "watchlist: ai prezzi pensa l'app.":
            "Two steps to get started:\n\n"
            "1.  Set your CardTrader token — the KEY button at the top right. "
            "You can create one for free on cardtrader.com, in the API "
            "section of your profile.\n\n"
            "2.  Sync the catalog — the circular ARROWS button (~5 minutes, "
            "first time only).\n\n"
            "Then search a card, pick an alert threshold and add it to the "
            "watchlist: the app takes care of the prices.",
    },
}
