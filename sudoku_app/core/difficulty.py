"""Modello centralizzato della difficoltà Sudoku.

La difficoltà tecnica usa la scala derivata da Sudoku Explainer 1.2.1.
Il carico risolutivo misura il lavoro logico cumulativo della soluzione.
La difficoltà di individuazione misura quanto sia difficile trovare una
prossima mossa accessibile, considerando anche le mosse con rating SE vicino.
"""

from __future__ import annotations

import math


DIFFICULTY_MODEL_VERSION = 6

TECHNIQUE_DIFFICULTY = {
    # INSERIMENTI DIRETTI
    "Last Value": 1.0,
    "Hidden Single (Box)": 1.2,
    "Hidden Single (Row/Column)": 1.5,
    "Naked Single": 1.8,

    # INTERSEZIONI BOX / LINEE
    "Direct Pointing": 2.4,
    "Pointing": 2.4,
    "Direct Claiming": 2.5,
    "Claiming": 2.5,

    # SOTTOINSIEMI
    "Naked Pair": 2.6,
    "Direct Hidden Pair": 3.0,
    "Hidden Pair": 3.0,
    "Naked Triple": 3.2,
    "Direct Hidden Triplet": 3.4,
    "Hidden Triple": 3.4,
    "Naked Quadruple": 3.6,
    "Hidden Quadruple": 3.7,

    # FISH
    "Swordfish": 4.1,
    "Jellyfish": 4.8,

    # WINGS
    "X-Wing": 3.8,
    "Y-Wing": 4.2,
    "XYZ-Wing": 4.4,
    "W-Wing": 4.5,

    # PATTERN A CIFRA SINGOLA
    "Skyscraper": 3.9,
    "Two-String Kite": 4.0,
    "Turbot Fish": 4.2,
    "Empty Rectangle": 4.3,

    # UNICITÀ
    "Unique Rectangle Type 1": 4.3,
    "Unique Rectangle Type 2": 4.5,
    "Unique Rectangle Type 4": 4.6,
    "BUG+1": 4.6,
    "Unique Rectangle Type 5": 4.7,
    "Unique Rectangle Type 3": 4.9,
    "BUG Type 2": 5.0,
    "BUG Type 4": 5.1,
    "BUG Type 3 (Pair)": 5.2,
    "BUG Type 3 (Triplet)": 5.4,
    "BUG Type 3 (Quad)": 5.6,

    # CATENE BIVALUE
    "Remote Pair": 4.7,
    "XY-Chain": 5.5,

    # CICLI BIDIREZIONALI
    "Bidirectional X-Cycle": 5.4,
    "Bidirectional Y-Cycle": 5.6,
    "XY-Cycle": 5.8,
    "Continuous Nice Loop": 6.1,
    "Bidirectional Cycle": 6.1,

    # CATENE FORZANTI STATICHE
    "Forcing X-Chain": 5.7,
    "Alternating Inference Chain": 6.0,
    "Forcing Chain": 6.7,

    # ESCLUSIONE
    "Aligned Pair Exclusion": 6.2,

    # ASSUNZIONI LOGICHE
    "Nishio": 7.1,

    # FORCING MULTIPLI
    "Cell Forcing Chain": 7.6,
    "Region Forcing Chain": 7.8,

    # FORCING DINAMICI
    "Dynamic Contradiction Forcing Chain": 8.5,
    "Dynamic Double Forcing Chain": 8.5,
    "Dynamic Cell Forcing Chain": 8.5,
    "Dynamic Region Forcing Chain": 8.5,
    "Dynamic Forcing Chain": 8.5,

    # FORCING DINAMICI PLUS
    "Dynamic Contradiction Forcing Chain Plus": 9.0,
    "Dynamic Double Forcing Chain Plus": 9.0,
    "Dynamic Cell Forcing Chain Plus": 9.0,
    "Dynamic Region Forcing Chain Plus": 9.0,
    "Dynamic Forcing Chain Plus": 9.0,


    # FORCING ANNIDATI
    "Nested Contradiction Forcing Chain": 9.5,
    "Nested Double Forcing Chain": 9.5,
    "Nested Cell Forcing Chain": 9.5,
    "Nested Region Forcing Chain": 9.5,
    "Nested Forcing Chain": 9.5,
}



TECHNICAL_DIFFICULTY_THRESHOLDS = (
    (1.4, "Molto facile"),
    (2.0, "Facile"),
    (2.9, "Medio"),
    (3.7, "Difficile"),
    (4.2, "Molto difficile"),
    (4.9, "Esperto"),
    (7.0, "Diabolico"),
    (9.0, "Estremo"),
    (10, "Incubo"),
    (float("inf"), "Oltre il limite"),
)


def technique_difficulty(technique):
    """Restituisce il rating SE canonico di una tecnica."""
    try:
        return float(TECHNIQUE_DIFFICULTY[technique])
    except KeyError as error:
        raise KeyError(
            f"Rating SE mancante per la tecnica {technique!r}."
        ) from error


def technical_difficulty_label(difficulty):
    """Converte un rating SE nella label editoriale del progetto."""
    difficulty = float(difficulty)

    for maximum, label in TECHNICAL_DIFFICULTY_THRESHOLDS:
        if difficulty <= maximum:
            return label

    return "Sconosciuto"



# ---------------------------------------------------------------------------
# Difficoltà di individuazione della mossa
# ---------------------------------------------------------------------------

MOVE_DISCOVERY_SE_HALF_LIFE = 0.5
MOVE_DISCOVERY_EXTRA_MOVE_DECAY = 0.1

MOVE_DISCOVERY_MIN = 1.0
MOVE_DISCOVERY_MAX = 10.0
MOVE_DISCOVERY_DECIMALS = 2


MOVE_DISCOVERY_THRESHOLDS = (
    (2.0, "Immediata"),
    (3.5, "Facile"),
    (5.5, "Moderata"),
    (7.0, "Difficile"),
    (8.0, "Molto difficile"),
    (9.5, "Estrema"),
    (10.0, "Quasi obbligata"),
)


def step_move_discovery_difficulty(
    effective_move_count,
    max_moves,
):
    """
    Calcola la difficoltà di individuazione di un singolo stato.

    Il punteggio varia da 1 a 10:
    - 1 quando sono disponibili almeno max_moves mosse effettive;
    - 10 quando è disponibile una sola mossa effettiva.

    La trasformazione logaritmica rende molto importante
    la differenza tra poche mosse, mentre riduce progressivamente
    l'effetto delle mosse aggiuntive.
    """
    if (
        isinstance(max_moves, bool)
        or int(max_moves) < 2
    ):
        raise ValueError(
            "Il numero massimo di mosse deve essere almeno 2."
        )

    max_moves = int(max_moves)
    effective_move_count = float(effective_move_count)

    if not math.isfinite(effective_move_count):
        raise ValueError(
            "Il numero effettivo di mosse deve essere finito."
        )

    if effective_move_count <= 0:
        raise ValueError(
            "Il numero effettivo di mosse deve essere positivo."
        )

    effective_move_count = min(
        float(max_moves),
        max(1.0, effective_move_count),
    )

    difficulty = (
        MOVE_DISCOVERY_MIN
        + (
            MOVE_DISCOVERY_MAX
            - MOVE_DISCOVERY_MIN
        )
        * (
            math.log(
                max_moves / effective_move_count
            )
            / math.log(max_moves)
        )
    )

    return round(
        difficulty,
        MOVE_DISCOVERY_DECIMALS,
    )


def move_discovery_label(difficulty):
    """
    Converte la difficoltà di individuazione
    nella relativa label.
    """
    difficulty = float(difficulty)

    if not math.isfinite(difficulty):
        raise ValueError(
            "La difficoltà di individuazione deve essere finita."
        )

    if not (
        MOVE_DISCOVERY_MIN
        <= difficulty
        <= MOVE_DISCOVERY_MAX
    ):
        raise ValueError(
            "La difficoltà di individuazione deve essere "
            "compresa tra 1 e 10."
        )

    for maximum, label in MOVE_DISCOVERY_THRESHOLDS:
        if difficulty <= maximum:
            return label

    return "Sconosciuta"


def aggregate_move_discovery_difficulty(
    step_difficulties,
):
    """
    Combina la difficoltà media con la media del 20% degli
    stati più difficili, così da valorizzare i colli di bottiglia
    senza dipendere da un singolo massimo.
    """
    if not step_difficulties:
        return 0.0

    values = sorted(
        (
            float(value)
            for value in step_difficulties
        ),
        reverse=True,
    )

    if any(
        not math.isfinite(value)
        for value in values
    ):
        raise ValueError(
            "Le difficoltà di individuazione devono "
            "essere numeri finiti."
        )

    if any(
        not (
            MOVE_DISCOVERY_MIN
            <= value
            <= MOVE_DISCOVERY_MAX
        )
        for value in values
    ):
        raise ValueError(
            "Le difficoltà di individuazione devono "
            "essere comprese tra 1 e 10."
        )

    mean = math.fsum(values) / len(values)

    hardest_count = max(
        1,
        math.ceil(len(values) * 0.20),
    )

    hardest_mean = (
        math.fsum(values[:hardest_count])
        / hardest_count
    )

    difficulty = (
        0.75 * mean
        + 0.25 * hardest_mean
    )

    return round(
        difficulty,
        MOVE_DISCOVERY_DECIMALS,
    )
    

# ---------------------------------------------------------------------------
# Carico risolutivo
# ---------------------------------------------------------------------------

RESOLUTION_LOAD_MULTIPLIER_PER_SE = 3.2
RESOLUTION_LOAD_REFERENCE_SE = TECHNIQUE_DIFFICULTY["Last Value"]
RESOLUTION_LOAD_DECIMALS = 2


RESOLUTION_LOAD_THRESHOLDS = (
    (80.0, "Molto basso"),
    (120.0, "Basso"),
    (200.0, "Medio"),
    (400.0, "Alto"),
    (1500.0, "Molto alto"),
    (12000.0, "Estremo"),
    (30000.0, "Incubo"),
    (float("inf"), "Oltre il limite"),
)

def resolution_load_label(resolution_load):
    """Converte il carico risolutivo totale in una label."""
    resolution_load = float(resolution_load)

    if not math.isfinite(resolution_load):
        raise ValueError(
            "Il carico risolutivo deve essere un numero finito."
        )

    if resolution_load < 0:
        raise ValueError(
            "Il carico risolutivo non può essere negativo."
        )

    for maximum, label in RESOLUTION_LOAD_THRESHOLDS:
        if resolution_load <= maximum:
            return label

    return "Sconosciuto"


def step_resolution_load(technical_difficulty):
    """
    Calcola il carico prodotto da uno step.

    Il Last Value vale 1. Ogni incremento di un punto SE
    moltiplica il carico per 3.2.
    """
    technical_difficulty = float(technical_difficulty)

    if not math.isfinite(technical_difficulty):
        raise ValueError(
            "La difficoltà tecnica deve essere un numero finito."
        )

    if technical_difficulty < 0:
        raise ValueError(
            "La difficoltà tecnica non può essere negativa."
        )

    return RESOLUTION_LOAD_MULTIPLIER_PER_SE ** (
        technical_difficulty
        - RESOLUTION_LOAD_REFERENCE_SE
    )


def aggregate_resolution_load(difficulty_scores):
    """Somma il carico risolutivo di tutti gli step."""
    load = math.fsum(
        step_resolution_load(score)
        for score in difficulty_scores
    )

    return round(load, RESOLUTION_LOAD_DECIMALS)