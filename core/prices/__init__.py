"""Strato dei PREZZI: provider intercambiabili, rete e token.

Sta nel `core` — e non dentro il Market Watch, dove è nato — perché **serve a
due moduli**: il Market Watch (prezzo più basso delle carte seguite) e la
Collezione (valore di quello che possiedi). È la stessa strada già presa da
`card_images.py`, `badges.py` e `rarity.py`: ciò che serve a due posti va in
un posto comune, perché i moduli non si importano fra loro.

C'è però un motivo più forte della simmetria: il **freno**. `cardtrader.LIMITER`
è un oggetto SOLO, e deve restarlo — due moduli con due limitatori separati
sommerebbero il traffico verso la stessa API dietro Cloudflare, che è
esattamente la raffica che il freno esiste per evitare. Condividere il modulo
è condividere il freno.
"""
