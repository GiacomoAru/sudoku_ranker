"""Enumerazione combinatoria delle Aligned Exclusion locali.

Il modulo non costruisce mosse e non consulta soluzioni complete: restituisce
soltanto pattern immutabili derivati dai candidati dello stato corrente.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product

from .data_structure import peers


Cell = tuple[int, int]
Candidate = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class AlignedExclusionPattern:
    degree: int
    base_cells: tuple[Cell, ...]
    excluder_cells: tuple[Cell, ...]
    eliminations: tuple[Candidate, ...]
    allowed_assignment_count: int
    rejected_assignment_count: int


def _candidate_cells(state):
    return tuple(
        (row, column)
        for row in range(9)
        for column in range(9)
        if state.grid[row, column] == 0
        and len(state.candidates[row][column]) >= 2
    )


def enumerate_aligned_exclusions(state, degree):
    """Enumera APE/ATE usando tutte le assegnazioni delle celle base.

    Un'assegnazione è respinta quando viola una visibilità fra celle base o
    quando consuma tutti i candidati di una cella escludente che vede ogni
    base. Un candidato assente da ogni assegnazione rimasta è eliminabile.
    """
    if degree not in (2, 3):
        raise ValueError("Aligned Exclusion supporta soltanto grado 2 o 3.")

    candidates = _candidate_cells(state)
    excluders_by_base = {}
    base_cells = []
    for base in candidates:
        visible = peers(*base)
        if any(
            state.grid[row, column] == 0
            and len(state.candidates[row][column]) == 1
            for row, column in visible
        ):
            continue
        excluders = {
            cell
            for cell in visible
            if 2 <= len(state.candidates[cell[0]][cell[1]]) <= degree
        }
        if len(excluders) >= degree:
            base_cells.append(base)
            excluders_by_base[base] = excluders

    patterns = []
    for bases in combinations(base_cells, degree):
        common_excluders = set.intersection(*(
            excluders_by_base[cell] for cell in bases
        ))
        if len(common_excluders) < degree:
            continue

        domains = tuple(
            tuple(sorted(state.candidates[row][column]))
            for row, column in bases
        )
        allowed = []
        rejected_count = 0
        relevant_excluders = set()

        for assignment in product(*domains):
            violates_base_visibility = any(
                assignment[left] == assignment[right]
                and bases[right] in peers(*bases[left])
                for left, right in combinations(range(degree), 2)
            )
            if violates_base_visibility:
                rejected_count += 1
                continue

            assigned_values = set(assignment)
            blockers = {
                cell
                for cell in common_excluders
                if state.candidates[cell[0]][cell[1]] <= assigned_values
            }
            if blockers:
                rejected_count += 1
                relevant_excluders.update(blockers)
                continue
            allowed.append(assignment)

        # Uno stato senza alcuna assegnazione locale è una contraddizione,
        # non una mossa di Aligned Exclusion da applicare parzialmente.
        if not allowed:
            continue

        eliminations = tuple(sorted(
            (row, column, value)
            for index, (row, column) in enumerate(bases)
            for value in domains[index]
            if not any(
                assignment[index] == value
                for assignment in allowed
            )
        ))
        if not eliminations:
            continue

        patterns.append(AlignedExclusionPattern(
            degree=degree,
            base_cells=tuple(bases),
            excluder_cells=tuple(sorted(relevant_excluders)),
            eliminations=eliminations,
            allowed_assignment_count=len(allowed),
            rejected_assignment_count=rejected_count,
        ))

    return tuple(patterns)


__all__ = [
    "AlignedExclusionPattern",
    "enumerate_aligned_exclusions",
]
