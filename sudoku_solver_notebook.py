# [markdown]
#  Sudoku Solver & Grader — catena logica di risoluzione
#
# Questo notebook implementa un risolutore di Sudoku "umano": ad ogni passo
# cerca **tutte** le tecniche applicabili (tra quelle della tassonomia
# fornita) e applica sempre e solo la **più semplice**, esattamente come
# farebbe una persona che risolve a mano seguendo la logica, non il
# tentativo-ed-errore.
#
# Ogni passo applicato viene registrato in una **catena logica**: tecnica
# usata, difficoltà, celle coinvolte, quante alternative erano disponibili in
# quel momento. Questa catena è l'informazione che poi usiamo per:
#
# 1. **valutare la difficoltà** complessiva del puzzle (non solo "qual è la
#    tecnica più difficile usata", ma anche quanto spesso serve);
# 2. **visualizzare** il procedimento, passo per passo o come grafico
#    d'insieme;
# 3. confrontare più puzzle tra loro in una galleria finale.
#
# # Struttura del notebook
#
# 1. Strutture dati di base (griglia + candidati)
# 2. Libreria delle tecniche (una funzione per famiglia, con difficoltà presa
#    dal documento fornito)
# 3. Motore risolutivo che costruisce la catena
# 4. Generatore di puzzle (con controllo di unicità della soluzione)
# 5. Visualizzazione (griglia singola, catena, galleria)
# 6. Esempi guidati
# 7. Galleria finale su un insieme di puzzle salvati
#
# **Nota sulla copertura delle tecniche.** Il documento fornito arriva fino a
# catene forzanti, AIC generali e ALS, che richiederebbero un motore
# d'inferenza molto più esteso. Qui sono implementate le famiglie che coprono
# la stragrande maggioranza dei Sudoku "umanamente risolvibili" (livelli
# 1–5: inserimenti diretti, sottoinsiemi nascosti/scoperti, intersezioni
# box/linee — Pointing/Claiming, Fish fino a Jellyfish, Y-Wing, XYZ-Wing,
# Unique Rectangle Type 1). Quando il motore non trova più mosse ma il puzzle
# non è completo, lo **segnala esplicitamente** come "Estremo — richiede
# tecniche non implementate" invece di bloccarsi silenziosamente o indovinare,
# e verifica comunque con un backtracking puro che il puzzle sia risolvibile
# (così la classificazione resta onesta anche sul limite del sistema).

%matplotlib inline
import random
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# [markdown]
# # 1. Strutture dati di base
#
# `SudokuState` tiene la griglia (numpy 9×9, 0 = cella vuota) e, per ogni
# cella vuota, l'insieme dei candidati ancora possibili. `place` assegna un
# valore e propaga automaticamente le eliminazioni ai vicini (riga, colonna,
# box); `eliminate` toglie un singolo candidato. Il backtracking puro serve
# **solo** come rete di sicurezza per verificare la risolvibilità quando le
# tecniche implementate non bastano — non è usato per risolvere normalmente.

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

# [markdown]
# # 2. Libreria delle tecniche
#
# Ogni funzione analizza lo stato corrente e restituisce **tutte** le istanze
# di quella tecnica al momento applicabili (può essercene più di una nella
# stessa griglia). Ogni mossa porta con sé: nome, famiglia, difficoltà (presa
# dalla tabella del documento), una descrizione testuale, le celle da
# compilare o le eliminazioni da fare, e le celle da evidenziare per la
# visualizzazione.
#
# Le difficoltà seguono esattamente la scala del documento:
#
# | Tecnica | Difficoltà |
# |---|---|
# | Naked/Hidden Single | 1 |
# | Pointing, Claiming, Naked Pair, Hidden Pair (in box) | 2 |
# | Hidden Pair (riga/colonna), Naked Triple, Unique Rectangle T1, X-Wing | 3 |
# | Naked Quadruple, Hidden Triple, Y-Wing, XYZ-Wing, Swordfish | 4 |
# | Hidden Quadruple, Jellyfish | 5 |
#
# Il registro `TECHNIQUE_FUNCS` in fondo associa ad ogni funzione la sua
# difficoltà minima possibile: il motore risolutivo lo usa per **non
# eseguire tecniche inutilmente costose** quando una mossa più semplice è già
# stata trovata (vedi sezione 3).

"""
Technique library. Every function takes a SudokuState and returns a list of
"Move" dicts describing every instance of that technique currently applicable
(there can be several in the same grid). The solver engine will later pick
the single simplest move across all techniques and apply it.

Move dict schema:
{
    'technique': str,           # display name, matches the taxonomy document
    'family': str,              # broader family, for reporting
    'difficulty': int,          # 1-6, per the taxonomy document
    'description': str,         # human readable explanation of this instance
    'placements': [(r,c,v)],    # cells to solve (usually 0 or 1 entries)
    'eliminations': [(r,c,v)],  # candidates to strike out
    'highlight': {              # cells to visually mark, by role
        'primary': [(r,c)],     # cells that define the pattern
        'secondary': [(r,c)],   # cells affected by eliminations
    }
}
A move must change something: it either places a digit or eliminates >=1
candidate; moves that would do nothing are not returned.
"""
from itertools import combinations


def _elim_move(technique, family, difficulty, description, eliminations, primary, state):
    """Build an elimination-only move, filtering out no-op eliminations."""
    real = [(r, c, v) for (r, c, v) in eliminations if v in state.candidates[r][c]]
    if not real:
        return None
    secondary = sorted(set((r, c) for (r, c, v) in real))
    return {
        'technique': technique, 'family': family, 'difficulty': difficulty,
        'description': description, 'placements': [], 'eliminations': real,
        'highlight': {'primary': primary, 'secondary': secondary},
    }


def _place_move(technique, family, difficulty, description, r, c, v, primary=None):
    return {
        'technique': technique, 'family': family, 'difficulty': difficulty,
        'description': description, 'placements': [(r, c, v)], 'eliminations': [],
        'highlight': {'primary': primary or [(r, c)], 'secondary': [(r, c)]},
    }


# ---------------------------------------------------------------- 1. direct
def naked_single(state):
    moves = []
    for r in range(9):
        for c in range(9):
            cand = state.candidates[r][c]
            if state.grid[r, c] == 0 and len(cand) == 1:
                v = next(iter(cand))
                moves.append(_place_move(
                    'Naked Single', 'Inserimenti diretti', 1,
                    f'La cella R{r+1}C{c+1} ha un solo candidato possibile: {v}.',
                    r, c, v))
    return moves


def hidden_single(state):
    moves = []
    seen = set()
    for u, kind in zip(UNITS, UNIT_KINDS):
        for v in range(1, 10):
            cells = [(r, c) for (r, c) in u if v in state.candidates[r][c]]
            if len(cells) == 1:
                r, c = cells[0]
                if (r, c, v) in seen:
                    continue
                seen.add((r, c, v))
                moves.append(_place_move(
                    'Hidden Single', 'Inserimenti diretti', 1,
                    f'Nel {kind} che contiene R{r+1}C{c+1}, il numero {v} puo comparire solo li.',
                    r, c, v, primary=list(u)))
    return moves


# ------------------------------------------------------- 2. locked candidate
def locked_candidates(state):
    moves = []
    # Pointing: within a box, a digit confined to one row/col -> strip from
    # the rest of that row/col outside the box.
    for u, kind in zip(UNITS, UNIT_KINDS):
        if kind != 'box':
            continue
        for v in range(1, 10):
            cells = [(r, c) for (r, c) in u if v in state.candidates[r][c]]
            if len(cells) < 2:
                continue
            rows = set(r for r, c in cells)
            cols = set(c for r, c in cells)
            if len(rows) == 1:
                r = next(iter(rows))
                elim = [(r, c, v) for c in range(9) if (r, c) not in cells]
                mv = _elim_move('Pointing', 'Intersezioni box/linee', 2,
                                 f'Nel box, il candidato {v} e confinato alla riga {r+1}: '
                                 f'eliminato dal resto della riga.', elim, list(cells), state)
                if mv:
                    moves.append(mv)
            if len(cols) == 1:
                c = next(iter(cols))
                elim = [(r, c, v) for r in range(9) if (r, c) not in cells]
                mv = _elim_move('Pointing', 'Intersezioni box/linee', 2,
                                 f'Nel box, il candidato {v} e confinato alla colonna {c+1}: '
                                 f'eliminato dal resto della colonna.', elim, list(cells), state)
                if mv:
                    moves.append(mv)
    # Claiming: within a row/col, a digit confined to one box -> strip from
    # the rest of that box outside the row/col.
    for u, kind in zip(UNITS, UNIT_KINDS):
        if kind not in ('row', 'col'):
            continue
        for v in range(1, 10):
            cells = [(r, c) for (r, c) in u if v in state.candidates[r][c]]
            if len(cells) < 2:
                continue
            boxes = set(box_of(r, c) for r, c in cells)
            if len(boxes) == 1:
                b = next(iter(boxes))
                box_cells = UNITS[18 + b]
                elim = [(r, c, v) for (r, c) in box_cells if (r, c) not in cells]
                mv = _elim_move('Claiming', 'Intersezioni box/linee', 2,
                                 f'Nella {kind}, il candidato {v} e confinato a un solo box: '
                                 f'eliminato dal resto del box.', elim, list(cells), state)
                if mv:
                    moves.append(mv)
    return moves


# --------------------------------------------------------- 3. naked subsets
_NAKED_DIFF = {2: 2, 3: 3, 4: 4}
_NAKED_NAME = {2: 'Naked Pair', 3: 'Naked Triple', 4: 'Naked Quadruple'}


def naked_subset(state, size):
    moves = []
    diff = _NAKED_DIFF[size]
    name = _NAKED_NAME[size]
    for u, kind in zip(UNITS, UNIT_KINDS):
        empties = [(r, c) for (r, c) in u if state.grid[r, c] == 0
                   and 2 <= len(state.candidates[r][c]) <= size]
        for combo in combinations(empties, size):
            union = set()
            for (r, c) in combo:
                union |= state.candidates[r][c]
            if len(union) != size:
                continue
            others = [(r, c) for (r, c) in u if (r, c) not in combo]
            elim = [(r, c, v) for (r, c) in others for v in union]
            mv = _elim_move(
                name, 'Sottoinsiemi bloccati', diff,
                f'Le celle {", ".join(f"R{r+1}C{c+1}" for r,c in combo)} contengono '
                f'solo i candidati {sorted(union)}: eliminati dal resto del {kind}.',
                elim, list(combo), state)
            if mv:
                moves.append(mv)
    return moves


# -------------------------------------------------------- 4. hidden subsets
_HIDDEN_DIFF_BOX = {2: 2, 3: 4, 4: 5}
_HIDDEN_DIFF_LINE = {2: 3, 3: 4, 4: 5}
_HIDDEN_NAME = {2: 'Hidden Pair', 3: 'Hidden Triple', 4: 'Hidden Quadruple'}


def hidden_subset(state, size):
    moves = []
    name = _HIDDEN_NAME[size]
    for u, kind in zip(UNITS, UNIT_KINDS):
        diff = _HIDDEN_DIFF_BOX[size] if kind == 'box' else _HIDDEN_DIFF_LINE[size]
        digit_cells = {}
        for v in range(1, 10):
            cells = [(r, c) for (r, c) in u if v in state.candidates[r][c]]
            if 1 <= len(cells) <= size:
                digit_cells[v] = cells
        digits = list(digit_cells.keys())
        for combo in combinations(digits, size):
            union_cells = set()
            for v in combo:
                union_cells |= set(digit_cells[v])
            if len(union_cells) != size:
                continue
            elim = []
            for (r, c) in union_cells:
                for v in state.candidates[r][c]:
                    if v not in combo:
                        elim.append((r, c, v))
            mv = _elim_move(
                name, 'Sottoinsiemi bloccati', diff,
                f'Nel {kind}, i numeri {list(combo)} compaiono solo nelle celle '
                f'{", ".join(f"R{r+1}C{c+1}" for r,c in union_cells)}: altri candidati eliminati li.',
                elim, list(union_cells), state)
            if mv:
                moves.append(mv)
    return moves


# ------------------------------------------------------------------- 5. fish
_FISH_NAME = {2: 'X-Wing', 3: 'Swordfish', 4: 'Jellyfish'}
_FISH_DIFF = {2: 3, 3: 4, 4: 5}


def fish(state, size):
    moves = []
    name = _FISH_NAME[size]
    diff = _FISH_DIFF[size]
    for v in range(1, 10):
        # rows -> columns
        row_cols = {}
        for r in range(9):
            cols = [c for c in range(9) if v in state.candidates[r][c]]
            if 2 <= len(cols) <= size:
                row_cols[r] = set(cols)
        for combo in combinations(row_cols.keys(), size):
            col_union = set()
            for r in combo:
                col_union |= row_cols[r]
            if len(col_union) != size:
                continue
            elim = []
            for c in col_union:
                for r in range(9):
                    if r not in combo and v in state.candidates[r][c]:
                        elim.append((r, c, v))
            primary = [(r, c) for r in combo for c in row_cols[r]]
            mv = _elim_move(
                name, 'Fish', diff,
                f'Il candidato {v} nelle righe {[r+1 for r in combo]} e confinato alle '
                f'colonne {sorted(c+1 for c in col_union)}: eliminato dal resto di quelle colonne.',
                elim, primary, state)
            if mv:
                moves.append(mv)
        # columns -> rows
        col_rows = {}
        for c in range(9):
            rows = [r for r in range(9) if v in state.candidates[r][c]]
            if 2 <= len(rows) <= size:
                col_rows[c] = set(rows)
        for combo in combinations(col_rows.keys(), size):
            row_union = set()
            for c in combo:
                row_union |= col_rows[c]
            if len(row_union) != size:
                continue
            elim = []
            for r in row_union:
                for c in range(9):
                    if c not in combo and v in state.candidates[r][c]:
                        elim.append((r, c, v))
            primary = [(r, c) for c in combo for r in col_rows[c]]
            mv = _elim_move(
                name, 'Fish', diff,
                f'Il candidato {v} nelle colonne {[c+1 for c in combo]} e confinato alle '
                f'righe {sorted(r+1 for r in row_union)}: eliminato dal resto di quelle righe.',
                elim, primary, state)
            if mv:
                moves.append(mv)
    return moves


# ------------------------------------------------------------------ 6. wings
def y_wing(state):
    moves = []
    bival = [(r, c) for r in range(9) for c in range(9)
             if state.grid[r, c] == 0 and len(state.candidates[r][c]) == 2]
    bival_set = set(bival)
    for pr, pc in bival:
        pcand = state.candidates[pr][pc]
        p_peers = [cell for cell in peers(pr, pc) if cell in bival_set]
        for (w1r, w1c), (w2r, w2c) in combinations(p_peers, 2):
            c1 = state.candidates[w1r][w1c]
            c2 = state.candidates[w2r][w2c]
            if c1 == c2 or c1 == pcand or c2 == pcand:
                continue
            if len(c1 & pcand) != 1 or len(c2 & pcand) != 1:
                continue
            shared_with_pivot = (c1 & pcand) | (c2 & pcand)
            if shared_with_pivot != pcand:
                continue
            z = c1 & c2
            if len(z) != 1:
                continue
            z = next(iter(z))
            targets = peers(w1r, w1c) & peers(w2r, w2c)
            targets.discard((pr, pc))
            elim = [(r, c, z) for (r, c) in targets if state.grid[r, c] == 0]
            mv = _elim_move(
                'Y-Wing', 'Wings', 4,
                f'Pivot R{pr+1}C{pc+1}{sorted(pcand)} con ali R{w1r+1}C{w1c+1}{sorted(c1)} '
                f'e R{w2r+1}C{w2c+1}{sorted(c2)}: il candidato {z} eliminato dalle celle che vedono entrambe le ali.',
                elim, [(pr, pc), (w1r, w1c), (w2r, w2c)], state)
            if mv:
                moves.append(mv)
    return moves


def xyz_wing(state):
    moves = []
    triv = [(r, c) for r in range(9) for c in range(9)
            if state.grid[r, c] == 0 and len(state.candidates[r][c]) == 3]
    bival = [(r, c) for r in range(9) for c in range(9)
             if state.grid[r, c] == 0 and len(state.candidates[r][c]) == 2]
    for pr, pc in triv:
        pcand = state.candidates[pr][pc]
        p_peers = [cell for cell in peers(pr, pc)
                   if cell in bival and state.candidates[cell[0]][cell[1]] < pcand]
        for (w1r, w1c), (w2r, w2c) in combinations(p_peers, 2):
            c1 = state.candidates[w1r][w1c]
            c2 = state.candidates[w2r][w2c]
            if c1 == c2:
                continue
            if (c1 | c2) != pcand:
                continue
            z = c1 & c2
            if len(z) != 1:
                continue
            z = next(iter(z))
            targets = peers(pr, pc) & peers(w1r, w1c) & peers(w2r, w2c)
            elim = [(r, c, z) for (r, c) in targets if state.grid[r, c] == 0]
            mv = _elim_move(
                'XYZ-Wing', 'Wings', 4,
                f'Pivot R{pr+1}C{pc+1}{sorted(pcand)} con ali R{w1r+1}C{w1c+1}{sorted(c1)} '
                f'e R{w2r+1}C{w2c+1}{sorted(c2)}: il candidato {z} eliminato dalle celle che vedono pivot e ali.',
                elim, [(pr, pc), (w1r, w1c), (w2r, w2c)], state)
            if mv:
                moves.append(mv)
    return moves


# ----------------------------------------------------------- 7. unique rect
def unique_rectangle_type1(state):
    moves = []
    bival = [(r, c) for r in range(9) for c in range(9)
             if state.grid[r, c] == 0 and len(state.candidates[r][c]) == 2]
    by_pair = {}
    for (r, c) in bival:
        key = frozenset(state.candidates[r][c])
        by_pair.setdefault(key, []).append((r, c))
    for pair, cells in by_pair.items():
        if len(cells) < 3:
            continue
        for (r1, c1), (r2, c2), (r3, c3) in combinations(cells, 3):
            rows = {r1, r2, r3}
            cols = {c1, c2, c3}
            if len(rows) != 2 or len(cols) != 2:
                continue
            r_a, r_b = sorted(rows)
            c_a, c_b = sorted(cols)
            boxes = {box_of(r_a, c_a), box_of(r_a, c_b), box_of(r_b, c_a), box_of(r_b, c_b)}
            if len(boxes) != 2:
                continue
            all_four = {(r_a, c_a), (r_a, c_b), (r_b, c_a), (r_b, c_b)}
            fourth = next(iter(all_four - {(r1, c1), (r2, c2), (r3, c3)}))
            fr, fc = fourth
            if state.grid[fr, fc] != 0 and pair.issubset(set()):
                continue
            if state.grid[fr, fc] != 0:
                continue
            if not pair.issubset(state.candidates[fr][fc]):
                continue
            if len(state.candidates[fr][fc]) <= 2:
                continue
            elim = [(fr, fc, v) for v in pair]
            mv = _elim_move(
                'Unique Rectangle Type 1', 'Unicita', 3,
                f'Le celle R{r1+1}C{c1+1}, R{r2+1}C{c2+1}, R{r3+1}C{c3+1} hanno solo i candidati '
                f'{sorted(pair)}: per evitare una soluzione non unica, eliminati da R{fr+1}C{fc+1}.',
                elim, [(r1, c1), (r2, c2), (r3, c3), (fr, fc)], state)
            if mv:
                moves.append(mv)
    return moves


# --------------------------------------------------------------- registry
# Each entry is (min_possible_difficulty, function). min_possible_difficulty
# is the lowest 'difficulty' this function could ever report (some
# functions, like hidden_subset, can report a couple of different values
# depending on whether the unit hit is a box or a line -- we use the
# smallest). The solver engine uses this to sort technique calls cheapest
# first and to stop early once nothing left could possibly be simpler than
# what has already been found, which is what keeps the app fast even though
# it is conceptually re-scanning the whole board at every single step.
TECHNIQUE_FUNCS = [
    (1, lambda s: naked_single(s)),
    (1, lambda s: hidden_single(s)),
    (2, lambda s: locked_candidates(s)),
    (2, lambda s: naked_subset(s, 2)),
    (2, lambda s: hidden_subset(s, 2)),
    (3, lambda s: unique_rectangle_type1(s)),
    (3, lambda s: naked_subset(s, 3)),
    (3, lambda s: fish(s, 2)),
    (4, lambda s: naked_subset(s, 4)),
    (4, lambda s: hidden_subset(s, 3)),
    (4, lambda s: y_wing(s)),
    (4, lambda s: xyz_wing(s)),
    (4, lambda s: fish(s, 3)),
    (5, lambda s: hidden_subset(s, 4)),
    (5, lambda s: fish(s, 4)),
]

# [markdown]
# # 3. Motore risolutivo
#
# Ad ogni step: `collect_all_moves` interroga le tecniche in ordine di
# difficoltà crescente e si ferma non appena nessuna tecnica rimasta potrebbe
# produrre qualcosa di più semplice di quanto già trovato (è solo
# un'ottimizzazione di velocità: il risultato — quale sia la mossa più
# semplice — è identico a uno scan completo, cambia solo quanto lavoro extra
# si fa per scoprirlo). Tra le mosse trovate alla difficoltà minima, un
# ordine di tie-break fisso (`_TECHNIQUE_ORDER`) rende la scelta
# deterministica quando due tecniche diverse sono a pari difficoltà.
#
# `solve_and_log` applica una mossa alla volta e registra ogni step nella
# catena, fino a soluzione completa, blocco (nessuna tecnica implementata
# trova più nulla) o contraddizione (un candidato azzerato — non dovrebbe mai
# succedere su un puzzle valido con solo eliminazioni logicamente corrette).
#
# `grade_difficulty` trasforma la catena in un giudizio: livello massimo
# raggiunto, istogramma di quante volte è servito ogni livello, e un
# punteggio medio pesato che distingue puzzle che toccano lo stesso livello
# massimo ma con frequenza diversa.

"""
Solver engine: at every step, collect every move every technique can find,
then apply only the single simplest one (lowest difficulty; ties broken by
a fixed technique order so the run is deterministic). Every applied step is
logged into a "chain" which is later used both for difficulty grading and
for visualisation.
"""

DIFFICULTY_LABEL = {
    1: 'Fondamentale', 2: 'Facile', 3: 'Intermedio',
    4: 'Avanzato', 5: 'Esperto', 6: 'Estremo',
}

# fixed priority used only to break ties between moves of equal difficulty,
# so that e.g. a Naked Pair is always preferred over a Hidden Pair when both
# are difficulty 2 and both are available in the same step.
_TECHNIQUE_ORDER = [
    'Naked Single', 'Hidden Single', 'Pointing', 'Claiming',
    'Naked Pair', 'Hidden Pair', 'Unique Rectangle Type 1',
    'Naked Triple', 'X-Wing', 'Naked Quadruple', 'Hidden Triple',
    'Y-Wing', 'XYZ-Wing', 'Swordfish', 'Hidden Quadruple', 'Jellyfish',
]


def _tie_rank(move):
    try:
        return _TECHNIQUE_ORDER.index(move['technique'])
    except ValueError:
        return len(_TECHNIQUE_ORDER)


def collect_all_moves(state, early_stop=True):
    """Run technique functions cheapest-first. If early_stop is True, stop
    as soon as we hold a move at difficulty D and every remaining function's
    best possible output is > D (it could never beat what we already have)."""
    moves = []
    best_diff = None
    for min_d, fn in TECHNIQUE_FUNCS:
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
    state = SudokuState(grid)
    chain = []
    step_no = 0

    while not state.is_solved() and step_no < max_steps:
        if state.is_stuck():
            return state, chain, 'contradiction'

        moves = collect_all_moves(state)
        if not moves:
            return state, chain, 'stuck'

        moves.sort(key=lambda m: (m['difficulty'], _tie_rank(m)))
        chosen = moves[0]
        n_alternatives = len(moves)

        apply_move(state, chosen)
        step_no += 1

        record = dict(chosen)
        record['step'] = step_no
        record['n_alternatives'] = n_alternatives
        record['grid_after'] = state.grid.copy()
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
        label = DIFFICULTY_LABEL.get(max_diff, '?')

    return {
        'label': label, 'max_difficulty': max_diff, 'score': round(score, 2),
        'histogram': histogram, 'status': status, 'n_steps': len(chain),
    }


def analyse_puzzle(grid, name=None):
    """Convenience wrapper: solve, grade, and package everything needed for
    later reporting/visualisation into one dict."""
    import numpy as np
    original = SudokuState(grid).grid.copy()
    state, chain, status = solve_and_log(grid)
    grading = grade_difficulty(chain, status)

    verified = None
    if status != 'solved':
        bt = backtracking_solve(original)
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

# [markdown]
# # 4. Generatore di puzzle (opzionale)
#
# Utility per creare puzzle di prova con **soluzione garantita unica**:
# genera una griglia piena casuale, poi toglie caselle una alla volta in
# ordine casuale mantenendo la rimozione solo se `count_solutions` conferma
# che la soluzione resta unica. Utile per costruire esempi o per il test
# batch della galleria finale, in alternativa ai puzzle fissi.
#
# Nota: puzzle con pochissimi indizi (sotto ~26) possono richiedere qualche
# secondo per via del controllo di unicità con backtracking puro.

"""
Small puzzle generator: builds a random full solution, then removes clues
one at a time (in random order), keeping a removal only if the puzzle still
has a unique solution. Used by the notebook to build demo puzzles instead of
relying only on hardcoded examples.
"""
import random
import numpy as np


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
        if count_solutions(puzzle, limit=2) == 1:
            n_clues -= 1
        else:
            puzzle[r, c] = saved
    return puzzle, full

# [markdown]
# # 5. Visualizzazione
#
# - `draw_grid`: disegna una griglia 9×9, con evidenziazione opzionale delle
#   celle coinvolte in una tecnica (giallo = celle che definiscono il
#   pattern, rosso chiaro = celle su cui avviene l'eliminazione/inserimento) e
#   possibilità di mostrare i candidati come "pencil marks".
# - `draw_step`: mostra lo stato della griglia **subito prima** di un dato
#   step della catena, con il pattern di quello step evidenziato e la
#   spiegazione testuale sotto forma di didascalia.
# - `plot_difficulty_chain`: la vista d'insieme della catena — un grafico a
#   dispersione step→difficoltà colorato per famiglia di tecnica, più un
#   istogramma dei livelli usati. È la rappresentazione "bidimensionale"
#   della difficoltà richiesta: non solo il picco massimo, ma tutto
#   l'andamento del ragionamento.
# - `gallery`: griglie finali di più puzzle affiancate, con etichetta di
#   difficoltà.
# - `summary_dataframe`: la catena come tabella pandas, per ispezione o
#   esportazione.

"""
Visualization helpers: draw a single grid (optionally highlighting a
technique instance), draw the difficulty chain of a solved puzzle, and lay
out a gallery of several analysed puzzles.
"""
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

DIFF_COLORS = {
    1: '#8ecae6', 2: '#95d5b2', 3: '#ffd166',
    4: '#f4a261', 5: '#e76f51', 6: '#9d0208',
}
DIFF_LABEL_SHORT = {1: 'L1', 2: 'L2', 3: 'L3', 4: 'L4', 5: 'L5', 6: 'L6'}


def draw_grid(grid, ax=None, highlight=None, candidates=None,
              title=None, given_mask=None):
    """Draw one 9x9 sudoku grid.
    highlight: dict with 'primary' / 'secondary' lists of (r,c) cells.
    candidates: optional 9x9 list-of-sets, drawn as small pencil marks in
        empty cells (used for close-up "what did the engine see" views).
    given_mask: optional 9x9 bool array; True cells are drawn bold (the
        puzzle's original clues) vs. thin (cells solved by the engine).
    """
    own_fig = ax is None
    if ax is None:
        fig, ax = plt.subplots(figsize=(4.2, 4.2))

    grid = np.array(grid)
    highlight = highlight or {}
    primary = set(highlight.get('primary', []))
    secondary = set(highlight.get('secondary', [])) - primary

    ax.set_xlim(0, 9)
    ax.set_ylim(0, 9)
    ax.set_aspect('equal')
    ax.invert_yaxis()
    ax.set_xticks([])
    ax.set_yticks([])

    for (r, c) in primary:
        ax.add_patch(patches.Rectangle((c, r), 1, 1, facecolor='#ffe28a', zorder=0))
    for (r, c) in secondary:
        ax.add_patch(patches.Rectangle((c, r), 1, 1, facecolor='#ffc2c2', zorder=0))

    for i in range(10):
        lw = 2.2 if i % 3 == 0 else 0.6
        ax.axhline(i, color='black', linewidth=lw, zorder=2)
        ax.axvline(i, color='black', linewidth=lw, zorder=2)

    for r in range(9):
        for c in range(9):
            v = grid[r, c]
            if v != 0:
                bold = given_mask is None or given_mask[r, c]
                ax.text(c + 0.5, r + 0.62, str(v), ha='center', va='center',
                         fontsize=16, fontweight='bold' if bold else 'normal',
                         color='black' if bold else '#1d3557', zorder=3)
            elif candidates is not None:
                cand = sorted(candidates[r][c])
                for v in cand:
                    cx = c + 0.18 + ((v - 1) % 3) * 0.32
                    cy = r + 0.22 + ((v - 1) // 3) * 0.28
                    ax.text(cx, cy, str(v), ha='center', va='center',
                            fontsize=6, color='#555555', zorder=3)

    if title:
        ax.set_title(title, fontsize=11)
    if own_fig:
        plt.tight_layout()
    return ax


def draw_step(analysis, step_index, figsize=(5.2, 5.2)):
    """Draw the grid state right after a given step in the chain, with the
    technique's pattern highlighted, plus a caption describing the move."""
    chain = analysis['chain']
    if not chain:
        print("Nessun passaggio registrato (il puzzle era gia risolto o bloccato subito).")
        return
    step_index = max(0, min(step_index, len(chain) - 1))
    move = chain[step_index]

    if step_index == 0:
        grid_before = analysis['original']
    else:
        grid_before = chain[step_index - 1]['grid_after']

    fig, ax = plt.subplots(figsize=figsize)
    draw_grid(grid_before, ax=ax, highlight=move['highlight'])
    caption = (f"Step {move['step']}/{len(chain)} - {move['technique']} "
               f"(difficolta {move['difficulty']})\n{move['description']}")
    ax.text(4.5, 9.55, caption, ha='center', va='top', fontsize=9, wrap=True)
    plt.tight_layout()
    plt.show()


def plot_difficulty_chain(analysis, figsize=(11, 4)):
    """Plot the difficulty level used at every step of the solving chain,
    colored by technique. This is the 'bidimensional' view of the chain:
    x = step number (progress through the solve), y = difficulty of the
    technique needed at that point, color = technique family."""
    chain = analysis['chain']
    if not chain:
        print("Catena vuota: nulla da visualizzare.")
        return

    steps = [m['step'] for m in chain]
    diffs = [m['difficulty'] for m in chain]
    families = [m['family'] for m in chain]
    fam_list = sorted(set(families))
    cmap = plt.get_cmap('tab10')
    fam_color = {f: cmap(i % 10) for i, f in enumerate(fam_list)}
    colors = [fam_color[f] for f in families]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize, gridspec_kw={'width_ratios': [2.4, 1]})

    ax1.scatter(steps, diffs, c=colors, s=45, zorder=3, edgecolor='black', linewidth=0.4)
    ax1.plot(steps, diffs, color='#cccccc', linewidth=1, zorder=1)
    ax1.set_xlabel('Step di risoluzione')
    ax1.set_ylabel('Difficolta della tecnica usata')
    ax1.set_yticks(range(1, 7))
    ax1.set_ylim(0.5, 6.5)
    ax1.set_title(f"Catena logica ({analysis['name']}) - {analysis['grading']['label']}")
    ax1.grid(alpha=0.3)

    handles = [plt.Line2D([0], [0], marker='o', color='w', label=f,
                           markerfacecolor=fam_color[f], markersize=8, markeredgecolor='black')
               for f in fam_list]
    ax1.legend(handles=handles, loc='upper left', fontsize=7, ncol=1,
               bbox_to_anchor=(1.02, 1.0), borderaxespad=0)

    hist = analysis['grading']['histogram']
    levels = list(range(1, 7))
    counts = [hist.get(l, 0) for l in levels]
    bar_colors = [DIFF_COLORS[l] for l in levels]
    ax2.bar([DIFF_LABEL_SHORT[l] for l in levels], counts, color=bar_colors, edgecolor='black')
    ax2.set_title('Passaggi per livello')
    ax2.set_ylabel('Numero di step')

    plt.tight_layout()
    plt.show()


def gallery(analyses, ncols=3, figsize_per_cell=(3.4, 3.6)):
    """Show the solved grid of several analysed puzzles side by side, with
    their difficulty label."""
    n = len(analyses)
    ncols = min(ncols, n) if n > 0 else 1
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols,
                              figsize=(figsize_per_cell[0] * ncols, figsize_per_cell[1] * nrows))
    axes = np.array(axes).reshape(-1)

    for i, res in enumerate(analyses):
        ax = axes[i]
        given_mask = res['original'] != 0
        draw_grid(res['solved_grid'], ax=ax, given_mask=given_mask)
        g = res['grading']
        subtitle = f"{res['name']}\n{g['label']} (max L{g['max_difficulty']}, {g.get('n_steps', 0)} step)"
        ax.set_title(subtitle, fontsize=9)

    for j in range(n, len(axes)):
        axes[j].axis('off')

    plt.tight_layout()
    plt.show()


def summary_dataframe(analysis):
    import pandas as pd
    rows = []
    for m in analysis['chain']:
        rows.append({
            'step': m['step'], 'tecnica': m['technique'], 'famiglia': m['family'],
            'difficolta': m['difficulty'], 'n_alternative': m['n_alternatives'],
            'descrizione': m['description'],
        })
    return pd.DataFrame(rows)

# [markdown]
# # 6. Esempi guidati
#
# ## 6.1 Un puzzle facile
#
# Un classico puzzle "easy": ci si aspetta che basti la famiglia degli
# inserimenti diretti (Naked/Hidden Single).

easy_puzzle = (
    "530070000"
    "600195000"
    "098000060"
    "800060003"
    "400803001"
    "700020006"
    "060000280"
    "000419005"
    "000080079"
)

easy_result = analyse_puzzle(easy_puzzle, name='easy')
print("Stato:", easy_result['status'])
print("Valutazione difficoltà:", easy_result['grading'])

draw_grid(easy_result['solved_grid'], given_mask=(easy_result['original'] != 0),
           title=f"{easy_result['name']} — {easy_result['grading']['label']}")
plt.show()

# [markdown]
# ## 6.2 Un puzzle che richiede tecniche intermedie/avanzate
#
# Generiamo un puzzle con soluzione unica e clue count medio-basso, per avere
# buone probabilità che servano tecniche oltre i semplici single. Se il primo
# tentativo risulta comunque troppo facile (può succedere, dipende dalla
# griglia casuale), si può rieseguire la cella con un altro seed.

rng = random.Random(12)
gen_puzzle, gen_full_solution = generate_unique_puzzle(target_clues=28, rng=rng)

hard_result = analyse_puzzle(gen_puzzle, name='generato')
print("Stato:", hard_result['status'])
print("Valutazione difficoltà:", hard_result['grading'])

tecniche_usate = {}
for m in hard_result['chain']:
    tecniche_usate[m['technique']] = tecniche_usate.get(m['technique'], 0) + 1
print("Tecniche usate nella catena:", tecniche_usate)

# [markdown]
# Vista d'insieme della catena logica: difficoltà per step, colorata per famiglia di tecnica, più istogramma dei livelli.

plot_difficulty_chain(hard_result)

# [markdown]
# Ispezione di un singolo passaggio: si può cambiare `step_index` per
# scorrere la catena e vedere esattamente dove la tecnica è stata applicata
# sulla griglia (celle gialle = pattern che definisce la mossa, celle rosa =
# celle modificate).

# indice dello step più difficile della catena, tanto per mostrarne uno interessante
if hard_result['chain']:
    hardest_idx = max(range(len(hard_result['chain'])),
                       key=lambda i: hard_result['chain'][i]['difficulty'])
    draw_step(hard_result, hardest_idx)

# [markdown]
# Tabella completa della catena, come DataFrame pandas.

summary_dataframe(hard_result)

# [markdown]
# # 7. Galleria finale
#
# Analizziamo e salviamo un piccolo insieme di puzzle (alcuni fissi, alcuni
# generati) e li visualizziamo tutti insieme, ciascuno con la propria
# etichetta di difficoltà. `saved_analyses` è la lista che raccoglie ogni
# puzzle analizzato in questa sessione: si può continuare ad aggiungerne altri
# richiamando `analyse_puzzle` e facendo `saved_analyses.append(...)` in
# qualunque punto del notebook, poi rilanciare le celle di questa sezione per
# aggiornare galleria e riepilogo.

saved_analyses = []

# un paio di puzzle fissi, per avere sempre un riferimento noto
saved_analyses.append(easy_result)

medium_puzzle = (
    "020840009"
    "090000060"
    "600000002"
    "003401800"
    "000000000"
    "004503200"
    "500000004"
    "030000070"
    "800097040"
)
saved_analyses.append(analyse_puzzle(medium_puzzle, name='medium'))

# alcuni puzzle generati con target di indizi diversi -> difficoltà attesa crescente
for target in [34, 30, 27]:
    rng_i = random.Random(target)
    p, _ = generate_unique_puzzle(target_clues=target, rng=rng_i)
    saved_analyses.append(analyse_puzzle(p, name=f'generato_{target}clue'))

saved_analyses.append(hard_result)

report_rows = []
for res in saved_analyses:
    g = res['grading']
    report_rows.append({
        'nome': res['name'],
        'stato': res['status'],
        'etichetta_difficolta': g['label'],
        'livello_max': g['max_difficulty'],
        'punteggio': g['score'],
        'n_step': g.get('n_steps', 0),
    })
import pandas as pd
pd.DataFrame(report_rows)

# [markdown]
# Galleria visiva di tutti i puzzle salvati finora.

gallery(saved_analyses, ncols=3)

# [markdown]
# ## Confronto delle catene
#
# Un'unica figura con la catena di difficoltà di ogni puzzle salvato,
# per confrontare a colpo d'occhio quanto e quando ciascuno richiede
# tecniche più avanzate.

for res in saved_analyses:
    if res['chain']:
        plot_difficulty_chain(res, figsize=(10, 3))
    else:
        print(f"{res['name']}: nessuno step registrato (già risolto o bloccato subito).")

# [markdown]
# # Note finali
#
# - La classificazione di difficoltà riflette **esattamente** la definizione
#   pratica del documento fornito: quanto è difficile individuare a mano il
#   pattern, non la complessità della dimostrazione logica.
# - Un puzzle che il motore segna come "stuck" non è necessariamente
#   irrisolvibile: significa che servirebbe una tecnica di livello 6 non
#   implementata qui (catene forzanti, AIC generali, ALS). Il flag
#   `backtracking_verified_solvable` conferma comunque se una soluzione
#   esiste.
# - Per estendere la copertura (es. Simple Colouring, X-Chain, W-Wing,
#   Unique Rectangle Type 2–5, BUG+1) basta aggiungere una nuova funzione con
#   la stessa firma `(state) -> list[move]` in `sudoku_techniques.py` e
#   registrarla in `TECHNIQUE_FUNCS` con la sua difficoltà minima: il motore
#   la userà automaticamente senza altre modifiche.

