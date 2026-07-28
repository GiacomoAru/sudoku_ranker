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
1. **Modificare interfaccia per:**

   1. ★ Fare che le due sezioni, sinistra e destra, scorrano entrambe e non venga data precedenza a quella di destra, se no è lungo arrivare al tasto invia.
   2. Modificare manualmente i campi e le scritte del sito
      1. a capo dopo puzzle
      2. perceived 1-10
   3. ★ rivedere completamente meccanismo di evidenziazione celle per spiegazione della mossa, chiarire celle principali, secondarie ecc. Mostrare anche i candidates per cella

   4. Il tasto `Apri` deve diventare `Chiudi`
   5. riordinare il json per posticipare catena e altre liste
   6. cambiare campi per il nome del sudoku e magari salvare altri metadati di salvataggio (dispositivo ecc.)
   7. Tema scuro?!?!
   8. ★ Renderlo carino da telefono.
      1. restringere a tastierino numerico negli input del sudoku anche nell'input formato sringa
   9. aggiungere un riferimento tra step visualizzato e punto della catena nel grafico o heatmap

2. **Migliorare il solver**
   1. chiarire stato "stuck" e quando un sudoku non ha soluzione unica
   2. migliorare ricerca profile, in modo da non cercare tutte le tecniche possibili se richiedono molta computazione
   3. scala logaritmica nella catena per l'asse della numerosità di tecniche, ma con 1 allineato con uno a sinistra


3. **Integrare riconoscimento Sudoku via foto:**
   1. ★ Prima implementazione con interfaccia web di riconoscimento Sudoku con conferma.
   2. Meccanismo di salvataggio foto e allenamento modello specializzato per riconoscimento cifre o fine-tuning di un modello pretrained.

4. **Ampliare interfaccia web con magari visualizzazione database ecc.**

5. **Implementare generatore offline di Sudoku ed esplorare la generazione e difficoltà.**
