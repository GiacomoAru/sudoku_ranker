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


Installazione:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Test:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Per avviare e gestire l'interfaccia LAN vedere [WEB_LAN.md](WEB_LAN.md).
