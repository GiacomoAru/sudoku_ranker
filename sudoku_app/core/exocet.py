"""Rilevatore strutturale del Junior Exocet acquisito in P17.2.

La versione eseguibile implementa soltanto la Regola 1: dopo aver validato
base, target, companion, cross-line, S-cell e cover house, elimina dai target
le cifre esterne all'insieme di base. Le altre regole restano nel catalogo
con stato ``planned``.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product

from . import search_config


Cell = tuple[int, int]
Candidate = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class JExocetPattern:
    orientation: str
    base_cells: tuple[Cell, Cell]
    base_digits: frozenset[int]
    target_cells: tuple[Cell, Cell]
    companion_cells: tuple[Cell, Cell]
    mirror_cells: tuple[tuple[Cell, Cell], tuple[Cell, Cell]]
    cross_line_house_ids: tuple[int, int, int]
    s_cells: tuple[Cell, ...]
    cover_house_ids: tuple[tuple[int, tuple[int, ...]], ...]
    escape_cells: tuple[Cell, Cell, Cell]
    eliminations: tuple[Candidate, ...]
    rule_id: str = "exocet.rule1"

    def to_dict(self):
        return {
            "pattern": "junior-exocet",
            "rule_id": self.rule_id,
            "orientation": self.orientation,
            "base_cells": [list(cell) for cell in self.base_cells],
            "base_digits": sorted(self.base_digits),
            "target_cells": [list(cell) for cell in self.target_cells],
            "companion_cells": [
                list(cell) for cell in self.companion_cells
            ],
            "mirror_cells": [
                [list(cell) for cell in pair]
                for pair in self.mirror_cells
            ],
            "cross_line_house_ids": list(self.cross_line_house_ids),
            "s_cells": [list(cell) for cell in self.s_cells],
            "cover_house_ids": [
                {"digit": digit, "house_ids": list(house_ids)}
                for digit, house_ids in self.cover_house_ids
            ],
            "escape_cells": [list(cell) for cell in self.escape_cells],
        }


def _values(state, cell):
    row, column = cell
    solved = int(state.grid[row, column])
    return {solved} if solved else set(state.candidates[row][column])


def _unsolved_candidates(state, cell):
    row, column = cell
    return (
        set(state.candidates[row][column])
        if int(state.grid[row, column]) == 0
        else set()
    )


def _minimum_cover(occurrences, allowed_houses):
    occurrences = set(occurrences)
    if not occurrences:
        return ()
    for size in (1, 2):
        for houses in combinations(allowed_houses, size):
            if all(
                any(cell in house_cells for _, house_cells in houses)
                for cell in occurrences
            ):
                return tuple(house_id for house_id, _ in houses)
    return None


def _row_geometry(base_cells, targets):
    base_row = base_cells[0][0]
    band = base_row // 3
    base_stack = base_cells[0][1] // 3
    segment_columns = set(range(base_stack * 3, base_stack * 3 + 3))
    missing_column = next(iter(
        segment_columns - {cell[1] for cell in base_cells}
    ))
    first, second = targets
    companions = ((second[0], first[1]), (first[0], second[1]))
    first_stack = first[1] // 3
    second_stack = second[1] // 3
    mirrors = (
        tuple(
            (second[0], column)
            for column in range(second_stack * 3, second_stack * 3 + 3)
            if column != second[1]
        ),
        tuple(
            (first[0], column)
            for column in range(first_stack * 3, first_stack * 3 + 3)
            if column != first[1]
        ),
    )
    cross_columns = (missing_column, first[1], second[1])
    s_cells = tuple(
        (row, column)
        for row in range(9)
        if row // 3 != band
        for column in cross_columns
    )
    allowed_houses = tuple(
        [(row, frozenset((row, column) for column in range(9)))
         for row in range(9) if row // 3 != band]
        + [(9 + column, frozenset((row, column) for row in range(9)))
           for column in cross_columns]
    )
    return {
        "companions": companions,
        "mirrors": mirrors,
        "cross_house_ids": tuple(9 + column for column in cross_columns),
        "s_cells": s_cells,
        "allowed_houses": allowed_houses,
        "escape_cells": tuple((base_row, column) for column in cross_columns),
    }


def _transpose_cells(cells):
    return tuple((column, row) for row, column in cells)


def _column_geometry(base_cells, targets):
    transposed = _row_geometry(
        _transpose_cells(base_cells),
        _transpose_cells(targets),
    )
    return {
        "companions": _transpose_cells(transposed["companions"]),
        "mirrors": tuple(
            _transpose_cells(pair) for pair in transposed["mirrors"]
        ),
        "cross_house_ids": tuple(
            house_id - 9 for house_id in transposed["cross_house_ids"]
        ),
        "s_cells": _transpose_cells(transposed["s_cells"]),
        "allowed_houses": tuple(
            (
                house_id + 9 if house_id < 9 else house_id - 9,
                frozenset(_transpose_cells(tuple(cells))),
            )
            for house_id, cells in transposed["allowed_houses"]
        ),
        "escape_cells": _transpose_cells(transposed["escape_cells"]),
    }


def _base_specs(state):
    for orientation in ("row", "column"):
        for box_row in range(3):
            for box_column in range(3):
                if orientation == "row":
                    segments = (
                        tuple(
                            (row, column)
                            for column in range(box_column * 3, box_column * 3 + 3)
                        )
                        for row in range(box_row * 3, box_row * 3 + 3)
                    )
                else:
                    segments = (
                        tuple(
                            (row, column)
                            for row in range(box_row * 3, box_row * 3 + 3)
                        )
                        for column in range(box_column * 3, box_column * 3 + 3)
                    )
                for segment in segments:
                    cells = tuple(
                        cell for cell in segment
                        if len(_unsolved_candidates(state, cell)) >= 2
                    )
                    for bases in combinations(cells, 2):
                        digits = frozenset().union(*(
                            _unsolved_candidates(state, cell)
                            for cell in bases
                        ))
                        if len(digits) in (3, 4):
                            yield orientation, tuple(sorted(bases)), digits


def _target_pairs(state, orientation, base_cells, base_digits):
    if orientation == "row":
        chute = base_cells[0][0] // 3
        base_box = base_cells[0][1] // 3
        other_boxes = [item for item in range(3) if item != base_box]
        target_groups = []
        for box in other_boxes:
            target_groups.append(tuple(
                (row, column)
                for row in range(chute * 3, chute * 3 + 3)
                if row != base_cells[0][0]
                for column in range(box * 3, box * 3 + 3)
                if base_digits <= _unsolved_candidates(state, (row, column))
            ))
        for first, second in product(*target_groups):
            if first[0] != second[0] and first[1] != second[1]:
                yield first, second
    else:
        transposed_state = _TransposedState(state)
        for targets in _target_pairs(
            transposed_state,
            "row",
            _transpose_cells(base_cells),
            base_digits,
        ):
            yield _transpose_cells(targets)


class _TransposedState:
    def __init__(self, state):
        self.grid = state.grid.T
        self.candidates = [
            [state.candidates[column][row] for column in range(9)]
            for row in range(9)
        ]


def enumerate_jexocet_rule1(state, *, truncated_out=None):
    limits = search_config.limits_for_state(state)
    patterns = []
    inspected = 0
    seen = set()

    for orientation, base_cells, base_digits in _base_specs(state):
        for targets in _target_pairs(
            state,
            orientation,
            base_cells,
            base_digits,
        ):
            inspected += 1
            if (
                limits.exocet_patterns is not None
                and inspected > limits.exocet_patterns
            ):
                if truncated_out is not None:
                    truncated_out.append("exocet_patterns")
                return tuple(patterns)

            geometry = (
                _row_geometry(base_cells, targets)
                if orientation == "row"
                else _column_geometry(base_cells, targets)
            )
            if any(
                _values(state, cell) & base_digits
                for cell in geometry["companions"]
            ):
                continue

            cover_house_ids = []
            valid_cover = True
            for digit in sorted(base_digits):
                occurrences = tuple(
                    cell for cell in geometry["s_cells"]
                    if digit in _values(state, cell)
                )
                cover = _minimum_cover(
                    occurrences,
                    geometry["allowed_houses"],
                )
                if cover is None:
                    valid_cover = False
                    break
                cover_house_ids.append((digit, cover))
            if not valid_cover:
                continue

            eliminations = tuple(sorted(
                (row, column, digit)
                for row, column in targets
                for digit in _unsolved_candidates(state, (row, column))
                if digit not in base_digits
            ))
            if not eliminations:
                continue

            signature = orientation, base_cells, tuple(sorted(targets))
            if signature in seen:
                continue
            seen.add(signature)
            patterns.append(JExocetPattern(
                orientation=orientation,
                base_cells=base_cells,
                base_digits=base_digits,
                target_cells=tuple(targets),
                companion_cells=tuple(geometry["companions"]),
                mirror_cells=tuple(geometry["mirrors"]),
                cross_line_house_ids=tuple(geometry["cross_house_ids"]),
                s_cells=tuple(geometry["s_cells"]),
                cover_house_ids=tuple(cover_house_ids),
                escape_cells=tuple(geometry["escape_cells"]),
                eliminations=eliminations,
            ))
            if (
                limits.exocet_results is not None
                and len(patterns) >= limits.exocet_results
            ):
                if truncated_out is not None:
                    truncated_out.append("exocet_results")
                return tuple(patterns)

    return tuple(patterns)


__all__ = ["JExocetPattern", "enumerate_jexocet_rule1"]
