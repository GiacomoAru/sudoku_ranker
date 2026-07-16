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
'''from sudoku_data_structure import *
from sudoku_techniques import *

from collections import Counter

TECHNIQUE_DIFFICULTY = {
    "Naked Single": 1.0,
    "Hidden Single": 1.2,

    "Pointing": 2.0,
    "Claiming": 2.2,
    "Naked Pair": 2.0,
    "Hidden Pair": 2.5,

    "Naked Triple": 3.0,
    "X-Wing": 3.5,
    "Unique Rectangle Type 1": 3.5,

    "Naked Quadruple": 4.0,
    "Hidden Triple": 4.0,
    "Y-Wing": 4.0,
    "XYZ-Wing": 4.5,
    "Swordfish": 4.5,

    "Hidden Quadruple": 5.0,
    "Jellyfish": 5.0,
    
    # fixed priority used only to break ties between moves of equal difficulty,
    # so that e.g. a Naked Pair is always preferred over a Hidden Pair when both
    # are difficulty 2 and both are available in the same step.
    _TECHNIQUE_ORDER = [
        'Naked Single', 'Hidden Single', 'Pointing', 'Claiming',
        'Naked Pair', 'Hidden Pair', 'Unique Rectangle Type 1',
        'Naked Triple', 'X-Wing', 'Naked Quadruple', 'Hidden Triple',
        'Y-Wing', 'XYZ-Wing', 'Swordfish', 'Hidden Quadruple', 'Jellyfish',
    ]
}'''




def _tie_rank(move):
    try:
        return st._TECHNIQUE_ORDER.index(move['technique'])
    except ValueError:
        return len(st._TECHNIQUE_ORDER)


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
            local_min = min(m['difficulty'] for m in found)
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

        moves.sort(
            key=lambda move: (
                move["difficulty"],
                _tie_rank(move),
            )
        )

        chosen = moves[0]
        n_alternatives = len(moves)

        apply_move(state, chosen)
        step_no += 1

        record = dict(chosen)
        record['step'] = step_no
        record['n_alternatives'] = n_alternatives
        record['grid_after'] = state.grid.copy()
        record["applicable_by_technique"] = applicable_by_technique
        chain.append(record)

        if verbose:
            print(f"[{step_no:03d}] {chosen['technique']:<26} "
                  f"(diff {chosen['difficulty']})  {chosen['description']}")

    status = 'solved' if state.is_solved() else 'stuck'
    return state, chain, status


def grade_difficulty(chain, status):
    """Turn a solving chain into a difficulty rating."""
    if not chain:
        return {'label': 'N/A', 'max_difficulty': 0, 'score': 0,
                'histogram': {}, 'status': status}

    diffs = [m['difficulty'] for m in chain]
    histogram = {lvl: diffs.count(lvl) for lvl in range(1, 7)}
    max_diff = max(diffs)

    # weighted score: rewards both the hardest technique required and how
    # often non-trivial techniques were needed, so two puzzles that both
    # peak at "Hard" but differ in how many hard steps they needed don't
    # get graded identically.
    score = sum(lvl * count for lvl, count in histogram.items()) / len(diffs)

    if status != 'solved':
        label = 'Estremo (richiede tecniche non implementate: catene forzanti / AIC)'
    else:
        label = st.DIFFICULTY_LABEL.get(max_diff, '?')

    return {
        'label': label, 'max_difficulty': max_diff, 'score': round(score, 2),
        'histogram': histogram, 'status': status, 'n_steps': len(chain),
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