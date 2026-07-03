"""Provider per l'API ufficiale di CardTrader (v2).

Documentazione: https://api.cardtrader.com/ (richiede un token Bearer che
ottieni dalla tua area sviluppatori su CardTrader).

VERIFICATO DAL VIVO (token reale, 2026-06-29) — le forme reali dell'API:
- game Yu-Gi-Oh! = id 4 (trovato per nome in /games, che torna un dict);
- /marketplace/products torna un dict indicizzato per blueprint_id (stringa),
  il cui valore è la lista degli annunci; il parser gestisce comunque anche
  la forma a lista pura, per robustezza;
- ogni annuncio contiene il prezzo in ENTRAMBE le forme: nidificata
  {"price": {"cents": .., "currency": ..}} e piatta "price_cents" /
  "price_currency"; il parser preferisce la prima;
- ogni blueprint ha un campo "version" che per le carte è la RARITÀ della
  stampa (es. "Secret Rare", "Starlight Rare"); /blueprints è paginato a 50
  elementi per pagina (vedi _all_blueprints).

Il prezzo più basso si ottiene da /marketplace/products?blueprint_id=ID,
prendendo il minimo tra tutti gli annunci attivi.
"""
from __future__ import annotations

import re
import time
from typing import Callable

import requests

from .base import CardRef, ListingFilters, PriceProvider, PriceQuote

# Scala delle condizioni CardTrader, dalla migliore alla peggiore.
CONDITIONS = ["Mint", "Near Mint", "Excellent", "Good", "Light Played", "Played", "Poor"]


def _condition_rank(name: str) -> int:
    try:
        return CONDITIONS.index(name)
    except ValueError:
        return len(CONDITIONS)  # sconosciuta = trattata come peggiore

API_BASE = "https://api.cardtrader.com/api/v2"
IMAGE_HOST = "https://www.cardtrader.com"  # le immagini blueprint hanno URL relativi a questo host
TIMEOUT = 20
BLUEPRINTS_PAGE_SIZE = 50  # /blueprints è paginato: max 50 elementi per pagina
BLUEPRINTS_MAX_PAGES = 200  # paracadute anti-loop (200*50 = 10.000 carte/espansione)


class CardTraderError(Exception):
    """Errore parlante da mostrare all'utente."""


# --------------------------------------------------------------------------- #
# Client HTTP
# --------------------------------------------------------------------------- #
class CardTraderClient:
    def __init__(self, token: str, session: requests.Session | None = None) -> None:
        self.token = token.strip()
        self.session = session or requests.Session()

    def _get(self, path: str, params: dict | None = None) -> object:
        url = f"{API_BASE}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        try:
            resp = self.session.get(url, params=params, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise CardTraderError(f"Errore di rete: {exc}") from exc

        if resp.status_code == 401:
            raise CardTraderError("Token non valido o scaduto (401). Reimposta il token.")
        if resp.status_code == 429:
            raise CardTraderError("Troppe richieste (429). Riprova tra poco.")
        if resp.status_code != 200:
            raise CardTraderError(f"Risposta inattesa dall'API ({resp.status_code}).")
        return resp.json()

    def games(self) -> object:
        return self._get("/games")

    def expansions(self) -> object:
        return self._get("/expansions")

    def blueprints(self, expansion_id, page: int | None = None) -> object:
        params: dict = {"expansion_id": expansion_id}
        if page is not None:
            params["page"] = page
        return self._get("/blueprints", params=params)

    def marketplace_products(self, blueprint_id) -> object:
        return self._get("/marketplace/products", params={"blueprint_id": blueprint_id})


# --------------------------------------------------------------------------- #
# Helpers di parsing (difensivi)
# --------------------------------------------------------------------------- #
def _as_list(payload: object) -> list:
    """Normalizza payload che possono arrivare come lista o come dict 'array'."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        # alcune risposte sono {"array": [...]} o un dict di liste
        if "array" in payload and isinstance(payload["array"], list):
            return payload["array"]
        return list(payload.values())
    return []


def _extract_price(product: dict) -> tuple[float, str] | None:
    price = product.get("price")
    if isinstance(price, dict):
        cents = price.get("cents")
        currency = price.get("currency", "EUR")
    else:
        cents = product.get("price_cents")
        currency = product.get("price_currency", "EUR")
    if cents is None:
        return None
    try:
        return float(cents) / 100.0, currency
    except (TypeError, ValueError):
        return None


# Riconoscimento "stampa americana" nei commenti del venditore.
# Confini di parola per non confondere parole italiane (es. "usato" NON è "usa").
# Coperti: USA / U.S.A. / American(o/a) / North American / NA print / US print.
_AMERICAN_RE = re.compile(
    r"\b(usa|u\.s\.a\.?|american[oa]?|north[\s\-]?american|(?:na|us)[\s\-]?print)\b",
    re.IGNORECASE,
)


def _is_american_print(product: dict) -> bool:
    """Euristica (non ufficiale) per la stampa USA di una carta inglese.

    Prerequisito: lingua INGLESE. Poi basta uno dei due segnali:
    - il venditore è americano (country_code == 'US');
    - il commento dell'annuncio cita USA/American.
    Una carta non inglese non può essere di stampa americana."""
    props = product.get("properties_hash") or {}
    if (props.get("yugioh_language") or "").lower() != "en":
        return False
    country = ((product.get("user") or {}).get("country_code") or "").upper()
    if country == "US":
        return True
    return bool(_AMERICAN_RE.search(product.get("description") or ""))


def _listing_matches(product: dict, f: ListingFilters) -> bool:
    """True se l'annuncio soddisfa i filtri impostati."""
    props = product.get("properties_hash") or {}
    user = product.get("user") or {}
    if f.language and (props.get("yugioh_language") or "").lower() != f.language.lower():
        return False
    if f.min_condition and _condition_rank(props.get("condition") or "") > _condition_rank(f.min_condition):
        return False
    if f.first_edition_only and not props.get("first_edition"):
        return False
    if f.zero_only and not user.get("can_sell_via_hub"):
        return False
    if f.exclude_graded and product.get("graded"):
        return False
    if f.pro_only and user.get("user_type") != "pro":
        return False
    if f.american_only and not _is_american_print(product):
        return False
    return True


def _listing_detail(product: dict) -> str:
    """Riassunto leggibile dell'annuncio scelto (condizione · lingua · Zero)."""
    props = product.get("properties_hash") or {}
    parts = []
    if props.get("condition"):
        parts.append(props["condition"])
    lang = props.get("yugioh_language")
    if lang:
        parts.append(str(lang).upper())
    if props.get("first_edition"):
        parts.append("1ª ed.")
    if (product.get("user") or {}).get("can_sell_via_hub"):
        parts.append("Zero")
    return " · ".join(parts)


def _products_list(payload: object, blueprint_id: str) -> list:
    """/marketplace/products può tornare una lista o un dict per blueprint."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        by_id = payload.get(str(blueprint_id))
        if isinstance(by_id, list):
            return by_id
        # fallback: prima lista trovata
        for value in payload.values():
            if isinstance(value, list):
                return value
    return []


def _find_yugioh_game(games_payload: object) -> dict | None:
    for game in _as_list(games_payload):
        if not isinstance(game, dict):
            continue
        label = f"{game.get('name', '')} {game.get('display_name', '')}".lower()
        if "yu-gi-oh" in label or "yugioh" in label:
            return game
    return None


def _blueprint_image_url(blueprint: dict) -> str:
    """URL assoluto dell'immagine di un blueprint (variante 'show', medio-grande).

    La risposta espone url relativi in image.{url, show, preview, social}; uso
    'show' (dimensione carta) con fallback all'url base. Stringa vuota se assente."""
    img = blueprint.get("image") or {}
    rel = (img.get("show") or {}).get("url") or img.get("url") or ""
    return f"{IMAGE_HOST}{rel}" if rel else ""


def _all_blueprints(client: CardTraderClient, expansion_id) -> list[dict]:
    """Tutti i blueprint di una espansione, seguendo la paginazione (50/pagina).

    /blueprints torna max 50 elementi per pagina: senza scorrere le pagine le
    espansioni grandi (la maggior parte dei set) verrebbero troncate. Mi fermo
    quando una pagina è incompleta/vuota, oppure quando non porta id nuovi
    (difesa nel caso l'API ignorasse il parametro `page`)."""
    seen: set = set()
    out: list[dict] = []
    for page in range(1, BLUEPRINTS_MAX_PAGES + 1):
        batch = _as_list(client.blueprints(expansion_id, page=page))
        new = 0
        for blueprint in batch:
            if not isinstance(blueprint, dict):
                continue
            bid = blueprint.get("id")
            if bid in seen:
                continue
            seen.add(bid)
            out.append(blueprint)
            new += 1
        if new == 0 or len(batch) < BLUEPRINTS_PAGE_SIZE:
            break  # ultima pagina (o l'API non pagina): fine
        time.sleep(0.1)  # gentilezza verso i rate limit
    return out


def fetch_catalog(client: CardTraderClient, progress: Callable[[int, int], None] | None = None) -> list[tuple]:
    """Scarica il catalogo Yu-Gi-Oh! (blueprint = stampa specifica di una carta).

    Ritorna righe (ref_id, name, detail, image_url, set_code), dove detail =
    "<rarità> · <espansione>" (es. "Secret Rare · Blazing Dominion"), image_url
    è l'URL dell'anteprima e set_code è il codice del set (es. "ROTA").
    È una operazione "una tantum" (poi si aggiorna ogni tanto), perciò può
    richiedere qualche minuto la prima volta.
    """
    game = _find_yugioh_game(client.games())
    if game is None:
        raise CardTraderError("Gioco Yu-Gi-Oh! non trovato nella risposta di /games.")
    game_id = game["id"]

    expansions = [
        exp for exp in _as_list(client.expansions())
        if isinstance(exp, dict) and exp.get("game_id") == game_id
    ]
    total = len(expansions)
    rows: list[tuple] = []
    for index, exp in enumerate(expansions, start=1):
        exp_name = exp.get("name", "")
        set_code = (exp.get("code") or "").upper()  # es. "rota" -> "ROTA"
        for blueprint in _all_blueprints(client, exp["id"]):
            # Su CardTrader il campo 'version' del blueprint è la rarità della
            # stampa (es. "Secret Rare", "Starlight Rare"); può mancare per i
            # prodotti non-carta (playmat, sleeve, …).
            rarity = blueprint.get("version") or ""
            detail = f"{rarity} · {exp_name}" if rarity else exp_name
            rows.append((str(blueprint["id"]), blueprint.get("name", ""), detail,
                         _blueprint_image_url(blueprint), set_code))
        if progress is not None:
            progress(index, total)
        time.sleep(0.1)  # gentilezza verso i rate limit
    return rows


# --------------------------------------------------------------------------- #
# Provider
# --------------------------------------------------------------------------- #
class CardTraderProvider(PriceProvider):
    name = "cardtrader"

    def __init__(self, client: CardTraderClient, repo, filters: ListingFilters | None = None) -> None:
        self.client = client
        self.repo = repo  # per la ricerca sul catalogo in cache
        self.filters = filters or ListingFilters()

    def search_cards(self, query: str) -> list[CardRef]:
        rows = self.repo.search_catalog(self.name, query)
        return [CardRef(id=str(r["ref_id"]), name=r["name"], detail=r["detail"] or "") for r in rows]

    def lowest_price(self, card_id: str, filters: ListingFilters | None = None) -> PriceQuote | None:
        f = filters if filters is not None else self.filters
        payload = self.client.marketplace_products(int(card_id))
        products = _products_list(payload, card_id)
        best: PriceQuote | None = None
        best_product: dict | None = None
        for product in products:
            if not isinstance(product, dict):
                continue
            if not _listing_matches(product, f):
                continue  # scartato dai filtri (globali o della singola carta)
            parsed = _extract_price(product)
            if parsed is None:
                continue
            amount, currency = parsed
            if best is None or amount < best.amount:
                best = PriceQuote(amount=amount, currency=currency, detail=_listing_detail(product))
                best_product = product
        if best is not None and best_product is not None:  # info sull'annuncio scelto
            user = best_product.get("user") or {}
            props = best_product.get("properties_hash") or {}
            best.seller = user.get("username") or ""
            best.seller_type = user.get("user_type") or ""
            best.country = (user.get("country_code") or "").upper()
            best.comment = best_product.get("description") or ""
            best.quantity = best_product.get("quantity") or 0
            # campi separati (colonne Condizione / Lingua / 1ª ed. / Zero)
            best.condition = props.get("condition") or ""
            best.language = (props.get("yugioh_language") or "").upper()
            best.first_edition = bool(props.get("first_edition"))
            best.zero = bool(user.get("can_sell_via_hub"))
        return best

    def card_name(self, card_id: str) -> str | None:
        return self.repo.catalog_name(self.name, card_id)
