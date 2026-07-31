"""Strutture riutilizzabili per i pattern basati sull'unicita'."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from .data_structure import UNITS, UNIT_KINDS
from .proof import ProofDAG, ProofNode


Cell = tuple[int, int]

CELL_UNITS = {
    (row, column): tuple(
        unit_index
        for unit_index, unit in enumerate(UNITS)
        if (row, column) in unit
    )
    for row in range(9)
    for column in range(9)
}


def _canonical_cycle(cells, house_ids):
    """Canonicalizza insieme rotazione, direzione e case del ciclo."""
    cells = tuple(cells)
    house_ids = tuple(house_ids)
    size = len(cells)
    variants = []

    for start in range(size):
        forward_cells = tuple(
            cells[(start + offset) % size]
            for offset in range(size)
        )
        forward_houses = tuple(
            house_ids[(start + offset) % size]
            for offset in range(size)
        )
        variants.append((forward_cells, forward_houses))

        reverse_cells = tuple(
            cells[(start - offset) % size]
            for offset in range(size)
        )
        reverse_houses = tuple(
            house_ids[(start - offset - 1) % size]
            for offset in range(size)
        )
        variants.append((reverse_cells, reverse_houses))

    return min(variants)


@dataclass(frozen=True, slots=True)
class UniqueLoopPattern:
    """Ciclo pari canonicalizzato che supporta i Unique Loop Type 1-4."""

    base_pair: tuple[int, int]
    cells: tuple[Cell, ...]
    house_ids: tuple[int, ...]
    extra_cells: tuple[Cell, ...]
    extra_values: tuple[int, ...]

    @property
    def signature(self):
        return self.base_pair, self.cells

    def proof_payload(self, loop_type):
        pattern = {
            "pattern": "unique_loop",
            "type": int(loop_type),
            "base_pair": list(self.base_pair),
            "cells": [list(cell) for cell in self.cells],
            "house_ids": list(self.house_ids),
            "house_kinds": [
                UNIT_KINDS[unit_index]
                for unit_index in self.house_ids
            ],
            "extra_cells": [list(cell) for cell in self.extra_cells],
            "extra_values": list(self.extra_values),
            "canonical_signature": [
                list(self.base_pair),
                [list(cell) for cell in self.cells],
            ],
        }
        dag = ProofDAG(
            nodes={
                0: ProofNode(
                    id=0,
                    kind="advanced-rule",
                    conclusion=None,
                    parents=(),
                    reason="unique-loop-deadly-pattern",
                    depth=0,
                    payload={
                        "presentation": False,
                        "uniqueness_pattern": pattern,
                    },
                ),
            },
            roots=(0,),
            conclusions=(),
        )
        return {
            "kind": "uniqueness-loop",
            "uniqueness_pattern": pattern,
            "proof_dag": dag.to_dict(),
        }


def _partial_loop_is_valid(path):
    """Scarta subito case con piu' di due nodi o parita' incompatibile."""
    for unit in UNITS:
        positions = [
            index
            for index, cell in enumerate(path)
            if cell in unit
        ]
        if len(positions) > 2:
            return False
        if len(positions) == 2 and positions[0] % 2 == positions[1] % 2:
            return False
    return True


def _complete_loop_is_valid(cells):
    if len(cells) < 6 or len(cells) % 2:
        return False
    for unit in UNITS:
        positions = [
            index
            for index, cell in enumerate(cells)
            if cell in unit
        ]
        if positions and (
            len(positions) != 2
            or positions[0] % 2 == positions[1] % 2
        ):
            return False
    return True


def enumerate_unique_loops(state):
    """Enumera tutti i cicli semplici, pari e strutturalmente validi.

    La cella minima e' sempre il punto iniziale della DFS. Rotazioni e versi
    opposti vengono poi consolidati dalla firma canonicale del pattern.
    """
    found = {}

    for first_value, second_value in combinations(range(1, 10), 2):
        pair = frozenset((first_value, second_value))
        eligible = tuple(sorted(
            (row, column)
            for row in range(9)
            for column in range(9)
            if state.grid[row, column] == 0
            and pair <= state.candidates[row][column]
        ))
        if len(eligible) < 6:
            continue
        eligible_set = set(eligible)

        for start in eligible:
            path = [start]
            visited = {start}

            def visit(last_house=None, first_house=None, edge_houses=()):
                current = path[-1]
                for house_id in CELL_UNITS[current]:
                    if house_id == last_house:
                        continue
                    for neighbour in UNITS[house_id]:
                        if neighbour not in eligible_set or neighbour == current:
                            continue

                        if neighbour == start:
                            if (
                                len(path) >= 6
                                and len(path) % 2 == 0
                                and house_id != first_house
                                and _complete_loop_is_valid(path)
                            ):
                                canonical_cells, canonical_houses = (
                                    _canonical_cycle(
                                        path,
                                        edge_houses + (house_id,),
                                    )
                                )
                                extras = {
                                    cell: (
                                        set(state.candidates[cell[0]][cell[1]])
                                        - set(pair)
                                    )
                                    for cell in canonical_cells
                                }
                                extra_cells = tuple(
                                    cell for cell in canonical_cells if extras[cell]
                                )
                                extra_values = tuple(sorted(
                                    set().union(*(
                                        extras[cell] for cell in extra_cells
                                    ))
                                    if extra_cells else set()
                                ))
                                if (
                                    len(extra_cells) <= 2
                                    or len(extra_values) == 1
                                ):
                                    pattern = UniqueLoopPattern(
                                        base_pair=(first_value, second_value),
                                        cells=canonical_cells,
                                        house_ids=canonical_houses,
                                        extra_cells=extra_cells,
                                        extra_values=extra_values,
                                    )
                                    previous = found.get(pattern.signature)
                                    if (
                                        previous is None
                                        or pattern.house_ids < previous.house_ids
                                    ):
                                        found[pattern.signature] = pattern
                            continue

                        if neighbour in visited or neighbour < start:
                            continue

                        neighbour_extras = (
                            set(state.candidates[neighbour[0]][neighbour[1]])
                            - set(pair)
                        )
                        current_extra_cells = [
                            cell
                            for cell in path
                            if set(state.candidates[cell[0]][cell[1]]) - set(pair)
                        ]
                        current_extra_values = set().union(*(
                            set(state.candidates[cell[0]][cell[1]]) - set(pair)
                            for cell in current_extra_cells
                        )) if current_extra_cells else set()
                        future_extra_count = len(current_extra_cells) + bool(
                            neighbour_extras
                        )
                        future_extra_values = (
                            current_extra_values | neighbour_extras
                        )
                        if (
                            future_extra_count > 2
                            and len(future_extra_values) > 1
                        ):
                            continue

                        path.append(neighbour)
                        if _partial_loop_is_valid(path):
                            visited.add(neighbour)
                            visit(
                                house_id,
                                house_id if first_house is None else first_house,
                                edge_houses + (house_id,),
                            )
                            visited.remove(neighbour)
                        path.pop()

            visit()

    return tuple(
        found[signature]
        for signature in sorted(found)
    )


__all__ = [
    "CELL_UNITS",
    "UniqueLoopPattern",
    "enumerate_unique_loops",
]
