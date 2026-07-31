"""Modello centralizzato della difficoltà Sudoku.

La difficoltà tecnica usa la scala derivata da Sudoku Explainer 1.2.1.
Il carico risolutivo misura il lavoro logico cumulativo della soluzione.
La difficoltà di individuazione misura quanto sia difficile trovare una
prossima mossa accessibile, considerando anche le mosse con rating SE vicino.
"""

from __future__ import annotations

import math

from .technique_catalog import TECHNIQUE_DIFFICULTY


DIFFICULTY_MODEL_VERSION = 6



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
