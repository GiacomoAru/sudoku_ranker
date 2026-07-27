"""
Canonicalizzazione esatta e randomizzazione dei Sudoku classici 9x9.

La forma canonica è il minimo lessicografico tra tutte le immagini ottenibili
con il gruppo standard delle simmetrie del Sudoku:

* permutazione delle cifre 1-9;
* permutazione delle righe dentro ciascuna banda;
* permutazione delle bande;
* permutazione delle colonne dentro ciascuno stack;
* permutazione degli stack;
* trasposizione.

Rotazioni e riflessioni sono già combinazioni delle operazioni precedenti.

L'algoritmo non usa firme euristiche. Considera esattamente le
2 * 1296 * 1296 = 3.359.232 trasformazioni geometriche, ma le raffina una
cella alla volta ed elimina subito tutti i candidati che non condividono il
prefisso lessicografico minimo. Le rinomine delle cifre non vengono enumerate:
per ogni immagine sono determinate univocamente dall'ordine della prima
occorrenza. I candidati ridondanti rimasti alla fine sono automorfismi o
trasformazioni che producono lo stesso minimo e non compromettono l'unicità
della griglia restituita.
"""

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from itertools import permutations, product
import random

import numpy as np


CANONICALIZATION_VERSION = "minlex-v1-standard-sudoku-group"

_PERMUTATIONS_OF_THREE = tuple(permutations(range(3)))


def _group_preserving_orders():
    """Genera le 1296 permutazioni ammesse per righe o colonne."""
    orders = []

    for group_order in _PERMUTATIONS_OF_THREE:
        for local_orders in product(_PERMUTATIONS_OF_THREE, repeat=3):
            order = tuple(
                3 * source_group + local_index
                for output_group, source_group in enumerate(group_order)
                for local_index in local_orders[output_group]
            )
            orders.append(order)

    return tuple(orders)


_GROUP_ORDERS = _group_preserving_orders()
_GROUP_ORDERS_ARRAY = np.asarray(_GROUP_ORDERS, dtype=np.uint8)
_ORDER_COUNT = len(_GROUP_ORDERS)
_GEOMETRIC_TRANSFORMATION_COUNT = 2 * _ORDER_COUNT * _ORDER_COUNT


def _normalise_grid(grid):
    if hasattr(grid, "grid"):
        grid = grid.grid

    if isinstance(grid, str):
        text = "".join(grid.split()).replace(".", "0")

        if len(text) != 81:
            raise ValueError(
                "Una griglia testuale deve contenere esattamente 81 celle."
            )

        if any(character not in "0123456789" for character in text):
            raise ValueError(
                "La griglia può contenere solo cifre da 0 a 9 oppure '.'."
            )

        grid = [int(character) for character in text]

    array = np.asarray(grid, dtype=np.int8)

    if array.size != 81:
        raise ValueError(
            f"Una griglia Sudoku deve contenere 81 valori, non {array.size}."
        )

    array = array.reshape(9, 9)

    if np.any((array < 0) | (array > 9)):
        raise ValueError("I valori della griglia devono essere compresi tra 0 e 9.")

    return array.copy()


def grid_to_string(grid):
    array = _normalise_grid(grid)
    return "".join(str(int(value)) for value in array.flat)


@dataclass(frozen=True)
class SudokuTransform:
    """
    Trasformazione da una griglia sorgente a una griglia destinazione.

    ``row_order`` e ``column_order`` indicano, per ogni indice di output,
    quale riga o colonna prendere dopo l'eventuale trasposizione.
    ``digit_map[d]`` contiene la cifra di output associata alla cifra ``d``.
    """

    transposed: bool
    row_order: tuple
    column_order: tuple
    digit_map: tuple

    def __post_init__(self):
        row_order = tuple(int(value) for value in self.row_order)
        column_order = tuple(int(value) for value in self.column_order)
        digit_map = tuple(int(value) for value in self.digit_map)

        if row_order not in _GROUP_ORDERS:
            raise ValueError("row_order non è una permutazione Sudoku valida.")

        if column_order not in _GROUP_ORDERS:
            raise ValueError("column_order non è una permutazione Sudoku valida.")

        if len(digit_map) == 9:
            digit_map = (0,) + digit_map

        if (
            len(digit_map) != 10
            or digit_map[0] != 0
            or sorted(digit_map[1:]) != list(range(1, 10))
        ):
            raise ValueError("digit_map deve essere una permutazione delle cifre 1-9.")

        object.__setattr__(self, "transposed", bool(self.transposed))
        object.__setattr__(self, "row_order", row_order)
        object.__setattr__(self, "column_order", column_order)
        object.__setattr__(self, "digit_map", digit_map)

    def apply(self, grid):
        array = _normalise_grid(grid)

        if self.transposed:
            array = array.T

        transformed = array[
            np.asarray(self.row_order, dtype=np.intp)
        ][:, np.asarray(self.column_order, dtype=np.intp)]

        return np.asarray(self.digit_map, dtype=np.int8)[transformed]

    def map_cell(self, row, column):
        """Mappa una coordinata dalla griglia sorgente a quella trasformata."""
        row = int(row)
        column = int(column)

        if not (0 <= row < 9 and 0 <= column < 9):
            raise ValueError("Riga e colonna devono essere comprese tra 0 e 8.")

        inverse_rows = np.argsort(self.row_order)
        inverse_columns = np.argsort(self.column_order)

        if self.transposed:
            return (
                int(inverse_rows[column]),
                int(inverse_columns[row]),
            )

        return (
            int(inverse_rows[row]),
            int(inverse_columns[column]),
        )

    def map_candidate(self, row, column, digit):
        mapped_row, mapped_column = self.map_cell(row, column)
        return mapped_row, mapped_column, self.digit_map[int(digit)]

    def inverse(self):
        inverse_rows = tuple(int(value) for value in np.argsort(self.row_order))
        inverse_columns = tuple(
            int(value) for value in np.argsort(self.column_order)
        )
        inverse_digits = [0] * 10

        for source, destination in enumerate(self.digit_map):
            inverse_digits[destination] = source

        if self.transposed:
            inverse_rows, inverse_columns = inverse_columns, inverse_rows

        return SudokuTransform(
            transposed=self.transposed,
            row_order=inverse_rows,
            column_order=inverse_columns,
            digit_map=tuple(inverse_digits),
        )

    def to_dict(self):
        return {
            "version": CANONICALIZATION_VERSION,
            "transposed": self.transposed,
            "row_order": list(self.row_order),
            "column_order": list(self.column_order),
            "digit_map": list(self.digit_map),
        }

    @classmethod
    def from_dict(cls, data):
        version = data.get("version", CANONICALIZATION_VERSION)

        if version != CANONICALIZATION_VERSION:
            raise ValueError(
                f"Versione di trasformazione non supportata: {version!r}."
            )

        return cls(
            transposed=data["transposed"],
            row_order=tuple(data["row_order"]),
            column_order=tuple(data["column_order"]),
            digit_map=tuple(data["digit_map"]),
        )


@dataclass(frozen=True)
class CanonicalizationResult:
    grid: np.ndarray
    canonical_string: str
    transform: SudokuTransform
    equivalent_minimum_count: int
    geometric_candidates: int = _GEOMETRIC_TRANSFORMATION_COUNT
    version: str = CANONICALIZATION_VERSION


@dataclass(frozen=True)
class RandomizationResult:
    grid: np.ndarray
    transform: SudokuTransform
    changed: bool
    version: str = CANONICALIZATION_VERSION


def _complete_digit_map(partial_map):
    digit_map = [int(value) for value in partial_map]
    available = iter(
        value
        for value in range(1, 10)
        if value not in digit_map
    )

    for digit in range(1, 10):
        if digit_map[digit] == 0:
            digit_map[digit] = next(available)

    return tuple(digit_map)


def _canonicalize_orientation(grid):
    """
    Raffina tutte le 1296² trasformazioni di una singola orientazione.

    Gli array contengono soltanto i candidati ancora compatibili con il
    prefisso minimo già determinato. Una copia filtrata viene eseguita solo
    quando il raffinamento ha realmente eliminato almeno un candidato.
    """
    row_indices = np.repeat(
        np.arange(_ORDER_COUNT, dtype=np.uint16),
        _ORDER_COUNT,
    )
    column_indices = np.tile(
        np.arange(_ORDER_COUNT, dtype=np.uint16),
        _ORDER_COUNT,
    )
    digit_maps = np.zeros(
        (row_indices.size, 10),
        dtype=np.uint8,
    )
    next_digits = np.ones(row_indices.size, dtype=np.uint8)
    canonical_values = np.zeros(81, dtype=np.uint8)

    for position in range(81):
        output_row, output_column = divmod(position, 9)
        source_rows = _GROUP_ORDERS_ARRAY[
            row_indices,
            output_row,
        ]
        source_columns = _GROUP_ORDERS_ARRAY[
            column_indices,
            output_column,
        ]
        values = grid[source_rows, source_columns]
        active_indices = np.arange(values.size)
        normalised_values = digit_maps[active_indices, values]
        newly_seen = (values != 0) & (normalised_values == 0)

        if np.any(newly_seen):
            digit_maps[
                active_indices[newly_seen],
                values[newly_seen],
            ] = next_digits[newly_seen]
            normalised_values[newly_seen] = next_digits[newly_seen]
            next_digits[newly_seen] += 1

        minimum = int(normalised_values.min())
        canonical_values[position] = minimum
        keep = normalised_values == minimum

        if not np.all(keep):
            row_indices = row_indices[keep]
            column_indices = column_indices[keep]
            digit_maps = digit_maps[keep]
            next_digits = next_digits[keep]

    return (
        canonical_values,
        int(row_indices[0]),
        int(column_indices[0]),
        _complete_digit_map(digit_maps[0]),
        int(row_indices.size),
    )


@lru_cache(maxsize=256)
def _canonicalize_string_cached(grid_string):
    grid = np.fromiter(
        (int(character) for character in grid_string),
        dtype=np.int8,
        count=81,
    ).reshape(9, 9)

    direct = _canonicalize_orientation(grid)
    transposed = _canonicalize_orientation(grid.T)
    direct_string = "".join(str(int(value)) for value in direct[0])
    transposed_string = "".join(str(int(value)) for value in transposed[0])

    if direct_string <= transposed_string:
        chosen = direct
        use_transpose = False
    else:
        chosen = transposed
        use_transpose = True

    equivalent_count = chosen[4]

    if direct_string == transposed_string:
        equivalent_count = direct[4] + transposed[4]

    transform = SudokuTransform(
        transposed=use_transpose,
        row_order=_GROUP_ORDERS[chosen[1]],
        column_order=_GROUP_ORDERS[chosen[2]],
        digit_map=chosen[3],
    )

    return (
        min(direct_string, transposed_string),
        transform,
        equivalent_count,
    )


def canonicalize_details(grid):
    """Restituisce forma canonica, trasformazione e dati sui pareggi finali."""
    canonical_string, transform, equivalent_count = (
        _canonicalize_string_cached(grid_to_string(grid))
    )
    canonical_grid = np.fromiter(
        (int(character) for character in canonical_string),
        dtype=np.int8,
        count=81,
    ).reshape(9, 9)

    return CanonicalizationResult(
        grid=canonical_grid,
        canonical_string=canonical_string,
        transform=transform,
        equivalent_minimum_count=equivalent_count,
    )


def canonicalize_sudoku(grid, return_transform=False):
    """
    Porta un Sudoku nella forma MinLex esatta della sua classe isomorfa.

    Con ``return_transform=True`` restituisce ``(grid, transform)``.
    """
    result = canonicalize_details(grid)

    if return_transform:
        return result.grid, result.transform

    return result.grid


def canonical_string(grid):
    return canonicalize_details(grid).canonical_string


def canonical_id_from_string(value):
    """Calcola l'indice hash di una stringa già in forma canonica."""
    value = str(value)

    if (
        len(value) != 81
        or any(character not in "0123456789" for character in value)
    ):
        raise ValueError("La forma canonica deve essere una stringa di 81 cifre.")

    payload = f"{CANONICALIZATION_VERSION}:{value}"
    return sha256(payload.encode("ascii")).hexdigest()


def canonical_id(grid):
    """
    Hash completo usato come indice, separato dalla forma canonica autorevole.

    L'archivio verifica sempre anche ``canonical_string`` prima di unire due
    record, quindi una collisione dell'hash non può creare un falso duplicato.
    """
    return canonical_id_from_string(canonical_string(grid))


def are_isomorphic(first, second):
    return canonical_string(first) == canonical_string(second)


def apply_transform(grid, transform):
    if isinstance(transform, dict):
        transform = SudokuTransform.from_dict(transform)

    if not isinstance(transform, SudokuTransform):
        raise TypeError("transform deve essere un SudokuTransform o un dizionario.")

    return transform.apply(grid)


def _coerce_rng(rng):
    if rng is None:
        return random.Random()

    if isinstance(rng, random.Random):
        return rng

    if isinstance(rng, int) and not isinstance(rng, bool):
        return random.Random(rng)

    raise TypeError("rng deve essere None, un seed intero o random.Random.")


def _random_group_order(rng):
    groups = list(range(3))
    rng.shuffle(groups)
    order = []

    for source_group in groups:
        local = list(range(3))
        rng.shuffle(local)
        order.extend(3 * source_group + value for value in local)

    return tuple(order)


def random_transform(rng=None):
    rng = _coerce_rng(rng)
    digits = list(range(1, 10))
    rng.shuffle(digits)

    return SudokuTransform(
        transposed=bool(rng.getrandbits(1)),
        row_order=_random_group_order(rng),
        column_order=_random_group_order(rng),
        digit_map=(0,) + tuple(digits),
    )


def randomize_details(grid, rng=None, max_attempts=32):
    """
    Produce un isomorfo casuale e restituisce anche la trasformazione inversa.

    Per griglie con simmetrie eccezionali (per esempio la griglia vuota) può
    essere impossibile ottenere una rappresentazione diversa; ``changed``
    rende esplicito questo caso.
    """
    source = _normalise_grid(grid)
    rng = _coerce_rng(rng)
    max_attempts = int(max_attempts)

    if max_attempts < 1:
        raise ValueError("max_attempts deve essere almeno 1.")

    transformed = source.copy()
    transform = None

    for _ in range(max_attempts):
        transform = random_transform(rng)
        transformed = transform.apply(source)

        if not np.array_equal(transformed, source):
            break

    return RandomizationResult(
        grid=transformed,
        transform=transform,
        changed=not np.array_equal(transformed, source),
    )


def randomize_sudoku(grid, rng=None, return_transform=False):
    """
    Crea una versione casuale, irriconoscibile ma isomorfa del Sudoku.

    Con ``return_transform=True`` restituisce ``(grid, transform)``.
    """
    result = randomize_details(grid, rng=rng)

    if return_transform:
        return result.grid, result.transform

    return result.grid


__all__ = [
    "CANONICALIZATION_VERSION",
    "CanonicalizationResult",
    "RandomizationResult",
    "SudokuTransform",
    "apply_transform",
    "are_isomorphic",
    "canonical_id",
    "canonical_id_from_string",
    "canonical_string",
    "canonicalize_details",
    "canonicalize_sudoku",
    "grid_to_string",
    "random_transform",
    "randomize_details",
    "randomize_sudoku",
]
