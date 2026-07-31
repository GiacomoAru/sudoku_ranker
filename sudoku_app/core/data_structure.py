'''
## 1. Strutture dati di base

`SudokuState` tiene la griglia (numpy 9×9, 0 = cella vuota) e, per ogni
cella vuota, l'insieme dei candidati ancora possibili. `place` assegna un
valore e propaga automaticamente le eliminazioni ai vicini (riga, colonna,
box); `eliminate` toglie un singolo candidato. Il backtracking puro serve
**solo** come rete di sicurezza per verificare la risolvibilità quando le
tecniche implementate non bastano — non è usato per risolvere normalmente.
'''


"""Strutture dati interne del motore Sudoku."""
import numpy as np
from itertools import combinations

ALL_DIGITS = set(range(1, 10))

UNIQUENESS_VERIFIED = "verified_unique"
UNIQUENESS_NOT_CHECKED = "not_checked"
UNIQUENESS_MULTIPLE_SOLUTIONS = "multiple_solutions"
UNIQUENESS_STATUSES = frozenset({
    UNIQUENESS_VERIFIED,
    UNIQUENESS_NOT_CHECKED,
    UNIQUENESS_MULTIPLE_SOLUTIONS,
})


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

    def __init__(
        self,
        grid,
        *,
        uniqueness_status=UNIQUENESS_NOT_CHECKED,
        initial_grid=None,
    ):
        if isinstance(grid, str):
            s = grid.strip().replace('.', '0')
            assert len(s) == 81, f"expected 81 chars, got {len(s)}"
            grid = [int(ch) for ch in s]
        self.grid = np.array(grid, dtype=int).reshape(9, 9)
        if uniqueness_status not in UNIQUENESS_STATUSES:
            allowed = ", ".join(sorted(UNIQUENESS_STATUSES))
            raise ValueError(
                f"uniqueness_status non valido: {uniqueness_status!r}; "
                f"valori ammessi: {allowed}."
            )
        self.uniqueness_status = uniqueness_status
        self.initial_grid = np.array(
            self.grid if initial_grid is None else initial_grid,
            dtype=int,
        ).reshape(9, 9).copy()
        self.given_mask = self.initial_grid != 0
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
        s = SudokuState(
            self.grid.copy(),
            uniqueness_status=self.uniqueness_status,
            initial_grid=self.initial_grid,
        )
        s.candidates = [[set(x) for x in row] for row in self.candidates]
        return s

    def empty_cells(self):
        return [(r, c) for r in range(9) for c in range(9) if self.grid[r, c] == 0]

    def to_string(self):
        return ''.join(str(self.grid[r, c]) for r in range(9) for c in range(9))

    @staticmethod
    def from_string(s, *, uniqueness_status=UNIQUENESS_NOT_CHECKED):
        s = s.strip().replace('.', '0')
        assert len(s) == 81, f"expected 81 chars, got {len(s)}"
        digits = [int(ch) for ch in s]
        return SudokuState(
            np.array(digits).reshape(9, 9),
            uniqueness_status=uniqueness_status,
        )
    


def backtracking_solve(grid):
    """
    Risolve il Sudoku con backtracking.

    Priorità:
    1. sceglie la cella vuota con meno candidati;
    2. a parità, sceglie quella con più celle vuote tra i peer.

    Restituisce la griglia risolta oppure None.
    """
    g = np.array(grid, dtype=int).copy()

    def possible_values(r, c):
        used = (
            set(g[r, :].tolist())
            | set(g[:, c].tolist())
        )

        br = 3 * (r // 3)
        bc = 3 * (c // 3)

        used |= set(
            g[br:br + 3, bc:bc + 3]
            .flatten()
            .tolist()
        )

        return ALL_DIGITS - used

    def unsolved_peer_count(r, c):
        return sum(
            1
            for rr, cc in peers(r, c)
            if g[rr, cc] == 0
        )

    def find_best_empty():
        best_position = None
        best_candidates = None
        best_peer_count = -1

        for r in range(9):
            for c in range(9):
                if g[r, c] != 0:
                    continue

                candidates = possible_values(r, c)

                # Contraddizione immediata.
                if not candidates:
                    return (r, c), set()

                peer_count = unsolved_peer_count(r, c)

                if (
                    best_candidates is None
                    or len(candidates) < len(best_candidates)
                    or (
                        len(candidates) == len(best_candidates)
                        and peer_count > best_peer_count
                    )
                ):
                    best_position = (r, c)
                    best_candidates = candidates
                    best_peer_count = peer_count

                    # Non si può trovare meno di un candidato.
                    if len(best_candidates) == 1:
                        return best_position, best_candidates

        return best_position, best_candidates

    def solve():
        position, candidates = find_best_empty()

        if position is None:
            return True

        if not candidates:
            return False

        r, c = position

        for value in sorted(candidates):
            g[r, c] = value

            if solve():
                return True

            g[r, c] = 0

        return False

    if solve():
        return g

    return None


def count_solutions(grid, limit=2):
    """Conta le soluzioni fino a ``limit`` scegliendo sempre la cella MRV."""
    g = np.array(grid, dtype=int).copy()
    for unit in UNITS:
        values = [
            int(g[row, column])
            for row, column in unit
            if int(g[row, column]) != 0
        ]
        if len(values) != len(set(values)):
            return 0

    count = 0

    def possible_values(r, c):
        used = (
            set(g[r, :].tolist())
            | set(g[:, c].tolist())
        )
        br, bc = 3 * (r // 3), 3 * (c // 3)
        used |= set(
            g[br:br + 3, bc:bc + 3]
            .flatten()
            .tolist()
        )
        return ALL_DIGITS - used

    def find_best_empty():
        best_position = None
        best_candidates = None

        for r in range(9):
            for c in range(9):
                if g[r, c] != 0:
                    continue
                candidates = possible_values(r, c)
                if not candidates:
                    return (r, c), set()
                if (
                    best_candidates is None
                    or len(candidates) < len(best_candidates)
                ):
                    best_position = (r, c)
                    best_candidates = candidates
                    if len(best_candidates) == 1:
                        return best_position, best_candidates

        return best_position, best_candidates

    def solve():
        nonlocal count
        position, candidates = find_best_empty()
        if position is None:
            count += 1
            return count >= limit
        if not candidates:
            return False

        r, c = position
        for value in sorted(candidates):
            g[r, c] = value
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
