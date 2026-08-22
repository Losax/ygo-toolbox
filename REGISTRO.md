# Registro — YGO Toolbox (per l'utente)

_Aggiornato: 2026-08-22_

App desktop (PySide6/Qt) per seguire i prezzi delle carte Yu-Gi-Oh! su
**CardTrader**. Tema scuro con accento teal.

---

## 1. Come si avvia

- **Da installer (quello che si dà agli amici):**
  `dist\YGO-Toolbox-Setup-vX.Y.Z.exe`, pubblicato anche fra le
  [Release su GitHub](https://github.com/Losax/ygo-toolbox/releases).
  Si installa **solo per l'utente** in
  `%LocalAppData%\Programs\YGO Toolbox`, **senza chiedere l'amministratore**,
  mette la voce nel menu Start e si rimuove dalle App di Windows.
  Aggiornare **non richiede più di scaricare niente a mano**: dalla v1.4.0
  l'app scarica da sola e basta premere *Riavvia e aggiorna* nel piede sotto il
  menu (vedi la tabella). A mano funziona ancora: si lancia il nuovo installer
  sopra il vecchio, e in entrambi i casi **watchlist, catalogo e token non si
  toccano**. SmartScreen avvisa **una volta sull'installer** scaricato dal
  browser (app non firmata), non sull'app installata — e non sull'aggiornamento
  automatico, che non passa dal browser.
- **Eseguibile nudo:** `dist\YGO Toolbox.exe` — è l'ingrediente da cui si
  costruisce l'installer, non l'artefatto da distribuire. Funziona col doppio
  clic (non serve Python). Icona: testa di *Primite Dragon Ether Beryl*.
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
| **Panoramica** | Pulsante *Panoramica*: nasconde la ricerca e allarga la watchlist con voci grandi. Colonne separate: Immagine, Nome, Rarità, Set, **Condizione** (sigla: NM, LP, …, nome intero nel tooltip), **Lingua**, **1ª ed.** (✓), **Zero** (✓), Prezzo, Var., **Venditore** (nome + **bandierina** del paese + badge **PRO**), **Commenti**, **Q.tà**. Transizione animata. |
| **Interfaccia adattiva** | Tutta l'app (testi, righe, miniature, colonne, sidebar) **scala con la dimensione della finestra** (fino a +30% a schermo intero). In Panoramica, sotto lo schermo intero **l'intera vista si rimpicciolisce** (righe, font, miniature, badge) per restare usabile a qualsiasi larghezza, senza scroll orizzontale; se serve le intestazioni si abbreviano (Cond., Vend., … — nome completo nel tooltip). |
| **Filtri per singola carta** | Icona **sliders** su ogni riga della watchlist: filtri validi solo per quella carta (con opzione "usa i filtri predefiniti"). Sovrascrivono i predefiniti. |
| **Quali carte hanno filtri propri** | Un **imbutino teal davanti al nome** marca le carte con filtri diversi dai predefiniti, così si vedono scorrendo l'elenco; anche l'icona sliders di quella riga diventa **teal** invece che grigia. |
| **Apri su CardTrader** | Icona **freccia in uscita** sulla riga, accanto ai filtri e al cestino: apre la pagina della carta sul sito. Basta l'id: CardTrader reindirizza alla pagina giusta. **I filtri non viaggiano nel link** — il sito non li accetta nell'indirizzo (li applica internamente) — perciò il tooltip elenca quelli in vigore, così si rimettono in due secondi. |
| **Rimuovi** | Icona **cestino** sulla riga (in Panoramica impostazioni e cestino sono impilati). |
| **Basi (mazzi)** | Pulsante **carte a ventaglio accanto alla barra di ricerca** (o tasto destro → *Nuova base…*): apre un modulo dove dai un **nome**, imposti i **filtri una volta sola per tutta la base**, poi cerchi le carte e dici **quante copie** ne vuoi. La ricerca è **la stessa della barra principale**: miniature, hover animato e pill del codice set. Cercare di nuovo una carta già presente aggiunge una copia. La base compare in watchlist come una cartella: **valore totale che tiene conto delle copie** e carte marcate `3×`. La **matita** sulla riga riapre lo stesso modulo per modificarla. Togliere una carta dalla base **non la cancella**: esce solo dalla base (lo storico prezzi resta). |
| **Da dove arrivano le copie** | Se ti servono 3 copie e il venditore più economico ne ha una, l'app prende le **3 copie più economiche davvero disponibili**, anche da venditori diversi: la colonna *Prezzo* mostra quanto costano tutte e tre, non tre volte il prezzo migliore. In Panoramica la cella *Q.tà* diventa `3 ▸`: **clic** e sotto la carta compare una riga per ogni venditore che contribuisce (quante copie, a che prezzo, condizione, paese). Se il mercato non basta, il prezzo diventa giallo e lo dice. |
| **Ordina per** | Riga di pulsantini sopra la tabella: **Manuale** (l'ordine che hai dato trascinando), **Rarità**, **Prezzo**, **Var.**. Il criterio attivo è **teal** con una freccetta; **cliccandolo di nuovo si inverte** il verso. L'ordinamento agisce **dentro ogni cartella/base** e fra le carte sciolte: i gruppi restano gruppi. Le carte senza il dato (prezzo mai visto, variazione non calcolabile) stanno **sempre in fondo**, in entrambi i versi. Il criterio si ricorda alla riapertura. |
| **Grafico dello storico** | **Doppio clic** su una carta in watchlist (o tasto destro → *Storico prezzi…*): si apre una finestra col grafico dei prezzi rilevati, il prezzo attuale, il minimo, il massimo, la variazione dal primo prezzo e da quanti giorni si segue la carta. Passando il mouse si legge il prezzo in vigore a quella data. Mostra solo i prezzi presi **con i filtri di adesso**; se ce ne sono di più vecchi, presi con altri filtri, un interruttore in basso li aggiunge smorzati e separati da una linea tratteggiata. |
| **Esporta / importa** | **Tasto destro** sulla watchlist → *Esporta tutto…* (backup: carte, cartelle, basi, preferenze e storico prezzi) oppure, sulla riga di una base, *Esporta questa base…* (il file da passare a un amico: solo le carte con copie e filtri). Il file è un **JSON leggibile**, apribile con Notepad, e pesa una quarantina di KB contro i 13 MB del database. Con *Importa da file…* l'app dice **cosa contiene** e poi chiede: **Aggiungi** (unisce; le carte già presenti vengono aggiornate) o **Sostituisci** (svuota e rimpiazza, con una conferma in più). Il **token non viene mai esportato**, e il catalogo nemmeno (si riscarica). |
| **Cartelle & ordinamento** | **Trascina le righe** per riordinare le carte o metterle in una **cartella espandibile** (trascinala sulla riga della cartella). La riga della cartella è **incolonnata come una carta**: nome (+ n° carte) sotto *Nome*, **valore totale** sotto *Prezzo*, **variazione %** sotto *Var.*, con pulsanti **rinomina** (matita) ed **elimina** (cestino). Clic per aprire/chiudere (stato ricordato). **Tasto destro**: nuova cartella, "Sposta nella cartella". |
| **Dove finisce una cartella** | Una **barra verticale teal** corre lungo tutta la cartella (intestazione + carte che contiene) e una **riga di chiusura** la sigilla in fondo: si vede a colpo d'occhio dove il gruppo finisce e dove ricominciano le carte fuori dalle cartelle. |
| **Filtri predefiniti (imbuto)** | Pulsante a **imbuto nell'header**: decide **quali annunci contano** nel calcolo del prezzo più basso (lingua, condizione, 1ª ed., Zero, graded, PRO, americana). Sono i filtri che una carta si porta dietro se la aggiungi senza impostarne di propri, e valgono per tutte quelle che non ne hanno. |
| **Filtri della carta che stai aggiungendo** | Pulsante **sliders accanto alla barra di ricerca**: dopo aver scelto una carta e **prima** di premere *Aggiungi*, puoi darle filtri suoi. Il pulsante si **accende in teal** quando quella carta ha filtri propri; con nessuna carta selezionata è spento. I filtri nascono insieme alla carta, quindi già il primo controllo del prezzo li rispetta. |
| **Opzioni (visualizzazione)** | Pulsante *Opzioni* (sliders) nell'header: preferenze di **visualizzazione** della watchlist (rarità come badge, set come codice), **animazioni dell'interfaccia** on/off (effetto immediato) e **lingua dell'app** (Italiano/English, si applica al riavvio). |
| **Finestre "in-app"** | Le impostazioni non si aprono più come finestre di Windows: sono **card del tema** senza cornice, con ombra e dissolvenza, posizionate accanto al pulsante che le apre. **Clic fuori dalla card = chiudi e applica** (come un menu; per scartare c'è *Annulla*). |
| **Si aggiorna da sola** | All'avvio l'app guarda se è uscita una versione nuova e, se sì, **la scarica in sottofondo senza chiedere**. Quando è pronta, **in basso a sinistra sotto il menu** (quindi visibile da qualunque pagina) compare *"Versione X.Y.Z pronta"* e un pulsante **Riavvia e aggiorna**: chiude l'app, installa, la riapre. Meno di un minuto. Watchlist, token e catalogo non si toccano. Se il download non riesce **non compare nessun errore**, resta *Apri la pagina* (il modo manuale di prima); se l'installazione non parte, **l'app non si chiude** e lo dice. Con una sincronizzazione o un controllo prezzi in corso, chiede prima. |

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
46. **Si vede quali carte hanno filtri propri (v1.0.10).** Nella watchlist un
    **imbutino teal davanti al nome** marca le carte con filtri diversi dai
    predefiniti: scorrendo l'elenco si notano subito. Lo spazio dell'imbutino
    è riservato su tutte le righe, così i nomi restano allineati anche dove
    non c'è. In più l'icona sliders di quella riga è **teal** invece che
    grigia, e il tooltip dice esplicitamente se la carta ha filtri propri o
    sta usando i predefiniti.
47. **Niente più crolli inventati dopo un cambio di filtri (v1.0.11).**
    Cambiando i filtri di una carta il prezzo cambia parecchio — normale, si
    sta guardando un'altra versione (altra lingua, altra condizione, altra
    stampa). Ma la **Var.%** lo confrontava col prezzo di prima e mostrava un
    tracollo che non è mai avvenuto; peggio, poteva far scattare **l'avviso di
    calo**. Ora ogni prezzo in archivio ricorda **con quali filtri** è stato
    rilevato, e si confronta solo con prezzi presi con gli stessi: dopo un
    cambio la Var. resta "—" finché non c'è un movimento vero.
48. **…e nemmeno rimettendo i filtri di prima (v1.0.12).** Restava un caso:
    togliere un filtro e poi **rimetterlo** faceva ricomparire il confronto
    con la vecchia serie — un movimento magari di tre settimane prima, che
    sembrava appena avvenuto (visto dal vivo su *Dominus Purge*: +30%). Ora
    il confronto vive solo **dentro il tratto attuale**: ogni cambio di filtri
    chiude il tratto precedente, e quello nuovo riparte da capo. Vale in
    salita come in discesa, e vale anche per gli avvisi di calo.
    Il **prezzo** resta comunque visibile (l'ultimo noto con quei filtri):
    a sparire è solo la percentuale, che è la cosa che mentiva. Lo storico
    completo resta nel database, per il grafico che verrà.
49. **Basi, cioè mazzi (v1.0.13).** Nuova funzione: una **base** è un gruppo di
    carte in più copie con **filtri in comune**, cioè quello che serve per
    seguire il prezzo di un mazzo intero.
    - **Un modulo unico** (pulsante *carte a ventaglio* accanto alla barra di
      ricerca): nome, filtri della base impostati **una volta sola**, ricerca
      delle carte e **numero di copie** per ciascuna. Cercando di nuovo una
      carta già in elenco si aggiunge una copia.
    - La ricerca nel modulo è **quella della barra principale**, non una
      copia: stesse **miniature**, stesso **hover animato**, stessa pill del
      codice set.
    - Finestra più grande e **numero di copie ben leggibile**: prima le righe
      erano troppo basse e del numero si vedeva solo una fettina centrale.
    - Nell'elenco della base ogni carta ha la sua **miniatura** accanto al
      nome. Se l'immagine è già stata vista nella ricerca non si riscarica.
    - In watchlist una base **si riconosce a colpo d'occhio** da una cartella
      normale: icona a **carte a ventaglio** (la stessa del pulsante che le crea)
      invece della cartella, e badge **BASE** accanto al nome. Le cartelle
      create prima di questa versione che hanno filtri propri o carte in più
      copie vengono riconosciute come basi da sole.
    - In watchlist la base è una cartella: **totale che moltiplica per le
      copie** (3× Ash Blossom vale tre Ash Blossom) e carte marcate `3×`, con
      il prezzo della singola copia.
    - I filtri seguono una **cascata**: quelli della carta, se ne ha di propri;
      altrimenti quelli della base; altrimenti i predefiniti.
    - Si modifica dalla **matita** sulla riga della base. Togliere una carta
      dalla base non la elimina dalla watchlist: esce solo dalla base, e lo
      storico dei prezzi resta.
    - Le copie si cambiano anche al volo, tasto destro → *Numero di copie…*.
50. **Pulsanti fantasma spariti.** Su alcune righe restavano appiccicate a
    sinistra, davanti al nome, due iconcine che non ci dovevano stare: erano
    pulsanti di render precedenti che Qt non aveva buttato. Ora a ogni
    ridisegno si fa pulizia.
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

51. **Le copie multiple ora dicono da dove arrivano (v1.0.19).** Segnalato su
    *Blitzclique Surge*: 3 copie richieste, ma il venditore più economico ne
    aveva una — e l'app moltiplicava il suo prezzo per tre, cioè un totale non
    ottenibile. Ora:
    - il costo è quello delle **3 copie più economiche davvero disponibili**,
      anche da venditori diversi (nessuna richiesta in più: gli annunci erano
      già tutti scaricati);
    - in Panoramica la cella *Q.tà* mostra `3 ▸`: **clic** e sotto la carta
      compaiono le righe dei venditori che contribuiscono, con quante copie,
      a che prezzo, condizione e paese;
    - se sul mercato non ce ne sono abbastanza, il prezzo si colora di giallo
      e il tooltip dice quante se ne trovano davvero.
    Il **totale della base** usa questo costo reale. La **Var.%** invece
    continua a misurare il movimento dei prezzi: dice come si è mosso il
    mercato, non come è cambiata la disponibilità.
52. **Pulsante "apri su CardTrader" (v1.0.20).** Sulla riga, insieme ai filtri
    e al cestino, c'è una freccia in uscita che apre la pagina della carta.
    **Sui filtri nel link, la risposta è no** e vale la pena saperlo: ho
    verificato sul sito, CardTrader applica i filtri con una chiamata interna
    e non li scrive mai nell'indirizzo — un link "con i filtri già attivi"
    semplicemente non esiste. Passarli comunque avrebbe prodotto un indirizzo
    che *sembra* filtrato e non lo è. Al loro posto il tooltip elenca i filtri
    in vigore per quella carta, così si rimettono a mano in due secondi.
53. **Condizioni abbreviate (v1.0.21) e a badge colorato (v1.0.22).** Nella
    colonna *Condizione* c'è la sigla — **M, NM, EX, SP, LP, GD, MP, PL, PO** —
    invece del nome per esteso, col nome intero nel tooltip: la colonna si
    stringe da 110 a 70 px e lo spazio va ai *Commenti*.
    Ora la sigla è anche un **badge colorato**: **verde** per le carte
    perfette, poi giallo, arancione e **rosso** man mano che la condizione
    scende. Anche la **lingua** è un badge, ma volutamente **neutro**: lì
    accanto il colore porta già un giudizio, e due semafori nella stessa riga
    si darebbero fastidio.
    Una condizione che non conosciamo resta **grigia e scritta per esteso**:
    meglio nessun giudizio che un colore sbagliato.
54. **Ordinamento della watchlist (v1.0.23).** Sopra la tabella una riga di
    pulsantini: *Manuale · Rarità · Prezzo · Var.*, con il criterio attivo in
    teal e una freccetta; rifacendo clic sullo stesso si inverte il verso, e la
    scelta si ricorda alla riapertura.
    Due decisioni che vale la pena conoscere:
    - **le cartelle e le basi restano gruppi**: si ordina *dentro* ciascuna e
      fra le carte sciolte. Un ordinamento globale avrebbe sciolto i gruppi,
      che è il contrario di quello che servono a fare;
    - **chi non ha il dato va sempre in fondo**, in entrambi i versi: una carta
      senza prezzo che galleggia in cima invertendo l'ordine farebbe sembrare
      la lista ordinata per sbaglio.
    La scala delle rarità è **convenzionale** (una ufficiale non esiste): segue
    la scarsità come la intendono i giocatori, da Common a Starlight Rare, e
    una rarità che non riconosciamo finisce tutta da una parte invece di
    sparpagliarsi.
55. **Installer e avviso di aggiornamento (v1.0.24).** Non si consegna più uno
    zip con l'exe dentro, ma un **installer**: doppio clic e avanti.
    - Si installa **solo per te**, senza chiedere la password di
      amministratore; mette la voce nel menu Start e si disinstalla dalle App
      di Windows come qualsiasi programma.
    - **SmartScreen dà meno noia, non più**: compare una volta sull'installer,
      poi l'app installata parte senza avvisi. Con lo zip invece l'avviso
      tornava a ogni exe nuovo, perché il marchio "scaricato da internet" si
      propaga ai file estratti.
    - Per aggiornare basta lanciare il nuovo installer: **se l'app è aperta la
      chiude lui**, e watchlist, catalogo e token restano al loro posto
      (verificato anche disinstallando).
    - All'avvio l'app **controlla se c'è una versione nuova** e mostra
      un'etichetta cliccabile in alto. Non scarica né installa niente da sola,
      e se non c'è rete (o il controllo non è raggiungibile) **tace**: un
      errore per un controllo che non hai chiesto sarebbe solo fastidio.
56. **Esporta e importa la watchlist (v1.0.25).** Finora i tuoi dati si
    potevano spostare solo copiando il file `.db`: binario, con uno schema
    dentro, illeggibile senza strumenti. Ora c'è un **file JSON** che fa da
    tramite e che l'app sa ritrasformare in database.
    - **Esporta tutto** = backup: carte, cartelle, basi, preferenze e storico
      prezzi. Sui tuoi dati veri sono ~40 KB, contro i 13 MB del database.
    - **Esporta questa base** (tasto destro su una base) = il file da passare a
      un amico: solo le carte con copie e filtri, senza storico né preferenze —
      per lui sarebbero ingombro privo di senso, i suoi filtri sono altri.
    - **Importa** dice prima cosa c'è nel file, poi chiede **Aggiungi** o
      **Sostituisci** (con una conferma in più, perché cancella).
    - Il **token non viene mai esportato**: è una credenziale e il file nasce
      per essere passato a qualcuno. Il catalogo nemmeno: 47.980 righe che si
      riscaricano in quattro minuti.
    - Reimportare lo stesso file due volte **non duplica niente**, e le date
      dello storico restano quelle originali invece di appiattirsi sul giorno
      dell'importazione.
    Ho scelto JSON e non CSV perché i dati sono **gerarchici** (le basi
    contengono carte, e sia le basi sia le carte portano un oggetto di filtri):
    in CSV servirebbero più file collegati da id, e per un amico sarebbe *meno*
    comprensibile, non più.
57. **Grafico dello storico prezzi (v1.0.26).** I prezzi si raccoglievano da
    un mese e si potevano solo leggere uno per volta, nella colonna *Var.*.
    Ora **doppio clic su una carta** (o tasto destro → *Storico prezzi…*) apre
    una finestra con l'andamento, il prezzo attuale, minimo, massimo, la
    variazione dal primo prezzo e da quanti giorni la segui. Il mouse sul
    grafico dice quanto costava a quella data.
    Tre scelte che cambiano cosa si legge:
    - **La linea va a gradini, non in diagonale.** L'app registra i *cambi* di
      prezzo, non i controlli: fra due punti il prezzo è rimasto quello. Una
      diagonale disegnerebbe una discesa graduale mai avvenuta — sulla tua
      *The Bystial Lubellion* si vede la differenza: il prezzo è stato fermo a
      200,54 € per diciotto giorni ed è **crollato il 24 luglio** a 164 €,
      mentre una linea "morbida" avrebbe raccontato un calo lento da inizio
      mese.
    - **La linea arriva a oggi**, perché l'ultimo prezzo rilevato è ancora
      quello in vigore: fermarla all'ultimo punto farebbe sembrare la carta
      abbandonata.
    - **Si vedono solo i prezzi presi con i filtri di adesso.** Quelli
      precedenti sono un altro prodotto (altra lingua, condizione, stampa) e
      restano nascosti dietro un interruttore, dove compaiono **smorzati e
      separati da una linea tratteggiata**: è la stessa regola che dalla
      v1.0.11 tiene fuori i crolli inventati, applicata al disegno. Le
      statistiche in alto parlano sempre e solo della serie attuale.
    Due dettagli venuti fuori guardando i tuoi dati veri: i controlli
    ravvicinati che registravano lo stesso prezzo (nei dati vecchi ce n'erano
    quattro in quindici secondi) si **fondono in un punto solo**, e i picchi
    veri restano — sulla *Fydraulis Harmonia* si vede l'annuncio a 170,64 €
    comparso il 6 luglio alle 17:53 e sparito **quarantaquattro secondi dopo**.
    L'asse dei prezzi **non parte da zero** (un movimento da 226 a 246 € su un
    asse zero-based sarebbe una riga piatta), ma i valori sono sempre scritti:
    la scala si legge, non si indovina.
58. **Il grafico nasce dalla carta (v1.0.27).** La finestra dello storico non
    compare più al centro dello schermo come una finestra qualsiasi: **si
    gonfia a partire dalla miniatura della carta** su cui hai fatto doppio
    clic, sfonda un po' la sua dimensione finale e rientra — il "pop" che dice
    da dove è arrivata. Chiudendola si **ritira nella stessa miniatura**.
    Per farlo bene la finestra ha perso la **cornice di Windows** ed è
    diventata una card del tema, con ombra e angoli tondi come le altre
    schermate delle impostazioni: una barra del titolo grigia che si ingrandiva
    avrebbe rovinato l'effetto. Al suo posto c'è una **✕ in alto a destra**, e
    la finestra si **trascina dall'intestazione**. Si chiude anche con Esc o
    col pulsante *Chiudi*; il clic fuori invece non fa niente — è una finestra
    che si guarda, non un menu.
    La **linea del grafico si disegna quando la finestra è atterrata**, non
    durante il volo: prima si disegnava mentre nessuno poteva vederla.
    Se in *Opzioni* le animazioni sono spente, la finestra si apre e basta.
59. **L'animazione, rifatta come si deve (v1.0.28).** La prima versione era
    **meccanica** e finiva con un **colpo di frusta**. Invece di ritoccare i
    numeri a occhio ho misurato quanti pixel cresce la finestra a ogni
    fotogramma, e i due difetti erano lì, in chiaro:
    - il **primo fotogramma saltava di 124 px** (da 60 a 184): la finestra non
      si vedeva partire, appariva già lanciata;
    - dopo essersi allargata **si ritirava per 11 fotogrammi**, fino a 13 px
      l'uno — 812 px/s all'indietro. Quello era il colpo di frusta.
    Ora il movimento è una **molla smorzata con partenza dolce**: primo
    fotogramma **+14 px**, sfondamento **+27 px** invece di 97, e il rientro
    massimo è di **4 px** che si spegne gradualmente (4, 3, 2, 1) — un
    assestamento, non un rinculo.
    Tre cose in più che rendevano il movimento "di gomma":
    - la finestra **non si deforma più**: partiva con le proporzioni della
      miniatura (quasi quadrata) e arrivava a quelle della finestra (larga),
      allungandosi per tutta la corsa. Ora parte già con le proporzioni
      giuste, centrata sulla carta, e cresce e basta;
    - **niente scatto allo scambio**: la finestra vera compare *sotto*
      l'immagine che sta volando, e solo dopo l'immagine sparisce. Prima
      restava un fotogramma di vuoto in mezzo;
    - la **linea del grafico** non parte più nello stesso istante in cui la
      finestra si assesta (i due movimenti si sommavano in un'unica frustata):
      aspetta un decimo di secondo e si disegna più lenta.
    I fotogrammi erano già a 62 al secondo anche prima: il problema non era la
    velocità del computer, era la forma del movimento.
60. **La linea non "sciabola" più (v1.0.29).** Sistemata la finestra, restava
    la comparsa del tratto: partiva **di scatto, aggressiva**. Due cause,
    misurate come prima:
    - la curva era una *OutCubic*, che parte alla **velocità massima**: il
      primo fotogramma scopriva **48 px** di grafico e poi rallentava fino a
      fermarsi. Ora accelera, corre e si posa: **primo fotogramma 1 px**,
      punta a 23 px (metà di prima), ultimo di nuovo 1 px, il tutto in 0,8
      secondi invece di 0,6;
    - il tratto veniva scoperto da una **tendina dal bordo netto** che correva
      sul grafico, e un bordo verticale duro in movimento si legge come una
      sciabolata. Ora il bordo è **sfumato**: la linea si materializza invece
      di essere svelata da un taglio.
61. **La linea si disegna UNA volta sola (v1.0.30).** Difetto introdotto dalle
    due versioni precedenti: il tratto compariva e **subito dopo si rifaceva
    da capo**. Motivo: la comparsa partiva da sola nel momento in cui il
    grafico riceveva i dati — cioè mentre la finestra era ancora in volo,
    quindi invisibile — e all'atterraggio ne vedevi la coda; poi ripartiva da
    zero quella "vera". Ora la comparsa non parte più da sola: la lancia solo
    chi mostra il grafico, una volta, a finestra ferma.
62. **La carta dentro la finestra dello storico (v1.0.31).** A sinistra del
    grafico ora c'è **l'immagine della carta**, grande, con la sua ombra — la
    finestra parla di lei, ed era l'unica a non esserci. La finestra è anche
    **un po' più larga** (da 690 a 870 px) per fare posto senza togliere spazio
    al grafico.
    Vale la stessa scala di ripieghi di sempre: stampa esatta → arte di
    un'altra stampa col timbro **"Stock"** → cornice vuota. E soprattutto
    **nessuna richiesta in più a CardTrader**: l'immagine è quella già
    scaricata per l'anteprima; se non c'è ancora, si mostra intanto la
    miniatura della riga e la grande prende il suo posto appena arriva.
    **Bug del grafico trovato guardando una schermata:** su una carta con
    massimo 51,00 € l'asse dei prezzi si fermava a 50,00 e **la punta usciva
    dal riquadro**. L'ultimo valore dell'asse ora è sempre ≥ del massimo dei
    dati.
63. **Modulo DATABASE (v1.1.0).** Il secondo modulo del toolbox: **tutte le
    carte Yu-Gi-Oh!**, cercabili e consultabili, dalla fonte YGOPRODeck.
    Nel menu laterale compare da solo, accanto a Market Watch.
    - **14.477 carte scaricate una volta e tenute sul tuo computer.** Non è
      una scelta nostra: la loro guida chiede espressamente di conservare i
      dati in locale e di non interrogare l'API a ogni ricerca. In cambio la
      ricerca è **istantanea e funziona anche senza rete**. Il primo
      scaricamento sono ~24 MB in pochi secondi; poi l'app controlla da sola
      se è uscita una versione nuova e te lo dice, senza scaricare niente.
    - **Ricerca in italiano.** Cercando *distruggi* si trovano 1.889 carte:
      oltre all'inglese scarichiamo anche i **testi italiani** (ci sono per
      11.599 carte su 14.477; per le altre, in genere le più recenti, la
      versione italiana non esiste e si vede l'inglese, detto chiaramente).
      Nell'elenco il nome italiano sta sotto quello inglese, e nella scheda
      un pulsantino **EN** mostra il testo originale.
    - **Filtri** per tipo, razza, attributo, archetipo (651!), livello e ban
      list. Le tendine si riempiono con quello che c'è davvero nei dati, non
      con elenchi scritti a mano che invecchierebbero.
    - **Ban list** con badge colorato per TCG, OCG e Goat, e un filtro per
      vedere solo le 315 carte in lista.
    - **Scheda** con immagine grande, tipo, statistiche, testo dell'effetto e
      i set in cui la carta è stata stampata.
    - **Ponte con Market Watch**: il pulsante *Segui i prezzi* porta la carta
      nella ricerca dell'altro modulo. Passa il NOME e non sceglie al posto
      tuo: YGOPRODeck ragiona per carta, CardTrader per singola stampa
      (rarità + espansione, prezzi diversissimi), e indovinare quale volevi
      sarebbe inventare.
    Nota sulle immagini: si scaricano **una alla volta e solo quelle che
    servono a schermo**, e restano salvate sul disco per sempre. YGOPRODeck
    mette in blacklist chi tira immagini a volume, e scaricarle tutte
    significherebbe ~400 MB.
64. **Database, prime correzioni (v1.1.1).**
    - **Elenco essenziale**: via le colonne *Tipo* e *Ban*. Restano immagine e
      nome (italiano sotto l'inglese); tipo e stato in ban list si leggono
      nella scheda, dove c'è spazio per dirli per intero invece che in una
      colonna stretta. Sparita anche l'intestazione: con una colonna sola non
      diceva niente.
    - **Miniature tagliate**: le immagini nell'elenco erano mozzate sopra e
      sotto. Causa: il tema dà alle righe della tabella 8 px di margine sopra
      e sotto, così in una riga da 78 px a un'immagine da 70 ne restavano 61.
      Ora l'altezza della riga tiene conto del margine.
    - **Immagine della scheda**: ora si ri-adatta da sola. Prima, rimpicciolendo
      la finestra, veniva tagliata anche lei.
65. **La carta si prende la pagina (v1.1.2).** Niente più pannello laterale:
    scegliendo una carta dall'elenco, **la pagina diventa sua** — ricerca,
    filtri ed elenco spariscono, e restano l'immagine grande a sinistra e
    tutto il resto a destra. Si torna indietro col pulsante *← Torna
    all'elenco* o col tasto **Esc**.
    Il vantaggio è doppio: l'elenco ha tutta la larghezza quando serve
    scorrerlo, la carta tutta la larghezza quando serve leggerla, invece di
    stare stretti in due metà per sempre. L'immagine della carta è passata da
    230 a 320 px di larghezza e si adatta all'altezza della pagina.
66. **La lingua del testo segue l'app (v1.1.3).** Il testo delle carte partiva
    sempre in italiano: con l'app impostata in inglese era una sorpresa. Ora
    la lingua predefinita è **quella dell'interfaccia** — app in inglese,
    carte in inglese; app in italiano, carte in italiano.
    L'interruttore accanto a *Effetto* ora mostra **la lingua verso cui
    passi** (IT o EN), non quella che stai leggendo, e la scelta resta mentre
    sfogli le altre carte. Dove la traduzione italiana non esiste (2.878 carte
    su 14.477) il pulsante sparisce del tutto e l'etichetta lo dice, invece di
    lasciar credere che l'inglese sia una scelta tua.
    Nell'elenco il nome italiano resta sempre sotto quello inglese: lì serve a
    ritrovare una carta che hai in mano, in qualunque lingua sia stampata.
67. **Badge delle lingue, e traduzioni fuori dall'elenco (v1.1.4).**
    - **Nell'elenco solo il nome inglese**, quello canonico: la traduzione
      sotto ogni voce affollava senza aiutare a scorrere. La **ricerca**
      continua però a coprire entrambe le lingue — puoi cercare *cenere* e
      trovare *Ash Blossom*.
    - **Sulla carta ci sono i badge delle lingue** (EN / IT) in alto a destra.
      Quello acceso decide cosa leggi, e cambia **nome e testo insieme**, non
      solo l'effetto. Il nome inglese non si perde mai: con l'italiano acceso
      passa nella riga sotto, perché è quello con cui la carta si cerca, si
      scambia e si gioca.
    - Dove la traduzione non esiste, il badge IT resta **spento e
      disabilitato**, col perché nel suggerimento. Toglierlo del tutto
      avrebbe fatto ballare la fila e non avrebbe detto niente; spento dice
      "questa carta in italiano non c'è".
    Il predefinito resta la lingua dell'app, e la scelta fatta coi badge vale
    anche per le carte che apri dopo.
68. **Le ristampe in un riquadro, con i badge di sempre (v1.1.5).** L'elenco
    dei set in cui la carta è uscita non è più testo sfuso: ora è un
    **riquadro col bordo**, una riga per stampa, con il **codice set** e la
    **rarità** resi con gli **stessi badge del Market Watch** — la pillola
    teal del set e la pillola colorata della rarità (UR, ScR, QCSR…, coi loro
    colori foil), nome completo nel suggerimento.
    Non si tagliano più a dodici: si vedono **tutte**. Una staple esce in
    decine di set, e mettere "…" nascondeva proprio il dato che si era venuti
    a cercare; la pagina scorre.
    Per riusare gli stessi badge, codice set e rarità si sono spostati nel
    **cuore dell'app** invece di restare dentro il Market Watch: i due moduli
    non si conoscono fra loro, e un vocabolario visivo comune deve stare in un
    posto comune. Nel Market Watch non cambia niente di visibile.
69. **Ristampe: via il nome esteso, e ordine sensato (v1.1.6).**
    - **Niente più nome dell'espansione scritto per esteso**: occupava metà
      riquadro e si ripeteva identico per ogni rarità dello stesso set
      (*RA01-EN016* compariva otto volte di fila). Ora c'è **una riga per
      codice**, con tutte le sue rarità accanto: su *Ash Blossom* 34 stampe
      stanno in 21 righe. Il nome dell'espansione e la data di uscita sono nel
      suggerimento del codice — il dato c'è, non ruba spazio.
    - **Ordine cronologico** per data di uscita del set, e dentro ogni set le
      rarità dalla più comune alla più ricercata. Le date non erano nei dati
      delle carte: si prendono da un elenco a parte dei set (1.028 set, 170 KB
      una tantum). Chi le ha già scaricate non deve rifare niente: l'app si
      procura il pezzo mancante da sola alla prima apertura.
    - I set di cui la fonte non dà la data (5 su 1.028) finiscono **in fondo**,
      non in cima: una data mancante non deve spacciarsi per "uscito prima di
      tutti".
    Nota su alcune rarità strane: per 192 stampe su 44.190 (lo 0,4%)
    YGOPRODeck mette nel campo rarità cose come *2*, *3*, *New* o *European
    debut*. Non sono rarità, ma sono quello che dice la fonte: si mostrano in
    grigio neutro col testo originale nel suggerimento, senza inventare una
    classificazione che non esiste.
70. **Via le "rarità" che rarità non sono (v1.1.7).** Quei badge con scritto
    *2*, *3*, *New* o *European debut* non compaiono più: erano refusi della
    fonte finiti nel campo sbagliato, e un badge dava loro la dignità di un
    dato. Sono 192 stampe su 44.190 (lo 0,43%); dove capitavano, la riga
    mostra il codice del set senza badge.
    Il filtro **non è una lista di quei valori** — invecchierebbe al primo
    refuso nuovo. Passa quello che l'app riconosce come rarità **oppure** che
    contiene una parola da rarità, così una rarità inventata l'anno prossimo
    continua a vedersi. Verificato su tutti i 48 valori diversi presenti nel
    database: scartati esattamente gli 8 sbagliati, **nessuna rarità vera
    persa**.
71. **Solo il codice del SET, non quello della carta (v1.1.8).** Nelle
    ristampe si legge *MACR* invece di *MACR-EN036*: il numero della carta
    dentro il set non serviva a niente e allungava ogni riga.
    C'è però un caso in cui il codice corto **non basta**: 142 codici sono
    condivisi da più espansioni — *MVP1* vale per Movie Pack, Gold Edition,
    Secret Edition e Special Edition, e *JUMP* copre 70 promo diverse. Se la
    stessa carta esce in due di quelle, due badge identici uno sopra l'altro
    sarebbero indistinguibili: per quelle righe (e solo per quelle) resta il
    codice completo. La regola è "il codice più corto che resta univoco".
    Le espansioni restano comunque **righe separate**: raggruppare per codice
    avrebbe fuso prodotti diversi in uno solo.
    Corretto anche un difetto emerso qui: passando da una carta all'altra, il
    badge della ban list della carta PRECEDENTE restava disegnato sopra le
    statistiche di quella nuova.
72. **Riquadro dei formati (v1.2.0).** Sotto il testo della carta c'è un
    riquadro nuovo con tre righe: **TCG**, **OCG** e **Genesys**. I badge
    della ban list, che prima stavano sciolti accanto al tipo, sono finiti
    lì — sono la stessa informazione: cosa può fare quella carta, in quel
    formato.
    Tre casi che prima si confondevano e ora si distinguono:
    - **in ban list** → il badge con lo stato (Vietata / Limitata /
      Semi-limitata);
    - **legale e non in lista** → *3 copie*, che è la regola, non una stima;
    - **mai uscita in quel formato** → lo dice, invece di far credere che se
      ne possano giocare tre. (Il dato c'è: la fonte elenca in quali formati
      ogni carta è uscita.)
    **Punti Genesys**: 715 carte hanno un punteggio, le altre 13.762 valgono
    zero — e uno zero è un punteggio vero, non un dato mancante: se il
    punteggio non è ancora stato scaricato la riga lo dice chiaramente.
    Nota sul costo: il punteggio Genesys l'API lo dà **solo** chiedendo tutto
    il database col filtro apposito, cioè **altri 24 MB** per un numero a
    carta. La sincronizzazione passa da ~41 a ~65 MB e da 4 a 7 secondi
    circa. Non esiste un modo più leggero: verificato, il campo non compare
    nella risposta normale nemmeno chiedendo i dati estesi.
    Chi ha già il database deve premere **Aggiorna** una volta per avere i
    punteggi; fino ad allora la riga Genesys dice che il dato manca.
73. **Filtri col vocabolario del gioco (v1.2.1).** I filtri usavano i nomi dei
    campi dell'API, non quelli di Yu-Gi-Oh!, e due erano proprio sbagliati:
    - **"Razza" non esiste** nel gioco. Quel campo, per i mostri, è il
      **Tipo** (Drago, Guerriero, Mago…); per magie e trappole è la
      **Proprietà** (Normale, Rapida, Continua, Equipaggiamento, Terreno,
      Rituale, Counter). L'API li mette tutti insieme in un campo solo: ora
      la tendina cambia nome e contenuto a seconda della carta scelta, così
      non ti offre "Counter" mentre cerchi un mostro.
    - **"Tipo" ora è "Carta"**, con le tre opzioni vere: **Mostro, Magia,
      Trappola**.
    - Siccome così si perdeva la possibilità di cercare Xyz, Synchro o Link,
      c'è una tendina **Categoria** con Normale, Effetto, Rituale, Fusione,
      Synchro, Xyz, Pendulum, Link, Tuner, Flip, Gemini, Spirit, Toon, Union.
    Categoria, Attributo e Livello/Rango riguardano **solo i mostri**:
    scegliendo Magia o Trappola si spengono e si azzerano, perché un filtro
    invisibile ancora attivo darebbe zero risultati senza spiegare perché.
    Contati sul database: 9.308 mostri, 2.864 magie, 2.075 trappole (le 230
    che mancano all'appello sono Skill Card e Token, che non sono nessuna
    delle tre); 599 Xyz, 473 Link, 816 Draghi, 571 magie Rapide, 179 trappole
    Counter.
74. **Ricerca sul modello di DuelingBook (v1.3.0).** Presa la loro maschera
    come riferimento, mancavano quattro cose:
    - **Nome e Testo sono due campi separati.** Prima ce n'era uno solo che
      cercava in entrambi: chi cercava *dragon* si trovava anche le centinaia
      di carte che *nominano* un drago nel proprio effetto. Ora sono 891
      contro 1.075, e si possono combinare (nome *dragon* + testo *destroy*:
      403 carte).
    - **Categoria e abilità sono due tendine.** Un mostro è Synchro **e**
      Tuner insieme, non l'uno oppure l'altro: con una tendina sola quella
      coppia non si poteva cercare (sono 59 carte).
    - **Intervalli** per Livello/Rango, ATK e DEF, con estremi inclusi e
      ognuno indipendente: si può dare solo il minimo o solo il massimo.
    - **Ordinamento** (alfabetico, ATK, DEF, Livello, più recenti) e
      **pagine**. Prima i risultati si tagliavano a 300 e il resto era
      **irraggiungibile**; ora si sfoglia con ◀ ▶, cento per pagina.
    Come prima, i filtri da mostro si spengono con Magia o Trappola
    selezionata.
75. **L'app si aggiorna da sola (v1.4.0).** Prima l'avviso c'era: un'etichetta
    gialla nell'header del Market Watch. Solo che l'app si apre sul
    **Database** (primo in ordine alfabetico), quindi stava nella pagina che
    non si guarda — e infatti l'installazione su questo PC era rimasta alla
    **1.0.24**, nove release indietro, con l'avviso attivo e la Release
    pubblicata. Un avviso che nessuno vede non è un avviso.
    Ora:
    - **l'avviso è un piede sotto il menu laterale**, quindi si vede da
      qualunque pagina;
    - **il download parte da solo**, in sottofondo, senza chiedere niente. Non
      c'è una barra invadente: la scritta passa da *"La sto preparando…"* a
      *"Versione X.Y.Z pronta"*;
    - **un pulsante, "Riavvia e aggiorna", fa tutto**: chiude l'app, installa,
      la riapre. Meno di un minuto, e a schermo si vede solo la barra di
      avanzamento dell'installazione.
    Cose che si notano solo se vanno male, e sono state fatte per quello:
    - **se il download non riesce non compare nessun errore** — non l'aveva
      chiesto nessuno. Resta l'avviso con *Apri la pagina*, che è il modo
      manuale di sempre e non è stato toccato;
    - **se l'installazione non parte** (antivirus, file in quarantena) **l'app
      non si chiude**: lo dice e offre *Apri la cartella* / *Apri la pagina*;
    - se è in corso una sincronizzazione o un giro prezzi, **chiede prima**:
      è l'unico momento in cui si possono perdere quattro minuti di lavoro;
    - al riavvio l'app **controlla di essere diventata davvero la versione
      nuova**. Se non lo è lo dice **una volta sola**, e quella versione non
      si riscarica più da sola — altrimenti sarebbero 48 MB a ogni avvio;
    - un installer già scaricato e verificato **non si riscarica**.
    Quanto dura: **quattro secondi** nei due giri in cui l'app era a regime,
    **trentaquattro** in quello in cui il pulsante è stato premuto quaranta
    secondi dopo l'avvio. La differenza non è l'installazione (un secondo) ma
    l'attesa dell'installer: se l'app fa in tempo a chiudersi da sé non aspetta
    nessuno, altrimenti Windows ci mette il suo mezzo minuto a chiuderla —
    lo stesso mezzo minuto che ogni aggiornamento manuale ha pagato finora.
    In entrambi i casi a schermo c'è la barra di avanzamento, e l'app torna su.

## 4. Note operative importanti

- **Non fare raffiche di richieste** verso CardTrader: è dietro Cloudflare e può
  bloccare temporaneamente l'IP (errori 403 su immagini e prezzi). Si sblocca da
  solo dopo un po'.
- Se cambia lo **schema del DB** in sviluppo e qualcosa non torna, si può
  cancellare `~\.ygo_toolbox\ygo_toolbox.db` (si perde la watchlist) e
  risincronizzare.
- Le funzioni di rete (prezzi, immagini) hanno bisogno di connessione e token
  valido.
