"""Mapping HoDoKu complementare alla difficoltà tecnica Sudoku Explainer.

Il rating SE resta invariato e continua a descrivere la tecnica teorica.
Questo modulo aggiunge la stima del carico di risoluzione basata sui valori
predefiniti di HoDoKu 2.2.4.

HoDoKu usa due attributi per tecnica, ``level`` e ``score``. Il punteggio del
puzzle è la somma dei punteggi degli step e il livello complessivo è il
maggiore fra il livello dello step più difficile e quello determinato dalla
somma. Le tecniche non presenti direttamente in HoDoKu sono marcate come
stime e ricondotte alla tecnica HoDoKu più vicina.

Fonti:
https://hodoku.sourceforge.net/en/docs_cre.php
https://github.com/1to9only/HoDoKu/blob/master/src/sudoku/Options.java
"""

from __future__ import annotations

HODOKU_MODEL_VERSION = "HoDoKu 2.2.4 defaults / mapping v1"

HODOKU_LEVEL_ORDER = {
    "Easy": 1,
    "Medium": 2,
    "Hard": 3,
    "Unfair": 4,
    "Extreme": 5,
}

HODOKU_LEVEL_LABELS_IT = {
    "Easy": "Facile",
    "Medium": "Medio",
    "Hard": "Difficile",
    "Unfair": "Ingiusto",
    "Extreme": "Estremo",
}

HODOKU_SCORE_THRESHOLDS = (
    (800, "Easy"),
    (1000, "Medium"),
    (1600, "Hard"),
    (1800, "Unfair"),
    (float("inf"), "Extreme"),
)


def _spec(score, level, *, estimated=False, basis=None):
    return {
        "score": int(score),
        "level": level,
        "estimated": bool(estimated),
        "basis": basis,
    }


# Valori esatti della configurazione predefinita HoDoKu.
HODOKU_EXACT_TECHNIQUES = {
    "Last Value": _spec(4, "Easy", basis="Full House"),
    "Hidden Single (Box)": _spec(14, "Easy", basis="Hidden Single"),
    "Hidden Single (Row/Column)": _spec(
        14,
        "Easy",
        basis="Hidden Single",
    ),
    "Naked Single": _spec(4, "Easy"),
    "Pointing": _spec(50, "Medium", basis="Locked Candidates Type 1"),
    "Claiming": _spec(50, "Medium", basis="Locked Candidates Type 2"),
    "Naked Pair": _spec(60, "Medium"),
    "Hidden Pair": _spec(70, "Medium"),
    "Naked Triple": _spec(80, "Medium"),
    "Hidden Triple": _spec(100, "Medium"),
    "Naked Quadruple": _spec(120, "Hard"),
    "Hidden Quadruple": _spec(150, "Hard"),
    "X-Wing": _spec(140, "Hard"),
    "Swordfish": _spec(150, "Hard"),
    "Jellyfish": _spec(160, "Hard"),
    "Remote Pair": _spec(110, "Hard"),
    "BUG+1": _spec(100, "Hard"),
    "Skyscraper": _spec(130, "Hard"),
    "Two-String Kite": _spec(150, "Hard"),
    "Turbot Fish": _spec(120, "Hard"),
    "Empty Rectangle": _spec(120, "Hard"),
    "Y-Wing": _spec(160, "Hard", basis="XY-Wing"),
    "XYZ-Wing": _spec(180, "Hard"),
    "W-Wing": _spec(150, "Hard"),
    "Unique Rectangle Type 1": _spec(100, "Hard", basis="Uniqueness 1"),
    "Unique Rectangle Type 2": _spec(100, "Hard", basis="Uniqueness 2"),
    "Unique Rectangle Type 3": _spec(100, "Hard", basis="Uniqueness 3"),
    "Unique Rectangle Type 4": _spec(100, "Hard", basis="Uniqueness 4"),
    "Unique Rectangle Type 5": _spec(100, "Hard", basis="Uniqueness 5"),
    "XY-Chain": _spec(260, "Unfair"),
    "Alternating Inference Chain": _spec(
        280,
        "Unfair",
        basis="Nice Loop/AIC",
    ),
    "Continuous Nice Loop": _spec(280, "Unfair", basis="Nice Loop/AIC"),
    "Forcing Chain": _spec(500, "Extreme"),
}


# Mapping dichiaratamente stimati. I punteggi delle tecniche "Direct"
# equivalgono ai due step che HoDoKu userebbe separatamente.
HODOKU_ESTIMATED_TECHNIQUES = {
    "Direct Pointing": _spec(
        64,
        "Medium",
        estimated=True,
        basis="Locked Candidates Type 1 + Hidden Single",
    ),
    "Direct Claiming": _spec(
        64,
        "Medium",
        estimated=True,
        basis="Locked Candidates Type 2 + Hidden Single",
    ),
    "Direct Hidden Pair": _spec(
        84,
        "Medium",
        estimated=True,
        basis="Hidden Pair + Hidden Single",
    ),
    "Direct Hidden Triplet": _spec(
        114,
        "Medium",
        estimated=True,
        basis="Hidden Triple + Hidden Single",
    ),
    "BUG Type 2": _spec(120, "Hard", estimated=True, basis="BUG+1"),
    "BUG Type 4": _spec(120, "Hard", estimated=True, basis="BUG+1"),
    "BUG Type 3 (Pair)": _spec(
        130,
        "Hard",
        estimated=True,
        basis="BUG+1",
    ),
    "BUG Type 3 (Triplet)": _spec(
        150,
        "Hard",
        estimated=True,
        basis="BUG+1",
    ),
    "BUG Type 3 (Quad)": _spec(
        170,
        "Hard",
        estimated=True,
        basis="BUG+1",
    ),
    "Aligned Pair Exclusion": _spec(
        300,
        "Unfair",
        estimated=True,
        basis="advanced exclusion",
    ),
    "Bidirectional X-Cycle": _spec(
        260,
        "Unfair",
        estimated=True,
        basis="X-Chain",
    ),
    "Bidirectional Y-Cycle": _spec(
        280,
        "Unfair",
        estimated=True,
        basis="Nice Loop/AIC",
    ),
    "XY-Cycle": _spec(
        280,
        "Unfair",
        estimated=True,
        basis="Nice Loop/AIC",
    ),
    "Forcing X-Chain": _spec(
        260,
        "Unfair",
        estimated=True,
        basis="X-Chain",
    ),
    "Bidirectional Cycle": _spec(
        280,
        "Unfair",
        estimated=True,
        basis="Nice Loop/AIC",
    ),
    "Nishio": _spec(
        500,
        "Extreme",
        estimated=True,
        basis="Forcing Chain",
    ),
    "Cell Forcing Chain": _spec(
        500,
        "Extreme",
        estimated=True,
        basis="Forcing Chain",
    ),
    "Region Forcing Chain": _spec(
        500,
        "Extreme",
        estimated=True,
        basis="Forcing Chain",
    ),
    "Dynamic Forcing Chain": _spec(
        700,
        "Extreme",
        estimated=True,
        basis="Forcing Net",
    ),
    "Dynamic Contradiction Forcing Chain": _spec(
        700,
        "Extreme",
        estimated=True,
        basis="Forcing Net",
    ),
    "Dynamic Double Forcing Chain": _spec(
        700,
        "Extreme",
        estimated=True,
        basis="Forcing Net",
    ),
    "Dynamic Cell Forcing Chain": _spec(
        700,
        "Extreme",
        estimated=True,
        basis="Forcing Net",
    ),
    "Dynamic Region Forcing Chain": _spec(
        700,
        "Extreme",
        estimated=True,
        basis="Forcing Net",
    ),
    "Dynamic Forcing Chain Plus": _spec(
        850,
        "Extreme",
        estimated=True,
        basis="extended Forcing Net",
    ),
    "Dynamic Contradiction Forcing Chain Plus": _spec(
        850,
        "Extreme",
        estimated=True,
        basis="extended Forcing Net",
    ),
    "Dynamic Double Forcing Chain Plus": _spec(
        850,
        "Extreme",
        estimated=True,
        basis="extended Forcing Net",
    ),
    "Dynamic Cell Forcing Chain Plus": _spec(
        850,
        "Extreme",
        estimated=True,
        basis="extended Forcing Net",
    ),
    "Dynamic Region Forcing Chain Plus": _spec(
        850,
        "Extreme",
        estimated=True,
        basis="extended Forcing Net",
    ),
    "Nested Forcing Chain": _spec(
        1000,
        "Extreme",
        estimated=True,
        basis="nested Forcing Net",
    ),
    "Nested Contradiction Forcing Chain": _spec(
        1000,
        "Extreme",
        estimated=True,
        basis="nested Forcing Net",
    ),
    "Nested Double Forcing Chain": _spec(
        1000,
        "Extreme",
        estimated=True,
        basis="nested Forcing Net",
    ),
    "Nested Cell Forcing Chain": _spec(
        1000,
        "Extreme",
        estimated=True,
        basis="nested Forcing Net",
    ),
    "Nested Region Forcing Chain": _spec(
        1000,
        "Extreme",
        estimated=True,
        basis="nested Forcing Net",
    ),
}

HODOKU_TECHNIQUES = {
    **HODOKU_EXACT_TECHNIQUES,
    **HODOKU_ESTIMATED_TECHNIQUES,
}


def hodoku_technique_rating(technique):
    """Restituisce una copia del mapping HoDoKu di una tecnica."""
    try:
        return dict(HODOKU_TECHNIQUES[technique])
    except KeyError as error:
        raise KeyError(
            f"Mapping HoDoKu mancante per la tecnica {technique!r}."
        ) from error


def hodoku_level_from_score(score):
    """Livello HoDoKu determinato dal solo punteggio cumulativo."""
    score = float(score)
    for maximum, level in HODOKU_SCORE_THRESHOLDS:
        if score <= maximum:
            return level
    return "Extreme"


def hodoku_puzzle_level(total_score, hardest_step_level):
    """Applica la regola HoDoKu: massimo fra score e step più difficile."""
    score_level = hodoku_level_from_score(total_score)
    return max(
        (score_level, hardest_step_level),
        key=lambda level: HODOKU_LEVEL_ORDER[level],
    )
