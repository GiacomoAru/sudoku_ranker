'''
## 2. Libreria delle tecniche

Ogni funzione analizza lo stato corrente e restituisce le conclusioni
logiche applicabili della tecnica. Le prove equivalenti vengono consolidate:
l'inventario conserva quante prove portano allo stesso risultato, ma espone
una sola mossa rappresentativa per ogni esito distinto. Le difficoltà sono
espresse nella scala classica Sudoku Explainer 1.2.1 (SE), non in livelli
generici da 1 a 5.

La tassonomia resta volutamente granulare: pattern moderni come Skyscraper,
Two-String Kite, Empty Rectangle, Remote Pair, XY-Chain, Turbot Fish e W-Wing
conservano il proprio nome, ma ricevono il rating della famiglia SE
equivalente. Il metadata della mossa conserva anche la tecnica logica genitrice
per consentire sia report dettagliati sia aggregazioni per famiglia.

Il registro `TECHNIQUE_FUNCS` in fondo è ordinato per rating SE minimo. Le
tecniche basate su catene generali, Nishio e forcing dinamiche delegano la
ricerca al motore di inferenza dedicato in `sudoku_logic_engine`. I risultati
sono classificati con tre granularità indipendenti: tecnica, famiglia logica
e strategia generale. Una cache per stato evita di ricalcolare i rilevatori
locali e le catene già richiesti durante lo stesso step di analisi.
'''

"""
Technique library. Every function takes a SudokuState and returns a list of
"Move" dicts describing every instance of that technique currently applicable
(there can be several in the same grid). The solver engine will later pick
the single simplest move across all techniques and apply it.

Move dict schema:
{
    'technique': str,           # display name, matches the taxonomy document
    'family': str,              # logical family, for detailed aggregation
    'strategy': str,            # broader strategy, for compact aggregation
    'difficulty': float,        # Sudoku Explainer 1.2.1 rating
    'description': str,         # human readable explanation of this instance
    'placements': [(r,c,v)],    # cells to solve (usually 0 or 1 entries)
    'eliminations': [(r,c,v)],  # candidates to strike out
    'highlight': {              # cells to visually mark, by role
        'primary': [(r,c)],     # cells that define the pattern
        'secondary': [(r,c)],   # cells affected by eliminations
    },
    'proof_count': int,         # equivalent proofs represented by this move
    'conclusion_count': int,    # atomic placements/eliminations in the move
}
A move must change something: it either places a digit or eliminates >=1
candidate; moves that would do nothing are not returned.
"""

from collections import defaultdict
from itertools import combinations

from sudoku_data_structure import *
import sudoku_logic_engine as logic_engine

TECHNIQUE_DIFFICULTY = {
    # Tecniche elementari (scala SE 1.2.1).
    "Last Value": 1.0,
    "Hidden Single (Box)": 1.2,
    "Hidden Single (Row/Column)": 1.5,
    "Direct Pointing": 1.7,
    "Direct Claiming": 1.9,
    "Direct Hidden Pair": 2.0,
    "Naked Single": 2.3,
    "Direct Hidden Triplet": 2.5,
    "Pointing": 2.6,
    "Claiming": 2.8,

    # Subset e fish.
    "Naked Pair": 3.0,
    "X-Wing": 3.2,
    "Hidden Pair": 3.4,
    "Naked Triple": 3.6,
    "Swordfish": 3.8,
    "Hidden Triple": 4.0,

    # Wings. SE chiama normalmente Y-Wing "XY-Wing".
    "Y-Wing": 4.2,
    "XYZ-Wing": 4.4,

    # Fascia SE 4.5-5.0. I nomi granulari vengono mantenuti e distribuiti
    # nella fascia indicativa fornita per i sottotipi.
    "Unique Rectangle Type 1": 4.5,
    "Unique Rectangle Type 2": 4.6,
    "Unique Rectangle Type 3": 4.8,
    "Unique Rectangle Type 4": 4.9,
    "Unique Rectangle Type 5": 5.0,
    "Naked Quadruple": 5.0,
    "Jellyfish": 5.2,
    "Hidden Quadruple": 5.4,
    "BUG+1": 5.6,
    "BUG Type 2": 5.7,
    "BUG Type 4": 5.7,
    "BUG Type 3 (Pair)": 5.8,
    "BUG Type 3 (Triplet)": 5.9,
    "BUG Type 3 (Quad)": 6.0,
    "Aligned Pair Exclusion": 6.2,

    # Cicli e catene statiche.
    "Bidirectional X-Cycle": 6.5,
    "Bidirectional Y-Cycle": 6.5,
    "Remote Pair": 6.5,       # Bidirectional Y-Cycle
    "XY-Chain": 6.5,          # Bidirectional Y-Cycle
    "XY-Cycle": 6.5,          # Bidirectional Y-Cycle
    "Forcing X-Chain": 6.6,

    # Nomi moderni mantenuti, rating della famiglia SE equivalente.
    "Skyscraper": 6.6,        # Forcing X-Chain
    "Two-String Kite": 6.6,  # Forcing X-Chain
    "Empty Rectangle": 6.6,  # Forcing X-Chain
    "Turbot Fish": 6.6,       # Forcing X-Chain breve
    "Forcing Chain": 7.0,
    "Alternating Inference Chain": 7.0,  # Forcing Chain
    "Bidirectional Cycle": 7.0,
    "Continuous Nice Loop": 7.0,         # Bidirectional Cycle
    "W-Wing": 7.0,           # Forcing Chain

    # Assunzioni, riduzioni multiple e propagazione dinamica.
    "Nishio": 7.5,
    "Cell Forcing Chain": 8.0,
    "Region Forcing Chain": 8.0,
    "Dynamic Forcing Chain": 8.5,
    "Dynamic Contradiction Forcing Chain": 8.5,
    "Dynamic Double Forcing Chain": 8.5,
    "Dynamic Cell Forcing Chain": 8.5,
    "Dynamic Region Forcing Chain": 8.5,
    "Dynamic Forcing Chain Plus": 9.0,
    "Dynamic Contradiction Forcing Chain Plus": 9.0,
    "Dynamic Double Forcing Chain Plus": 9.0,
    "Dynamic Cell Forcing Chain Plus": 9.0,
    "Dynamic Region Forcing Chain Plus": 9.0,
    "Nested Forcing Chain": 9.5,
    "Nested Contradiction Forcing Chain": 9.5,
    "Nested Double Forcing Chain": 9.5,
    "Nested Cell Forcing Chain": 9.5,
    "Nested Region Forcing Chain": 9.5,
}

# Il nome specifico resta distinto dalla famiglia logica che ne determina il
# rating SE e l'algoritmo. È utile anche ai report che vogliono aggregare o
# espandere la tassonomia a seconda del livello di dettaglio desiderato.
MODERN_TECHNIQUE_PARENT = {
    "Remote Pair": "Bidirectional Y-Cycle",
    "XY-Chain": "Bidirectional Y-Cycle",
    "XY-Cycle": "Bidirectional Y-Cycle",
    "Skyscraper": "Forcing X-Chain",
    "Two-String Kite": "Forcing X-Chain",
    "Empty Rectangle": "Forcing X-Chain",
    "Turbot Fish": "Forcing X-Chain",
    "W-Wing": "Forcing Chain",
    "Alternating Inference Chain": "Forcing Chain",
    "Continuous Nice Loop": "Bidirectional Cycle",
    "Dynamic Contradiction Forcing Chain": "Dynamic Forcing Chain",
    "Dynamic Double Forcing Chain": "Dynamic Forcing Chain",
    "Dynamic Cell Forcing Chain": "Dynamic Forcing Chain",
    "Dynamic Region Forcing Chain": "Dynamic Forcing Chain",
    "Dynamic Contradiction Forcing Chain Plus": "Dynamic Forcing Chain Plus",
    "Dynamic Double Forcing Chain Plus": "Dynamic Forcing Chain Plus",
    "Dynamic Cell Forcing Chain Plus": "Dynamic Forcing Chain Plus",
    "Dynamic Region Forcing Chain Plus": "Dynamic Forcing Chain Plus",
    "Nested Contradiction Forcing Chain": "Nested Forcing Chain",
    "Nested Double Forcing Chain": "Nested Forcing Chain",
    "Nested Cell Forcing Chain": "Nested Forcing Chain",
    "Nested Region Forcing Chain": "Nested Forcing Chain",
}

# Intervalli SE delle tecniche implementate dal motore logico. Il rating
# canonico usato dal solver è il minimo dell'intervallo; l'estremo superiore
# documenta la crescita storica legata alla lunghezza/complessità della prova.
LOGIC_ENGINE_TECHNIQUE_RANGES = {
    "Bidirectional X-Cycle": (6.5, 7.5),
    "Bidirectional Y-Cycle": (6.5, 7.5),
    "Forcing X-Chain": (6.6, 7.6),
    "Forcing Chain": (7.0, 8.0),
    "Bidirectional Cycle": (7.0, 8.0),
    "Nishio": (7.5, 8.5),
    "Cell Forcing Chain": (8.0, 9.0),
    "Region Forcing Chain": (8.0, 9.0),
    "Dynamic Forcing Chain": (8.5, 9.5),
    "Dynamic Forcing Chain Plus": (9.0, 10.0),
    "Nested Forcing Chain": (9.5, float("inf")),
}

# Nome storico mantenuto per compatibilità: tutte le voci che richiedevano il
# motore sono ora coperte.
TECHNIQUES_REQUIRING_LOGIC_ENGINE = {}

# La generalizzazione dei rettangoli a Unique Loop di 6+ celle richiede un
# enumeratore di cicli alternati con validazione delle case. È un componente
# a grafo dedicato; i rettangoli (loop di quattro celle) restano coperti dai
# cinque rilevatori granulari già presenti.
TECHNIQUES_REQUIRING_PATTERN_ENGINE = {
    "Unique Loop (6+ cells)": (4.6, 5.0),
}

_TECHNIQUE_ORDER = [
    # 1.0
    "Last Value",

    # 1.2
    "Hidden Single (Box)",

    # 1.5
    "Hidden Single (Row/Column)",

    # 1.7-2.0
    "Direct Pointing",
    "Direct Claiming",
    "Direct Hidden Pair",

    # 2.3-2.8
    "Naked Single",
    "Direct Hidden Triplet",
    "Pointing",
    "Claiming",

    # 3.0-4.0
    "Naked Pair",
    "X-Wing",
    "Hidden Pair",
    "Naked Triple",
    "Swordfish",
    "Hidden Triple",

    # 4.2-4.4
    "Y-Wing",
    "XYZ-Wing",

    # 4.5-5.6
    "Unique Rectangle Type 1",
    "Unique Rectangle Type 2",
    "Unique Rectangle Type 3",
    "Unique Rectangle Type 4",
    "Unique Rectangle Type 5",
    "Naked Quadruple",
    "Jellyfish",
    "Hidden Quadruple",
    "BUG+1",
    "BUG Type 2",
    "BUG Type 4",
    "BUG Type 3 (Pair)",
    "BUG Type 3 (Triplet)",
    "BUG Type 3 (Quad)",

    # Tecniche locali oltre la fascia BUG.
    "Aligned Pair Exclusion",

    # Cicli e catene generali gestiti dal motore logico.
    "Bidirectional X-Cycle",
    "Remote Pair",
    "XY-Chain",
    "XY-Cycle",
    "Bidirectional Y-Cycle",

    # Le specializzazioni precedono la famiglia generale a parità di rating,
    # così il log conserva il nome più informativo quando entrambe descrivono
    # la stessa eliminazione.
    "Skyscraper",
    "Two-String Kite",
    "Empty Rectangle",
    "Turbot Fish",
    "Forcing X-Chain",
    "W-Wing",
    "Alternating Inference Chain",
    "Forcing Chain",
    "Continuous Nice Loop",
    "Bidirectional Cycle",

    # Forcing multipli e dinamici.
    "Nishio",
    "Cell Forcing Chain",
    "Region Forcing Chain",
    "Dynamic Contradiction Forcing Chain",
    "Dynamic Double Forcing Chain",
    "Dynamic Cell Forcing Chain",
    "Dynamic Region Forcing Chain",
    "Dynamic Forcing Chain",
    "Dynamic Contradiction Forcing Chain Plus",
    "Dynamic Double Forcing Chain Plus",
    "Dynamic Cell Forcing Chain Plus",
    "Dynamic Region Forcing Chain Plus",
    "Dynamic Forcing Chain Plus",
    "Nested Contradiction Forcing Chain",
    "Nested Double Forcing Chain",
    "Nested Cell Forcing Chain",
    "Nested Region Forcing Chain",
    "Nested Forcing Chain",
]


# ---------------------------------------------------------------- taxonomy
# ``family`` mantiene una tassonomia abbastanza granulare per le heatmap
# dettagliate. ``strategy`` raggruppa invece famiglie affini in poche righe
# leggibili. La tecnica specifica resta sempre disponibile in ``technique``.
TECHNIQUE_FAMILY_ORDER = [
    "Inserimenti diretti",
    "Intersezioni box/linee",
    "Sottoinsiemi bloccati",
    "Fish",
    "Wings",
    "Unicita",
    "Exclusion",
    "Pattern a cifra singola",
    "Cicli bidirezionali",
    "Catene forzanti",
    "Assunzioni logiche",
    "Forcing multipli",
    "Forcing dinamici",
    "Forcing annidati",
]

TECHNIQUE_STRATEGY_ORDER = [
    "Tecniche elementari",
    "Sottoinsiemi e intersezioni",
    "Fish e wings",
    "Unicita ed esclusione",
    "Pattern a cifra singola",
    "Catene statiche",
    "Forcing multipli",
    "Forcing dinamici",
    "Forcing annidati",
]

TECHNIQUE_FAMILY = {
    "Last Value": "Inserimenti diretti",
    "Hidden Single (Box)": "Inserimenti diretti",
    "Hidden Single (Row/Column)": "Inserimenti diretti",
    "Naked Single": "Inserimenti diretti",
    "Direct Pointing": "Intersezioni box/linee",
    "Direct Claiming": "Intersezioni box/linee",
    "Pointing": "Intersezioni box/linee",
    "Claiming": "Intersezioni box/linee",
    "Direct Hidden Pair": "Sottoinsiemi bloccati",
    "Direct Hidden Triplet": "Sottoinsiemi bloccati",
    "Naked Pair": "Sottoinsiemi bloccati",
    "Hidden Pair": "Sottoinsiemi bloccati",
    "Naked Triple": "Sottoinsiemi bloccati",
    "Hidden Triple": "Sottoinsiemi bloccati",
    "Naked Quadruple": "Sottoinsiemi bloccati",
    "Hidden Quadruple": "Sottoinsiemi bloccati",
    "X-Wing": "Fish",
    "Swordfish": "Fish",
    "Jellyfish": "Fish",
    "Y-Wing": "Wings",
    "XYZ-Wing": "Wings",
    "W-Wing": "Wings",
    "Unique Rectangle Type 1": "Unicita",
    "Unique Rectangle Type 2": "Unicita",
    "Unique Rectangle Type 3": "Unicita",
    "Unique Rectangle Type 4": "Unicita",
    "Unique Rectangle Type 5": "Unicita",
    "BUG+1": "Unicita",
    "BUG Type 2": "Unicita",
    "BUG Type 3 (Pair)": "Unicita",
    "BUG Type 3 (Triplet)": "Unicita",
    "BUG Type 3 (Quad)": "Unicita",
    "BUG Type 4": "Unicita",
    "Aligned Pair Exclusion": "Exclusion",
    "Skyscraper": "Pattern a cifra singola",
    "Two-String Kite": "Pattern a cifra singola",
    "Empty Rectangle": "Pattern a cifra singola",
    "Turbot Fish": "Pattern a cifra singola",
    "Bidirectional X-Cycle": "Cicli bidirezionali",
    "Bidirectional Y-Cycle": "Cicli bidirezionali",
    "Remote Pair": "Cicli bidirezionali",
    "XY-Chain": "Cicli bidirezionali",
    "XY-Cycle": "Cicli bidirezionali",
    "Bidirectional Cycle": "Cicli bidirezionali",
    "Continuous Nice Loop": "Cicli bidirezionali",
    "Forcing X-Chain": "Catene forzanti",
    "Forcing Chain": "Catene forzanti",
    "Alternating Inference Chain": "Catene forzanti",
    "Nishio": "Assunzioni logiche",
    "Cell Forcing Chain": "Forcing multipli",
    "Region Forcing Chain": "Forcing multipli",
    "Dynamic Forcing Chain": "Forcing dinamici",
    "Dynamic Contradiction Forcing Chain": "Forcing dinamici",
    "Dynamic Double Forcing Chain": "Forcing dinamici",
    "Dynamic Cell Forcing Chain": "Forcing dinamici",
    "Dynamic Region Forcing Chain": "Forcing dinamici",
    "Dynamic Forcing Chain Plus": "Forcing dinamici",
    "Dynamic Contradiction Forcing Chain Plus": "Forcing dinamici",
    "Dynamic Double Forcing Chain Plus": "Forcing dinamici",
    "Dynamic Cell Forcing Chain Plus": "Forcing dinamici",
    "Dynamic Region Forcing Chain Plus": "Forcing dinamici",
    "Nested Forcing Chain": "Forcing annidati",
    "Nested Contradiction Forcing Chain": "Forcing annidati",
    "Nested Double Forcing Chain": "Forcing annidati",
    "Nested Cell Forcing Chain": "Forcing annidati",
    "Nested Region Forcing Chain": "Forcing annidati",
}

_FAMILY_TO_STRATEGY = {
    "Inserimenti diretti": "Tecniche elementari",
    "Intersezioni box/linee": "Sottoinsiemi e intersezioni",
    "Sottoinsiemi bloccati": "Sottoinsiemi e intersezioni",
    "Fish": "Fish e wings",
    "Wings": "Fish e wings",
    "Unicita": "Unicita ed esclusione",
    "Exclusion": "Unicita ed esclusione",
    "Pattern a cifra singola": "Pattern a cifra singola",
    "Cicli bidirezionali": "Catene statiche",
    "Catene forzanti": "Catene statiche",
    "Assunzioni logiche": "Forcing multipli",
    "Forcing multipli": "Forcing multipli",
    "Forcing dinamici": "Forcing dinamici",
    "Forcing annidati": "Forcing annidati",
}

TECHNIQUE_STRATEGY = {
    technique: _FAMILY_TO_STRATEGY[family]
    for technique, family in TECHNIQUE_FAMILY.items()
}


def technique_family(technique, fallback=None):
    """Restituisce la famiglia canonica di una tecnica."""
    if technique in TECHNIQUE_FAMILY:
        return TECHNIQUE_FAMILY[technique]
    if fallback is not None:
        return fallback
    parent = MODERN_TECHNIQUE_PARENT.get(technique)
    if parent in TECHNIQUE_FAMILY:
        return TECHNIQUE_FAMILY[parent]
    return "Altro"


def technique_strategy(technique, family=None):
    """Restituisce la strategia generale usata nelle viste compatte."""
    if technique in TECHNIQUE_STRATEGY:
        return TECHNIQUE_STRATEGY[technique]
    family = family or technique_family(technique)
    return _FAMILY_TO_STRATEGY.get(family, "Altro")


def technique_metadata(technique):
    """Metadata stabile consumabile da solver, report e visualizzazioni."""
    family = technique_family(technique)
    return {
        "technique": technique,
        "family": family,
        "strategy": technique_strategy(technique, family),
        "difficulty": _canonical_difficulty(technique),
        "parent": MODERN_TECHNIQUE_PARENT.get(technique, technique),
    }


_missing_family_metadata = set(TECHNIQUE_DIFFICULTY) - set(TECHNIQUE_FAMILY)
if _missing_family_metadata:
    missing = ", ".join(sorted(_missing_family_metadata))
    raise RuntimeError(f"Metadata di famiglia mancante per: {missing}")


# ---------------------------------------------------------- move utilities
def _normalise_triplets(items):
    return sorted({
        (int(r), int(c), int(value))
        for r, c, value in items
    })


def _normalise_cells(items):
    return sorted({
        (int(r), int(c))
        for r, c in items
    })


def _atomic_conclusions(placements, eliminations):
    return {
        ("place", r, c, value)
        for r, c, value in placements
    } | {
        ("eliminate", r, c, value)
        for r, c, value in eliminations
    }


def _build_move(
    technique,
    family,
    difficulty,
    description,
    placements,
    eliminations,
    primary,
    secondary=None,
    proof_count=1,
    extra=None,
):
    """Costruisce una Move con tassonomia e conteggi uniformi."""
    placements = _normalise_triplets(placements)
    eliminations = _normalise_triplets(eliminations)
    conclusions = _atomic_conclusions(placements, eliminations)

    if not conclusions:
        return None

    canonical_family = technique_family(technique, family)
    canonical_strategy = technique_strategy(technique, canonical_family)
    primary = _normalise_cells(primary)

    if secondary is None:
        secondary = [
            (r, c)
            for _, r, c, _ in conclusions
        ]

    move = {
        "technique": technique,
        "family": canonical_family,
        "strategy": canonical_strategy,
        "difficulty": _canonical_difficulty(technique, difficulty),
        "description": description,
        "placements": placements,
        "eliminations": eliminations,
        "highlight": {
            "primary": primary,
            "secondary": _normalise_cells(secondary),
        },
        "proof_count": max(int(proof_count), 1),
        "conclusion_count": len(conclusions),
    }

    if extra:
        move.update(extra)

    return move


# -------------------------------------------------------------- state cache
# Il solver interroga molte funzioni sullo stesso stato. Le catene, inoltre,
# richiamano tecniche locali per escludere conclusioni gia spiegate in modo
# piu semplice. La cache evita che questi rilevatori vengano rieseguiti.
_CACHE_ATTRIBUTE = "_sudoku_technique_analysis_cache"


def _state_signature(state):
    grid = state.grid
    if hasattr(grid, "tobytes"):
        grid_signature = grid.tobytes()
    else:
        grid_signature = tuple(
            int(grid[r][c])
            for r in range(9)
            for c in range(9)
        )

    candidate_signature = tuple(
        tuple(sorted(int(value) for value in state.candidates[r][c]))
        for r in range(9)
        for c in range(9)
    )

    return grid_signature, candidate_signature


def _state_cache(state):
    signature = _state_signature(state)
    cache_data = getattr(state, _CACHE_ATTRIBUTE, None)

    if (
        cache_data is None
        or cache_data.get("signature") != signature
    ):
        cache_data = {
            "signature": signature,
            "moves": {},
        }
        try:
            setattr(state, _CACHE_ATTRIBUTE, cache_data)
        except (AttributeError, TypeError):
            # Stato con __slots__ restrittivi: la correttezza non dipende
            # dalla cache, quindi si usa semplicemente un contenitore locale.
            pass

    return cache_data["moves"]


def _cached_moves(state, key, producer):
    cache = _state_cache(state)
    if key not in cache:
        cache[key] = tuple(producer())
    return list(cache[key])


def clear_technique_cache(state):
    """Invalida esplicitamente la cache, utile per test o mutation custom."""
    try:
        delattr(state, _CACHE_ATTRIBUTE)
    except AttributeError:
        pass


def _cached_local(state, key, function, *args):
    return _cached_moves(
        state,
        f"local:{key}",
        lambda: function(state, *args),
    )


def _canonical_difficulty(technique, fallback=None):
    """Restituisce il rating SE canonico della tecnica."""
    if technique in TECHNIQUE_DIFFICULTY:
        return float(TECHNIQUE_DIFFICULTY[technique])
    if fallback is None:
        raise KeyError(f"Rating SE mancante per {technique!r}")
    return float(fallback)


def _elim_move(technique, family, difficulty, description, eliminations, primary, state):
    """Costruisce una mossa di sole eliminazioni, scartando i no-op."""
    real = [
        (r, c, value)
        for r, c, value in eliminations
        if value in state.candidates[r][c]
    ]
    return _build_move(
        technique=technique,
        family=family,
        difficulty=difficulty,
        description=description,
        placements=(),
        eliminations=real,
        primary=primary,
    )


def _place_move(technique, family, difficulty, description, r, c, v, primary=None):
    return _build_move(
        technique=technique,
        family=family,
        difficulty=difficulty,
        description=description,
        placements=[(r, c, v)],
        eliminations=(),
        primary=primary or [(r, c)],
        secondary=[(r, c)],
    )


def _direct_move(technique, family, difficulty, description, placement,
                 eliminations, primary, state):
    """Costruisce una tecnica Direct: eliminazioni e Hidden Single finale."""
    real = [
        (r, c, value)
        for r, c, value in eliminations
        if value in state.candidates[r][c]
    ]
    r, c, value = placement
    return _build_move(
        technique=technique,
        family=family,
        difficulty=difficulty,
        description=description,
        placements=[(r, c, value)],
        eliminations=real,
        primary=primary,
    )


# ---------------------------------------------------------- 1.0 last value
def last_value(state):
    """Ultima cella vuota di una riga, colonna o box (SE 1.0)."""
    moves = []
    seen = set()
    for unit, kind in zip(UNITS, UNIT_KINDS):
        empties = [(r, c) for r, c in unit if state.grid[r, c] == 0]
        if len(empties) != 1:
            continue
        r, c = empties[0]
        missing = ALL_DIGITS - {int(state.grid[rr, cc]) for rr, cc in unit}
        if len(missing) != 1:
            continue
        value = next(iter(missing))
        if value not in state.candidates[r][c] or (r, c, value) in seen:
            continue
        seen.add((r, c, value))
        moves.append(_place_move(
            'Last Value', 'Inserimenti diretti', 1.0,
            f'R{r+1}C{c+1} è l ultima cella vuota del {kind}: '
            f'deve contenere {value}.',
            r, c, value, primary=list(unit),
        ))
    return moves


# -------------------------------------------------------------- 1.2-2.3
def naked_single(state):
    moves = []
    for r in range(9):
        for c in range(9):
            cand = state.candidates[r][c]
            if state.grid[r, c] == 0 and len(cand) == 1:
                v = next(iter(cand))
                moves.append(_place_move(
                    'Naked Single', 'Inserimenti diretti', 2.3,
                    f'La cella R{r+1}C{c+1} ha un solo candidato possibile: {v}.',
                    r, c, v))
    return moves


def hidden_single(state):
    moves = []
    seen = set()
    for u, kind in zip(UNITS, UNIT_KINDS):
        # Con una sola cella vuota SE classifica la mossa come Last Value.
        if sum(state.grid[r, c] == 0 for r, c in u) <= 1:
            continue
        for v in range(1, 10):
            cells = [(r, c) for (r, c) in u if v in state.candidates[r][c]]
            if len(cells) == 1:
                r, c = cells[0]
                technique = (
                    'Hidden Single (Box)'
                    if kind == 'box'
                    else 'Hidden Single (Row/Column)'
                )
                key = (technique, r, c, v)
                if key in seen:
                    continue
                seen.add(key)
                moves.append(_place_move(
                    technique, 'Inserimenti diretti',
                    1.2 if kind == 'box' else 1.5,
                    f'Nel {kind} che contiene R{r+1}C{c+1}, il numero {v} puo comparire solo li.',
                    r, c, v, primary=list(u)))
    return moves


# ----------------------------------------------------- 1.7-1.9 direct locking
def direct_locked_candidates(state):
    """Pointing/Claiming che producono subito un Hidden Single."""
    moves = []
    seen = set()

    # Pointing: un box blocca il candidato su una linea. In un altro box
    # attraversato dalla stessa linea resta una sola posizione fuori linea.
    for box_index in range(9):
        box = UNITS[18 + box_index]
        for value in range(1, 10):
            source = [
                (r, c) for r, c in box
                if value in state.candidates[r][c]
            ]
            if len(source) < 2:
                continue

            for axis in ('row', 'col'):
                coordinates = {
                    r if axis == 'row' else c for r, c in source
                }
                if len(coordinates) != 1:
                    continue
                coordinate = next(iter(coordinates))

                for other_box_index in range(9):
                    if other_box_index == box_index:
                        continue
                    other_box = UNITS[18 + other_box_index]
                    if not any(
                        (r if axis == 'row' else c) == coordinate
                        for r, c in other_box
                    ):
                        continue
                    positions = [
                        (r, c) for r, c in other_box
                        if value in state.candidates[r][c]
                    ]
                    if len(positions) <= 1:
                        continue
                    removed = [
                        (r, c) for r, c in positions
                        if (r if axis == 'row' else c) == coordinate
                    ]
                    remaining = [
                        cell for cell in positions if cell not in removed
                    ]
                    if not removed or len(remaining) != 1:
                        continue
                    target = remaining[0]
                    eliminations = [
                        (r, c, value) for r, c in removed
                    ]
                    mv = _direct_move(
                        'Direct Pointing', 'Intersezioni box/linee', 1.7,
                        f'Il Pointing del candidato {value} dal box '
                        f'{box_index+1} elimina le altre posizioni nella '
                        f'{axis} {coordinate+1} e lascia un Hidden Single in '
                        f'R{target[0]+1}C{target[1]+1}.',
                        (target[0], target[1], value), eliminations,
                        source + positions, state,
                    )
                    _append_unique(moves, mv, seen)

    # Claiming: una riga/colonna blocca il candidato in un box. In un'altra
    # linea dello stesso tipo che attraversa il box resta una sola posizione
    # esterna al box.
    for source_kind in ('row', 'col'):
        source_indexes = (
            range(9) if source_kind == 'row' else range(9, 18)
        )
        for source_index in source_indexes:
            source_unit = UNITS[source_index]
            source_number = (
                source_index + 1
                if source_kind == 'row'
                else source_index - 8
            )
            for value in range(1, 10):
                source = [
                    (r, c) for r, c in source_unit
                    if value in state.candidates[r][c]
                ]
                if len(source) < 2:
                    continue
                boxes = {box_of(r, c) for r, c in source}
                if len(boxes) != 1:
                    continue
                box_index = next(iter(boxes))
                box = UNITS[18 + box_index]

                other_indexes = (
                    {r for r, _ in box}
                    if source_kind == 'row'
                    else {c for _, c in box}
                )
                other_indexes.discard(
                    source_index
                    if source_kind == 'row'
                    else source_index - 9
                )
                for other in sorted(other_indexes):
                    other_unit = UNITS[
                        other if source_kind == 'row' else 9 + other
                    ]
                    positions = [
                        (r, c) for r, c in other_unit
                        if value in state.candidates[r][c]
                    ]
                    if len(positions) <= 1:
                        continue
                    removed = [cell for cell in positions if cell in box]
                    remaining = [cell for cell in positions if cell not in box]
                    if not removed or len(remaining) != 1:
                        continue
                    target = remaining[0]
                    eliminations = [
                        (r, c, value) for r, c in removed
                    ]
                    mv = _direct_move(
                        'Direct Claiming', 'Intersezioni box/linee', 1.9,
                        f'Il Claiming del candidato {value} dalla '
                        f'{source_kind} {source_number} elimina le altre '
                        f'posizioni nel box {box_index+1} e lascia un Hidden '
                        f'Single in R{target[0]+1}C{target[1]+1}.',
                        (target[0], target[1], value), eliminations,
                        source + positions, state,
                    )
                    _append_unique(moves, mv, seen)

    return moves


# ------------------------------------------------------- 2.6-2.8 locked candidate
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


# --------------------------------------------------- 2.0/2.5 direct hidden set
_DIRECT_HIDDEN_NAME = {
    2: 'Direct Hidden Pair',
    3: 'Direct Hidden Triplet',
}


def direct_hidden_subset(state, size):
    """Hidden Pair/Triplet che produce subito un Hidden Single."""
    if size not in _DIRECT_HIDDEN_NAME:
        raise ValueError("Una tecnica Direct SE esiste solo per size 2 o 3")

    technique = _DIRECT_HIDDEN_NAME[size]
    moves = []
    seen = set()

    for unit, kind in zip(UNITS, UNIT_KINDS):
        empties = [
            (r, c) for r, c in unit if state.grid[r, c] == 0
        ]
        if len(empties) <= size:
            continue

        digit_cells = {}
        for value in range(1, 10):
            cells = [
                (r, c) for r, c in unit
                if value in state.candidates[r][c]
            ]
            if 1 <= len(cells) <= size:
                digit_cells[value] = cells

        for digits in combinations(sorted(digit_cells), size):
            subset_cells = set()
            for value in digits:
                subset_cells.update(digit_cells[value])
            if len(subset_cells) != size:
                continue

            eliminations = [
                (r, c, value)
                for r, c in subset_cells
                for value in state.candidates[r][c]
                if value not in digits
            ]
            if not eliminations:
                continue

            for hidden_value in range(1, 10):
                if hidden_value in digits:
                    continue
                positions = [
                    (r, c) for r, c in unit
                    if hidden_value in state.candidates[r][c]
                ]
                if len(positions) <= 1:
                    continue
                remaining = [
                    cell for cell in positions if cell not in subset_cells
                ]
                if len(remaining) != 1:
                    continue
                target = remaining[0]
                mv = _direct_move(
                    technique, 'Sottoinsiemi bloccati',
                    2.0 if size == 2 else 2.5,
                    f'Nel {kind}, i numeri {list(digits)} formano un '
                    f'{technique}. Le eliminazioni risultanti lasciano '
                    f'{hidden_value} come Hidden Single in '
                    f'R{target[0]+1}C{target[1]+1}.',
                    (target[0], target[1], hidden_value), eliminations,
                    list(subset_cells) + [target], state,
                )
                _append_unique(moves, mv, seen)

    return moves


# --------------------------------------------------------- 3. naked subsets
_NAKED_DIFF = {2: 3.0, 3: 3.6, 4: 5.0}
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
_HIDDEN_DIFF_BOX = {2: 3.4, 3: 4.0, 4: 5.4}
_HIDDEN_DIFF_LINE = {2: 3.4, 3: 4.0, 4: 5.4}
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
_FISH_DIFF = {2: 3.2, 3: 3.8, 4: 5.2}


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


def empty_rectangle(state):
    """Empty Rectangle: ERI di box collegata a una coppia coniugata.

    Nel box le posizioni di un candidato devono stare sull'unione di una
    mini-riga e una mini-colonna, con l'intersezione vuota e almeno una
    posizione su ciascun braccio. Una strong link esterna allineata con un
    braccio chiude la breve X-Chain e produce l'eliminazione sull'altro asse.
    """
    moves = []
    seen = set()

    for digit in range(1, 10):
        for box_index in range(9):
            box = UNITS[18 + box_index]
            box_rows = sorted({r for r, _ in box})
            box_columns = sorted({c for _, c in box})
            positions = {
                (r, c) for r, c in box
                if digit in state.candidates[r][c]
            }
            if len(positions) < 2:
                continue

            for eri_row in box_rows:
                for eri_column in box_columns:
                    eri = (eri_row, eri_column)
                    if eri in positions:
                        continue
                    if not all(
                        r == eri_row or c == eri_column
                        for r, c in positions
                    ):
                        continue
                    row_arm = {
                        cell for cell in positions
                        if cell[0] == eri_row
                    }
                    column_arm = {
                        cell for cell in positions
                        if cell[1] == eri_column
                    }
                    if not row_arm or not column_arm:
                        continue

                    # Strong link verticale: una estremità è allineata con la
                    # mini-riga dell'ERI; il target incrocia l'altra estremità
                    # con la mini-colonna dell'ERI.
                    for external_column in sorted(
                        set(range(9)) - set(box_columns)
                    ):
                        link = [
                            (r, external_column) for r in range(9)
                            if digit in state.candidates[r][external_column]
                        ]
                        if len(link) != 2:
                            continue
                        aligned = [cell for cell in link if cell[0] == eri_row]
                        if len(aligned) != 1:
                            continue
                        outer = link[0] if link[1] == aligned[0] else link[1]
                        if outer[0] in box_rows:
                            continue
                        target = (outer[0], eri_column)
                        mv = _elim_move(
                            'Empty Rectangle',
                            'Pattern a cifra singola',
                            6.6,
                            f'Nel box {box_index+1}, le posizioni di {digit} '
                            f'formano un Empty Rectangle con ERI '
                            f'R{eri_row+1}C{eri_column+1}. La coppia '
                            f'coniugata in colonna {external_column+1} '
                            f'elimina {digit} da '
                            f'R{target[0]+1}C{target[1]+1}.',
                            [(target[0], target[1], digit)],
                            sorted(positions | set(link)),
                            state,
                        )
                        _append_unique(moves, mv, seen)

                    # Caso trasposto con strong link orizzontale.
                    for external_row in sorted(
                        set(range(9)) - set(box_rows)
                    ):
                        link = [
                            (external_row, c) for c in range(9)
                            if digit in state.candidates[external_row][c]
                        ]
                        if len(link) != 2:
                            continue
                        aligned = [cell for cell in link if cell[1] == eri_column]
                        if len(aligned) != 1:
                            continue
                        outer = link[0] if link[1] == aligned[0] else link[1]
                        if outer[1] in box_columns:
                            continue
                        target = (eri_row, outer[1])
                        mv = _elim_move(
                            'Empty Rectangle',
                            'Pattern a cifra singola',
                            6.6,
                            f'Nel box {box_index+1}, le posizioni di {digit} '
                            f'formano un Empty Rectangle con ERI '
                            f'R{eri_row+1}C{eri_column+1}. La coppia '
                            f'coniugata in riga {external_row+1} elimina '
                            f'{digit} da R{target[0]+1}C{target[1]+1}.',
                            [(target[0], target[1], digit)],
                            sorted(positions | set(link)),
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


# ---------------------------------------------------------- 5.7-6.0 BUG 2-4
def _bug_core(state):
    """Rimuove virtualmente i candidati extra e valida il deadly pattern."""
    unsolved = [
        (r, c) for r in range(9) for c in range(9)
        if state.grid[r, c] == 0
    ]
    if not unsolved or any(
        len(state.candidates[r][c]) < 2 for r, c in unsolved
    ):
        return None

    extra_values = {}
    for unit in UNITS:
        for value in range(1, 10):
            positions = [
                (r, c) for r, c in unit
                if value in state.candidates[r][c]
            ]
            if len(positions) in (0, 2):
                continue
            high_cardinality = [
                cell for cell in positions
                if len(state.candidates[cell[0]][cell[1]]) >= 3
            ]
            if not high_cardinality:
                return None
            # Se più celle sono possibili, un'altra casa deve identificare
            # univocamente ciascun extra. La validazione finale scarta i casi
            # rimasti ambigui.
            if len(high_cardinality) == 1:
                extra_values.setdefault(high_cardinality[0], set()).add(value)

    if not extra_values:
        return None

    virtual = {}
    for cell in unsolved:
        candidates = set(state.candidates[cell[0]][cell[1]])
        candidates -= extra_values.get(cell, set())
        if len(candidates) != 2:
            return None
        virtual[cell] = candidates

    for unit in UNITS:
        for value in range(1, 10):
            count = sum(value in virtual.get(cell, set()) for cell in unit)
            if count not in (0, 2):
                return None

    bug_cells = sorted(extra_values)
    all_extra_values = set().union(*extra_values.values())
    common_peers = set(peers(*bug_cells[0]))
    for cell in bug_cells[1:]:
        common_peers &= peers(*cell)
    common_peers -= set(bug_cells)

    return bug_cells, extra_values, all_extra_values, common_peers


def bug_types_2_to_4(state):
    """Rileva le varianti BUG 2, 3 e 4 senza usare assunzioni o catene."""
    core = _bug_core(state)
    if core is None:
        return []

    bug_cells, extra_values, all_extra_values, common_peers = core
    if len(bug_cells) < 2:
        return []

    moves = []
    seen = set()

    # BUG Type 2: tutte le celle BUG condividono lo stesso candidato extra;
    # almeno una deve assumerlo.
    if len(all_extra_values) == 1:
        value = next(iter(all_extra_values))
        eliminations = [
            (r, c, value) for r, c in common_peers
        ]
        mv = _elim_move(
            'BUG Type 2', 'Unicita', 5.7,
            f'Le celle BUG {", ".join(f"R{r+1}C{c+1}" for r, c in bug_cells)} '
            f'condividono il candidato extra {value}: deve essere vero in '
            f'almeno una di esse.',
            eliminations, bug_cells, state,
        )
        _append_unique(moves, mv, seen)

    # BUG Type 4: due celle BUG nella stessa casa condividono un unico
    # candidato non-extra, che resta bloccato fra le due celle.
    if len(bug_cells) == 2 and _common_units(bug_cells):
        first, second = bug_cells
        common_non_extra = (
            state.candidates[first[0]][first[1]]
            & state.candidates[second[0]][second[1]]
        ) - all_extra_values
        if len(common_non_extra) == 1:
            locked_value = next(iter(common_non_extra))
            eliminations = []
            for cell in bug_cells:
                removable = (
                    state.candidates[cell[0]][cell[1]]
                    - extra_values[cell]
                    - {locked_value}
                )
                eliminations.extend(
                    (cell[0], cell[1], value) for value in removable
                )
            mv = _elim_move(
                'BUG Type 4', 'Unicita', 5.7,
                f'Le due celle BUG condividono il candidato non-extra '
                f'{locked_value}, che rimane bloccato fra loro.',
                eliminations, bug_cells, state,
            )
            _append_unique(moves, mv, seen)

    # BUG Type 3: l'unione degli extra si comporta come una pseudo-cella e,
    # con altre celle della casa comune, forma un Naked Set.
    if len(all_extra_values) > 1 and common_peers:
        type3_names = {
            2: 'BUG Type 3 (Pair)',
            3: 'BUG Type 3 (Triplet)',
            4: 'BUG Type 3 (Quad)',
        }
        for _, unit, kind in _common_units(bug_cells):
            available = [
                cell for cell in unit
                if cell in common_peers
                and state.grid[cell[0], cell[1]] == 0
            ]
            for subset_size, technique in type3_names.items():
                support_count = subset_size - 1
                if (
                    len(all_extra_values) > subset_size
                    or len(available) < support_count
                ):
                    continue
                for support in combinations(available, support_count):
                    naked_values = set(all_extra_values)
                    for r, c in support:
                        naked_values |= state.candidates[r][c]
                    if len(naked_values) != subset_size:
                        continue
                    locked = set(bug_cells) | set(support)
                    eliminations = [
                        (r, c, value)
                        for r, c in unit
                        if (r, c) not in locked
                        for value in naked_values
                    ]
                    mv = _elim_move(
                        technique, 'Unicita',
                        TECHNIQUE_DIFFICULTY[technique],
                        f'Gli extra BUG {sorted(all_extra_values)} agiscono '
                        f'come una pseudo-cella e, insieme a '
                        f'{", ".join(f"R{r+1}C{c+1}" for r, c in support)}, '
                        f'formano un sottoinsieme bloccato nel {kind}.',
                        eliminations,
                        bug_cells + list(support),
                        state,
                    )
                    _append_unique(moves, mv, seen)

    return moves


# ---------------------------------------------- 6.2 aligned pair exclusion
def aligned_pair_exclusion(state):
    """Aligned Pair Exclusion classica di Sudoku Explainer.

    Per ogni coppia di celle base valuta tutte le coppie di candidati. Una
    combinazione è vietata se assegna lo stesso valore a celle che si vedono
    oppure se svuota una cella bivalue che vede entrambe le basi. Un candidato
    che non compare in alcuna combinazione ammessa può essere eliminato.

    È un controllo combinatorio locale: non usa backtracking né un motore di
    catene.
    """
    moves = []
    seen = set()
    bivalue = {
        (r, c) for r in range(9) for c in range(9)
        if state.grid[r, c] == 0 and len(state.candidates[r][c]) == 2
    }
    base_cells = [
        (r, c) for r in range(9) for c in range(9)
        if state.grid[r, c] == 0
        and len(state.candidates[r][c]) >= 2
        and not any(
            len(state.candidates[rr][cc]) == 1
            for rr, cc in peers(r, c)
            if state.grid[rr, cc] == 0
        )
        and bool(peers(r, c) & bivalue)
    ]

    excluders = {
        cell: peers(*cell) & bivalue for cell in base_cells
    }

    for first, second in combinations(base_cells, 2):
        common_excluders = excluders[first] & excluders[second]
        # È la stessa soglia conservativa usata da SE 1.2.1.
        if len(common_excluders) < 2:
            continue

        first_values = sorted(state.candidates[first[0]][first[1]])
        second_values = sorted(state.candidates[second[0]][second[1]])
        allowed = []
        relevant_excluders = set()

        for first_value in first_values:
            for second_value in second_values:
                if (
                    first_value == second_value
                    and second in peers(*first)
                ):
                    continue

                assigned = {first_value, second_value}
                blocking = [
                    cell for cell in common_excluders
                    if state.candidates[cell[0]][cell[1]] <= assigned
                ]
                if blocking:
                    relevant_excluders.update(blocking)
                    continue
                allowed.append((first_value, second_value))

        eliminations = []
        for value in first_values:
            if not any(pair[0] == value for pair in allowed):
                eliminations.append((first[0], first[1], value))
        for value in second_values:
            if not any(pair[1] == value for pair in allowed):
                eliminations.append((second[0], second[1], value))

        mv = _elim_move(
            'Aligned Pair Exclusion', 'Exclusion', 6.2,
            f'Le celle base R{first[0]+1}C{first[1]+1} e '
            f'R{second[0]+1}C{second[1]+1} condividono celle bivalue '
            f'vincolanti. I candidati indicati non appartengono ad alcuna '
            f'combinazione compatibile.',
            eliminations,
            [first, second] + sorted(relevant_excluders),
            state,
        )
        _append_unique(moves, mv, seen)

    return moves


# -------------------------------------------- logical implication engine
_LOGIC_TECHNIQUE_FAMILY = {
    technique: technique_family(technique)
    for technique in TECHNIQUE_DIFFICULTY
    if TECHNIQUE_DIFFICULTY[technique] >= 6.5
}


def _conclusion_effects(move):
    return _atomic_conclusions(
        move.get("placements", ()),
        move.get("eliminations", ()),
    )


def _effects_of_moves(moves):
    effects = set()
    for move in moves:
        effects.update(_conclusion_effects(move))
    return effects


def _specific_logic_technique(state, parent, deduction):
    """Classifica una prova generale solo quando il sottotipo e univoco."""
    logic = deduction.get("logic", {})
    chains = logic.get("chains", [])
    kind = logic.get("kind")

    if parent in ("Bidirectional Y-Cycle", "XY-Chain") and chains:
        chain_items = (
            chains[0][1:-1]
            if parent == "XY-Chain"
            else chains[0][:-1]
        )
        cells = {
            (item["row"], item["column"])
            for item in chain_items
        }
        candidate_sets = [
            set(state.candidates[r][c]) for r, c in cells
        ]
        if parent == "XY-Chain" and len(cells) >= 2 and candidate_sets:
            common_pair = candidate_sets[0]
            if (
                len(common_pair) == 2
                and all(values == common_pair for values in candidate_sets)
            ):
                return "Remote Pair"
        if parent == "XY-Chain" and len(cells) >= 3 and all(
            len(values) == 2 for values in candidate_sets
        ):
            return "XY-Chain"
        if parent == "Bidirectional Y-Cycle" and len(cells) >= 2 and all(
            len(values) == 2 for values in candidate_sets
        ):
            return "XY-Cycle"

    if parent == "Forcing X-Chain" and len(chains) == 1:
        if len(chains[0]) == 6:
            return "Turbot Fish"

    if parent == "Forcing Chain":
        return "Alternating Inference Chain"

    if parent == "Bidirectional Cycle":
        return "Continuous Nice Loop"

    dynamic_names = {
        "dynamic-contradiction": "Contradiction",
        "dynamic-reduction": "Double",
        "dynamic-cell-reduction": "Cell",
        "dynamic-region-reduction": "Region",
    }
    subtype = dynamic_names.get(kind)
    if subtype and parent == "Dynamic Forcing Chain":
        return f"Dynamic {subtype} Forcing Chain"
    if subtype and parent == "Dynamic Forcing Chain Plus":
        return f"Dynamic {subtype} Forcing Chain Plus"
    if subtype and parent == "Nested Forcing Chain":
        return f"Nested {subtype} Forcing Chain"

    return parent


def _nested_structure_depth(value, depth=0):
    if isinstance(value, dict):
        if not value:
            return depth
        return max(
            _nested_structure_depth(item, depth + 1)
            for item in value.values()
        )
    if isinstance(value, (list, tuple, set)):
        if not value:
            return depth
        return max(
            _nested_structure_depth(item, depth + 1)
            for item in value
        )
    return depth


def _proof_metrics(deduction):
    """Stima deterministica della complessita della prova mostrata."""
    logic = deduction.get("logic", {}) or {}
    chains = logic.get("chains", ()) or ()
    chain_lengths = [
        len(chain)
        for chain in chains
        if isinstance(chain, (list, tuple))
    ]
    node_count = sum(chain_lengths)

    return {
        "chain_count": len(chain_lengths),
        "node_count": node_count,
        "max_chain_length": max(chain_lengths, default=0),
        "nesting_depth": _nested_structure_depth(logic),
        "primary_cell_count": len(set(deduction.get("primary", ()))),
    }


def _proof_rank(deduction, placements, eliminations):
    metrics = _proof_metrics(deduction)
    return (
        metrics["nesting_depth"],
        metrics["node_count"],
        metrics["max_chain_length"],
        metrics["primary_cell_count"],
        len(placements) + len(eliminations),
        deduction.get("description", ""),
    )


def _logic_moves(state, technique, excluded_effects=()):
    """
    Adatta e consolida le deduzioni del motore logico.

    Le prove con identico esito vengono raggruppate. Per ogni esito resta la
    prova meno complessa, mentre ``proof_count`` conserva quante prove grezze
    equivalenti sono state trovate. Le conclusioni gia ottenibili tramite una
    tecnica piu specifica o semplice vengono rimosse singolarmente, non solo
    quando costituiscono l'intera mossa.
    """
    excluded_effects = set(excluded_effects)
    grouped = {}

    raw_deductions = logic_engine.find_logic_deductions(state, technique)

    for deduction in raw_deductions:
        raw_placements = _normalise_triplets(
            (r, c, value)
            for r, c, value in deduction.get("placements", ())
            if state.grid[r, c] == 0
            and value in state.candidates[r][c]
        )
        raw_eliminations = _normalise_triplets(
            (r, c, value)
            for r, c, value in deduction.get("eliminations", ())
            if value in state.candidates[r][c]
        )

        placements = [
            item for item in raw_placements
            if ("place", *item) not in excluded_effects
        ]
        eliminations = [
            item for item in raw_eliminations
            if ("eliminate", *item) not in excluded_effects
        ]

        if not placements and not eliminations:
            continue

        specific = _specific_logic_technique(
            state,
            technique,
            deduction,
        )
        signature = (
            specific,
            tuple(placements),
            tuple(eliminations),
        )
        rank = _proof_rank(deduction, placements, eliminations)

        bucket = grouped.get(signature)
        if bucket is None:
            grouped[signature] = {
                "proof_count": 1,
                "best_rank": rank,
                "best_deduction": deduction,
                "placements": placements,
                "eliminations": eliminations,
                "specific": specific,
            }
        else:
            bucket["proof_count"] += 1
            if rank < bucket["best_rank"]:
                bucket["best_rank"] = rank
                bucket["best_deduction"] = deduction

    moves = []
    order_rank = {
        name: index
        for index, name in enumerate(_TECHNIQUE_ORDER)
    }

    ordered_groups = sorted(
        grouped.values(),
        key=lambda item: (
            order_rank.get(item["specific"], len(order_rank)),
            tuple(item["placements"]),
            tuple(item["eliminations"]),
        ),
    )

    for bucket in ordered_groups:
        deduction = bucket["best_deduction"]
        specific = bucket["specific"]
        description = deduction.get("description", specific)

        if specific != technique:
            description = description.replace(technique, specific, 1)
            if specific not in description:
                description = f"{specific}: {description}"

        proof = dict(deduction.get("logic", {}) or {})
        proof["parent_technique"] = technique
        proof["specific_technique"] = specific
        proof["metrics"] = _proof_metrics(deduction)
        proof["equivalent_proof_count"] = bucket["proof_count"]

        move = _build_move(
            technique=specific,
            family=technique_family(specific),
            difficulty=_canonical_difficulty(specific),
            description=description,
            placements=bucket["placements"],
            eliminations=bucket["eliminations"],
            primary=deduction.get("primary", ()),
            proof_count=bucket["proof_count"],
            extra={"logic": proof},
        )
        if move is not None:
            moves.append(move)

    return moves


def _effects_from_functions(state, functions):
    effects = set()
    for function in functions:
        effects.update(_effects_of_moves(function(state)))
    return effects


def bidirectional_x_cycle(state):
    def produce():
        excluded = _effects_of_moves(
            _cached_local(state, "fish:2", fish, 2)
        )
        return _logic_moves(state, "Bidirectional X-Cycle", excluded)

    return _cached_moves(state, "logic:Bidirectional X-Cycle", produce)


def xy_chain(state):
    def produce():
        specific_moves = (
            _cached_local(state, "y_wing", y_wing)
            + _cached_local(state, "naked_subset:2", naked_subset, 2)
        )
        return _logic_moves(
            state,
            "XY-Chain",
            _effects_of_moves(specific_moves),
        )

    return _cached_moves(state, "logic:XY-Chain", produce)


def bidirectional_y_cycle(state):
    def produce():
        specific_moves = (
            _cached_local(state, "y_wing", y_wing)
            + _cached_local(state, "naked_subset:2", naked_subset, 2)
            + bidirectional_x_cycle(state)
            + xy_chain(state)
        )
        return _logic_moves(
            state,
            "Bidirectional Y-Cycle",
            _effects_of_moves(specific_moves),
        )

    return _cached_moves(state, "logic:Bidirectional Y-Cycle", produce)


def forcing_x_chain(state):
    def produce():
        specific_moves = (
            _cached_local(state, "skyscraper", skyscraper)
            + _cached_local(state, "two_string_kite", two_string_kite)
            + _cached_local(state, "empty_rectangle", empty_rectangle)
            + bidirectional_x_cycle(state)
            + xy_chain(state)
            + bidirectional_y_cycle(state)
        )
        return _logic_moves(
            state,
            "Forcing X-Chain",
            _effects_of_moves(specific_moves),
        )

    return _cached_moves(state, "logic:Forcing X-Chain", produce)


def forcing_chain(state):
    def produce():
        specific_moves = (
            _cached_local(state, "w_wing", w_wing)
            + _cached_local(state, "y_wing", y_wing)
            + bidirectional_x_cycle(state)
            + xy_chain(state)
            + bidirectional_y_cycle(state)
            + forcing_x_chain(state)
        )
        return _logic_moves(
            state,
            "Forcing Chain",
            _effects_of_moves(specific_moves),
        )

    return _cached_moves(state, "logic:Forcing Chain", produce)


def bidirectional_cycle(state):
    def produce():
        excluded = _effects_from_functions(
            state,
            (
                bidirectional_x_cycle,
                xy_chain,
                bidirectional_y_cycle,
                forcing_x_chain,
                forcing_chain,
            ),
        )
        return _logic_moves(state, "Bidirectional Cycle", excluded)

    return _cached_moves(state, "logic:Bidirectional Cycle", produce)


def nishio(state):
    def produce():
        excluded = _effects_from_functions(
            state,
            (
                bidirectional_x_cycle,
                xy_chain,
                bidirectional_y_cycle,
                forcing_x_chain,
                forcing_chain,
                bidirectional_cycle,
            ),
        )
        return _logic_moves(state, "Nishio", excluded)

    return _cached_moves(state, "logic:Nishio", produce)


def cell_forcing_chain(state):
    def produce():
        excluded = _effects_from_functions(
            state,
            (
                bidirectional_x_cycle,
                xy_chain,
                bidirectional_y_cycle,
                forcing_x_chain,
                forcing_chain,
                bidirectional_cycle,
                nishio,
            ),
        )
        return _logic_moves(state, "Cell Forcing Chain", excluded)

    return _cached_moves(state, "logic:Cell Forcing Chain", produce)


def region_forcing_chain(state):
    def produce():
        excluded = _effects_from_functions(
            state,
            (
                bidirectional_x_cycle,
                xy_chain,
                bidirectional_y_cycle,
                forcing_x_chain,
                forcing_chain,
                bidirectional_cycle,
                nishio,
                cell_forcing_chain,
            ),
        )
        return _logic_moves(state, "Region Forcing Chain", excluded)

    return _cached_moves(state, "logic:Region Forcing Chain", produce)


def dynamic_forcing_chain(state):
    def produce():
        excluded = _effects_from_functions(
            state,
            (
                bidirectional_x_cycle,
                xy_chain,
                bidirectional_y_cycle,
                forcing_x_chain,
                forcing_chain,
                bidirectional_cycle,
                nishio,
                cell_forcing_chain,
                region_forcing_chain,
            ),
        )
        return _logic_moves(state, "Dynamic Forcing Chain", excluded)

    return _cached_moves(state, "logic:Dynamic Forcing Chain", produce)


def dynamic_forcing_chain_plus(state):
    def produce():
        excluded = _effects_from_functions(
            state,
            (
                bidirectional_x_cycle,
                xy_chain,
                bidirectional_y_cycle,
                forcing_x_chain,
                forcing_chain,
                bidirectional_cycle,
                nishio,
                cell_forcing_chain,
                region_forcing_chain,
                dynamic_forcing_chain,
            ),
        )
        return _logic_moves(
            state,
            "Dynamic Forcing Chain Plus",
            excluded,
        )

    return _cached_moves(
        state,
        "logic:Dynamic Forcing Chain Plus",
        produce,
    )


def nested_forcing_chain(state):
    def produce():
        excluded = _effects_from_functions(
            state,
            (
                bidirectional_x_cycle,
                xy_chain,
                bidirectional_y_cycle,
                forcing_x_chain,
                forcing_chain,
                bidirectional_cycle,
                nishio,
                cell_forcing_chain,
                region_forcing_chain,
                dynamic_forcing_chain,
                dynamic_forcing_chain_plus,
            ),
        )
        return _logic_moves(state, "Nested Forcing Chain", excluded)

    return _cached_moves(state, "logic:Nested Forcing Chain", produce)


# --------------------------------------------------------------- registry
# Il registro pubblico resta una sequenza di coppie ``(difficolta_minima,
# funzione)`` per compatibilita con il solver. ``TECHNIQUE_SPECS`` espone in
# aggiunta chiavi stabili e il tipo di motore, utili per profiling e report.

def _local_runner(key, function, *args):
    def runner(state):
        return _cached_local(state, key, function, *args)

    runner.__name__ = f"cached_{key.replace(':', '_')}"
    return runner


TECHNIQUE_SPECS = [
    {"minimum_difficulty": 1.0, "key": "last_value", "engine": "local", "runner": _local_runner("last_value", last_value)},
    {"minimum_difficulty": 1.2, "key": "hidden_single", "engine": "local", "runner": _local_runner("hidden_single", hidden_single)},
    {"minimum_difficulty": 1.7, "key": "direct_locked", "engine": "local", "runner": _local_runner("direct_locked", direct_locked_candidates)},
    {"minimum_difficulty": 2.0, "key": "direct_hidden_pair", "engine": "local", "runner": _local_runner("direct_hidden_subset:2", direct_hidden_subset, 2)},
    {"minimum_difficulty": 2.3, "key": "naked_single", "engine": "local", "runner": _local_runner("naked_single", naked_single)},
    {"minimum_difficulty": 2.5, "key": "direct_hidden_triplet", "engine": "local", "runner": _local_runner("direct_hidden_subset:3", direct_hidden_subset, 3)},
    {"minimum_difficulty": 2.6, "key": "locked_candidates", "engine": "local", "runner": _local_runner("locked_candidates", locked_candidates)},
    {"minimum_difficulty": 3.0, "key": "naked_pair", "engine": "local", "runner": _local_runner("naked_subset:2", naked_subset, 2)},
    {"minimum_difficulty": 3.2, "key": "x_wing", "engine": "local", "runner": _local_runner("fish:2", fish, 2)},
    {"minimum_difficulty": 3.4, "key": "hidden_pair", "engine": "local", "runner": _local_runner("hidden_subset:2", hidden_subset, 2)},
    {"minimum_difficulty": 3.6, "key": "naked_triple", "engine": "local", "runner": _local_runner("naked_subset:3", naked_subset, 3)},
    {"minimum_difficulty": 3.8, "key": "swordfish", "engine": "local", "runner": _local_runner("fish:3", fish, 3)},
    {"minimum_difficulty": 4.0, "key": "hidden_triple", "engine": "local", "runner": _local_runner("hidden_subset:3", hidden_subset, 3)},
    {"minimum_difficulty": 4.2, "key": "y_wing", "engine": "local", "runner": _local_runner("y_wing", y_wing)},
    {"minimum_difficulty": 4.4, "key": "xyz_wing", "engine": "local", "runner": _local_runner("xyz_wing", xyz_wing)},
    {"minimum_difficulty": 4.5, "key": "ur_type_1", "engine": "local", "runner": _local_runner("ur_type_1", unique_rectangle_type1)},
    {"minimum_difficulty": 4.6, "key": "ur_type_2", "engine": "local", "runner": _local_runner("ur_type_2", unique_rectangle_type2)},
    {"minimum_difficulty": 4.8, "key": "ur_type_3", "engine": "local", "runner": _local_runner("ur_type_3", unique_rectangle_type3)},
    {"minimum_difficulty": 4.9, "key": "ur_type_4", "engine": "local", "runner": _local_runner("ur_type_4", unique_rectangle_type4)},
    {"minimum_difficulty": 5.0, "key": "ur_type_5", "engine": "local", "runner": _local_runner("ur_type_5", unique_rectangle_type5)},
    {"minimum_difficulty": 5.0, "key": "naked_quad", "engine": "local", "runner": _local_runner("naked_subset:4", naked_subset, 4)},
    {"minimum_difficulty": 5.2, "key": "jellyfish", "engine": "local", "runner": _local_runner("fish:4", fish, 4)},
    {"minimum_difficulty": 5.4, "key": "hidden_quad", "engine": "local", "runner": _local_runner("hidden_subset:4", hidden_subset, 4)},
    {"minimum_difficulty": 5.6, "key": "bug_plus_one", "engine": "local", "runner": _local_runner("bug_plus_one", bug_plus_one)},
    {"minimum_difficulty": 5.7, "key": "bug_types", "engine": "local", "runner": _local_runner("bug_types", bug_types_2_to_4)},
    {"minimum_difficulty": 6.2, "key": "aligned_pair_exclusion", "engine": "local", "runner": _local_runner("aligned_pair_exclusion", aligned_pair_exclusion)},
    {"minimum_difficulty": 6.5, "key": "bidirectional_x_cycle", "engine": "logic", "runner": bidirectional_x_cycle},
    {"minimum_difficulty": 6.5, "key": "xy_chain", "engine": "logic", "runner": xy_chain},
    {"minimum_difficulty": 6.5, "key": "bidirectional_y_cycle", "engine": "logic", "runner": bidirectional_y_cycle},
    {"minimum_difficulty": 6.6, "key": "skyscraper", "engine": "local", "runner": _local_runner("skyscraper", skyscraper)},
    {"minimum_difficulty": 6.6, "key": "two_string_kite", "engine": "local", "runner": _local_runner("two_string_kite", two_string_kite)},
    {"minimum_difficulty": 6.6, "key": "empty_rectangle", "engine": "local", "runner": _local_runner("empty_rectangle", empty_rectangle)},
    {"minimum_difficulty": 6.6, "key": "forcing_x_chain", "engine": "logic", "runner": forcing_x_chain},
    {"minimum_difficulty": 7.0, "key": "w_wing", "engine": "local", "runner": _local_runner("w_wing", w_wing)},
    {"minimum_difficulty": 7.0, "key": "forcing_chain", "engine": "logic", "runner": forcing_chain},
    {"minimum_difficulty": 7.0, "key": "bidirectional_cycle", "engine": "logic", "runner": bidirectional_cycle},
    {"minimum_difficulty": 7.5, "key": "nishio", "engine": "logic", "runner": nishio},
    {"minimum_difficulty": 8.0, "key": "cell_forcing_chain", "engine": "logic", "runner": cell_forcing_chain},
    {"minimum_difficulty": 8.0, "key": "region_forcing_chain", "engine": "logic", "runner": region_forcing_chain},
    {"minimum_difficulty": 8.5, "key": "dynamic_forcing_chain", "engine": "logic", "runner": dynamic_forcing_chain},
    {"minimum_difficulty": 9.0, "key": "dynamic_forcing_chain_plus", "engine": "logic", "runner": dynamic_forcing_chain_plus},
    {"minimum_difficulty": 9.5, "key": "nested_forcing_chain", "engine": "logic", "runner": nested_forcing_chain},
]

TECHNIQUE_FUNCS = [
    (spec["minimum_difficulty"], spec["runner"])
    for spec in TECHNIQUE_SPECS
]

