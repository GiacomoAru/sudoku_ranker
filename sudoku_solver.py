'''
## 3. Motore risolutivo

Ad ogni step: `collect_all_moves` interroga le tecniche in ordine di
difficoltà crescente e si ferma non appena nessuna tecnica rimasta potrebbe
produrre qualcosa di più semplice di quanto già trovato (è solo
un'ottimizzazione di velocità: il risultato — quale sia la mossa più
semplice — è identico a uno scan completo, cambia solo quanto lavoro extra
si fa per scoprirlo). Tra le mosse trovate alla difficoltà minima, un
ordine di tie-break fisso (`_TECHNIQUE_ORDER`) rende la scelta
deterministica quando due tecniche diverse sono a pari difficoltà.

`solve_and_log` applica una mossa alla volta e registra ogni step nella
catena, fino a soluzione completa, blocco (nessuna tecnica implementata
trova più nulla) o contraddizione (un candidato azzerato — non dovrebbe mai
succedere su un puzzle valido con solo eliminazioni logicamente corrette).

`grade_difficulty` trasforma la catena in un giudizio: livello massimo
raggiunto, istogramma di quante volte è servito ogni livello, e un
punteggio medio pesato che distingue puzzle che toccano lo stesso livello
massimo ma con frequenza diversa.
'''


"""
Solver engine: at every step, collect every move every technique can find,
then apply only the single simplest one (lowest difficulty; ties broken by
a fixed technique order so the run is deterministic). Every applied step is
logged into a "chain" which is later used both for difficulty grading and
for visualisation.
"""

import sudoku_data_structure as sds
import sudoku_techniques as st


from collections import Counter

DIFFICULTY_LABEL = {
    1: "Fondamentale",
    2: "Facile",
    3: "Intermedio",
    4: "Avanzato",
    5: "Esperto",
}
DIFFICULTY_WORKLOAD_WEIGHT = {
    1: 0,
    2: 1,
    3: 3,
    4: 8,
    5: 20,
}
_TECHNIQUE_RANK = {
    technique: index
    for index, technique in enumerate(st._TECHNIQUE_ORDER)
}



def _difficulty_score(move):
    """
    Restituisce la difficoltà precisa della tecnica.

    Usa TECHNIQUE_DIFFICULTY come fonte principale e il valore contenuto
    nella mossa solamente come fallback.
    """
    return float(
        st.TECHNIQUE_DIFFICULTY.get(
            move["technique"],
            move.get("difficulty", 99),
        )
    )
def _difficulty_level(move):
    """
    Converte il punteggio preciso nella categoria generale 1-5.

    Esempi:
    1.2 -> livello 1
    3.5 -> livello 3
    4.7 -> livello 4
    """
    return int(_difficulty_score(move))
def _tie_rank(move):
    return _TECHNIQUE_RANK.get(
        move["technique"],
        len(_TECHNIQUE_RANK),
    )
def _move_sort_key(move):
    return (
        _difficulty_score(move),
        _tie_rank(move),
    )


def collect_all_moves(state, early_stop=True):
    """Run technique functions cheapest-first. If early_stop is True, stop
    as soon as we hold a move at difficulty D and every remaining function's
    best possible output is > D (it could never beat what we already have)."""
    moves = []
    best_diff = None
    for min_d, fn in st.TECHNIQUE_FUNCS:
        if early_stop and best_diff is not None and min_d > best_diff:
            break
        found = fn(state)
        if found:
            moves.extend(found)
            local_min = min(_difficulty_score(move) for move in found)
            best_diff = local_min if best_diff is None else min(best_diff, local_min)
    return moves


def collect_all_moves_full(state):
    """Same as collect_all_moves but never early-stops -- used when the
    caller wants a complete inventory of every applicable technique (e.g.
    for reporting 'N alternatives were available at this step')."""
    return collect_all_moves(state, early_stop=False)


def apply_move(state, move):
    for (r, c, v) in move['placements']:
        state.place(r, c, v)
    for (r, c, v) in move['eliminations']:
        state.eliminate(r, c, v)


def solve_and_log(grid, max_steps=2000, verbose=False):
    """Run the human-style solver, returning (final_state, chain, status).

    status is one of: 'solved', 'stuck' (no technique applies but grid is
    not complete -- would need un-implemented advanced/forcing techniques),
    'contradiction' (a candidate set emptied out -- should not normally
    happen on a valid puzzle).
    """
    state = sds.SudokuState(grid)
    chain = []
    step_no = 0

    while not state.is_solved() and step_no < max_steps:
        if state.is_stuck():
            return state, chain, 'contradiction'

        moves = collect_all_moves_full(state)

        if not moves:
            return state, chain, 'stuck'

        applicable_by_technique = dict(
            Counter(move["technique"] for move in moves)
        )

        moves.sort(key=_move_sort_key)

        chosen = moves[0]
        chosen_score = _difficulty_score(chosen)
        chosen_level = int(chosen_score)
        n_alternatives = len(moves)

        apply_move(state, chosen)
        step_no += 1
        
        record = dict(chosen)
        record["step"] = step_no
        record["n_alternatives"] = n_alternatives
        record["grid_after"] = state.grid.copy()
        record["applicable_by_technique"] = applicable_by_technique

        record["difficulty"] = chosen_score
        record["difficulty_level"] = chosen_level

        chain.append(record)

        if verbose:
            print(
                f"[{step_no:03d}] "
                f"{chosen['technique']:<30} "
                f"(diff {chosen_score:.1f}) "
                f"{chosen['description']}"
            )

    status = 'solved' if state.is_solved() else 'stuck'
    return state, chain, status


def grade_difficulty(chain, status):
    """Valuta il livello tecnico richiesto e il carico di risoluzione."""
    if not chain:
        return {
            "label": "N/A",
            "max_difficulty": 0,
            "max_level": 0,
            "score": 0,
            "workload_score": 0,
            "histogram": {},
            "status": status,
            "n_steps": 0,
        }

    difficulty_scores = [
        float(
            move.get(
                "difficulty",
                st.TECHNIQUE_DIFFICULTY.get(
                    move["technique"],
                    99,
                ),
            )
        )
        for move in chain
    ]

    difficulty_levels = [
        int(score)
        for score in difficulty_scores
    ]

    histogram = {
        level: difficulty_levels.count(level)
        for level in range(1, 6)
    }

    max_difficulty = max(difficulty_scores)
    max_level = int(max_difficulty)

    hardest_steps = sum(
        score == max_difficulty
        for score in difficulty_scores
    )

    nontrivial_steps = sum(
        level >= 2
        for level in difficulty_levels
    )

    advanced_steps = sum(
        level >= 4
        for level in difficulty_levels
    )

    workload_score = sum(
        DIFFICULTY_WORKLOAD_WEIGHT[level]
        for level in difficulty_levels
    )

    if status == "solved":
        label = DIFFICULTY_LABEL.get(
            max_level,
            "Sconosciuto",
        )
    else:
        label = "Oltre la copertura del solver"

    return {
        "label": label,
        "max_difficulty": max_difficulty,
        "max_level": max_level,

        # Mantenuto per compatibilità con il notebook.
        "score": workload_score,
        "workload_score": workload_score,

        "histogram": histogram,
        "status": status,
        "n_steps": len(chain),

        "hardest_steps": hardest_steps,
        "nontrivial_steps": nontrivial_steps,
        "advanced_steps": advanced_steps,
    }


def analyse_puzzle(grid, name=None):
    """Convenience wrapper: solve, grade, and package everything needed for
    later reporting/visualisation into one dict."""
    import numpy as np
    original = sds.SudokuState(grid).grid.copy()
    state, chain, status = solve_and_log(grid)
    grading = grade_difficulty(chain, status)

    verified = None
    if status != 'solved':
        bt = sds.backtracking_solve(original)
        verified = bt is not None

    return {
        'name': name or 'puzzle',
        'original': original,
        'solved_grid': state.grid.copy(),
        'chain': chain,
        'status': status,
        'grading': grading,
        'backtracking_verified_solvable': verified,
    }