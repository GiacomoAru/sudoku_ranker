# Roadmap di Sudoku Ranker

Questo documento raccoglie le modifiche pianificate per il progetto.

Le priorità indicate sono:

- **P0**: problema bloccante o rischio di risultati errati;
- **P1**: miglioramento importante;
- **P2**: miglioramento utile ma non urgente;
- **P3**: idea futura o sperimentale.

## 1. Correttezza e prestazioni del solver

### P0

- Verificare che il solver rispetti sempre l’ordinamento delle tecniche per difficoltà SE.
- Aggiungere test automatici che controllino che una tecnica più difficile non venga scelta quando ne esiste una più semplice.
- Verificare il tie-break tra tecniche con difficoltà uguale e tra conclusioni equivalenti.
- Misurare il tempo impiegato da ogni tecnica durante l’analisi.
- Controllare che il limite massimo di risultati venga applicato dentro tutte le funzioni di ricerca, non soltanto dopo la generazione delle mosse.

### P1

- Migliorare i messaggi del server durante le analisi lunghe.
- Rendere espliciti nei log:
  - tecnica in esecuzione;
  - tempo impiegato;
  - numero di risultati distinti trovati;
  - utilizzo della cache;
  - motivo dell’interruzione anticipata.
- Rivedere il caching delle modalità di analisi:
  - un risultato `deep` deve poter soddisfare richieste `profile` e `superficial`;
  - un profilo con finestra maggiore deve poter soddisfare profili con finestra minore;
  - la cache non deve forzare calcoli più costosi di quelli richiesti;
  - i risultati parziali non devono essere scambiati per inventari completi.
- Implementare un pattern engine per Unique Loop con almeno 6 celle.

## 2. Metriche e grafici

### P1

- Calibrare le soglie del carico risolutivo usando il database reale.
- Studiare la distribuzione di:
  - difficoltà tecnica;
  - carico risolutivo;
  - difficoltà di individuazione;
  - numero di step;
  - tecniche più frequenti.
- Verificare la correlazione tra metriche automatiche e difficoltà percepita dagli utenti.

### P2

- Usare una scala logaritmica per la numerosità delle tecniche nella catena, mantenendo il valore 1 chiaramente allineato.
- Spostare la legenda della catena sotto il grafico.
- Collegare lo step mostrato nel player al punto corrispondente nella catena e nella mappa delle tecniche.
- Valutare Plotly o un’altra libreria interattiva per hover, selezione dello step e sincronizzazione con la griglia.
- Mostrare grafici vuoti o uno stato illustrato prima della prima analisi e in caso di puzzle non risolto.

## 3. Interfaccia web

### P1

- Ripulire le scritte superflue o fuori contesto.
- Mantenere un riferimento discreto all’autore e al repository GitHub.
- Rivedere completamente il sistema di evidenziazione delle mosse:
  - celle principali;
  - celle secondarie;
  - candidati coinvolti;
  - candidati eliminati;
  - collegamenti e catene;
  - distinzione chiara tra valori inseriti e candidati.
- Mostrare i candidati dentro ogni cella durante la spiegazione.
- Migliorare significativamente la resa su telefono.

### P2

- Consentire di scegliere dall’interfaccia:
  - modalità `superficial`, `profile` o `deep`;
  - ampiezza della finestra profile;
  - limite massimo di risultati per tecnica.
- Integrare la gestione dell’archivio e della cache nell’interfaccia.
- Esporre le funzioni `trivialize` e `symmetrize`.
- Consentire sia di scattare sia di importare immagini già presenti sul dispositivo.
- Correggere favicon e metadati del sito.

## 4. OCR e acquisizione della griglia

### P1

- Permettere all’utente di correggere manualmente i quattro vertici della griglia sopra la foto.
- Supportare un quadrilatero prospettico non necessariamente rettangolare.
- Mostrare un’anteprima aggiornata dopo lo spostamento dei vertici.
- Continuare la pipeline OCR usando i vertici confermati dall’utente.
- Migliorare il riconoscimento di temi scuri e verificare il comportamento del negativo automatico.

### P2

- Salvare separatamente:
  - rilevamento automatico;
  - correzione manuale dei vertici;
  - lettura OCR iniziale;
  - correzione finale dell’utente.
- Individuare e scartare prima del salvataggio le immagini che non contengono una griglia Sudoku plausibile.
- Migliorare periodicamente il classificatore usando le immagini corrette raccolte nell’archivio.
- Allenare e confrontare modelli specializzati sul dataset reale.
- Preparare test OCR con:
  - fotografie inclinate;
  - pagine curve;
  - riflessi;
  - temi scuri;
  - griglie colorate;
  - cifre stampate e scritte a mano.

## 5. Collegamento Internet e distribuzione

### P0

- Analizzare la lentezza del collegamento pubblico, soprattutto durante il caricamento delle fotografie.
- Misurare separatamente:
  - upload dell’immagine;
  - riconoscimento OCR;
  - analisi del Sudoku;
  - generazione dei grafici;
  - salvataggio su disco.

### P1

- Definire una politica di privacy per le fotografie caricate.
- Stabilire tempi di conservazione e modalità di cancellazione.
- Proteggere l’archivio da accessi non autorizzati.
- Validare dimensioni, formato e contenuto dei file ricevuti.
- Aggiungere rate limiting o cooldown per utente o indirizzo IP.
- Limitare il numero massimo di job simultanei.
- Impedire che richieste ripetute saturino CPU, memoria o spazio su disco.

### P2

- Valutare una distribuzione stabile con dominio o sottodominio permanente.
- Preparare configurazione di produzione, logging e backup.
- Separare chiaramente ambiente locale, test e pubblico.

## 6. Archivio e dataset

### P1

- Conservare sempre i valori numerici grezzi delle metriche, separati dalle label.
- Rendere possibile ricalcolare le label senza rieseguire l’intera soluzione.
- Gestire correttamente il salvataggio di un Sudoku già presente:
  - mostrare i metadati esistenti;
  - permettere la modifica;
  - evitare duplicati;
  - conservare una cronologia minima delle modifiche importanti.
- Verificare periodicamente la consistenza dell’indice canonico.

### P2

- Creare strumenti per analizzare il database e generare statistiche.
- Preparare esportazioni in JSON, CSV e formati adatti all’addestramento OCR.
- Separare chiaramente dati pubblicabili, privati e diagnostici.

## 7. Generazione e trasformazione dei Sudoku

### P2

- Integrare nell’interfaccia la simmetrizzazione dei puzzle.
- Integrare la funzione di trivializzazione.
- Salvare le trasformazioni applicate e il rapporto con il puzzle originale.

### P3

- Implementare un generatore offline di Sudoku.
- Generare puzzle in batch e analizzarli prima dell’inserimento nell’archivio.
- Consentire filtri per:
  - difficoltà tecnica;
  - carico risolutivo;
  - difficoltà di individuazione;
  - tecnica obbligatoria;
  - simmetria;
  - numero di indizi.

## Prossimi interventi consigliati

Ordine suggerito per le prossime modifiche:

1. verificare con test l’ordinamento SE delle tecniche;
2. profilare le tecniche più lente;
3. completare il limite interno dei risultati in ogni tecnica;
4. migliorare evidenziazione e visualizzazione dei candidati;
5. aggiungere la correzione manuale dei vertici OCR;
6. misurare la lentezza del collegamento pubblico;
7. definire privacy, sicurezza e limiti del servizio;
8. calibrare le metriche usando il database raccolto.
