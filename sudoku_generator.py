'''
## 4. Generatore di puzzle (opzionale)

Utility per creare puzzle di prova con **soluzione garantita unica**:
genera una griglia piena casuale, poi toglie caselle una alla volta in
ordine casuale mantenendo la rimozione solo se `count_solutions` conferma
che la soluzione resta unica. Utile per costruire esempi o per il test
batch della galleria finale, in alternativa ai puzzle fissi.

Nota: puzzle con pochissimi indizi (sotto ~26) possono richiedere qualche
secondo per via del controllo di unicità con backtracking puro.
'''

"""
Small puzzle generator: builds a random full solution, then removes clues
one at a time (in random order), keeping a removal only if the puzzle still
has a unique solution. Used by the notebook to build demo puzzles instead of
relying only on hardcoded examples.
"""

import random
import numpy as np
import sudoku_data_structure as sds

def random_full_grid(rng=None):
    rng = rng or random.Random()
    g = np.zeros((9, 9), dtype=int)

    def valid(r, c, v):
        if v in g[r, :] or v in g[:, c]:
            return False
        br, bc = 3 * (r // 3), 3 * (c // 3)
        if v in g[br:br + 3, bc:bc + 3]:
            return False
        return True

    cells = [(r, c) for r in range(9) for c in range(9)]

    def solve(i=0):
        if i == 81:
            return True
        r, c = cells[i]
        digits = list(range(1, 10))
        rng.shuffle(digits)
        for v in digits:
            if valid(r, c, v):
                g[r, c] = v
                if solve(i + 1):
                    return True
                g[r, c] = 0
        return False

    solve()
    return g


def generate_unique_puzzle(target_clues=30, rng=None, max_attempts_per_cell=1):
    """Dig a random full grid down to (at most) target_clues givens while
    keeping the solution unique. May stop above target_clues if it can't dig
    further without breaking uniqueness -- that's normal near the low end."""
    rng = rng or random.Random()
    full = random_full_grid(rng)
    puzzle = full.copy()
    cells = [(r, c) for r in range(9) for c in range(9)]
    rng.shuffle(cells)

    n_clues = 81
    for (r, c) in cells:
        if n_clues <= target_clues:
            break
        saved = puzzle[r, c]
        puzzle[r, c] = 0
        if sds.count_solutions(puzzle, limit=2) == 1:
            n_clues -= 1
        else:
            puzzle[r, c] = saved
    return puzzle, full