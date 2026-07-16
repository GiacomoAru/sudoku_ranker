'''
## 1. Strutture dati di base

`SudokuState` tiene la griglia (numpy 9×9, 0 = cella vuota) e, per ogni
cella vuota, l'insieme dei candidati ancora possibili. `place` assegna un
valore e propaga automaticamente le eliminazioni ai vicini (riga, colonna,
box); `eliminate` toglie un singolo candidato. Il backtracking puro serve
**solo** come rete di sicurezza per verificare la risolvibilità quando le
tecniche implementate non bastano — non è usato per risolvere normalmente.
'''


"""
Core data structures for the Sudoku solver/grader.
"""
import numpy as np
from itertools import combinations

ALL_DIGITS = set(range(1, 10))


def get_units():
    units = []
    kinds = []
    for r in range(9):
        units.append([(r, c) for c in range(9)])
        kinds.append('row')
    for c in range(9):
        units.append([(r, c) for r in range(9)])
        kinds.append('col')
    for br in range(0, 9, 3):
        for bc in range(0, 9, 3):
            units.append([(r, c) for r in range(br, br + 3) for c in range(bc, bc + 3)])
            kinds.append('box')
    return units, kinds


UNITS, UNIT_KINDS = get_units()

_PEERS_CACHE = {}


def peers(r, c):
    key = (r, c)
    if key in _PEERS_CACHE:
        return _PEERS_CACHE[key]
    p = set()
    for u in UNITS:
        if (r, c) in u:
            p.update(u)
    p.discard((r, c))
    _PEERS_CACHE[key] = p
    return p


def box_of(r, c):
    return 3 * (r // 3) + (c // 3)


class SudokuState:
    """Mutable state: grid of solved digits + candidate sets for empty cells."""

    def __init__(self, grid):
        if isinstance(grid, str):
            s = grid.strip().replace('.', '0')
            assert len(s) == 81, f"expected 81 chars, got {len(s)}"
            grid = [int(ch) for ch in s]
        self.grid = np.array(grid, dtype=int).reshape(9, 9)
        self.candidates = [[set() for _ in range(9)] for _ in range(9)]
        self._init_candidates()

    def _init_candidates(self):
        for r in range(9):
            for c in range(9):
                if self.grid[r, c] == 0:
                    self.candidates[r][c] = self._compute_possible(r, c)
                else:
                    self.candidates[r][c] = set()

    def _compute_possible(self, r, c):
        used = set(self.grid[r, :].tolist()) | set(self.grid[:, c].tolist())
        br, bc = 3 * (r // 3), 3 * (c // 3)
        used |= set(self.grid[br:br + 3, bc:bc + 3].flatten().tolist())
        return ALL_DIGITS - used

    def place(self, r, c, v):
        """Assign value v to cell (r,c) and propagate eliminations to peers."""
        self.grid[r, c] = v
        self.candidates[r][c] = set()
        for (rr, cc) in peers(r, c):
            self.candidates[rr][cc].discard(v)

    def eliminate(self, r, c, v):
        if v in self.candidates[r][c]:
            self.candidates[r][c].discard(v)
            return True
        return False

    def is_solved(self):
        return bool(np.all(self.grid != 0))

    def is_stuck(self):
        """True if some empty cell has zero candidates (contradiction)."""
        for r in range(9):
            for c in range(9):
                if self.grid[r, c] == 0 and len(self.candidates[r][c]) == 0:
                    return True
        return False

    def copy(self):
        s = SudokuState(self.grid.copy())
        s.candidates = [[set(x) for x in row] for row in self.candidates]
        return s

    def empty_cells(self):
        return [(r, c) for r in range(9) for c in range(9) if self.grid[r, c] == 0]

    def to_string(self):
        return ''.join(str(self.grid[r, c]) for r in range(9) for c in range(9))

    @staticmethod
    def from_string(s):
        s = s.strip().replace('.', '0')
        assert len(s) == 81, f"expected 81 chars, got {len(s)}"
        digits = [int(ch) for ch in s]
        return SudokuState(np.array(digits).reshape(9, 9))
    


def backtracking_solve(grid):
    """Plain backtracking solver used only to (a) validate puzzles have a
    unique-ish solution and (b) provide a fallback so the app never gets
    stuck without an answer, even when a step wasn't found by any
    human-style technique."""
    g = np.array(grid, dtype=int).copy()

    def find_empty():
        for r in range(9):
            for c in range(9):
                if g[r, c] == 0:
                    return r, c
        return None

    def valid(r, c, v):
        if v in g[r, :] or v in g[:, c]:
            return False
        br, bc = 3 * (r // 3), 3 * (c // 3)
        if v in g[br:br + 3, bc:bc + 3]:
            return False
        return True

    def solve():
        pos = find_empty()
        if pos is None:
            return True
        r, c = pos
        for v in range(1, 10):
            if valid(r, c, v):
                g[r, c] = v
                if solve():
                    return True
                g[r, c] = 0
        return False

    if solve():
        return g
    return None


def count_solutions(grid, limit=2):
    """Count solutions up to `limit` (stops early). Used to check that a
    generated/edited puzzle has a unique solution before using it as a demo."""
    g = np.array(grid, dtype=int).copy()
    count = 0

    def find_empty():
        for r in range(9):
            for c in range(9):
                if g[r, c] == 0:
                    return r, c
        return None

    def valid(r, c, v):
        if v in g[r, :] or v in g[:, c]:
            return False
        br, bc = 3 * (r // 3), 3 * (c // 3)
        if v in g[br:br + 3, bc:bc + 3]:
            return False
        return True

    def solve():
        nonlocal count
        pos = find_empty()
        if pos is None:
            count += 1
            return count >= limit
        r, c = pos
        for v in range(1, 10):
            if valid(r, c, v):
                g[r, c] = v
                if solve():
                    return True
                g[r, c] = 0
        return False

    solve()
    return count


def is_valid_complete_grid(grid):
    g = np.array(grid)
    if g.shape != (9, 9):
        return False
    full = set(range(1, 10))
    for i in range(9):
        if set(g[i, :].tolist()) != full or set(g[:, i].tolist()) != full:
            return False
    for br in range(0, 9, 3):
        for bc in range(0, 9, 3):
            if set(g[br:br + 3, bc:bc + 3].flatten().tolist()) != full:
                return False
    return True