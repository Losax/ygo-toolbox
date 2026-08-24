"""Lettura dei file `.ydk` — il formato con cui si scambiano i mazzi.

È un formato a righe, senza virgolette né parentesi: una riga per COPIA, con
il *passcode* della carta (il numero stampato sulla carta stessa). Le sezioni
si aprono con una riga direttiva:

    #created by ...      ← commento libero, si ignora
    #main
    14558127             ← tre righe uguali = tre copie
    14558127
    14558127
    #extra
    27572350
    !side                ← il side usa `!`, non `#`: è così nel formato
    34267821

Scelte fatte qui, e il perché:

- **Le tre sezioni si sommano.** Una base serve a sapere quante copie
  *possedere*: se una carta sta 2 volte nel main e 1 nel side, servono 3
  copie. Nel file d'esempio capita davvero (Mulcharmy Purulia). Le quantità
  per sezione restano comunque disponibili, per poterle mostrare.
- **Nessuna rete, nessun database, nessun Qt.** Solo testo → dati, così il
  test lo prova senza interfaccia.
- **Quello che non si capisce non si butta via in silenzio**: le righe non
  riconosciute finiscono in `ignored` e l'interfaccia le mostra. Un passcode
  che non esiste è un dato mancante, non uno zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# `#main`/`#extra` col cancelletto, `!side` con l'esclamativo: è l'asimmetria
# del formato, non un errore. Alcuni editor scrivono `#side`: si accetta.
_SECTIONS = {
    "main": "main",
    "extra": "extra",
    "side": "side",
}

MAX_COPIES = 99      # come nel dialogo della base


@dataclass
class YdkCard:
    """Una carta del file, con le copie divise per sezione."""

    passcode: int
    main: int = 0
    extra: int = 0
    side: int = 0

    @property
    def total(self) -> int:
        """Copie da possedere: le sezioni si sommano (vedi il modulo)."""
        return min(MAX_COPIES, self.main + self.extra + self.side)

    def sections_label(self) -> str:
        """"2 main + 1 side" — per spiegare da dove esce il totale.

        Si mostra SOLO quando la carta sta in più di una sezione: per una
        carta normale il numero delle copie basta e avanza.
        """
        parti = [f"{n} {nome}" for nome, n in
                 (("main", self.main), ("extra", self.extra), ("side", self.side)) if n]
        return " + ".join(parti)

    @property
    def split(self) -> bool:
        """La carta compare in più di una sezione."""
        return sum(1 for n in (self.main, self.extra, self.side) if n) > 1


@dataclass
class YdkDeck:
    cards: list[YdkCard] = field(default_factory=list)
    #: righe che non erano né direttive né passcode (con il numero di riga)
    ignored: list[tuple[int, str]] = field(default_factory=list)

    @property
    def total_copies(self) -> int:
        return sum(c.total for c in self.cards)


def decode(data: bytes) -> str:
    """Testo di un `.ydk`, comunque sia stato salvato.

    I file girano fra editor diversi (YGOPro, EDOPro, siti web): si vedono
    BOM e code page a caso. Conta solo poter leggere le cifre, quindi si
    ripiega su latin-1, che non fallisce mai, invece di sollevare.
    """
    for codec in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return data.decode(codec)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def parse(text: str) -> YdkDeck:
    """Testo di un `.ydk` → carte con le copie, in ordine di apparizione.

    L'ordine è quello del file, non alfabetico: chi ha costruito il mazzo di
    solito mette i mostri principali in cima, e ritrovarlo aiuta a
    riconoscerlo.
    """
    deck = YdkDeck()
    per_codice: dict[int, YdkCard] = {}
    # Se il file comincia con i numeri senza dichiarare `#main`, quelle copie
    # non si perdono: stanno nel mazzo principale.
    sezione = "main"

    for numero, riga in enumerate(text.splitlines(), start=1):
        riga = riga.strip()
        if not riga:
            continue
        if riga[0] in "#!":
            nome = riga[1:].strip().lower()
            if nome in _SECTIONS:
                sezione = _SECTIONS[nome]
            # ogni altra direttiva (`#created by ...`) è un commento: si ignora
            continue
        if riga.isdigit():
            codice = int(riga)          # normalizza gli zeri davanti
            carta = per_codice.get(codice)
            if carta is None:
                carta = YdkCard(passcode=codice)
                per_codice[codice] = carta
                deck.cards.append(carta)
            setattr(carta, sezione, getattr(carta, sezione) + 1)
            continue
        deck.ignored.append((numero, riga))

    return deck


def parse_file(path) -> YdkDeck:
    """Come `parse`, leggendo da disco (in binario: vedi `decode`)."""
    with open(path, "rb") as fh:
        return parse(decode(fh.read()))
