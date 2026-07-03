"""Contratto comune per le fonti di prezzo.

Un "provider" sa fare due cose:
- cercare carte per nome  -> restituisce dei CardRef (riferimenti);
- dato un riferimento, trovare il prezzo più basso disponibile.

Cambiando provider (CardTrader, in futuro CardMarket, ecc.) il resto del
modulo Market Watch non cambia.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass


@dataclass
class CardRef:
    """Riferimento a una carta specifico del provider."""
    id: str          # per CardTrader = blueprint_id
    name: str
    detail: str = ""        # es. espansione / rarità
    image_url: str = ""     # URL assoluto dell'immagine (per l'anteprima)


@dataclass
class ListingFilters:
    """Criteri per decidere quali annunci contano nel calcolo del prezzo.

    Valori vuoti / False = nessun vincolo su quel criterio."""
    language: str = ""          # codice lingua, es. "it"/"en" ("" = qualsiasi)
    min_condition: str = ""     # condizione minima accettata ("" = qualsiasi)
    first_edition_only: bool = False
    zero_only: bool = False     # solo annunci acquistabili con CardTrader Zero
    exclude_graded: bool = False
    pro_only: bool = False      # solo venditori "pro"
    american_only: bool = False  # euristica "stampa americana" (vedi cardtrader._listing_matches)

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "min_condition": self.min_condition,
            "first_edition_only": self.first_edition_only,
            "zero_only": self.zero_only,
            "exclude_graded": self.exclude_graded,
            "pro_only": self.pro_only,
            "american_only": self.american_only,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "ListingFilters":
        data = data or {}
        return cls(
            language=data.get("language", ""),
            min_condition=data.get("min_condition", ""),
            first_edition_only=bool(data.get("first_edition_only", False)),
            zero_only=bool(data.get("zero_only", False)),
            exclude_graded=bool(data.get("exclude_graded", False)),
            pro_only=bool(data.get("pro_only", False)),
            american_only=bool(data.get("american_only", False)),
        )

    def active(self) -> bool:
        """True se almeno un filtro è impostato."""
        return any([
            self.language, self.min_condition, self.first_edition_only,
            self.zero_only, self.exclude_graded, self.pro_only, self.american_only,
        ])


@dataclass
class PriceQuote:
    """Una quotazione di prezzo trovata sul marketplace (annuncio più basso)."""
    amount: float
    currency: str
    detail: str = ""        # riassunto: condizione · lingua · 1ª ed. · Zero
    seller: str = ""        # username venditore
    seller_type: str = ""   # "pro" / "normal"
    country: str = ""       # es. "IT", "US"
    comment: str = ""       # nota del venditore (description)
    quantity: int = 0
    # campi strutturati dell'annuncio scelto (per colonne separate in Panoramica)
    condition: str = ""     # es. "Near Mint"
    language: str = ""      # codice lingua maiuscolo, es. "EN"
    first_edition: bool = False
    zero: bool = False      # acquistabile con CardTrader Zero

    def to_dict(self) -> dict:
        """Per la persistenza (mw_last_quote): JSON round-trip con from_dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "PriceQuote":
        data = data or {}
        return cls(
            amount=float(data.get("amount", 0.0)),
            currency=data.get("currency", "EUR"),
            detail=data.get("detail", ""),
            seller=data.get("seller", ""),
            seller_type=data.get("seller_type", ""),
            country=data.get("country", ""),
            comment=data.get("comment", ""),
            quantity=int(data.get("quantity", 0) or 0),
            condition=data.get("condition", ""),
            language=data.get("language", ""),
            first_edition=bool(data.get("first_edition", False)),
            zero=bool(data.get("zero", False)),
        )


class PriceProvider(ABC):
    name: str = ""

    @abstractmethod
    def search_cards(self, query: str) -> list[CardRef]:
        ...

    @abstractmethod
    def lowest_price(self, card_id: str) -> PriceQuote | None:
        ...
