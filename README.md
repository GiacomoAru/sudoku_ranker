# Sudoku Logic Lab

Motore logico, archivio canonico e interfaccia web LAN per l'analisi dei
Sudoku classici 9×9.

## Struttura

```text
sudoku_app/
    core/       motore, tecniche, canonicalizzazione e visualizzazioni
    archive/    persistenza JSON e indice delle classi isomorfe
    web/        API FastAPI, coda dei job e interfaccia browser

archives/
    offline/    archivio predefinito per notebook e script
    online/     archivio isolato usato dal server web
    backups/    copie storiche dell'archivio

notebooks/      notebook di analisi e manutenzione
examples/       esempi Python
scripts/        gestione del server LAN
tests/          test automatici
```

## Scale di difficoltà

Ogni analisi espone tre valori complementari:

- **Difficoltà Tecnica** (`technical_difficulty`): massimo rating Sudoku
  Explainer richiesto;
- **Carico di risoluzione** (`resolution_load`): somma dei punteggi HoDoKu;
- **Difficoltà percepita** (`perceived_difficulty`): valore sulla stessa scala
  numerica SE, corretto soltanto per scarsità e ripetizione delle mosse.

La label dipende esclusivamente dalla Difficoltà Tecnica. HoDoKu e difficoltà
percepita sono valori indipendenti, utili per confrontare e ordinare i puzzle.
Ogni Sudoku salvato o analizzato deve avere esattamente una soluzione; questa
garanzia è esposta anche nel JSON come `unique_solution`.

## Riconoscimento da foto

L'interfaccia LAN accetta foto JPEG, PNG e WebP fino a 12 MB. La pipeline
individua la griglia, corregge la prospettiva, riconosce le cifre e compila gli
81 input. Le celle incerte restano evidenziate e devono essere controllate
prima di avviare l'analisi.

Il rilevatore include un fallback per pagine fotografate curve o con bordi
discontinui e ridimensiona automaticamente le sorgenti ad alta risoluzione.

Ogni foto ricevuta viene conservata in `archives/online/photos/` insieme
all'anteprima raddrizzata, alle confidenze OCR e, dopo l'invio, alla griglia
corretta dall'utente. Questo crea progressivamente un dataset supervisionato
senza mescolare le immagini con l'archivio offline.


Installazione:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Test:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Per avviare l'interfaccia in locale, LAN o tramite un link HTTPS pubblico
raggiungibile dal telefono vedere [WEB_LAN.md](WEB_LAN.md).


# Prossime Modifiche:
1. **Modificare interfaccia per:**

   1. Modificare manualmente i campi e le scritte del sito
      1. ripulire scritte superflue o fuori contesto
      3. inserire riferimento a github e creatore
   2. ★ rivedere completamente meccanismo di evidenziazione celle per spiegazione della mossa, chiarire celle principali, secondarie ecc. Mostrare anche i candidates per cella e rivedere metodi di evidenziazione singola di candidati.
   6. ★ Renderlo carino da telefono.
   7. aggiungere un riferimento tra step visualizzato e punto della catena nel grafico o heatmap, magari usare plotly che è più adatta per  interazione web?
   10. creare immagini "vuote" da mostrare al caricamento pagina e quando si invai un sudoku irrisolvibiel
   11. importare immagini oltre a scattarle

2. **collegamento internet**
   1. il collegamento è lentiiiissimo, normale? soprattutto per le foto
   2. favicon.io ??? risolvere
   3. attualmente salva tutte le foto anche quelle senza sudoku... cercare di vfare una scrematura
   4. gestione privacy
   5. sicurezza database
   6. cooldown necessari per  utente?

3. **Modifiche OCR**
   1. ★ creare riconoscimento estremi griglia, e dare la possibilità di modificarli sopra la foto, anche NON quadrato causa deformazioni prospettiche, poi avendo gli estremi continuare con la normale pipeline, circa come googledrive fa la scanerizzazione documenti
   2. riuscire a riconoscere bene temi scuri, magari usando il negativo?

2. **Migliorare il solver** IMPORTANTISSIMO, CREDO CHE NON VENGA SEGUITO L'ORDINAMENTO DELLE TECNICHE PER SEMPLICITA SE!!!!
   3. grafici:
      1. scala logaritmica nella catena per l'asse della numerosità di tecniche, ma con 1 allineato con uno a sinistra
      2. legenda esterna (sotto) della catena

   4. miglirare stampe del server rispetto a analisi
   5. implementare pattern engine per Unique Loop (6+ cells)
   6. fare che ricerche profile usino deep in memoria, e profile bassi usino alti, anche totalmente vsto che sono solo meglio.
   

3. **Integrare riconoscimento Sudoku via foto:**
   1. migliorare periodicamente con le nuove foto
   1. Allenare e confrontare modelli specializzati a partire dall'archivio raccolto

4. **Ampliare interfaccia web**
   1. dare possibilità di cambiare tipo di analisi (deep, profile window etc) e gestire al meglio possibile archivio e caching
   2. trivialize
   3. simmetrize

5. **Implementare generatore offline di Sudoku**
