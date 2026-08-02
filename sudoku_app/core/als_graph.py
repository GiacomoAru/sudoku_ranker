"""Grafo degli Almost Locked Set e dei loro RCC.

Il modulo contiene soltanto la relazione strutturale fra ALS.  Enumerazione,
tecniche e classificazione restano in :mod:`sudoku_app.core.als`, così ogni
consumer usa la stessa definizione autorevole di Restricted Common Candidate.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Iterable

from .data_structure import peers


Cell = tuple[int, int]
Candidate = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class RCC:
    """Restricted Common Candidate fra due ALS.

    Le occorrenze sono conservate insieme alla tripla richiesta dalla patch:
    rendono verificabile il requisito di visibilità completa senza dover
    ricostruire il supporto dal testo della mossa.
    """

    digit: int
    left_als_id: int
    right_als_id: int
    left_occurrences: frozenset[Cell] = frozenset()
    right_occurrences: frozenset[Cell] = frozenset()

    def __post_init__(self):
        digit = int(self.digit)
        left_id = int(self.left_als_id)
        right_id = int(self.right_als_id)
        left_occurrences = frozenset(
            (int(row), int(column))
            for row, column in self.left_occurrences
        )
        right_occurrences = frozenset(
            (int(row), int(column))
            for row, column in self.right_occurrences
        )
        if digit not in range(1, 10):
            raise ValueError("La cifra RCC deve essere compresa tra 1 e 9.")
        if left_id < 0 or right_id < 0 or left_id == right_id:
            raise ValueError("Un RCC deve collegare due ALS distinti.")
        if left_id > right_id:
            left_id, right_id = right_id, left_id
            left_occurrences, right_occurrences = (
                right_occurrences,
                left_occurrences,
            )
        object.__setattr__(self, "digit", digit)
        object.__setattr__(self, "left_als_id", left_id)
        object.__setattr__(self, "right_als_id", right_id)
        object.__setattr__(self, "left_occurrences", left_occurrences)
        object.__setattr__(self, "right_occurrences", right_occurrences)

    @property
    def key(self) -> tuple[int, int, int]:
        return self.left_als_id, self.right_als_id, self.digit

    @property
    def support_candidates(self) -> tuple[Candidate, ...]:
        return tuple(sorted(
            {(row, column, self.digit) for row, column in self.left_occurrences}
            | {
                (row, column, self.digit)
                for row, column in self.right_occurrences
            }
        ))

    def occurrences_for(self, als_id: int) -> frozenset[Cell]:
        als_id = int(als_id)
        if als_id == self.left_als_id:
            return self.left_occurrences
        if als_id == self.right_als_id:
            return self.right_occurrences
        raise KeyError(f"L'ALS {als_id} non appartiene all'RCC.")

    def to_dict(self) -> dict:
        return {
            "digit": self.digit,
            "left_als_id": self.left_als_id,
            "right_als_id": self.right_als_id,
            "left_occurrences": [
                list(cell) for cell in sorted(self.left_occurrences)
            ],
            "right_occurrences": [
                list(cell) for cell in sorted(self.right_occurrences)
            ],
        }

    @classmethod
    def from_dict(cls, value):
        return cls(
            digit=value["digit"],
            left_als_id=value["left_als_id"],
            right_als_id=value["right_als_id"],
            left_occurrences=frozenset(
                tuple(cell) for cell in value.get("left_occurrences", ())
            ),
            right_occurrences=frozenset(
                tuple(cell) for cell in value.get("right_occurrences", ())
            ),
        )


def _occurrences(state, als, digit: int) -> frozenset[Cell]:
    return frozenset(
        cell
        for cell in als.cells
        if int(digit) in state.candidates[cell[0]][cell[1]]
    )


def restricted_common_candidates(left, right, state) -> tuple[RCC, ...]:
    """Restituisce soltanto candidati con visibilità incrociata completa.

    Una cella non vede se stessa. Di conseguenza un candidato presente nella
    parte sovrapposta di due ALS non può essere promosso accidentalmente a RCC.
    """

    if left.id == right.id:
        return ()
    result = []
    for digit in sorted(left.candidates & right.candidates):
        left_cells = _occurrences(state, left, digit)
        right_cells = _occurrences(state, right, digit)
        if not left_cells or not right_cells:
            continue
        if all(
            right_cell in peers(*left_cell)
            for left_cell in left_cells
            for right_cell in right_cells
        ):
            result.append(RCC(
                digit=digit,
                left_als_id=left.id,
                right_als_id=right.id,
                left_occurrences=left_cells,
                right_occurrences=right_cells,
            ))
    return tuple(result)


class ALSGraph:
    """Grafo non orientato degli ALS, indicizzato per coppia e cifra."""

    def __init__(self, state, als_nodes: Iterable):
        self.state = state
        self.als_nodes = tuple(sorted(als_nodes, key=lambda als: als.id))
        self.by_id = {als.id: als for als in self.als_nodes}
        if len(self.by_id) != len(self.als_nodes):
            raise ValueError("Gli id ALS del grafo devono essere univoci.")

        by_digit = defaultdict(list)
        for als in self.als_nodes:
            for digit in als.candidates:
                by_digit[digit].append(als.id)

        candidate_pairs = set()
        for als_ids in by_digit.values():
            candidate_pairs.update(combinations(sorted(als_ids), 2))

        by_pair = {}
        adjacency = defaultdict(set)
        for left_id, right_id in sorted(candidate_pairs):
            rccs = restricted_common_candidates(
                self.by_id[left_id],
                self.by_id[right_id],
                state,
            )
            if not rccs:
                continue
            by_pair[(left_id, right_id)] = rccs
            adjacency[left_id].add(right_id)
            adjacency[right_id].add(left_id)

        self._by_pair = by_pair
        self._adjacency = {
            als_id: tuple(sorted(neighbors))
            for als_id, neighbors in adjacency.items()
        }

    @staticmethod
    def _pair(left_id: int, right_id: int) -> tuple[int, int]:
        left_id, right_id = int(left_id), int(right_id)
        return (left_id, right_id) if left_id < right_id else (
            right_id,
            left_id,
        )

    @property
    def rccs(self) -> tuple[RCC, ...]:
        return tuple(
            rcc
            for pair in sorted(self._by_pair)
            for rcc in self._by_pair[pair]
        )

    @property
    def pairs(self) -> tuple[tuple[int, int], ...]:
        return tuple(sorted(self._by_pair))

    def between(self, left, right) -> tuple[RCC, ...]:
        left_id = left.id if hasattr(left, "id") else int(left)
        right_id = right.id if hasattr(right, "id") else int(right)
        if left_id == right_id:
            return ()
        return self._by_pair.get(self._pair(left_id, right_id), ())

    def neighbors(self, als) -> tuple:
        als_id = als.id if hasattr(als, "id") else int(als)
        return tuple(
            self.by_id[neighbor_id]
            for neighbor_id in self._adjacency.get(als_id, ())
        )

    def occurrences(self, als, digit: int) -> frozenset[Cell]:
        node = self.by_id[int(als)] if not hasattr(als, "cells") else als
        return _occurrences(self.state, node, int(digit))

    def visible_targets(
        self,
        digit: int,
        occurrence_cells: Iterable[Cell],
        *,
        excluded_cells: Iterable[Cell] = (),
    ) -> frozenset[Candidate]:
        """Candidati esterni che vedono tutte le occorrenze indicate."""

        occurrence_cells = frozenset(occurrence_cells)
        if not occurrence_cells:
            return frozenset()
        visible = None
        for row, column in occurrence_cells:
            cell_peers = peers(row, column)
            visible = set(cell_peers) if visible is None else visible & cell_peers
        visible.difference_update(frozenset(excluded_cells))
        return frozenset(
            (row, column, int(digit))
            for row, column in visible
            if int(digit) in self.state.candidates[row][column]
        )

    def targets_for_alses(
        self,
        digit: int,
        als_nodes: Iterable,
        *,
        excluded_cells: Iterable[Cell] = (),
    ) -> frozenset[Candidate]:
        nodes = tuple(als_nodes)
        occurrences = set().union(*(
            self.occurrences(als, digit) for als in nodes
        ))
        return self.visible_targets(
            digit,
            occurrences,
            excluded_cells=excluded_cells,
        )


__all__ = [
    "ALSGraph",
    "Candidate",
    "Cell",
    "RCC",
    "restricted_common_candidates",
]
