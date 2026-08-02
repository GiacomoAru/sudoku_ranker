"""Nodi di gruppo condivisi dal grafo AIC e dal modello delle prove."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .data_structure import UNITS


Cell = tuple[int, int]
Candidate = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class GroupNode:
    """Proposizione: ``digit`` occupa una delle ``cells`` del segmento."""

    digit: int
    cells: frozenset[Cell]
    house_ids: tuple[int, ...]
    role: str

    def __post_init__(self):
        digit = int(self.digit)
        cells = frozenset(
            (int(row), int(column)) for row, column in self.cells
        )
        house_ids = tuple(sorted({int(item) for item in self.house_ids}))
        role = str(self.role).strip()
        object.__setattr__(self, "digit", digit)
        object.__setattr__(self, "cells", cells)
        object.__setattr__(self, "house_ids", house_ids)
        object.__setattr__(self, "role", role)

        if digit not in range(1, 10):
            raise ValueError("La cifra di un GroupNode deve essere tra 1 e 9.")
        if len(cells) < 2:
            raise ValueError("Un vero GroupNode richiede almeno due celle.")
        if any(
            not 0 <= row < 9 or not 0 <= column < 9
            for row, column in cells
        ):
            raise ValueError("Un GroupNode contiene una cella non valida.")
        if role not in {"row-segment", "column-segment"}:
            raise ValueError("Ruolo GroupNode non riconosciuto.")

        common_houses = tuple(
            house_id
            for house_id, unit in enumerate(UNITS)
            if cells <= set(unit)
        )
        if house_ids != common_houses:
            raise ValueError(
                "house_ids deve contenere tutte e sole le case del gruppo."
            )
        rows = {row for row, _ in cells}
        columns = {column for _, column in cells}
        if role == "row-segment" and len(rows) != 1:
            raise ValueError("Un row-segment deve appartenere a una riga.")
        if role == "column-segment" and len(columns) != 1:
            raise ValueError("Un column-segment deve appartenere a una colonna.")
        if not any(house_id >= 18 for house_id in house_ids):
            raise ValueError("Un GroupNode deve essere confinato in un box.")

    @property
    def candidates(self) -> tuple[Candidate, ...]:
        return tuple(
            (row, column, self.digit) for row, column in sorted(self.cells)
        )

    def to_dict(self) -> dict:
        return {
            "digit": self.digit,
            "cells": [list(cell) for cell in sorted(self.cells)],
            "house_ids": list(self.house_ids),
            "role": self.role,
        }

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, Mapping):
            raise TypeError("Un GroupNode serializzato deve essere una mappa.")
        return cls(
            digit=value["digit"],
            cells=frozenset(tuple(cell) for cell in value.get("cells", ())),
            house_ids=tuple(value.get("house_ids", ())),
            role=value["role"],
        )


def group_node(value) -> GroupNode:
    if isinstance(value, GroupNode):
        return value
    return GroupNode.from_dict(value)


__all__ = ["Candidate", "Cell", "GroupNode", "group_node"]
