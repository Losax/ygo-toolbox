# Registro — YGO Toolbox (per l'utente)

_Aggiornato: 2026-07-28_

App desktop (PySide6/Qt) per seguire i prezzi delle carte Yu-Gi-Oh! su
**CardTrader**. Tema scuro con accento teal.

---

## 1. Come si avvia

- **Eseguibile:** `dist\YGO Toolbox.exe` (doppio clic, non serve Python). Icona:
  testa di *Primite Dragon Ether Beryl*.
- **Da sorgente (sviluppo):**
  ```
  .venv\Scripts\activate
  python main.py
  ```
- **Token CardTrader:** file `C:\Users\<utente>\.ygo_toolbox\cardtrader_token.txt`
  (oppure variabile d'ambiente `CARDTRADER_TOKEN`). Serve per sincronizzare il
  catalogo e controllare i prezzi. Si imposta anche dal pulsante **Token**.
- I dati (token, DB catalogo/watchlist/storico) stanno in `~/.ygo_toolbox\`,
  fuori dal progetto.

---

## 2. Funzionalità e uso

| Funzione | Come si usa |
|---|---|
| **Sincronizza catalogo** | Pulsante in alto. Scarica tutte le stampe YGO (~48.000) con immagine, rarità e codice set. Operazione una tantum (~4-5 min). |
| **Ricerca live** | Scrivi nel campo: i risultati compaiono mentre digiti. Cerca per **parole parziali in qualsiasi ordine** su **nome + rarità + codice set** (es. `impulse quarter`). Ogni voce mostra miniatura, nome — rarità e il **codice set** (pill a destra; hover = nome completo). |
| **Anteprima immagine** | Selezionando un risultato (o una riga in watchlist) l'immagine appare nel riquadro a destra. |
| **Se l'immagine manca** | L'app mostra quella di **un'altra stampa della stessa carta** (preferendo la versione **senza rarità**: l'arte è identica), con sopra la scritta **"Stock" in diagonale** a ricordare che non è la stampa esatta. Solo se non esiste proprio nessuna immagine resta una cornice vuota. Le immagini che non si scaricano vengono riprovate al successivo *Controlla ora*. |
| **Aggiungi alla watchlist** | Seleziona una stampa, imposta la **soglia di calo %**, clic su *Aggiungi*. |
| **Controlla ora / Auto** | Riscarica il prezzo più basso; se scende oltre soglia → notifica di sistema. L'intervallo automatico è impostabile. In più, **all'apertura dell'app parte un controllo automatico** (~2,5 s dopo l'avvio), così la Var.% mostra il movimento reale dall'ultima sessione. |
| **Dati ricordati al riavvio** | L'**ultimo annuncio** di ogni carta (condizione, lingua, venditore, commenti…) è salvato su DB: riaprendo l'app la Panoramica è **subito piena**, con l'orario dell'ultimo controllo. Rimuovendo una carta si cancellano anche i suoi dati (niente accumulo). |
| **Nessuna copia** | Se **nessun annuncio** soddisfa i filtri (globali o della carta), la riga mostra "Nessuna copia" invece di un prezzo non conforme. Lo stato è ricordato al riavvio (si aggiorna al prossimo controllo). |
| **Panoramica** | Pulsante *Panoramica*: nasconde la ricerca e allarga la watchlist con voci grandi. Colonne separate: Immagine, Nome, Rarità, Set, **Condizione**, **Lingua**, **1ª ed.** (✓), **Zero** (✓), Prezzo, Var., **Venditore** (nome + **bandierina** del paese + badge **PRO**), **Commenti**, **Q.tà**. Transizione animata. |
| **Interfaccia adattiva** | Tutta l'app (testi, righe, miniature, colonne, sidebar) **scala con la dimensione della finestra** (fino a +30% a schermo intero). In Panoramica, sotto lo schermo intero **l'intera vista si rimpicciolisce** (righe, font, miniature, badge) per restare usabile a qualsiasi larghezza, senza scroll orizzontale; se serve le intestazioni si abbreviano (Cond., Vend., … — nome completo nel tooltip). |
| **Filtri per singola carta** | Icona **sliders** su ogni riga della watchlist: filtri validi solo per quella carta (con opzione "usa i filtri predefiniti"). Sovrascrivono i predefiniti. |
| **Rimuovi** | Icona **cestino** sulla riga (in Panoramica impostazioni e cestino sono impilati). |
| **Cartelle & ordinamento** | **Trascina le righe** per riordinare le carte o metterle in una **cartella espandibile** (trascinala sulla riga della cartella). La riga della cartella è **incolonnata come una carta**: nome (+ n° carte) sotto *Nome*, **valore totale** sotto *Prezzo*, **variazione %** sotto *Var.*, con pulsanti **rinomina** (matita) ed **elimina** (cestino). Clic per aprire/chiudere (stato ricordato). **Tasto destro**: nuova cartella, "Sposta nella cartella". |
| **Dove finisce una cartella** | Una **barra verticale teal** corre lungo tutta la cartella (intestazione + carte che contiene) e una **riga di chiusura** la sigilla in fondo: si vede a colpo d'occhio dove il gruppo finisce e dove ricominciano le carte fuori dalle cartelle. |
| **Filtri predefiniti (imbuto)** | Pulsante a **imbuto nell'header**: decide **quali annunci contano** nel calcolo del prezzo più basso (lingua, condizione, 1ª ed., Zero, graded, PRO, americana). Sono i filtri che una carta si porta dietro se la aggiungi senza impostarne di propri, e valgono per tutte quelle che non ne hanno. |
| **Filtri della carta che stai aggiungendo** | Pulsante **sliders accanto alla barra di ricerca**: dopo aver scelto una carta e **prima** di premere *Aggiungi*, puoi darle filtri suoi. Il pulsante si **accende in teal** quando quella carta ha filtri propri; con nessuna carta selezionata è spento. I filtri nascono insieme alla carta, quindi già il primo controllo del prezzo li rispetta. |
| **Opzioni (visualizzazione)** | Pulsante *Opzioni* (sliders) nell'header: preferenze di **visualizzazione** della watchlist (rarità come badge, set come codice), **animazioni dell'interfaccia** on/off (effetto immediato) e **lingua dell'app** (Italiano/English, si applica al riavvio). |
| **Finestre "in-app"** | Le impostazioni non si aprono più come finestre di Windows: sono **card del tema** senza cornice, con ombra e dissolvenza, posizionate accanto al pulsante che le apre. **Clic fuori dalla card = chiudi e applica** (come un menu; per scartare c'è *Annulla*). |

### Filtri disponibili (Opzioni)
- **Lingua** (es. Italiano, Inglese, …)
- **Condizione minima** (Near Mint, Excellent, …)
- **Solo prima edizione**
- **Solo acquistabili con CardTrader Zero**
- **Escludi carte graded**
- **Solo venditori PRO**
- **Solo stampa americana (USA)** — criterio *non ufficiale*: carta in inglese
  **e** (venditore americano **oppure** commento con USA / American / NA-US print /
  US Edition / North American). Selezionandolo la lingua è forzata a Inglese.

I filtri sono **salvati** e ri-applicati; cambiandoli l'app ricontrolla subito.

---

## 3. Cronologia lavori di questa sessione

1. Configurato e **verificato dal vivo** il provider CardTrader (token reale).
2. **Bug catalogo risolto:** l'API pagina i blueprint a 50/pagina; prima ne
   salvavamo solo 50 per set → mancavano carte/stampe. Ora pagina tutto
   (catalogo da ~22k a ~48k carte).
3. Aggiunta la **rarità** della stampa.
4. **Grafica rinnovata:** tema scuro/teal, card con ombre, più aria, animazioni
   (dissolvenze, pulse del prezzo quando cambia, barra di avanzamento, hover
   animato con "gonfiarsi" delle voci).
5. **Ricerca live** (typeahead) al posto del pulsante "Cerca", poi resa
   **a token** (parole parziali, qualsiasi ordine).
6. **Anteprima immagine** grande + **miniature** nel menù a tendina.
7. **Codice set** abbreviato nel menù (con tooltip del nome completo).
8. **Filtri annunci** (finestra Opzioni), incluso lo "stampa americana".
9. **Eseguibile** (.exe) con **icona** dedicata (testa di drago).
10. Ottimizzazioni prestazioni (immagini più veloci, ricerca senza lag).

### Aggiornamenti successivi (stessa giornata)
11. **"Nessuna copia"**: se nessun annuncio soddisfa i filtri, la carta non
    mostra più un prezzo non conforme; lo stato è **persistito** tra i riavvii.
12. **Modalità Panoramica**: la ricerca si nasconde (con animazione) e la
    watchlist si allarga con voci grandi e **colonne modulari**
    (Immagine, Nome, Rarità, Set, Condizione, Prezzo, Var., Venditore,
    Commenti, Q.tà). Pulsanti azione impilati.
13. **Miniatura della carta** all'inizio di ogni riga della watchlist.
14. **Filtri per singola carta** (icona impostazioni per riga) che
    sovrascrivono quelli globali, con opzione "usa globali".

### Sessione 2026-07-01/02
15. **Interfaccia adattiva**: tutti gli elementi (testi, righe, miniature,
    colonne, sidebar) scalano con la larghezza della finestra (0,9×–1,3×).
16. **Colonne separate in Panoramica**: Condizione, **Lingua**, **1ª ed.** e
    **Zero** non sono più un'unica voce; ✓ teal per i flag attivi.
17. **Colonna Venditore con iconcine**: bandierina del paese (disegnata
    dall'app, ~38 paesi) e badge **PRO** teal, con tooltip.
18. **Intestazioni mai troncate** e colonne che si adattano allo spazio
    (a schermo intero niente scroll orizzontale in Panoramica).
19. **Persistenza dell'ultimo annuncio** (`mw_last_quote`): al riavvio la
    Panoramica è già piena; "Nessuna copia" unificato nella stessa tabella
    (migrazione automatica dal vecchio formato). Rimozione carta = pulizia
    completa di storico e annuncio; sfoltimento dello storico oltre 90 giorni
    (resta il minimo giornaliero, pronto per il futuro grafico).
20. **Controllo automatico all'apertura** dell'app (oltre a quello periodico).
21. **Var.% dall'ultimo cambio di prezzo**: i controlli ripetuti con prezzo
    invariato non la azzerano più (e non gonfiano lo storico).
22. **Opzioni di visualizzazione** (in *Opzioni*): rarità come **badge colorato**
    con la sigla (UR, ScR, QCSR, … — colore in stile foil, nome nel tooltip) e
    set come **pill del codice** (es. LOB, stessa estetica della ricerca) invece
    del nome completo.
23. **Cartelle espandibili e ordinamento manuale** della watchlist: drag&drop
    delle righe, cartelle con stato aperto/chiuso ricordato, menu tasto destro
    (nuova/rinomina/elimina/sposta), riga con 📁 nome · n° carte · totale € e
    pulsanti rinomina/elimina.
24. **Fluidità**: apertura/chiusura cartelle **animata** (fisarmonica),
    scorrimento della watchlist **per pixel** (niente più scatti di riga in
    riga), aggiornamenti della tabella senza sfarfallio e riscalatura della
    finestra senza scatti durante il trascinamento del bordo.
25. **Restyling "liscio"**: font **Inter** incorporato nell'app (licenza OFL,
    con hinting leggero → testo più morbido) e angoli più arrotondati su
    card, bottoni, input, tabella e popup.
26. **Voci più distinguibili**: righe alternate (zebra) e separatori più
    marcati nella watchlist e nel popup di ricerca.
27. **Animazione allo spostamento**: la voce spostata (drag&drop o menu)
    "si inserisce" nella nuova posizione con un lampo teal che svanisce;
    se finisce in una cartella chiusa, lampeggia la cartella.
28. **Prestazioni scroll**: via l'ombra dalla tabella (dimezzava gli fps a
    ogni frame di scorrimento) e rotellina con **scorrimento animato** dolce.
    Risolto anche un **crash** alla massimizzazione in Panoramica (animazione
    su celle già distrutte); eventuali errori dell'exe ora finiscono in
    `~/.ygo_toolbox/log.txt`.
29. **Header a icone**: i pulsanti Token / Sincronizza / Opzioni / Panoramica
    sono diventati pulsanti-icona quadrati (chiave, frecce circolari, sliders,
    griglia) con tooltip — schermata principale più pulita. La griglia si
    accende in teal quando la Panoramica è attiva.
30. **Impostazioni riorganizzate e "in-app"**: filtri annunci spostati sul
    pulsante a **imbuto accanto alla ricerca**; Opzioni ora contiene solo la
    visualizzazione. Entrambe si aprono come **card senza cornice di Windows**
    (ombra, fade-in, vicino al pulsante); **clic fuori = chiudi e applica**.
31. **Filtri rifiniti**: freccette delle tendine ridisegnate (chevron
    visibile), checkbox sostituite da **interruttori a pallino animati**
    (scorrono e si accendono in teal), e la **lingua è sempre modificabile**:
    scegliendo una lingua diversa dall'inglese, la spunta "americana" si
    spegne da sola (prima bloccava il cambio lingua).
32. **Hover della ricerca senza tagli**: la voce che si "gonfia" al passaggio
    del mouse non viene più mozzata ai bordi (crescita orizzontale calibrata
    sui margini del popup). Rifatte anche le **freccette dei campi numerici**
    ("Auto ogni", "Avvisa al calo di"): chevron visibili in pulsantini con
    hover, senza più sbordare dal campo.
33. **Lingua dell'app** (in *Opzioni*): Italiano o **English** — tutta
    l'interfaccia è tradotta (header, tabella, filtri, cartelle, menu, stati,
    notifiche); la scelta si applica al riavvio.
34. **Animazioni disattivabili** (in *Opzioni*): un interruttore spegne tutte
    le animazioni (dissolvenze, fisarmoniche, scroll morbido, switch, card) —
    ogni azione diventa immediata; effetto istantaneo, senza riavvio.
35. **Pronta per la distribuzione (v1.0.0)**: versione nel titolo e nei
    metadati dell'exe, **card di benvenuto** al primo avvio (token + catalogo),
    guida `LEGGIMI.txt` (con istruzioni SmartScreen) e pacchetto
    `dist\YGO Toolbox v1.0.0.zip` pronto da girare. Testata da utente nuovo
    (profilo pulito).
36. **Menu a tendina rifatti**: le tendine dei filtri sono card
    **arrotondate** (via le fasce squadrate sopra/sotto le voci) e si aprono/
    chiudono con dissolvenza e scivolamento; anche la card delle impostazioni
    **esce con animazione** su OK/Annulla/clic fuori. Tempi delle animazioni
    ricalibrati (più morbidi e visibili). Corretti due bug: interruttori che
    non si spegnevano e crash alla massimizzazione in Panoramica.
37. **Notifiche sul telefono: accantonate.** Era stata fatta una prima versione
    via bot Telegram (avvisi di calo inoltrati dal PC), ma la strada per il
    "companion mobile" è ancora da decidere → funzione **rimossa** il
    2026-07-28 per non portarsi dietro mezza soluzione. Le notifiche restano
    quelle di sistema, sul PC. Il codice non è perso: sta nella cronologia di
    git (commit `12f68bf`), pronto da ripescare quando si sceglierà come
    procedere.
38. **v1.0.1**: exe ricompilato e nuovo pacchetto `dist\YGO Toolbox v1.0.1.zip`.
    Numero alzato perché il v1.0.0 era già confezionato per essere girato: due
    exe diversi con lo stesso numero creerebbero solo confusione. Il vecchio
    pacchetto è stato **eliminato** (in `dist\` sta solo la versione corrente;
    all'occorrenza si ricostruisce dal tag/commit di quella release).
39. **Basta "Troppe richieste (429)" (v1.0.2).** Il controllo di tutte le carte
    faceva una richiesta per carta **tutte attaccate**: con una watchlist piena
    CardTrader si difendeva e il controllo falliva **in blocco**, senza
    aggiornare niente. Ora:
    - le richieste sono **distanziate** nel tempo, e la distanza si **tara da
      sola**: si allarga se CardTrader si lamenta, si restringe quando tutto
      fila. La taratura viene **ricordata** anche dopo la chiusura dell'app,
      così non si ricomincia da capo ogni volta;
    - un 429 non è più un errore: la carta viene **ritentata** dopo una pausa
      (rispettando l'attesa chiesta dal server);
    - se qualche carta proprio non passa, **le altre vengono comunque
      aggiornate e salvate** — prima si perdeva tutto il giro. Le carte non
      controllate **mantengono il prezzo precedente**, non diventano
      "Nessuna copia";
    - durante il controllo la barra di stato mostra **l'avanzamento**
      (es. "Controllo prezzi… 12/40"), e se qualcosa è rimasto indietro lo
      dice ("Controllo parziale (38 carte su 40): 2 non aggiornate").
40. **Bug della rotellina risolto** (trovato nel log durante le prove del punto
    39): scorrendo la watchlist, ogni scatto dato *dopo* che l'animazione
    precedente era finita generava un errore interno (finiva in
    `~/.ygo_toolbox/log.txt` senza chiudere l'app, ma era un rischio di crash
    nell'exe). Lo scorrimento animato ora usa un solo oggetto riutilizzato.
41. **Cartelle rifatte (v1.0.3).**
    - **Incolonnate come le carte:** il nome sta sotto *Nome*, il **valore
      totale** sotto *Prezzo* e la **variazione %** sotto *Var.* — prima erano
      tutti infilati in un'unica riga di testo che ignorava le intestazioni.
      A cartella **chiusa** si legge quindi il riepilogo con lo stesso colpo
      d'occhio di una carta. In Panoramica il numero di carte finisce nella
      colonna *Q.tà*.
    - **Nuova variazione di cartella:** è la variazione del **valore totale**
      (somma di adesso contro somma di prima), non la media delle percentuali:
      una carta da 200 € pesa quanto vale, coerentemente col totale mostrato
      accanto. Le carte "Nessuna copia" restano fuori dal conto.
    - **Si vede dove finisce una cartella:** una barra verticale teal
      accompagna tutta la cartella e una riga di chiusura la sigilla in fondo,
      prima delle carte sciolte.
    - **Più curate:** l'emoji 📁 ha lasciato il posto a un'**icona disegnata
      dall'app** (con la freccetta di apertura), in tinta col tema e nitida a
      ogni dimensione; nome in grassetto su fascia continua.
42. **Nomi allineati in Panoramica (v1.0.4).** In Panoramica i nomi lunghi
    vanno a capo e, per le carte dentro una cartella, la **prima riga** del
    nome risultava spostata rispetto alle successive: il rientro era fatto con
    spazi nel testo, che valgono solo per la prima riga. Ora il rientro è
    vero e proprio (si sposta il disegno), quindi tutte le righe del nome sono
    allineate.
43. **Immagini mancanti: mai più il buco (v1.0.6).** Capitava che l'immagine di
    una carta non si trovasse (la stampa non ce l'ha in catalogo, oppure il
    download fallisce). Ora, nell'ordine:
    - si prova l'immagine della **stampa esatta**;
    - se non c'è o non si scarica, si usa quella di **un'altra stampa della
      stessa carta**, preferendo la versione **senza rarità** (l'arte più
      "liscia"). Sopra ci va la scritta **"Stock" in diagonale,
      semitrasparente**: l'arte è giusta, la stampa no, e si deve vedere.
      Non costa nessuna richiesta in più — l'elenco dei ripieghi si costruisce
      dal catalogo già in memoria;
    - solo se non esiste nessuna immagine della carta resta una **cornice
      vuota** discreta.
    *(Una prima versione metteva le iniziali della carta al posto del buco:
    scartata, faceva più rumore del problema che risolveva.)*
44. **Le carte che restavano senza immagine (v1.0.7).** Il ripiego funzionava
    per alcune carte (*Azamina Mu Rcielago*) e non per altre
    (*Deception of the Sinful Spoils*). Motivo: per le stampe di cui non ha la
    foto, CardTrader non lascia il campo vuoto — manda **un suo rettangolo
    grigio**, uguale per tutte le carte. L'app lo prendeva per un'immagine
    buona e non cercava il ripiego; se poi quella stampa capitava per prima in
    elenco, veniva scelta *lei* come ripiego, e la carta restava senza niente.
    Ora quel rettangolo è riconosciuto e trattato come "immagine assente".
    Nel tuo catalogo riguardava **645 stampe su 47.980**: dopo la correzione
    ne restano scoperte **9**, e la watchlist ha tutte le immagini.
    Non serve risincronizzare il catalogo: la correzione vale anche su quello
    già scaricato.
45. **Filtri: predefiniti e "di questa carta", separati (v1.0.8).** Prima
    l'imbuto accanto alla ricerca faceva una cosa sola: cambiare i filtri
    globali. Ora sono due pulsanti con due mestieri distinti:
    - **imbuto nell'header** → *filtri predefiniti*: quelli che una carta si
      porta dietro quando la aggiungi senza toccare niente;
    - **sliders accanto alla ricerca** → *filtri di questa carta*: dopo aver
      scelto la carta e prima di premere *Aggiungi*, le dai filtri suoi. Il
      pulsante è spento se non hai selezionato nulla e si **accende in teal**
      quando la carta ha filtri propri, così vedi a colpo d'occhio cosa stai
      per aggiungere. Cambiando carta i filtri preparati si azzerano: erano
      per quella.
    I filtri della carta **nascono insieme a lei**, quindi già il primo
    controllo del prezzo li rispetta (prima si potevano impostare solo dopo,
    dalla riga in watchlist). L'icona a sliders è la stessa dei filtri per
    riga: è lo stesso mestiere, su una carta sola.
    Di conseguenza **Opzioni ha cambiato icona**: era anch'essa a sliders, ora
    è un **ingranaggio**. Nell'header le cinque icone sono così tutte diverse:
    chiave (token), frecce (sincronizza), imbuto (filtri predefiniti),
    ingranaggio (opzioni), griglia (panoramica).
    In più, un'immagine che non si scarica **non viene più richiesta a ogni
    ridisegno** (era una raffica verso CardTrader, che sta dietro Cloudflare e
    risponde 403): viene ricordata e riprovata al successivo *Controlla ora*.
    **La causa vera:** controllando il catalogo scaricato è saltato fuori che
    le immagini mancanti non esistono — tutte le 47.980 stampe hanno il loro
    indirizzo. A fallire era lo **scaricamento**, perché le miniature
    partivano tutte insieme. Ora vengono richieste **una ogni 80 millesimi di
    secondo**: alla vista non cambia niente, ma CardTrader smette di
    scambiarci per un robot.

---

## 4. Note operative importanti

- **Non fare raffiche di richieste** verso CardTrader: è dietro Cloudflare e può
  bloccare temporaneamente l'IP (errori 403 su immagini e prezzi). Si sblocca da
  solo dopo un po'.
- Se cambia lo **schema del DB** in sviluppo e qualcosa non torna, si può
  cancellare `~\.ygo_toolbox\ygo_toolbox.db` (si perde la watchlist) e
  risincronizzare.
- Le funzioni di rete (prezzi, immagini) hanno bisogno di connessione e token
  valido.
