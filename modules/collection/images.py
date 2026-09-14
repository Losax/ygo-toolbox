"""Miniature delle carte della collezione, dalla cache su DISCO.

Da dove arrivano le immagini, e perché non da CardTrader. Le stampe della
collezione vengono dal catalogo dei prezzi, che per ognuna ha anche un'anteprima
sul CDN di CardTrader — ma quel CDN sta dietro Cloudflare e risponde 403 alle
raffiche (è il motivo per cui il Market Watch scarica le miniature una per volta
e si ricorda quelle perse). Una collezione si guarda a pagine intere di nove
carte, quindi qui si usa l'altra strada: l'illustrazione di YGOPRODeck, presa
da `core.card_images`, cioè dalla **stessa cache su disco** del Database. Chi
ha già sfogliato il Database le vede comparire senza scaricare niente.

Il prezzo di questa scelta, detto chiaro perché è un compromesso vero:
l'immagine è quella della CARTA, non della singola stampa — una Ultra Rare e
la sua ristampa Common mostrano la stessa illustrazione. La stampa, però, è
scritta accanto (set e rarità), che è l'informazione che conta davvero; e per
chi ha carte con arti alternative non indicizzate resta la cornice vuota,
mai l'immagine di un'altra carta scelta per somiglianza.

Il ponte nome → illustrazione passa da `core.card_catalog`, in sola lettura.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtGui import QPixmap

from core import card_catalog, card_images
from core.storage import Storage


class ThumbSource(QObject):
    """Da un nome di carta alla sua miniatura, con un solo download per carta.

    Non sa niente dell'interfaccia: chi disegna si collega a `ready` e ridipinge
    quando arriva qualcosa. Le immagini già su disco sono disponibili subito,
    le altre arrivano spaziate e restano lì per sempre.
    """

    ready = Signal(str)     # nome della carta la cui miniatura è arrivata

    def __init__(self, storage: Storage, parent=None) -> None:
        super().__init__(parent)
        self._storage = storage
        self._ref: dict[str, tuple[int, str]] = {}   # nome -> (card_id, url)
        self._pix: dict[str, QPixmap] = {}
        self._asked: set[int] = set()
        self._id_name: dict[int, str] = {}
        #: nomi che il catalogo carte non conosce: non si richiedono più
        self._sconosciuti: set[str] = set()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(4)
        self._signals = card_images.ImageSignals()
        self._signals.done.connect(self._on_image)

    def resolve(self, names) -> None:
        """Traduce in blocco i nomi che non conosce ancora.

        In blocco perché è una query sola per tutta la pagina invece di una per
        carta: il ponte verso `cdb_cards` legge a blocchi di 400.
        """
        mancanti = [n for n in dict.fromkeys(names)
                    if n and n not in self._ref and n not in self._sconosciuti]
        if not mancanti:
            return
        try:
            righe = card_catalog.by_name(self._storage, mancanti)
        except card_catalog.CardCatalogError:
            # Il catalogo carte c'è ma non si legge: niente miniature, e
            # nessun rumore — la collezione resta perfettamente utilizzabile
            # con le cornici vuote. Chi vuole sapere perché lo trova scritto
            # nel Market Watch, che di quel guasto è il proprietario.
            righe = {}
        for nome in mancanti:
            riga = righe.get(nome)
            if riga is None:
                self._sconosciuti.add(nome)
                continue
            url = riga["image_small_url"] or riga["image_url"] or ""
            self._ref[nome] = (int(riga["id"]), url)
            self._id_name[int(riga["id"])] = nome

    def pixmap(self, name: str) -> QPixmap | None:
        """La miniatura **se c'è già**, altrimenti None. NON scarica niente.

        Leggere e scaricare sono due gesti diversi, e tenerli separati è
        l'unica difesa che funziona: chi disegna una tabella chiama questa per
        ogni riga — anche per le mille fuori dallo schermo — e se leggere
        mettesse in coda un download basterebbe aprire l'app per mandare mille
        richieste a YGOPRODeck. È la stessa divisione che il Database fa da
        sempre fra `_request_image` e il riempimento della tabella.
        """
        if not name:
            return None
        pronta = self._pix.get(name)
        if pronta is not None:
            return pronta
        dati = self._ref.get(name)
        if dati is None:
            return None
        su_disco = card_images.cached(dati[0], small=True)
        if su_disco is not None:
            pix = QPixmap(str(su_disco))
            if not pix.isNull():
                self._pix[name] = pix
                return pix
        return None

    def request(self, name: str) -> None:
        """Chiede la miniatura di UNA carta, se serve davvero.

        La chiamano solo i posti che sanno cosa c'è **a schermo**: le righe
        visibili della tabella, le tasche della pagina aperta, l'anteprima del
        dialogo. Un URL già fallito non si ritenta (GOTCHA 1) e una carta già
        chiesta non si chiede due volte.
        """
        if not name or name in self._pix:
            return
        dati = self._ref.get(name)
        if dati is None:
            return
        card_id, url = dati
        if card_images.cached(card_id, small=True) is not None:
            return                      # c'è su disco: la prenderà `pixmap`
        if not url or card_id in self._asked or card_images.failed(url):
            return
        self._asked.add(card_id)
        self._pool.start(card_images.ImageTask(card_id, url, True, self._signals))

    def stop(self) -> None:
        """Butta la coda e aspetta chi è già partito.

        Senza, chiudendo l'app con cinquanta miniature in coda si resta
        appesi finché finiscono: sono `QRunnable` in un `QThreadPool`, che di
        suo aspetta tutto quello che ha accettato.
        """
        self._pool.clear()
        self._pool.waitForDone(3000)

    def _on_image(self, card_id: int, _small: bool, percorso: str) -> None:
        nome = self._id_name.get(int(card_id), "")
        if not percorso or not nome:
            return          # persa: resta la cornice vuota, non si ritenta
        pix = QPixmap(percorso)
        if pix.isNull():
            return
        self._pix[nome] = pix
        self.ready.emit(nome)
