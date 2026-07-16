# [markdown]
#  Test completo di archivio, analisi e visualizzazione Sudoku
#
# Questo notebook verifica l'intero flusso:
#
# 1. genera un nuovo Sudoku con soluzione unica;
# 2. lo salva nell'archivio;
# 3. lo ricarica dal file;
# 4. esegue l'analisi completa, che al primo accesso deve essere calcolata e salvata;
# 5. visualizza il risultato in tutti i modi disponibili;
# 6. richiede nuovamente la stessa analisi e verifica che venga restituita dalla cache in memoria.
#
# Il notebook presuppone questi moduli nello stesso progetto:
#
# - `sudoku_solver.py`
# - `sudoku_archive.py`
# - `sudoku_visualization.py`
#

import random
import time

import matplotlib.pyplot as plt
import pandas as pd

import sudoku_solver as ss
import sudoku_archive as sa
import sudoku_visualization as sv
import sudoku_generator as sg

plt.rcParams["figure.figsize"] = (7, 7)


# [markdown]
# # 1. Generazione di un nuovo Sudoku
#
# Viene usato un seed casuale, così ogni esecuzione completa del notebook tende a produrre un Sudoku nuovo. In questo modo non dovrebbe esistere già un'analisi salvata per la stessa griglia.
#

seed = random.SystemRandom().randrange(1, 10**9)
rng = random.Random(seed)

generated_puzzle, generated_solution = sg.generate_unique_puzzle(
    target_clues=30,
    rng=rng,
)

puzzle_name = f"generated_{seed}"

print("Seed:", seed)
print("Nome:", puzzle_name)
print("Numero di indizi:", int((generated_puzzle != 0).sum()))

sv.draw_grid(
    generated_puzzle,
    title=f"{puzzle_name} — puzzle generato",
)
plt.show()


# [markdown]
# # 2. Salvataggio del Sudoku
#
# Il Sudoku viene salvato nella cartella `puzzles` dell'archivio. Il nome del file dipende dall'identificatore derivato dalla griglia.
#

saved_info = sa.save_sudoku(
    generated_puzzle,
    name=puzzle_name,
    metadata={
        "seed": seed,
        "target_clues": 30,
        "purpose": "test completo archivio e cache",
    },
)

print("Sudoku salvato")
print("ID:", saved_info["id"])
print("Nome:", saved_info["name"])
print("Percorso:", saved_info["path"])


# [markdown]
# # 3. Caricamento del Sudoku
#
# Il Sudoku viene ricaricato usando il nome assegnato. La griglia caricata viene confrontata con quella generata.
#

loaded_info = sa.load_sudoku(puzzle_name)
loaded_puzzle = loaded_info["grid"]

print("Sudoku caricato")
print("ID:", loaded_info["id"])
print("Nome:", loaded_info["name"])
print("Percorso:", loaded_info["path"])
print("Griglia identica all'originale:", (loaded_puzzle == generated_puzzle).all())

sv.draw_grid(
    loaded_puzzle,
    title=f"{loaded_info['name']} — ricaricato dall'archivio",
)
plt.show()


# [markdown]
# # 4. Prima analisi completa
#
# Dato che il Sudoku è appena stato generato, la sua analisi non dovrebbe essere presente né nella cache in memoria né nell'archivio. La prima chiamata deve quindi:
#
# 1. eseguire il solver;
# 2. costruire la catena logica;
# 3. valutare la difficoltà;
# 4. salvare automaticamente l'analisi;
# 5. inserirla nella cache in memoria.
#

start = time.perf_counter()

first_result = sa.analyse_puzzle_cached(
    loaded_puzzle,
    name=loaded_info["name"],
)

first_elapsed = time.perf_counter() - start

print("Prima analisi completata")
print("Tempo:", round(first_elapsed, 4), "secondi")
print("Stato:", first_result["status"])
print("Valutazione:", first_result["grading"])
print("Numero di step:", len(first_result["chain"]))


# [markdown]
# # 5. Visualizzazione della griglia risolta
#

sv.draw_grid(
    first_result["solved_grid"],
    given_mask=(first_result["original"] != 0),
    title=(
        f"{first_result['name']} — "
        f"{first_result['grading']['label']}"
    ),
)
plt.show()


# [markdown]
# # 6. Catena di difficoltà
#
# Mostra il livello di difficoltà usato a ogni step e il numero complessivo di passaggi per livello.
#

sv.plot_difficulty_chain(first_result)


# [markdown]
# # 7. Passaggio più difficile
#
# Viene visualizzato lo stato della griglia in corrispondenza del passaggio con difficoltà massima.
#

if first_result["chain"]:
    hardest_index = max(
        range(len(first_result["chain"])),
        key=lambda index: first_result["chain"][index]["difficulty"],
    )

    hardest_move = first_result["chain"][hardest_index]

    print("Indice:", hardest_index)
    print("Step:", hardest_move["step"])
    print("Tecnica:", hardest_move["technique"])
    print("Difficoltà:", hardest_move["difficulty"])
    print("Descrizione:", hardest_move["description"])

    sv.draw_step(first_result, hardest_index)
else:
    print("Nessun passaggio disponibile.")


# [markdown]
# # 8. Tabella completa della catena
#

chain_dataframe = sv.summary_dataframe(first_result)
chain_dataframe


# [markdown]
# # 9. Frequenza delle tecniche effettivamente usate
#

technique_counts = (
    chain_dataframe["tecnica"]
    .value_counts()
    .rename_axis("tecnica")
    .reset_index(name="numero_step")
)

technique_counts


# [markdown]
# # 10. Attività delle tecniche durante la risoluzione
#
# Se `sudoku_visualization.py` contiene `plot_technique_activity`, viene mostrata la heatmap con:
#
# - righe: tecniche;
# - colonne: step;
# - valori: numero di applicazioni disponibili in quello stato.
#
# Le analisi devono contenere `applicable_by_technique` perché questa visualizzazione sia significativa.
#

if hasattr(sv, "plot_technique_activity"):
    has_activity_data = any(
        "applicable_by_technique" in step
        for step in first_result["chain"]
    )

    if has_activity_data:
        sv.plot_technique_activity(first_result)
    else:
        print(
            "La funzione esiste, ma l'analisi non contiene "
            "'applicable_by_technique'. Aggiorna solve_and_log "
            "e incrementa ANALYSIS_VERSION."
        )
else:
    print(
        "plot_technique_activity non è presente in "
        "sudoku_visualization.py."
    )


# [markdown]
# # 11. Galleria
#
# La galleria è pensata per più Sudoku, ma può essere usata anche con un solo risultato per verificare la vista riepilogativa.
#

sudoku_ref_list = sa.list_sudokus()
sudoku_list = [sa.load_sudoku(x['name']) for x in sudoku_ref_list]
sudoku_analysis_list = [sa.analyse_puzzle_cached(x['grid'], x['name']) for x in sudoku_list]

sv.gallery(sudoku_analysis_list, ncols=5)

# [markdown]
# # 12. Riepilogo sintetico
#

grading = first_result["grading"]

summary = pd.DataFrame([
    {
        "nome": first_result["name"],
        "stato": first_result["status"],
        "difficoltà": grading["label"],
        "livello_massimo": grading["max_difficulty"],
        "punteggio": grading["score"],
        "numero_step": grading.get("n_steps", len(first_result["chain"])),
        "solvibile_verificato": first_result.get(
            "backtracking_verified_solvable"
        ),
    }
])

summary


# [markdown]
# # 13. Seconda richiesta della stessa analisi
#
# La stessa analisi viene richiesta di nuovo nello stesso processo Python. Se la cache in memoria funziona, `analyse_puzzle_cached` deve restituire lo stesso oggetto già presente in `_ANALYSIS_MEMORY_CACHE`, senza rileggere o ricalcolare l'analisi.
#
# Il controllo più diretto è `second_result is first_result`.
#

start = time.perf_counter()

second_result = sa.analyse_puzzle_cached(
    loaded_puzzle,
    name=loaded_info["name"],
)

second_elapsed = time.perf_counter() - start

print("Seconda richiesta completata")
print("Tempo:", round(second_elapsed, 6), "secondi")
print("Stesso oggetto in memoria:", second_result is first_result)
print(
    "Contenuto equivalente:",
    second_result["grading"] == first_result["grading"]
    and len(second_result["chain"]) == len(first_result["chain"]),
)

if second_result is first_result:
    print("OK: l'analisi è stata presa dalla cache in memoria.")
else:
    print(
        "La seconda analisi non è lo stesso oggetto. "
        "Controlla l'implementazione di analyse_puzzle_cached."
    )


# [markdown]
# # 14. Controllo dell'archivio
#
# Mostra l'elenco dei Sudoku salvati e verifica che quello appena creato risulti analizzato.
#

archive_dataframe = pd.DataFrame(sa.list_sudokus())

if not archive_dataframe.empty:
    archive_dataframe = archive_dataframe[
        archive_dataframe["id"] == loaded_info["id"]
    ]

archive_dataframe


