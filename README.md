# Sudoku Ranker

Motore logico, archivio canonico e interfaccia web per l’analisi di Sudoku classici 9×9.

Il progetto consente di inserire o fotografare un Sudoku, verificarne l’unicità, analizzarne la soluzione passo per passo, stimarne la difficoltà e archiviarlo evitando duplicati dovuti a trasformazioni isomorfe.

Sviluppato da [Giacomo Aru](https://github.com/GiacomoAru).

Repository: [github.com/GiacomoAru/sudoku_ranker](https://github.com/GiacomoAru/sudoku_ranker)

## Funzionalità principali

- analisi logica passo per passo;
- motore Fish parametrico per varianti Basic, Franken e Mutant;
- Simple e Multi Colors sul grafo delle coppie coniugate;
- X-Chain, XY-Chain, AIC, Nice Loop e varianti Grouped sul grafo d'implicazione condiviso;
- motore ALS/RCC comune per ALS-XZ, ALS-XY-Wing, ALS Chain, Death Blossom
  e generalized wings fino a TUVWXYZ-Wing;
- ordinamento delle tecniche secondo difficoltà crescente;
- tre metriche complementari di difficoltà;
- riconoscimento locale da foto, senza servizi esterni;
- correzione prospettica della griglia;
- supporto a immagini JPEG, PNG e WebP;
- riconoscimento di griglie con tema chiaro o scuro;
- archivio JSON separato per uso offline e web;
- canonicalizzazione MinLex e raggruppamento dei Sudoku isomorfi;
- verifica obbligatoria della soluzione unica;
- visualizzazione della catena di risoluzione, dei candidati coinvolti e
  delle tecniche disponibili;
- accesso locale, tramite rete LAN o tunnel HTTPS.

## Struttura del progetto

```text
sudoku_app/
    core/       motore, tecniche, Fish, difficoltà, canonicalizzazione e visualizzazioni
    archive/    persistenza JSON e indice delle classi isomorfe
    web/        API FastAPI, coda dei job e interfaccia browser

archives/
    offline/    archivio predefinito per notebook e script
    online/     archivio isolato usato dal server web
    backups/    copie storiche dell’archivio

notebooks/      notebook di analisi e manutenzione
examples/       esempi Python
scripts/        gestione del server LAN
tests/          test automatici
```

## Metriche di difficoltà

Ogni analisi espone tre valori distinti.

### Difficoltà tecnica

`technical_difficulty`

È il massimo rating Sudoku Explainer richiesto durante la soluzione. Descrive la tecnica più difficile necessaria per completare il puzzle.

### Carico risolutivo

`resolution_load`

È il lavoro logico cumulativo della soluzione. Ogni step contribuisce con un peso crescente in modo esponenziale rispetto al proprio rating SE, così le tecniche avanzate incidono molto più delle tecniche elementari.

Questa metrica distingue, per esempio, un Sudoku con una sola tecnica difficile da uno che richiede molti passaggi difficili o ripetuti.

Le soglie attuali sono provvisorie e potranno essere calibrate meglio usando la distribuzione dei valori raccolti nel database.

### Difficoltà di individuazione della mossa

`move_discovery_difficulty`

Stima quanto sia difficile trovare la prossima mossa disponibile. Considera:

- il numero effettivo di mosse accessibili;
- la distanza SE rispetto alla mossa più semplice;
- la posizione delle alternative nell’inventario ordinato;
- la presenza di esiti logici distinti.

Il valore è normalizzato su una scala da 1 a 10.

Le tre metriche sono indipendenti e devono essere interpretate insieme.

## Modalità di analisi

Il motore supporta tre modalità:

- `superficial`: conserva soltanto la frontiera delle mosse più semplici;
- `profile`: esplora una finestra configurabile sopra la difficoltà minima;
- `deep`: costruisce l’inventario logico completo disponibile.

La modalità predefinita è `profile`, con finestra attuale pari a `1.5` punti SE.

Il limite massimo di risultati per tecnica viene applicato durante la ricerca, così le tecniche costose possono interrompersi appena è stato raccolto un numero sufficiente di esiti distinti.

## Motore Fish

Il modulo `sudoku_app.core.fish` rappresenta ogni configurazione mediante base
set e cover set e usa la stessa pipeline per X-Wing, Swordfish e Jellyfish.
La classificazione strutturale distingue Fish Basic, Franken e Mutant e gestisce
le varianti Finned, Sashimi e Siamese; Endo-Finned e Cannibalistic sono esposti
come modificatori del pattern. Le conclusioni equivalenti vengono consolidate
prima di essere consegnate al solver.

La ricerca procede per livelli Basic, Franken e Mutant e applica limiti
espliciti alle configurazioni complesse, così il costo delle varianti avanzate
resta controllato durante l’analisi ordinaria.

## Coloring

Il modulo `sudoku_app.core.coloring` riusa gli archi X forti dello
`StaticImplicationGraph`. Per ogni cifra separa le componenti connesse delle
coppie coniugate, ne verifica la bipartizione e assegna due colori opposti.

Il detector distingue esplicitamente Color Trap, Color Wrap e Multi Colors
Type 1/2. Le varianti Multi operano soltanto fra componenti scollegate; ogni
conclusione conserva il pattern colorato e una prova `ProofDAG` con archi
alternati `peer`/`x`.

## AIC e Nice Loop

Lo `StaticImplicationGraph` conserva per ogni arco i candidati e le case che
ne giustificano il weak o strong link. Questi supporti appartengono al
`ProofDAG`; `chains` e `chain_links` sono soltanto viste derivate.

Il motore classifica strutturalmente X-Chain, XY-Chain, Discontinuous Nice
Loop, AIC Type 1/2 e Continuous Nice Loop. Ogni percorso deve alternare
realmente strong e weak link: le AIC derivano le conclusioni dalla polarità
degli endpoint, mentre un loop continuo elimina soltanto attraverso i supporti
delle weak link rese strong dal resto del ciclo.

## Group Nodes

Il medesimo grafo accetta `GroupNode` che rappresentano la proposizione OR
«la cifra occupa una di queste celle» in un segmento linea-box. Un weak link
verso un gruppo richiede visibilità su tutti i suoi membri; un strong link
esiste soltanto quando due nodi partizionano esattamente le posizioni della
cifra in una casa.

La classificazione mantiene separati `Grouped X-Chain`, `Grouped AIC`,
`Grouped Nice Loop` e `Grouped Continuous Nice Loop`. Le prove serializzate e
le evidenze candidate-level conservano il gruppo come nodo distinto: una
catena composta soltanto da candidati singoli non riceve mai il nome Grouped.

## Almost Locked Sets

I moduli `sudoku_app.core.als` e `sudoku_app.core.als_graph` enumerano una sola
volta gli Almost Locked Sets e costruiscono il grafo dei Restricted Common
Candidates. Gli ALS equivalenti sono deduplicati e un RCC esiste soltanto se
ogni sua occorrenza in un ALS vede ogni occorrenza nell'altro.

Lo stesso motore produce Singly e Doubly Linked ALS-XZ, ALS-XY-Wing, ALS
Chain, Death Blossom e ALS-AIC. WXYZ, VWXYZ, UVWXYZ e TUVWXYZ-Wing sono
classificazioni strutturali delle corrispondenti deduzioni ALS-XZ; il payload
mantiene sia il nome specifico sia il parent ALS che ne giustifica la logica.
Le prove conservano ogni ALS come nodo strutturato nel `ProofDAG`.

## Riconoscimento da foto

L’interfaccia accetta immagini JPEG, PNG e WebP fino a 12 MB.

La pipeline:

1. individua il quadrilatero della griglia;
2. corregge la prospettiva;
3. divide la griglia in 81 celle;
4. isola i glifi;
5. classifica le cifre con descrittori HOG ed esempi sintetici;
6. segnala le letture incerte;
7. applica soltanto correzioni conservative per conflitti evidenti.

Il riconoscimento prova automaticamente anche il negativo dell’immagine quando la griglia presenta uno sfondo scuro o quando il rilevamento normale fallisce.

Le celle con bassa confidenza devono essere controllate manualmente prima dell’analisi.

## Archivio fotografico

Le immagini ricevute dal server possono essere conservate in:

```text
archives/online/photos/
```

Per ogni acquisizione possono essere salvati:

- immagine originale;
- anteprima raddrizzata;
- coordinate della griglia;
- confidenze OCR;
- lettura automatica iniziale;
- griglia corretta dall’utente.

Questo archivio può diventare un dataset supervisionato per migliorare periodicamente il riconoscimento.

Prima di rendere pubblico il servizio è necessario definire chiaramente conservazione, cancellazione e trattamento delle immagini.

## Installazione

Da PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Il corpus compatto e permanente del solver può essere eseguito da solo con:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_solver_corpus -v
```

Origini, formato e procedura di estensione sono documentati in
[`tests/fixtures/solver_corpus/README.md`](tests/fixtures/solver_corpus/README.md).

Le mosse espongono inoltre una spiegazione strutturata e una mappa
`visual_evidence` a livello di candidato. Per una vista testuale pencil-mark
si possono usare `format_candidate_grid(...)` e `print_candidate_grid(...)`
dal modulo `sudoku_app.core.move_presentation`.

Nel player web le celle che forniscono le premesse sono distinte da quelle
modificate. Le catene mostrano esclusivamente le inferenze dichiarate dal
`ProofDAG`: linea continua per gli strong link, tratteggiata per i weak link e
frecce bidirezionali soltanto per equivalenze dimostrate esplicitamente.

## Avvio dell’interfaccia web

Per avviare il server in locale, nella rete LAN o tramite un collegamento HTTPS pubblico, consulta:

[WEB_LAN.md](WEB_LAN.md)

## Stato del progetto

Il progetto è in sviluppo attivo. Le metriche, le soglie di classificazione e il riconoscimento OCR continueranno a essere calibrati usando i Sudoku e le immagini raccolti nell’archivio.

Le attività pianificate sono raccolte in [ROADMAP.md](ROADMAP.md).

## Autore

**Giacomo Aru**

- GitHub: [GiacomoAru](https://github.com/GiacomoAru)
- Repository: [sudoku_ranker](https://github.com/GiacomoAru/sudoku_ranker)
