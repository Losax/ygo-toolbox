"""Come si scrivono cifre e date nella Collezione.

Un file suo, minuscolo, perché lo usano sia la tabella sia la pagina del
raccoglitore, e perché la regola che contiene è una regola del progetto, non un
dettaglio di stile: **un dato che non c'è si scrive "—", mai zero**. Averla in
un posto solo vuol dire che non può sfuggire in uno dei due.
"""
from __future__ import annotations

from datetime import datetime

from core.i18n import tr


def soldi(valore, valuta: str = "EUR") -> str:
    """Una cifra, o "—" se il dato non c'è. Mai uno zero al posto del vuoto."""
    if valore is None:
        return "—"
    simbolo = "€" if (valuta or "EUR").upper() == "EUR" else (valuta or "")
    return f"{float(valore):.2f} {simbolo}".strip()


def quando(iso: str) -> str:
    """Data ISO → "14/09/2026 18:32"; vuota → "mai"."""
    if not iso:
        return tr("mai")
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso
