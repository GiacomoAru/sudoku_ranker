'''
## 2. Libreria delle tecniche

Ogni funzione analizza lo stato corrente e restituisce **tutte** le istanze
di quella tecnica al momento applicabili (può essercene più di una nella
stessa griglia). Ogni mossa porta con sé: nome, famiglia, difficoltà (presa
dalla tabella del documento), una descrizione testuale, le celle da
compilare o le eliminazioni da fare, e le celle da evidenziare per la
visualizzazione.

Le difficoltà seguono esattamente la scala del documento:

| Tecnica | Difficoltà |
|---|---|
| Naked/Hidden Single | 1 |
| Pointing, Claiming, Naked Pair, Hidden Pair (in box) | 2 |
| Hidden Pair (riga/colonna), Naked Triple, Unique Rectangle T1, X-Wing | 3 |
| Naked Quadruple, Hidden Triple, Y-Wing, XYZ-Wing, Swordfish | 4 |
| Hidden Quadruple, Jellyfish | 5 |

Il registro `TECHNIQUE_FUNCS` in fondo associa ad ogni funzione la sua
difficoltà minima possibile: il motore risolutivo lo usa per **non
eseguire tecniche inutilmente costose** quando una mossa più semplice è già
stata trovata (vedi sezione 3).
'''

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
import sudoku_data_structure as sds


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
    for u, kind in zip(sds.UNITS, sds.UNIT_KINDS):
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
    for u, kind in zip(sds.UNITS, sds.UNIT_KINDS):
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
    for u, kind in zip(sds.UNITS, sds.UNIT_KINDS):
        if kind not in ('row', 'col'):
            continue
        for v in range(1, 10):
            cells = [(r, c) for (r, c) in u if v in state.candidates[r][c]]
            if len(cells) < 2:
                continue
            boxes = set(sds.box_of(r, c) for r, c in cells)
            if len(boxes) == 1:
                b = next(iter(boxes))
                box_cells = sds.UNITS[18 + b]
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
    for u, kind in zip(sds.UNITS, sds.UNIT_KINDS):
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
    for u, kind in zip(sds.UNITS, sds.UNIT_KINDS):
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
        p_peers = [cell for cell in sds.peers(pr, pc) if cell in bival_set]
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
            targets = sds.peers(w1r, w1c) & sds.peers(w2r, w2c)
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
        p_peers = [cell for cell in sds.peers(pr, pc)
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
            targets = sds.peers(pr, pc) & sds.peers(w1r, w1c) & sds.peers(w2r, w2c)
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
            boxes = {sds.box_of(r_a, c_a), sds.box_of(r_a, c_b), sds.box_of(r_b, c_a), sds.box_of(r_b, c_b)}
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