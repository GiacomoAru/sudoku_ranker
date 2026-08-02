"""Proposizioni ALS tipizzate condivise da grafo e ``ProofDAG``.

Un ``ALSNode`` non rappresenta genericamente un Almost Locked Set: rappresenta
la proposizione OR "la cifra ``digit`` compare in una delle sue occorrenze
all'interno dell'ALS".  Questa granularita' rende espliciti i due link usati
dalle ALS-AIC:

* link strong interno fra due cifre dello stesso ALS;
* link weak RCC/visibilita' fra proposizioni della stessa cifra.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .data_structure import UNITS


Cell = tuple[int, int]
Candidate = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class ALSNode:
    """Proposizione OR relativa a una cifra di un ALS validato."""

    als_id: int
    house_id: int
    cells: frozenset[Cell]
    digits: frozenset[int]
    digit: int
    occurrences: frozenset[Cell]
    role: str = "als-digit"

    def __post_init__(self):
        object.__setattr__(self, "als_id", int(self.als_id))
        object.__setattr__(self, "house_id", int(self.house_id))
        object.__setattr__(self, "cells", frozenset(
            (int(row), int(column)) for row, column in self.cells
        ))
        object.__setattr__(self, "digits", frozenset(
            int(value) for value in self.digits
        ))
        object.__setattr__(self, "digit", int(self.digit))
        object.__setattr__(self, "occurrences", frozenset(
            (int(row), int(column)) for row, column in self.occurrences
        ))
        object.__setattr__(self, "role", str(self.role))
        self.validate()

    def validate(self) -> None:
        if self.als_id < 0:
            raise ValueError("L'id di un ALSNode non puo' essere negativo.")
        if self.house_id not in range(len(UNITS)):
            raise ValueError("La casa di un ALSNode deve essere tra 0 e 26.")
        if not self.cells or not self.cells <= set(UNITS[self.house_id]):
            raise ValueError("Le celle ALSNode devono appartenere alla casa.")
        if len(self.digits) != len(self.cells) + 1:
            raise ValueError("Un ALSNode richiede la struttura ALS N+1.")
        if not self.digits <= set(range(1, 10)):
            raise ValueError("Un ALSNode contiene cifre non valide.")
        if self.digit not in self.digits:
            raise ValueError("La cifra del nodo deve appartenere all'ALS.")
        if not self.occurrences or not self.occurrences <= self.cells:
            raise ValueError("Le occorrenze devono essere non vuote e interne.")
        if self.role != "als-digit":
            raise ValueError("Ruolo ALSNode non riconosciuto.")

    @property
    def candidates(self) -> tuple[Candidate, ...]:
        return tuple(
            (row, column, self.digit)
            for row, column in sorted(self.occurrences)
        )

    @property
    def als_key(self):
        """Identita' strutturale dell'ALS, indipendente dalla cifra scelta."""
        return (
            self.als_id,
            self.house_id,
            tuple(sorted(self.cells)),
            tuple(sorted(self.digits)),
        )

    def to_dict(self) -> dict:
        return {
            "node_type": "als",
            "als_id": self.als_id,
            "house_id": self.house_id,
            "cells": [list(cell) for cell in sorted(self.cells)],
            "digits": sorted(self.digits),
            "digit": self.digit,
            "occurrences": [
                list(cell) for cell in sorted(self.occurrences)
            ],
            "role": self.role,
        }

    @classmethod
    def from_dict(cls, value: Mapping):
        if not isinstance(value, Mapping):
            raise TypeError("Un ALSNode serializzato deve essere una mappa.")
        return cls(
            als_id=value["als_id"],
            house_id=value["house_id"],
            cells=frozenset(tuple(cell) for cell in value["cells"]),
            digits=frozenset(value["digits"]),
            digit=value["digit"],
            occurrences=frozenset(
                tuple(cell) for cell in value["occurrences"]
            ),
            role=value.get("role", "als-digit"),
        )

    @classmethod
    def from_als(cls, als, state, digit: int):
        digit = int(digit)
        return cls(
            als_id=als.id,
            house_id=als.house_id,
            cells=als.cells,
            digits=als.candidates,
            digit=digit,
            occurrences=frozenset(
                cell
                for cell in als.cells
                if digit in state.candidates[cell[0]][cell[1]]
            ),
        )


def als_node(value) -> ALSNode:
    if isinstance(value, ALSNode):
        return value
    return ALSNode.from_dict(value)


__all__ = ["ALSNode", "Candidate", "Cell", "als_node"]
