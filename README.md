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


Installazione:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Test:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Per avviare e gestire l'interfaccia LAN vedere [WEB_LAN.md](WEB_LAN.md).


# Prossime Modifiche:
1 - modificare interfaccia per:
    1.1 - fare che le due sezioni (sinistra e destra) scorrano entrambe e non venga data precedenza a quella di destra, se no è lungo arrivare al tasto invia
    1.2 - mostrare info sulla canonicizzazione e mostrare bene i vari punteggi di difficoltà
    1.3 - il tasto apri deve diventare chiudi, e sarebbe carino riordinare il json per lasciare ultima la catena e prima cose utili e leggibili
    1.4 - cambiare i campi di salvataggio, non so ancora come, ma meglio di così
    1.5 - tema scuro ?!?!
    1.6 - mostrare candidates e migliorare spiegazione delle mosse
    
2 - 