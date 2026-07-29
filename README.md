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

- `max_difficulty`: rating Sudoku Explainer della tecnica massima;
- `hodoku_score` e `hodoku_level`: stima basata sui default HoDoKu 2.2.4;
- `perceived_difficulty`: carico percepito riscalato monotonamente da 1 a 10.

La label editoriale è determinata dalla tecnica cognitivamente più difficile,
non dal numero di passi. Coppie e locked candidates restano sotto i basic fish
e i single-digit pattern: X-Wing e Skyscraper sono quindi distinti come
tecniche `Hard` secondo la tassonomia HoDoKu.

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
      2. valutare la migrazione della chiave dati `perceived_difficulty` a `perceived`, preservando gli archivi esistenti.
   2. ★ rivedere completamente meccanismo di evidenziazione celle per spiegazione della mossa, chiarire celle principali, secondarie ecc. Mostrare anche i candidates per cella e rivedere metodi di evidenziazione singola di candidati.

   3. riordinare il json per posticipare catena e altre liste
   4. cambiare i campi necessari al salvataggio del sudoku, renderli opzionali e nascosti da tendina, e gestire normalizzazione di testo ecc. Magari rivedere anche 
   tecniche di salvataggio e dati salvati
   5. rendere le varie "opzionni" nascoste in tendida di default, in modo da non mostrare tutto ma solo quel che si vuole.
   6. ★ Renderlo carino da telefono.
   7. aggiungere un riferimento tra step visualizzato e punto della catena nel grafico o heatmap
   10. creare immagini "vuote" da mostrare al caricamento pagina e quando si invai un sudoku irrisolvibiel
   11. importare immagini oltre a scattarle

2. **collegamento internet**
   1. il collegamento è lentiiiissimo, normale? soprattutto per le foto
   2. favicon.io ??? risolvere
   3. attualmente salva tutte le foto anche quelle senza sudoku... cercare di vfare una scrematura

3. **Modifiche OCR**
   1. ★ creare riconoscimento estremi griglia, e dare la possibilità di modificarli sopra la foto, anche NON quadrato causa deformazioni prospettiche, poi avendo gli estremi continuare con la normale pipeline, circa come googledrive fa la scanerizzazione documenti

2. **Migliorare il solver**
   1. chiarire stato "stuck" e quando un sudoku non ha soluzione unica, magari darne una e aggiungere l'ultimo step di soluzione che è andare a caso.
   1. gestire casi triviali di sudoku che attualmente causano una lunga analisi (1 solo numero)
   2. migliorare ricerca profile:
      1. in modo da non cercare tutte le tecniche possibili se richiedono molta computazione, magari limitare massimo a >= 10??
      2. ridurre finestra standard a 2
   3. grafici:
      1. scala logaritmica nella catena per l'asse della numerosità di tecniche, ma con 1 allineato con uno a sinistra
      2. legenda esterna (sotto) della catena

   4. miglirare stampe del server rispetto a analisi
   5. implementare pattern engine per Unique Loop (6+ cells)

3. **Integrare riconoscimento Sudoku via foto:**
   1. migliorare periodicamente con le nuove foto
   1. Allenare e confrontare modelli specializzati a partire dall'archivio raccolto

4. **Ampliare interfaccia web**
   1. dare possibilità di cambiare tipo di analisi (deep, profile window etc) e gestire al meglio possibile archivio e caching
   2. trivialize
   3. simmetrize

5. **Implementare generatore offline di Sudoku ed esplorare la generazione e difficoltà.**
