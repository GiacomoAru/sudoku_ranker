"""Motore strutturale per Sue de Coq ed Extended Sue de Coq."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from .data_structure import UNITS, box_of


Cell = tuple[int, int]
Candidate = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class SueDeCoqPattern:
    line_kind: str
    line_index: int
    box_index: int
    intersection_cells: tuple[Cell, ...]
    line_cells: tuple[Cell, ...]
    box_cells: tuple[Cell, ...]
    intersection_digits: frozenset[int]
    line_core_digits: frozenset[int]
    box_core_digits: frozenset[int]
    line_extra_digits: frozenset[int]
    box_extra_digits: frozenset[int]
    eliminations: tuple[Candidate, ...]
    extended: bool


def _candidate_union(state, cells):
    values = set()
    for row, column in cells:
        values.update(state.candidates[row][column])
    return frozenset(values)


def _nonempty_subsets(cells):
    for size in range(1, len(cells) + 1):
        yield from combinations(cells, size)


def _empty_candidate_cells(state, cells):
    return tuple(sorted(
        (row, column)
        for row, column in cells
        if state.grid[row, column] == 0
        and state.candidates[row][column]
    ))


def _eliminations(state, cells, digits):
    return {
        (row, column, value)
        for row, column in cells
        for value in digits
        if value in state.candidates[row][column]
    }


def enumerate_sue_de_coq(state):
    """Enumera decomposizioni valide fra una linea e un box.

    La parte di ciascun subset che appartiene ai candidati dell'intersezione
    è disgiunta da quella dell'altro lato. Gli eventuali candidati extra
    consumano una cella del rispettivo subset, come nella forma estesa.
    """
    patterns = []
    seen = set()

    for line_kind, unit_offset in (("row", 0), ("column", 9)):
        for line_index in range(9):
            line = set(UNITS[unit_offset + line_index])
            line_empty = set(_empty_candidate_cells(state, line))
            if len(line_empty) < 3:
                continue

            intersecting_boxes = sorted({
                box_of(row, column) for row, column in line
            })
            for box_index in intersecting_boxes:
                box = set(UNITS[18 + box_index])
                box_empty = set(_empty_candidate_cells(state, box))
                intersection = tuple(sorted(line_empty & box_empty))
                if len(intersection) < 2:
                    continue

                for intersection_size in range(2, len(intersection) + 1):
                    for intersection_cells in combinations(
                        intersection,
                        intersection_size,
                    ):
                        intersection_set = set(intersection_cells)
                        intersection_digits = _candidate_union(
                            state,
                            intersection_cells,
                        )
                        surplus = (
                            len(intersection_digits)
                            - len(intersection_cells)
                        )
                        if surplus < 2:
                            continue

                        line_source = tuple(sorted(
                            line_empty - intersection_set
                        ))
                        for line_cells in _nonempty_subsets(line_source):
                            line_digits = _candidate_union(state, line_cells)
                            line_core = line_digits & intersection_digits
                            line_extra = line_digits - intersection_digits
                            line_contribution = (
                                len(line_cells) - len(line_extra)
                            )
                            if (
                                not line_core
                                or line_contribution <= 0
                                or line_contribution >= surplus
                            ):
                                continue

                            box_source = tuple(sorted(
                                box_empty
                                - intersection_set
                                - set(line_cells)
                            ))
                            for box_cells in _nonempty_subsets(box_source):
                                box_digits = _candidate_union(
                                    state,
                                    box_cells,
                                )
                                box_core = box_digits & intersection_digits
                                box_extra = box_digits - intersection_digits
                                box_contribution = (
                                    len(box_cells) - len(box_extra)
                                )
                                if not box_core or box_contribution <= 0:
                                    continue
                                if line_core & box_core:
                                    continue
                                if (
                                    line_contribution + box_contribution
                                    != surplus
                                ):
                                    continue

                                pattern_cells = (
                                    intersection_set
                                    | set(line_cells)
                                    | set(box_cells)
                                )
                                shared_extras = line_extra & box_extra
                                line_targets = line_empty - pattern_cells
                                box_targets = box_empty - pattern_cells
                                line_elimination_digits = (
                                    (
                                        intersection_digits | line_digits
                                    ) - box_digits
                                ) | shared_extras
                                box_elimination_digits = (
                                    (
                                        intersection_digits | box_digits
                                    ) - line_digits
                                ) | shared_extras
                                eliminations = (
                                    _eliminations(
                                        state,
                                        line_targets,
                                        line_elimination_digits,
                                    )
                                    | _eliminations(
                                        state,
                                        box_targets,
                                        box_elimination_digits,
                                    )
                                )
                                if not eliminations:
                                    continue

                                extended = bool(
                                    line_extra
                                    or box_extra
                                    or intersection_set != set(intersection)
                                )
                                signature = (
                                    extended,
                                    tuple(sorted(eliminations)),
                                    tuple(intersection_cells),
                                    tuple(line_cells),
                                    tuple(box_cells),
                                )
                                if signature in seen:
                                    continue
                                seen.add(signature)
                                patterns.append(SueDeCoqPattern(
                                    line_kind=line_kind,
                                    line_index=line_index,
                                    box_index=box_index,
                                    intersection_cells=tuple(
                                        intersection_cells
                                    ),
                                    line_cells=tuple(line_cells),
                                    box_cells=tuple(box_cells),
                                    intersection_digits=intersection_digits,
                                    line_core_digits=frozenset(line_core),
                                    box_core_digits=frozenset(box_core),
                                    line_extra_digits=frozenset(line_extra),
                                    box_extra_digits=frozenset(box_extra),
                                    eliminations=tuple(sorted(eliminations)),
                                    extended=extended,
                                ))

    return tuple(patterns)


__all__ = [
    "SueDeCoqPattern",
    "enumerate_sue_de_coq",
]
