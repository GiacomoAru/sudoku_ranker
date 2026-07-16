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
| Hidden Pair (riga/colonna), Naked Triple, Unique Rectangle T1, X-Wing, Skyscraper, Two-String Kite | 3 |
| Naked Quadruple, Hidden Triple, Y-Wing, XYZ-Wing, W-Wing, UR T2/T4, BUG+1, Swordfish | 4 |
| Hidden Quadruple, Jellyfish, UR T3/T5 | 5 |

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
from sudoku_data_structure import *

TECHNIQUE_DIFFICULTY = {
    # Inserimenti diretti
    "Naked Single": 1.0,
    "Hidden Single": 1.2,

    # Intersezioni e coppie
    "Naked Pair": 2.0,
    "Pointing": 2.0,
    "Claiming": 2.2,
    "Hidden Pair": 2.5,

    # Pattern intermedi
    "Naked Triple": 3.0,
    "Skyscraper": 3.2,
    "Two-String Kite": 3.3,
    "X-Wing": 3.5,
    "Unique Rectangle Type 1": 3.5,

    # Pattern avanzati
    "Naked Quadruple": 4.0,
    "Hidden Triple": 4.0,
    "Y-Wing": 4.0,
    "Unique Rectangle Type 2": 4.0,
    "BUG+1": 4.0,

    "Unique Rectangle Type 4": 4.2,
    "W-Wing": 4.2,

    "XYZ-Wing": 4.5,
    "Swordfish": 4.5,

    "Unique Rectangle Type 3": 4.7,
    "Unique Rectangle Type 5": 4.7,

    # Pattern esperti
    "Hidden Quadruple": 5.0,
    "Jellyfish": 5.0,
}
_TECHNIQUE_ORDER = [
    # 1.0
    "Naked Single",

    # 1.2
    "Hidden Single",

    # 2.0
    "Naked Pair",
    "Pointing",

    # 2.2
    "Claiming",

    # 2.5
    "Hidden Pair",

    # 3.0
    "Naked Triple",

    # 3.2
    "Skyscraper",

    # 3.3
    "Two-String Kite",

    # 3.5
    "X-Wing",
    "Unique Rectangle Type 1",

    # 4.0
    "Naked Quadruple",
    "Hidden Triple",
    "Y-Wing",
    "Unique Rectangle Type 2",
    "BUG+1",

    # 4.2
    "Unique Rectangle Type 4",
    "W-Wing",

    # 4.5
    "XYZ-Wing",
    "Swordfish",

    # 4.7
    "Unique Rectangle Type 3",
    "Unique Rectangle Type 5",

    # 5.0
    "Hidden Quadruple",
    "Jellyfish",
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


def _unit_name(unit_index, kind):
    if kind == 'row':
        return f'riga {unit_index + 1}'
    if kind == 'col':
        return f'colonna {unit_index - 9 + 1}'
    return f'box {unit_index - 18 + 1}'


def _strong_links(state, digit):
    """Restituisce tutte le coppie coniugate per un candidato."""
    links = []
    seen = set()
    for unit_index, (unit, kind) in enumerate(zip(UNITS, UNIT_KINDS)):
        cells = tuple(sorted(
            (r, c) for (r, c) in unit
            if digit in state.candidates[r][c]
        ))
        if len(cells) != 2:
            continue
        key = (cells, unit_index)
        if key in seen:
            continue
        seen.add(key)
        links.append((cells[0], cells[1], _unit_name(unit_index, kind)))
    return links


def _common_peer_cells(cells):
    cells = list(cells)
    if not cells:
        return set()
    common = set(peers(*cells[0]))
    for cell in cells[1:]:
        common &= peers(*cell)
    common -= set(cells)
    return common


def _move_signature(move):
    return (
        move['technique'],
        tuple(sorted(move.get('placements', []))),
        tuple(sorted(move.get('eliminations', []))),
    )


def _append_unique(moves, move, seen):
    if move is None:
        return
    signature = _move_signature(move)
    if signature not in seen:
        seen.add(signature)
        moves.append(move)


def w_wing(state):
    """Due celle bivalue uguali collegate da una coppia coniugata."""
    moves = []
    seen = set()
    bival = [
        (r, c) for r in range(9) for c in range(9)
        if state.grid[r, c] == 0 and len(state.candidates[r][c]) == 2
    ]

    for p1, p2 in combinations(bival, 2):
        pair = state.candidates[p1[0]][p1[1]]
        if state.candidates[p2[0]][p2[1]] != pair:
            continue
        if p2 in peers(*p1):
            continue

        for link_digit in sorted(pair):
            elimination_digit = next(iter(pair - {link_digit}))
            for a, b, unit_name in _strong_links(state, link_digit):
                if a in (p1, p2) or b in (p1, p2):
                    continue

                orientations = ((a, b), (b, a))
                for end1, end2 in orientations:
                    if end1 not in peers(*p1) or end2 not in peers(*p2):
                        continue

                    targets = _common_peer_cells((p1, p2))
                    pattern = {p1, p2, a, b}
                    eliminations = [
                        (r, c, elimination_digit)
                        for (r, c) in targets - pattern
                    ]
                    mv = _elim_move(
                        'W-Wing', 'Wings', 4,
                        f'Le celle R{p1[0]+1}C{p1[1]+1} e '
                        f'R{p2[0]+1}C{p2[1]+1} contengono entrambe '
                        f'{sorted(pair)}. La coppia coniugata del candidato '
                        f'{link_digit} nella {unit_name} collega le due celle: '
                        f'il candidato {elimination_digit} viene eliminato '
                        f'dalle celle che vedono entrambe.',
                        eliminations,
                        [p1, p2, a, b],
                        state,
                    )
                    _append_unique(moves, mv, seen)
    return moves


# --------------------------------------------------- 7. single digit patterns
def skyscraper(state):
    """Skyscraper orientati per righe o per colonne."""
    moves = []
    seen = set()

    for digit in range(1, 10):
        row_positions = {
            r: tuple(c for c in range(9) if digit in state.candidates[r][c])
            for r in range(9)
        }
        row_positions = {
            r: cols for r, cols in row_positions.items() if len(cols) == 2
        }

        for r1, r2 in combinations(row_positions, 2):
            cols1 = set(row_positions[r1])
            cols2 = set(row_positions[r2])
            shared = cols1 & cols2
            if len(shared) != 1:
                continue

            base_col = next(iter(shared))
            roof1 = (r1, next(iter(cols1 - shared)))
            roof2 = (r2, next(iter(cols2 - shared)))
            base1 = (r1, base_col)
            base2 = (r2, base_col)

            targets = _common_peer_cells((roof1, roof2))
            pattern = {base1, base2, roof1, roof2}
            eliminations = [
                (r, c, digit) for (r, c) in targets - pattern
            ]
            mv = _elim_move(
                'Skyscraper', 'Pattern a cifra singola', 3,
                f'Il candidato {digit} compare due volte nelle righe '
                f'{r1+1} e {r2+1}; le basi sono allineate in colonna '
                f'{base_col+1}. Almeno uno dei tetti '
                f'R{roof1[0]+1}C{roof1[1]+1} e '
                f'R{roof2[0]+1}C{roof2[1]+1} deve essere vero.',
                eliminations,
                [base1, base2, roof1, roof2],
                state,
            )
            _append_unique(moves, mv, seen)

        col_positions = {
            c: tuple(r for r in range(9) if digit in state.candidates[r][c])
            for c in range(9)
        }
        col_positions = {
            c: rows for c, rows in col_positions.items() if len(rows) == 2
        }

        for c1, c2 in combinations(col_positions, 2):
            rows1 = set(col_positions[c1])
            rows2 = set(col_positions[c2])
            shared = rows1 & rows2
            if len(shared) != 1:
                continue

            base_row = next(iter(shared))
            roof1 = (next(iter(rows1 - shared)), c1)
            roof2 = (next(iter(rows2 - shared)), c2)
            base1 = (base_row, c1)
            base2 = (base_row, c2)

            targets = _common_peer_cells((roof1, roof2))
            pattern = {base1, base2, roof1, roof2}
            eliminations = [
                (r, c, digit) for (r, c) in targets - pattern
            ]
            mv = _elim_move(
                'Skyscraper', 'Pattern a cifra singola', 3,
                f'Il candidato {digit} compare due volte nelle colonne '
                f'{c1+1} e {c2+1}; le basi sono allineate in riga '
                f'{base_row+1}. Almeno uno dei tetti '
                f'R{roof1[0]+1}C{roof1[1]+1} e '
                f'R{roof2[0]+1}C{roof2[1]+1} deve essere vero.',
                eliminations,
                [base1, base2, roof1, roof2],
                state,
            )
            _append_unique(moves, mv, seen)

    return moves


def two_string_kite(state):
    """Due coppie coniugate, una in riga e una in colonna, unite da un box."""
    moves = []
    seen = set()

    for digit in range(1, 10):
        row_links = []
        for r in range(9):
            cells = [(r, c) for c in range(9)
                     if digit in state.candidates[r][c]]
            if len(cells) == 2:
                row_links.append(tuple(cells))

        col_links = []
        for c in range(9):
            cells = [(r, c) for r in range(9)
                     if digit in state.candidates[r][c]]
            if len(cells) == 2:
                col_links.append(tuple(cells))

        for row_pair in row_links:
            for col_pair in col_links:
                # Il pattern standard usa quattro celle distinte.
                if len(set(row_pair) | set(col_pair)) != 4:
                    continue
                for row_bridge in row_pair:
                    row_outer = (
                        row_pair[1] if row_pair[0] == row_bridge else row_pair[0]
                    )
                    for col_bridge in col_pair:
                        col_outer = (
                            col_pair[1] if col_pair[0] == col_bridge else col_pair[0]
                        )

                        if row_bridge == col_bridge:
                            continue
                        if box_of(*row_bridge) != box_of(*col_bridge):
                            continue

                        targets = _common_peer_cells((row_outer, col_outer))
                        pattern = {
                            row_bridge, row_outer, col_bridge, col_outer
                        }
                        eliminations = [
                            (r, c, digit) for (r, c) in targets - pattern
                        ]
                        mv = _elim_move(
                            'Two-String Kite',
                            'Pattern a cifra singola',
                            3,
                            f'Il candidato {digit} forma una coppia coniugata '
                            f'nella riga {row_pair[0][0]+1} e una nella '
                            f'colonna {col_pair[0][1]+1}. Le estremita '
                            f'R{row_bridge[0]+1}C{row_bridge[1]+1} e '
                            f'R{col_bridge[0]+1}C{col_bridge[1]+1} sono '
                            f'nello stesso box, quindi almeno una delle altre '
                            f'due estremita deve essere vera.',
                            eliminations,
                            [row_bridge, row_outer, col_bridge, col_outer],
                            state,
                        )
                        _append_unique(moves, mv, seen)

    return moves


# ----------------------------------------------------------- 8. unique rect
def _rectangle_patterns(state):
    """Genera rettangoli validi: due righe, due colonne e due box."""
    for r1, r2 in combinations(range(9), 2):
        for c1, c2 in combinations(range(9), 2):
            cells = (
                (r1, c1), (r1, c2),
                (r2, c1), (r2, c2),
            )
            if any(state.grid[r, c] != 0 for r, c in cells):
                continue
            if len({box_of(r, c) for r, c in cells}) != 2:
                continue

            common = set(state.candidates[cells[0][0]][cells[0][1]])
            for r, c in cells[1:]:
                common &= state.candidates[r][c]

            for pair_tuple in combinations(sorted(common), 2):
                pair = frozenset(pair_tuple)
                extras = {
                    cell: set(state.candidates[cell[0]][cell[1]]) - set(pair)
                    for cell in cells
                }
                yield cells, pair, extras


def _common_units(cells):
    cells = set(cells)
    result = []
    for unit_index, (unit, kind) in enumerate(zip(UNITS, UNIT_KINDS)):
        if cells <= set(unit):
            result.append((unit_index, unit, kind))
    return result


def unique_rectangle_type1(state):
    moves = []
    seen = set()

    for cells, pair, extras in _rectangle_patterns(state):
        extra_cells = [cell for cell in cells if extras[cell]]
        if len(extra_cells) != 1:
            continue
        target = extra_cells[0]
        if any(extras[cell] for cell in cells if cell != target):
            continue

        eliminations = [(target[0], target[1], digit) for digit in pair]
        mv = _elim_move(
            'Unique Rectangle Type 1', 'Unicita', 3,
            f'Il rettangolo {", ".join(f"R{r+1}C{c+1}" for r, c in cells)} '
            f'ha la coppia {sorted(pair)} in tre celle pure. Per evitare '
            f'il rettangolo mortale, la coppia viene eliminata da '
            f'R{target[0]+1}C{target[1]+1}.',
            eliminations,
            list(cells),
            state,
        )
        _append_unique(moves, mv, seen)

    return moves


def unique_rectangle_type2(state):
    moves = []
    seen = set()

    for cells, pair, extras in _rectangle_patterns(state):
        roof = [cell for cell in cells if extras[cell]]
        floor = [cell for cell in cells if not extras[cell]]
        if len(roof) != 2 or len(floor) != 2:
            continue
        if roof[0][0] != roof[1][0] and roof[0][1] != roof[1][1]:
            continue
        if any(len(extras[cell]) != 1 for cell in roof):
            continue

        extra1 = next(iter(extras[roof[0]]))
        extra2 = next(iter(extras[roof[1]]))
        if extra1 != extra2:
            continue
        extra_digit = extra1

        targets = _common_peer_cells(roof) - set(cells)
        eliminations = [
            (r, c, extra_digit) for (r, c) in targets
        ]
        mv = _elim_move(
            'Unique Rectangle Type 2', 'Unicita', 4,
            f'Nel rettangolo basato su {sorted(pair)}, le celle tetto '
            f'R{roof[0][0]+1}C{roof[0][1]+1} e '
            f'R{roof[1][0]+1}C{roof[1][1]+1} condividono il solo '
            f'candidato extra {extra_digit}. Almeno uno dei due extra '
            f'deve essere vero.',
            eliminations,
            list(cells),
            state,
        )
        _append_unique(moves, mv, seen)

    return moves


def unique_rectangle_type3(state):
    """UR Type 3 con pseudo-cella e Naked Pair, Triple o Quadruple."""
    moves = []
    seen = set()

    for cells, pair, extras in _rectangle_patterns(state):
        roof = [cell for cell in cells if extras[cell]]
        floor = [cell for cell in cells if not extras[cell]]
        if len(roof) != 2 or len(floor) != 2:
            continue
        if roof[0][0] != roof[1][0] and roof[0][1] != roof[1][1]:
            continue

        virtual_candidates = extras[roof[0]] | extras[roof[1]]
        if len(virtual_candidates) < 2:
            continue

        for unit_index, unit, kind in _common_units(roof):
            available = []
            for cell in unit:
                if cell in cells or state.grid[cell[0], cell[1]] != 0:
                    continue
                candidates = state.candidates[cell[0]][cell[1]]
                if not candidates:
                    continue
                # Versione conservativa: le celle di supporto non devono
                # contenere i due candidati del rettangolo.
                if candidates & set(pair):
                    continue
                available.append(cell)

            for support_count in range(1, min(3, len(available)) + 1):
                subset_size = support_count + 1
                for support in combinations(available, support_count):
                    union = set(virtual_candidates)
                    for r, c in support:
                        union |= state.candidates[r][c]

                    if len(union) != subset_size:
                        continue

                    locked = set(cells) | set(support)
                    eliminations = [
                        (r, c, digit)
                        for (r, c) in unit
                        if (r, c) not in locked
                        for digit in union
                    ]
                    mv = _elim_move(
                        'Unique Rectangle Type 3', 'Unicita', 5,
                        f'Nel rettangolo basato su {sorted(pair)}, gli extra '
                        f'{sorted(virtual_candidates)} delle celle tetto '
                        f'agiscono come una pseudo-cella. Insieme a '
                        f'{", ".join(f"R{r+1}C{c+1}" for r, c in support)} '
                        f'formano un sottoinsieme bloccato nella '
                        f'{_unit_name(unit_index, kind)}.',
                        eliminations,
                        list(cells) + list(support),
                        state,
                    )
                    _append_unique(moves, mv, seen)

    return moves


def unique_rectangle_type4(state):
    moves = []
    seen = set()

    for cells, pair, extras in _rectangle_patterns(state):
        roof = [cell for cell in cells if extras[cell]]
        floor = [cell for cell in cells if not extras[cell]]
        if len(roof) != 2 or len(floor) != 2:
            continue
        if roof[0][0] != roof[1][0] and roof[0][1] != roof[1][1]:
            continue

        for unit_index, unit, kind in _common_units(roof):
            locked_digits = []
            for digit in sorted(pair):
                positions = {
                    (r, c) for (r, c) in unit
                    if digit in state.candidates[r][c]
                }
                if positions == set(roof):
                    locked_digits.append(digit)

            # Se entrambi i candidati sono coniugati nella stessa unita,
            # il rettangolo mortale sarebbe gia forzato: non e un Type 4
            # valido su un Sudoku unico.
            if len(locked_digits) != 1:
                continue

            locked_digit = locked_digits[0]
            other_digit = next(iter(set(pair) - {locked_digit}))
            eliminations = [
                (r, c, other_digit) for (r, c) in roof
            ]
            mv = _elim_move(
                'Unique Rectangle Type 4', 'Unicita', 4,
                f'Nel rettangolo basato su {sorted(pair)}, il candidato '
                f'{locked_digit} compare nella '
                f'{_unit_name(unit_index, kind)} solo nelle due celle '
                f'tetto. Per evitare il rettangolo mortale, '
                f'{other_digit} viene eliminato da entrambe.',
                eliminations,
                list(cells),
                state,
            )
            _append_unique(moves, mv, seen)

    return moves


def unique_rectangle_type5(state):
    """UR Type 5: stesso extra in due celle diagonali oppure in tre celle."""
    moves = []
    seen = set()

    for cells, pair, extras in _rectangle_patterns(state):
        extra_cells = [cell for cell in cells if extras[cell]]
        if len(extra_cells) not in (2, 3):
            continue
        if any(len(extras[cell]) != 1 for cell in extra_cells):
            continue

        extra_digits = {next(iter(extras[cell])) for cell in extra_cells}
        if len(extra_digits) != 1:
            continue
        extra_digit = next(iter(extra_digits))

        if len(extra_cells) == 2:
            first, second = extra_cells
            if first[0] == second[0] or first[1] == second[1]:
                continue

        if any(extras[cell] for cell in cells if cell not in extra_cells):
            continue

        targets = _common_peer_cells(extra_cells) - set(cells)
        eliminations = [
            (r, c, extra_digit) for (r, c) in targets
        ]
        mv = _elim_move(
            'Unique Rectangle Type 5', 'Unicita', 5,
            f'Nel rettangolo basato su {sorted(pair)}, il candidato extra '
            f'{extra_digit} deve comparire in almeno una delle celle '
            f'{", ".join(f"R{r+1}C{c+1}" for r, c in extra_cells)}.',
            eliminations,
            list(cells),
            state,
        )
        _append_unique(moves, mv, seen)

    return moves


def bug_plus_one(state):
    """Riconosce una BUG+1 in forma stretta e piazza il candidato extra."""
    unsolved = [
        (r, c) for r in range(9) for c in range(9)
        if state.grid[r, c] == 0
    ]
    if not unsolved:
        return []

    triple_cells = [
        cell for cell in unsolved
        if len(state.candidates[cell[0]][cell[1]]) == 3
    ]
    if len(triple_cells) != 1:
        return []

    target = triple_cells[0]
    if any(
        len(state.candidates[r][c]) != 2
        for r, c in unsolved
        if (r, c) != target
    ):
        return []

    valid_extra_digits = []
    target_candidates = state.candidates[target[0]][target[1]]

    for extra_digit in sorted(target_candidates):
        valid = True
        for unit in UNITS:
            contains_target = target in unit
            for digit in range(1, 10):
                count = sum(
                    digit in state.candidates[r][c]
                    for r, c in unit
                )
                if contains_target and digit == extra_digit:
                    if count != 3:
                        valid = False
                        break
                elif count not in (0, 2):
                    valid = False
                    break
            if not valid:
                break

        if valid:
            valid_extra_digits.append(extra_digit)

    if len(valid_extra_digits) != 1:
        return []

    value = valid_extra_digits[0]
    return [_place_move(
        'BUG+1', 'Unicita', 4,
        f'Tutte le celle irrisolte sono bivalue tranne '
        f'R{target[0]+1}C{target[1]+1}. Il candidato {value} e '
        f'lunico candidato extra compatibile con una BUG+1 e deve '
        f'essere inserito.',
        target[0], target[1], value,
    )]


# --------------------------------------------------------------- registry
# Simple Coloring, X-Chains, AIC e altre catene generali restano escluse:
# richiedono un motore a grafo dedicato e una gestione delle inferenze.
TECHNIQUE_FUNCS = [
    (1, lambda s: naked_single(s)),
    (1, lambda s: hidden_single(s)),
    (2, lambda s: locked_candidates(s)),
    (2, lambda s: naked_subset(s, 2)),
    (2, lambda s: hidden_subset(s, 2)),
    (3, lambda s: unique_rectangle_type1(s)),
    (3, lambda s: naked_subset(s, 3)),
    (3, lambda s: fish(s, 2)),
    (3, lambda s: skyscraper(s)),
    (3, lambda s: two_string_kite(s)),
    (4, lambda s: naked_subset(s, 4)),
    (4, lambda s: hidden_subset(s, 3)),
    (4, lambda s: unique_rectangle_type2(s)),
    (4, lambda s: unique_rectangle_type4(s)),
    (4, lambda s: bug_plus_one(s)),
    (4, lambda s: y_wing(s)),
    (4, lambda s: xyz_wing(s)),
    (4, lambda s: w_wing(s)),
    (4, lambda s: fish(s, 3)),
    (5, lambda s: unique_rectangle_type3(s)),
    (5, lambda s: unique_rectangle_type5(s)),
    (5, lambda s: hidden_subset(s, 4)),
    (5, lambda s: fish(s, 4)),
]
