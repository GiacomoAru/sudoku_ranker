"""Motore parametrico delle Aligned Exclusion basate su ALS canonici.

Il modulo enumera tutte le assegnazioni delle celle base. Un'assegnazione
viene respinta quando viola una casa Sudoku oppure quando due o piu' cifre
assegnate rimuovono due candidati distinti dallo stesso Almost Locked Set.
Gli ALS provengono esclusivamente da ``als.enumerate_als``.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product

from . import als as als_engine
from . import search_config
from .data_structure import peers


Cell = tuple[int, int]
Candidate = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class RejectedAssignment:
    values: tuple[int, ...]
    reason: str
    als_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class AlignedExclusionPattern:
    degree: int
    base_cells: tuple[Cell, ...]
    aligned: bool
    excluder_als: tuple[als_engine.ALS, ...]
    eliminations: tuple[Candidate, ...]
    allowed_assignments: tuple[tuple[int, ...], ...]
    allowed_assignment_count: int
    rejected_assignment_count: int
    rejected_assignments: tuple[RejectedAssignment, ...]

    @property
    def excluder_cells(self):
        return tuple(sorted(set().union(*(
            item.cells for item in self.excluder_als
        ))))


def _candidate_cells(state):
    return tuple(
        (row, column)
        for row in range(9)
        for column in range(9)
        if state.grid[row, column] == 0
        and len(state.candidates[row][column]) >= 2
    )


def _all_see_each_other(cells):
    return all(
        right in peers(*left)
        for left, right in combinations(cells, 2)
    )


def _minimum_als_cover(blocker_sets):
    """Restituisce il minor insieme di ALS che respinge tutti i casi."""
    blocker_sets = tuple(frozenset(items) for items in blocker_sets if items)
    if not blocker_sets:
        return ()
    candidates = tuple(sorted(set().union(*blocker_sets)))
    for size in range(1, len(candidates) + 1):
        for subset in combinations(candidates, size):
            chosen = set(subset)
            if all(chosen & blockers for blockers in blocker_sets):
                return subset
    return ()


def enumerate_aligned_exclusions(
    state,
    degree,
    *,
    truncated_out=None,
    als_nodes=None,
):
    """Enumera Aligned Exclusion di qualunque grado positivo.

    Ogni conclusione conserva il minimo insieme di ALS sufficiente a
    respingere tutte le assegnazioni che contengono il candidato eliminato.
    I budget P17 limitano soltanto la modalita' ``limited`` e propagano una
    causa tipizzata tramite ``truncated_out``.
    """
    if isinstance(degree, bool) or int(degree) < 2:
        raise ValueError("Aligned Exclusion richiede grado almeno 2.")
    degree = int(degree)
    limits = search_config.limits_for_state(state)
    if (
        limits.aligned_max_degree is not None
        and degree > limits.aligned_max_degree
    ):
        if truncated_out is not None:
            truncated_out.append("aligned_max_degree")
        return ()

    all_als = tuple(
        als_engine.enumerate_als(state)
        if als_nodes is None else als_nodes
    )
    als_by_id = {item.id: item for item in all_als}
    candidate_cells = _candidate_cells(state)
    patterns = []
    base_count = 0
    assignment_count = 0
    stop = False

    for bases in combinations(candidate_cells, degree):
        base_count += 1
        if (
            limits.aligned_base_combinations is not None
            and base_count > limits.aligned_base_combinations
        ):
            if truncated_out is not None:
                truncated_out.append("aligned_base_combinations")
            break

        domains = tuple(
            tuple(sorted(state.candidates[row][column]))
            for row, column in bases
        )
        eligible_als = tuple(
            item for item in all_als
            if item.cells.isdisjoint(bases)
            and sum(
                any(
                    occurrence in peers(*base)
                    for occurrence in item.occurrences(state, digit)
                )
                for base in bases
                for digit in domains[bases.index(base)]
                if digit in item.candidates
            ) >= 2
        )
        if not eligible_als:
            continue

        rejected = []
        allowed = []

        for assignment in product(*domains):
            assignment_count += 1
            if (
                limits.aligned_assignments is not None
                and assignment_count > limits.aligned_assignments
            ):
                if truncated_out is not None:
                    truncated_out.append("aligned_assignments")
                stop = True
                break

            violates_house = any(
                assignment[left] == assignment[right]
                and bases[right] in peers(*bases[left])
                for left, right in combinations(range(degree), 2)
            )
            if violates_house:
                item = RejectedAssignment(
                    values=tuple(assignment),
                    reason="base-house-conflict",
                )
                rejected.append(item)
                continue

            blockers = []
            for excluder in eligible_als:
                removed_digits = set()
                for base, value in zip(bases, assignment):
                    if value not in excluder.candidates:
                        continue
                    occurrences = excluder.occurrences(state, value)
                    if occurrences and all(
                        occurrence in peers(*base)
                        for occurrence in occurrences
                    ):
                        removed_digits.add(value)
                if len(removed_digits) >= 2:
                    blockers.append(excluder.id)

            if blockers:
                item = RejectedAssignment(
                    values=tuple(assignment),
                    reason="als-cardinality",
                    als_ids=tuple(sorted(blockers)),
                )
                rejected.append(item)
            else:
                allowed.append(tuple(assignment))

        if stop:
            break
        if not allowed:
            continue

        grouped = {}
        for position, (row, column) in enumerate(bases):
            for value in domains[position]:
                if any(item[position] == value for item in allowed):
                    continue
                relevant = tuple(
                    item for item in rejected
                    if item.values[position] == value
                    and item.reason == "als-cardinality"
                )
                support_ids = _minimum_als_cover(
                    item.als_ids for item in relevant
                )
                if not support_ids:
                    continue
                grouped.setdefault(support_ids, []).append(
                    (row, column, value)
                )

        for support_ids, eliminations in sorted(grouped.items()):
            support_set = set(support_ids)
            positions = {
                cell: index for index, cell in enumerate(bases)
            }
            relevant_rejected = []
            for item in rejected:
                if not any(
                    item.values[positions[(row, column)]] == value
                    for row, column, value in eliminations
                ):
                    continue
                relevant_rejected.append(RejectedAssignment(
                    values=item.values,
                    reason=item.reason,
                    als_ids=tuple(sorted(
                        set(item.als_ids) & support_set
                    )),
                ))
            patterns.append(AlignedExclusionPattern(
                degree=degree,
                base_cells=tuple(bases),
                aligned=_all_see_each_other(bases),
                excluder_als=tuple(
                    als_by_id[item] for item in support_ids
                ),
                eliminations=tuple(sorted(eliminations)),
                allowed_assignments=tuple(sorted(allowed)),
                allowed_assignment_count=len(allowed),
                rejected_assignment_count=len(relevant_rejected),
                rejected_assignments=tuple(relevant_rejected),
            ))
            if (
                limits.aligned_results is not None
                and len(patterns) >= limits.aligned_results
            ):
                if truncated_out is not None:
                    truncated_out.append("aligned_results")
                stop = True
                break
        if stop:
            break

    return tuple(patterns)


__all__ = [
    "AlignedExclusionPattern",
    "RejectedAssignment",
    "enumerate_aligned_exclusions",
]
