"""Motore comune per ALS, RCC, generalized wings e catene ALS.

Le funzioni di questo modulo producono deduzioni logiche indipendenti dal
catalogo e dalla presentazione.  ``techniques.als`` è il solo adattatore che
le converte in Move pubbliche.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from itertools import combinations
from typing import Iterable

from .als_graph import ALSGraph, RCC
from .data_structure import UNITS, peers


Cell = tuple[int, int]
Candidate = tuple[int, int, int]

DEFAULT_MAX_ALS_CELLS = 8
DEFAULT_MAX_CHAIN_ALSES = 8
DEFAULT_MAX_RAW_RESULTS = 512

GENERALIZED_WING_IDS = {
    (3, False): "wing.wxyz",
    (3, True): "wing.wxyz.double",
    (4, False): "wing.vwxyz",
    (4, True): "wing.vwxyz.double",
    (5, False): "wing.uvwxyz",
    (5, True): "wing.uvwxyz.double",
    (6, False): "wing.tuvwxyz",
}


@dataclass(frozen=True, slots=True)
class ALS:
    """Almost Locked Set canonico: N celle e precisamente N+1 cifre."""

    id: int
    house_id: int
    cells: frozenset[Cell]
    candidates: frozenset[int]

    def __post_init__(self):
        object.__setattr__(self, "id", int(self.id))
        object.__setattr__(self, "house_id", int(self.house_id))
        object.__setattr__(self, "cells", frozenset(
            (int(row), int(column)) for row, column in self.cells
        ))
        object.__setattr__(self, "candidates", frozenset(
            int(digit) for digit in self.candidates
        ))
        self.validate()

    def validate(self) -> None:
        if self.id < 0:
            raise ValueError("L'id ALS non può essere negativo.")
        if self.house_id not in range(len(UNITS)):
            raise ValueError("La casa ALS deve essere compresa tra 0 e 26.")
        if not self.cells:
            raise ValueError("Un ALS deve contenere almeno una cella.")
        if any(
            row not in range(9) or column not in range(9)
            for row, column in self.cells
        ):
            raise ValueError("Un ALS contiene una cella fuori griglia.")
        if not self.cells <= set(UNITS[self.house_id]):
            raise ValueError("Tutte le celle ALS devono appartenere alla casa.")
        if not self.candidates <= set(range(1, 10)):
            raise ValueError("Un ALS contiene una cifra non valida.")
        if len(self.candidates) != len(self.cells) + 1:
            raise ValueError("Un ALS deve avere N celle e N+1 candidati.")

    @property
    def signature(self) -> tuple[tuple[Cell, ...], tuple[int, ...]]:
        return tuple(sorted(self.cells)), tuple(sorted(self.candidates))

    def occurrences(self, state, digit: int) -> frozenset[Cell]:
        return frozenset(
            cell
            for cell in self.cells
            if int(digit) in state.candidates[cell[0]][cell[1]]
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "house_id": self.house_id,
            "cells": [list(cell) for cell in sorted(self.cells)],
            "candidates": sorted(self.candidates),
        }

    @classmethod
    def from_dict(cls, value):
        return cls(
            id=value["id"],
            house_id=value["house_id"],
            cells=frozenset(tuple(cell) for cell in value["cells"]),
            candidates=frozenset(value["candidates"]),
        )


def enumerate_als(state, max_cells: int = DEFAULT_MAX_ALS_CELLS) -> tuple[ALS, ...]:
    """Enumera e deduplica gli ALS equivalenti nelle 27 case Sudoku."""

    if isinstance(max_cells, bool) or int(max_cells) < 1:
        raise ValueError("max_cells deve essere un intero positivo.")
    max_cells = min(int(max_cells), 8)
    signatures = {}

    for house_id, house in enumerate(UNITS):
        unsolved = tuple(
            cell
            for cell in house
            if int(state.grid[cell[0], cell[1]]) == 0
            and state.candidates[cell[0]][cell[1]]
        )
        for size in range(1, min(max_cells, len(unsolved)) + 1):
            eligible = tuple(
                cell for cell in unsolved
                if len(state.candidates[cell[0]][cell[1]]) <= size + 1
            )
            if len(eligible) < size:
                continue
            for subset in combinations(eligible, size):
                digits = frozenset().union(*(
                    state.candidates[row][column]
                    for row, column in subset
                ))
                if len(digits) != size + 1:
                    continue
                signature = tuple(sorted(subset)), tuple(sorted(digits))
                signatures.setdefault(signature, house_id)

    return tuple(
        ALS(
            id=index,
            house_id=signatures[signature],
            cells=frozenset(signature[0]),
            candidates=frozenset(signature[1]),
        )
        for index, signature in enumerate(sorted(
            signatures,
            key=lambda item: (len(item[0]), item[0], item[1]),
        ), start=1)
    )


@dataclass(frozen=True, slots=True)
class ALSDeduction:
    """Pattern ALS completo prima dell'adattamento a una Move."""

    technique_id: str
    als_nodes: tuple[ALS, ...]
    rccs: tuple[RCC, ...]
    eliminations: frozenset[Candidate]
    endpoint_digit: int | None = None
    stem_cell: Cell | None = None
    stem_links: tuple[tuple[int, int], ...] = ()
    stem_link_occurrences: tuple[tuple[int, int, frozenset[Cell]], ...] = ()
    parent_technique_id: str | None = None
    equivalent_pattern_count: int = 1

    def __post_init__(self):
        if not self.technique_id:
            raise ValueError("Una deduzione ALS deve avere una tecnica.")
        if not self.als_nodes:
            raise ValueError("Una deduzione ALS deve contenere almeno un ALS.")
        if not self.eliminations:
            raise ValueError("Una deduzione ALS deve produrre eliminazioni.")
        if self.endpoint_digit is not None and self.endpoint_digit not in range(1, 10):
            raise ValueError("La cifra terminale ALS non è valida.")
        if self.stem_cell is not None:
            row, column = self.stem_cell
            if row not in range(9) or column not in range(9):
                raise ValueError("La stem cell non è valida.")

    @property
    def primary_cells(self) -> tuple[Cell, ...]:
        cells = set().union(*(als.cells for als in self.als_nodes))
        if self.stem_cell is not None:
            cells.add(self.stem_cell)
        return tuple(sorted(cells))

    @property
    def als_parent_technique_id(self) -> str:
        return self.parent_technique_id or self.technique_id

    def to_dict(self) -> dict:
        return {
            "technique_id": self.technique_id,
            "als_parent_technique_id": self.als_parent_technique_id,
            "als_nodes": [als.to_dict() for als in self.als_nodes],
            "rccs": [rcc.to_dict() for rcc in self.rccs],
            "endpoint_digit": self.endpoint_digit,
            "stem_cell": (
                list(self.stem_cell) if self.stem_cell is not None else None
            ),
            "stem_links": [
                {"digit": digit, "als_id": als_id}
                for digit, als_id in self.stem_links
            ],
            "stem_link_occurrences": [
                {
                    "digit": digit,
                    "als_id": als_id,
                    "occurrences": [list(cell) for cell in sorted(cells)],
                }
                for digit, als_id, cells in self.stem_link_occurrences
            ],
            "eliminations": [list(item) for item in sorted(self.eliminations)],
            "equivalent_pattern_count": self.equivalent_pattern_count,
        }

    def proof_payload(self) -> dict:
        """Costruisce un ProofDAG con nodi ALS strutturati nel payload."""

        from .proof import ImplicationEdgeSupport, ProofDAG, ProofNode

        nodes = {}
        supports = []
        next_id = 0

        def add(kind, parents=(), reason="als", payload=None, conclusion=None):
            nonlocal next_id
            parents = tuple(parents)
            depth = 0 if not parents else 1 + max(
                nodes[parent].depth for parent in parents
            )
            node = ProofNode(
                id=next_id,
                kind=kind,
                conclusion=conclusion,
                parents=parents,
                reason=reason,
                depth=depth,
                payload=payload or {},
            )
            nodes[node.id] = node
            next_id += 1
            return node.id

        if self.stem_cell is not None:
            stem_id = add(
                "advanced-rule",
                reason="death-blossom-stem",
                payload={
                    "node_type": "als-stem",
                    "cell": list(self.stem_cell),
                    "links": [list(item) for item in self.stem_links],
                    "presentation": False,
                },
            )
            terminal_ids = []
            link_by_als = defaultdict(list)
            for digit, als_id in self.stem_links:
                link_by_als[als_id].append(digit)
            occurrences_by_link = {
                (digit, als_id): cells
                for digit, als_id, cells in self.stem_link_occurrences
            }
            for als in self.als_nodes:
                node_id = add(
                    "advanced-rule",
                    parents=(stem_id,),
                    reason="als-stem-rcc",
                    payload={
                        "node_type": "als",
                        "als": als.to_dict(),
                        "link_digits": sorted(link_by_als[als.id]),
                        "presentation": False,
                    },
                )
                support_candidates = {
                    (*self.stem_cell, digit)
                    for digit in link_by_als[als.id]
                }
                for digit in link_by_als[als.id]:
                    support_candidates.update(
                        (row, column, digit)
                        for row, column in occurrences_by_link[
                            (digit, als.id)
                        ]
                    )
                supports.append(ImplicationEdgeSupport(
                    stem_id,
                    node_id,
                    tuple(sorted(support_candidates)),
                ))
                terminal_ids.append(node_id)
            evidence_id = add(
                "branch",
                parents=terminal_ids,
                reason="all-petals",
                payload={
                    "branch_count": len(terminal_ids),
                    "presentation": False,
                },
            )
        else:
            parent = None
            for index, als in enumerate(self.als_nodes):
                incoming = self.rccs[index - 1:index]
                outgoing = self.rccs[index:index + 1]
                node_id = add(
                    "advanced-rule",
                    parents=(() if parent is None else (parent,)),
                    reason=("als-root" if parent is None else "als-rcc"),
                    payload={
                        "node_type": "als",
                        "als": als.to_dict(),
                        "incoming_rcc_digits": [rcc.digit for rcc in incoming],
                        "outgoing_rcc_digits": [rcc.digit for rcc in outgoing],
                        "presentation": False,
                    },
                )
                if parent is not None:
                    link_rccs = [
                        rcc for rcc in self.rccs
                        if {
                            rcc.left_als_id,
                            rcc.right_als_id,
                        } == {self.als_nodes[index - 1].id, als.id}
                    ]
                    supports.append(ImplicationEdgeSupport(
                        parent,
                        node_id,
                        tuple(sorted({
                            candidate
                            for rcc in link_rccs
                            for candidate in rcc.support_candidates
                        })),
                    ))
                parent = node_id
            evidence_id = parent

        conclusion_ids = []
        for row, column, digit in sorted(self.eliminations):
            conclusion_ids.append(add(
                "common-conclusion",
                parents=(evidence_id,),
                reason="elimination",
                payload={"action": "elimination", "presentation": False},
                conclusion=(row, column, digit, False),
            ))

        dag = ProofDAG(
            nodes=nodes,
            roots=tuple(sorted(
                node.id for node in nodes.values() if not node.parents
            )),
            conclusions=tuple(conclusion_ids),
            edge_supports=tuple(supports),
        )
        return {
            "kind": self.technique_id,
            "proof_dag": dag.to_dict(),
            "als_node_count": len(self.als_nodes),
            "rcc_count": len(self.rccs) + len(self.stem_links),
        }


def _pair_generalized_wing_id(left, right, *, double_linked: bool):
    singles = [als for als in (left, right) if len(als.cells) == 1]
    if len(singles) != 1:
        return None
    small = singles[0]
    large = right if small is left else left
    if (
        len(small.candidates) != 2
        or len(large.cells) not in range(3, 7)
        or not small.candidates <= large.candidates
        or len(small.cells | large.cells) != len(large.cells) + 1
    ):
        return None
    return GENERALIZED_WING_IDS.get((len(large.cells), bool(double_linked)))


def _outside_union(nodes: Iterable[ALS]) -> frozenset[Cell]:
    return frozenset().union(*(als.cells for als in nodes))


def find_als_xz(graph) -> tuple[ALSDeduction, ...]:
    """Singly/Doubly Linked ALS-XZ e generalized wings derivate."""

    results = []
    for left_id, right_id in graph.pairs:
        left = graph.by_id[left_id]
        right = graph.by_id[right_id]
        pair_rccs = graph.between(left, right)
        union_cells = left.cells | right.cells

        if len(pair_rccs) == 1:
            rcc = pair_rccs[0]
            for digit in sorted(
                (left.candidates & right.candidates) - {rcc.digit}
            ):
                eliminations = graph.targets_for_alses(
                    digit,
                    (left, right),
                    excluded_cells=union_cells,
                )
                if not eliminations:
                    continue
                technique_id = (
                    _pair_generalized_wing_id(
                        left, right, double_linked=False
                    )
                    or "als.xz.single"
                )
                results.append(ALSDeduction(
                    technique_id=technique_id,
                    als_nodes=(left, right),
                    rccs=(rcc,),
                    eliminations=eliminations,
                    endpoint_digit=digit,
                    parent_technique_id=(
                        "als.xz.single"
                        if technique_id != "als.xz.single"
                        else None
                    ),
                ))
            continue

        for selected in combinations(pair_rccs, 2):
            selected_digits = {rcc.digit for rcc in selected}
            eliminations = set()

            # Ogni cifra non-RCC è locked nel proprio ALS.
            for als in (left, right):
                for digit in sorted(als.candidates - selected_digits):
                    eliminations.update(graph.visible_targets(
                        digit,
                        graph.occurrences(als, digit),
                        # L'altro ALS è parte della prova e non può essere
                        # usato contemporaneamente come target.
                        excluded_cells=union_cells,
                    ))

            # Ciascun RCC deve essere vero in uno dei due ALS.
            for digit in sorted(selected_digits):
                eliminations.update(graph.targets_for_alses(
                    digit,
                    (left, right),
                    excluded_cells=union_cells,
                ))
            if not eliminations:
                continue
            technique_id = (
                _pair_generalized_wing_id(
                    left, right, double_linked=True
                )
                or "als.xz.double"
            )
            results.append(ALSDeduction(
                technique_id=technique_id,
                als_nodes=(left, right),
                rccs=tuple(selected),
                eliminations=frozenset(eliminations),
                parent_technique_id=(
                    "als.xz.double"
                    if technique_id != "als.xz.double"
                    else None
                ),
            ))
    return _deduplicate(results)


def find_als_xy_wings(graph) -> tuple[ALSDeduction, ...]:
    """Cerca triple A-X-C-Y-B con RCC adiacenti distinti."""

    results = []
    for center in graph.als_nodes:
        neighbors = graph.neighbors(center)
        for first, last in combinations(neighbors, 2):
            if first.id > last.id:
                first, last = last, first
            union_cells = first.cells | center.cells | last.cells
            for first_rcc in graph.between(first, center):
                for last_rcc in graph.between(center, last):
                    if first_rcc.digit == last_rcc.digit:
                        continue
                    for digit in sorted(
                        (first.candidates & last.candidates)
                        - {first_rcc.digit, last_rcc.digit}
                    ):
                        eliminations = graph.targets_for_alses(
                            digit,
                            (first, last),
                            excluded_cells=union_cells,
                        )
                        if eliminations:
                            results.append(ALSDeduction(
                                technique_id="als.xy_wing",
                                als_nodes=(first, center, last),
                                rccs=(first_rcc, last_rcc),
                                eliminations=eliminations,
                                endpoint_digit=digit,
                            ))
    return _deduplicate(results)


def find_als_chains(
    graph,
    *,
    max_alses: int = DEFAULT_MAX_CHAIN_ALSES,
    max_results: int = DEFAULT_MAX_RAW_RESULTS,
) -> tuple[ALSDeduction, ...]:
    """Cammini ALS-RCC compatibili; distingue ALS Chain e ALS-AIC."""

    from collections import deque

    max_alses = max(4, min(int(max_alses), 12))
    max_results = max(1, int(max_results))
    max_search_states = max(32_768, max_results * 32)
    searched_states = 0
    results = []
    outcome_signatures = set()

    # Precalcola soltanto le coppie di estremi che possono produrre almeno
    # una conclusione. La BFS può così condividere tutti i prefissi di catena
    # per lo stesso ALS iniziale, invece di ripetere una ricerca per target.
    endpoint_targets = {}
    for first, last in combinations(graph.als_nodes, 2):
        if first.cells <= last.cells or last.cells <= first.cells:
            continue
        by_digit = {}
        for digit in sorted(first.candidates & last.candidates):
            targets = graph.targets_for_alses(
                digit,
                (first, last),
                # HoDoKu consente eliminazioni cannibalistiche negli ALS
                # interni; soltanto i due estremi sono protetti.
                excluded_cells=first.cells | last.cells,
            )
            if targets:
                by_digit[digit] = targets
        if by_digit:
            endpoint_targets[(first.id, last.id)] = by_digit

    def evaluate(path, links):
        first, last = path[0], path[-1]
        by_digit = endpoint_targets.get((first.id, last.id))
        if not by_digit:
            return
        endpoint_digits = set(by_digit) - {
            links[0].digit,
            links[-1].digit,
        }
        has_multi_rcc_link = any(
            len(graph.between(left, right)) > 1
            for left, right in zip(path, path[1:])
        )
        technique_id = (
            "chain.als_aic" if has_multi_rcc_link else "als.chain"
        )
        eliminations = set()
        used_endpoint_digits = []
        for digit in sorted(endpoint_digits):
            digit_eliminations = by_digit[digit]
            if digit_eliminations:
                eliminations.update(digit_eliminations)
                used_endpoint_digits.append(digit)
        if eliminations:
            outcome = technique_id, tuple(sorted(eliminations))
            if outcome in outcome_signatures:
                return
            outcome_signatures.add(outcome)
            results.append(ALSDeduction(
                technique_id=technique_id,
                als_nodes=path,
                rccs=links,
                eliminations=frozenset(eliminations),
                endpoint_digit=(
                    used_endpoint_digits[0]
                    if len(used_endpoint_digits) == 1
                    else None
                ),
            ))

    for start in graph.als_nodes:
        if not any(pair[0] == start.id for pair in endpoint_targets):
            continue
        queue = deque([((start,), ())])
        visited = set()
        while queue:
            path, links = queue.popleft()
            searched_states += 1
            if searched_states > max_search_states:
                break
            if len(path) >= max_alses:
                continue
            current = path[-1]
            for neighbor in graph.neighbors(current):
                if neighbor in path:
                    continue
                if (
                    len(path) >= 3
                    and (
                        start.cells <= neighbor.cells
                        or neighbor.cells <= start.cells
                    )
                ):
                    continue
                for rcc in graph.between(current, neighbor):
                    if links and rcc.digit == links[-1].digit:
                        continue
                    next_path = path + (neighbor,)
                    next_links = links + (rcc,)
                    first_digit = next_links[0].digit
                    state_key = (
                        neighbor.id,
                        rcc.digit,
                        first_digit,
                        min(len(next_path), 4),
                    )
                    if state_key in visited:
                        continue
                    visited.add(state_key)
                    if len(next_path) >= 4 and neighbor.id > start.id:
                        evaluate(next_path, next_links)
                    queue.append((next_path, next_links))
        if searched_states > max_search_states:
            break

    return _deduplicate(results)[:max_results]


def _petals_for_stem(graph, stem: Cell, digit: int) -> tuple[ALS, ...]:
    return tuple(
        als
        for als in graph.als_nodes
        if stem not in als.cells
        and digit in als.candidates
        and all(
            cell in peers(*stem)
            for cell in graph.occurrences(als, digit)
        )
    )


def find_death_blossoms(
    graph,
    *,
    max_results: int = DEFAULT_MAX_RAW_RESULTS,
) -> tuple[ALSDeduction, ...]:
    """Cerca stem e un petal ALS per ognuno dei candidati della stem."""

    results = []
    max_results = max(1, int(max_results))
    max_search_states = max(32_768, max_results * 64)
    searched_states = 0

    for row in range(9):
        for column in range(9):
            stem = (row, column)
            stem_digits = frozenset(graph.state.candidates[row][column])
            if len(stem_digits) < 2:
                continue
            options = {
                digit: _petals_for_stem(graph, stem, digit)
                for digit in sorted(stem_digits)
            }
            if any(not values for values in options.values()):
                continue
            ordered_digits = tuple(sorted(
                stem_digits,
                key=lambda digit: (len(options[digit]), digit),
            ))

            def visit(index, selected, common_digits):
                nonlocal searched_states
                searched_states += 1
                if searched_states > max_search_states:
                    return
                if len(results) >= max_results:
                    return
                if index == len(ordered_digits):
                    petals = tuple(dict.fromkeys(selected))
                    union_cells = _outside_union(petals) | {stem}
                    for endpoint in sorted(common_digits - stem_digits):
                        eliminations = graph.targets_for_alses(
                            endpoint,
                            petals,
                            excluded_cells=union_cells,
                        )
                        if eliminations:
                            by_id = {als.id: als for als in petals}
                            results.append(ALSDeduction(
                                technique_id="als.death_blossom",
                                als_nodes=tuple(
                                    by_id[als_id] for als_id in sorted(by_id)
                                ),
                                rccs=(),
                                eliminations=eliminations,
                                endpoint_digit=endpoint,
                                stem_cell=stem,
                                stem_links=tuple(sorted(
                                    (digit, als.id)
                                    for digit, als in zip(ordered_digits, selected)
                                )),
                                stem_link_occurrences=tuple(sorted(
                                    (
                                        digit,
                                        als.id,
                                        graph.occurrences(als, digit),
                                    )
                                    for digit, als in zip(ordered_digits, selected)
                                )),
                            ))
                    return

                digit = ordered_digits[index]
                for petal in options[digit]:
                    next_common = (
                        set(petal.candidates)
                        if common_digits is None
                        else common_digits & petal.candidates
                    )
                    if not (next_common - stem_digits):
                        continue
                    visit(
                        index + 1,
                        selected + (petal,),
                        frozenset(next_common),
                    )
                    if len(results) >= max_results:
                        return

            visit(0, (), None)
            if searched_states > max_search_states:
                return _deduplicate(results)
            if len(results) >= max_results:
                return _deduplicate(results)
    return _deduplicate(results)


def _deduplicate(deductions: Iterable[ALSDeduction]) -> tuple[ALSDeduction, ...]:
    buckets = {}
    for deduction in deductions:
        signature = (
            deduction.technique_id,
            tuple(sorted(deduction.eliminations)),
        )
        existing = buckets.get(signature)
        if existing is None:
            buckets[signature] = deduction
        else:
            existing_size = len(existing.als_nodes) + len(existing.rccs)
            current_size = len(deduction.als_nodes) + len(deduction.rccs)
            representative = deduction if current_size < existing_size else existing
            buckets[signature] = replace(
                representative,
                equivalent_pattern_count=(
                    existing.equivalent_pattern_count
                    + deduction.equivalent_pattern_count
                ),
            )
    return tuple(sorted(
        buckets.values(),
        key=lambda item: (
            item.technique_id,
            tuple(sorted(item.eliminations)),
            tuple(als.id for als in item.als_nodes),
        ),
    ))


def find_all_als(
    state,
    *,
    max_cells: int = DEFAULT_MAX_ALS_CELLS,
    max_chain_alses: int = DEFAULT_MAX_CHAIN_ALSES,
    max_results: int = DEFAULT_MAX_RAW_RESULTS,
) -> tuple[ALSDeduction, ...]:
    """Esegue una sola enumerazione e condivide il medesimo grafo RCC."""

    graph = ALSGraph(state, enumerate_als(state, max_cells=max_cells))
    producers = (
        find_als_xz(graph),
        find_als_xy_wings(graph),
        find_als_chains(
            graph,
            max_alses=max_chain_alses,
            max_results=max_results,
        ),
        find_death_blossoms(graph, max_results=max_results),
    )
    return _deduplicate(
        deduction
        for group in producers
        for deduction in group
    )[:max_results]


__all__ = [
    "ALS",
    "ALSDeduction",
    "Candidate",
    "Cell",
    "DEFAULT_MAX_ALS_CELLS",
    "DEFAULT_MAX_CHAIN_ALSES",
    "GENERALIZED_WING_IDS",
    "RCC",
    "enumerate_als",
    "find_all_als",
    "find_als_chains",
    "find_als_xy_wings",
    "find_als_xz",
    "find_death_blossoms",
]
