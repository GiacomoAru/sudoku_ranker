# Corpus di regressione del solver

Questo corpus è intenzionalmente piccolo e versionato insieme al codice. Ha
due livelli complementari:

- `hodoku_regression.txt`: uno stato candidati *gold* per tecnica, con
  conclusione attesa esatta;
- `puzzles.json`: quattro puzzle completi, uno per fascia, risolti end-to-end.

I casi locali provengono dalla **HoDoKu Regression Test Library 1.3** e ne
conservano il formato originale:

```text
:tecnica:candidati:griglia:candidati rimossi:eliminazioni:piazzamenti:extra
```

Nella griglia, `+N` indica un valore già piazzato e non un dato iniziale. È
essenziale per testare correttamente tecniche come gli Avoidable Rectangle.
HoDoKu distribuisce le proprie librerie secondo GNU Free Documentation License
1.3: <https://hodoku.sourceforge.net/en/libs.php>.

I puzzle completi provengono dal **Sudoku Exchange Puzzle Bank**, dichiarato di
pubblico dominio. La licenza upstream è copiata in
`LICENSE-SUDOKU-EXCHANGE.txt`.

## Esecuzione

Solo il corpus:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_solver_corpus -v
```

Il modulo è inoltre scoperto automaticamente dalla suite ordinaria. Quando una
nuova tecnica diventa stabile, il suo caso è già presente nella sezione futura:
si aggiunge il relativo `TechniqueBinding` in `tests/solver_corpus.py` e si
rimuove il codice da `PLANNED_HODOKU_CODES`.

P13 attiva inoltre i casi `0709` e `0710`: verificano rispettivamente una
conclusione esatta di Grouped Continuous Nice Loop e di Grouped Nice Loop.

P14 attiva i casi `0901`-`0904`: coprono rispettivamente Singly Linked
ALS-XZ, ALS-XY-Wing, ALS Chain e Death Blossom con conclusioni gold esatte.
