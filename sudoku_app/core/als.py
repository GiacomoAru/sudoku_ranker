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

from .als_graph import ALSGraph, ALSImplicationGraph, RCC
from .als_nodes import ALSNode
from .data_structure import UNITS, peers
from . import search_config


Cell = tuple[int, int]
Candidate = tuple[int, int, int]

DEFAULT_MAX_ALS_CELLS = 8
DEFAULT_MAX_CHAIN_ALSES = search_config.LIMITED_SEARCH_LIMITS.als_chain_alses
DEFAULT_MAX_RAW_RESULTS = search_config.LIMITED_SEARCH_LIMITS.als_results
DEFAULT_MAX_AIC_ALSES = search_config.LIMITED_SEARCH_LIMITS.als_aic_alses
DEFAULT_MAX_AIC_SEARCH_ATTEMPTS = (
    search_config.LIMITED_SEARCH_LIMITS.als_aic_attempts
)
DEFAULT_MAX_AIC_PATH_STATES = (
    search_config.LIMITED_SEARCH_LIMITS.als_aic_path_states
)

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
        if evidence_id is not None:
            dag.nodes[evidence_id].payload["rcc_count"] = (
                len(self.rccs) + len(self.stem_links)
            )
        return {
            "kind": self.technique_id,
            "proof_dag": dag.to_dict(),
            "als_node_count": len(self.als_nodes),
            "rcc_count": len(self.rccs) + len(self.stem_links),
        }


@dataclass(frozen=True, slots=True)
class ALSAICDeduction:
    """AIC mista costruita sul grafo CandidateNode/ALSNode."""

    technique_id: str
    als_nodes: tuple[ALS, ...]
    rccs: tuple[RCC, ...]
    eliminations: frozenset[Candidate]
    chains: tuple[tuple[object, ...], ...]
    chain_reasons: tuple[tuple[str, ...], ...]
    chain_supports: tuple[tuple[dict, ...], ...]
    equivalent_pattern_count: int = 1
    endpoint_digit: int | None = None
    stem_cell: Cell | None = None
    stem_links: tuple = ()
    stem_link_occurrences: tuple = ()
    parent_technique_id: str | None = "se.forcing_chain"
    search_truncated: bool = False
    search_attempt_count: int = 0
    search_budget: tuple[int, int, int] = (
        DEFAULT_MAX_AIC_ALSES,
        DEFAULT_MAX_AIC_SEARCH_ATTEMPTS,
        DEFAULT_MAX_AIC_PATH_STATES,
    )

    def __post_init__(self):
        if self.technique_id != "chain.als_aic":
            raise ValueError("ALSAICDeduction richiede chain.als_aic.")
        if not self.als_nodes or not any(
            len(als.cells) >= 2 for als in self.als_nodes
        ):
            raise ValueError("Una ALS-AIC richiede almeno un ALS multicella.")
        if not self.eliminations or not self.chains:
            raise ValueError("Una ALS-AIC deve avere prova e conclusione.")
        if len(self.chains) != len(self.chain_reasons):
            raise ValueError("Catene e motivi ALS-AIC non coincidono.")
        for chain, reasons in zip(self.chains, self.chain_reasons):
            if len(reasons) != len(chain) - 1:
                raise ValueError("Numero di archi ALS-AIC non valido.")
            structured = [
                literal[0]
                for literal in chain
                if isinstance(literal, tuple)
                and len(literal) == 2
                and isinstance(literal[0], ALSNode)
            ]
            candidates = [
                literal for literal in chain
                if isinstance(literal, tuple) and len(literal) == 4
            ]
            if not structured or not candidates:
                raise ValueError("Una ALS-AIC deve essere realmente mista.")

    @property
    def primary_cells(self) -> tuple[Cell, ...]:
        cells = set().union(*(als.cells for als in self.als_nodes))
        cells.update((row, column) for row, column, _ in self.eliminations)
        return tuple(sorted(cells))

    @property
    def als_parent_technique_id(self) -> str:
        return "se.forcing_chain"

    def to_dict(self) -> dict:
        from .proof import literal_record
        return {
            "technique_id": self.technique_id,
            "als_parent_technique_id": self.als_parent_technique_id,
            "als_nodes": [als.to_dict() for als in self.als_nodes],
            "rccs": [rcc.to_dict() for rcc in self.rccs],
            "eliminations": [list(item) for item in sorted(self.eliminations)],
            "chains": [
                [literal_record(literal) for literal in chain]
                for chain in self.chains
            ],
            "equivalent_pattern_count": self.equivalent_pattern_count,
            "search": {
                "truncated": self.search_truncated,
                "attempt_count": self.search_attempt_count,
                "max_alses": self.search_budget[0],
                "max_endpoint_attempts": self.search_budget[1],
                "max_path_states": self.search_budget[2],
            },
        }

    def proof_payload(self) -> dict:
        from .proof import ProofDAG
        dag = ProofDAG.from_chains(
            assumptions=tuple(chain[0] for chain in self.chains),
            chains=self.chains,
            chain_reasons=self.chain_reasons,
            chain_supports=self.chain_supports,
            proof_kind="als-endpoint-aic",
            eliminations=self.eliminations,
        )
        return {
            "kind": "als-endpoint-aic",
            "proof_dag": dag.to_dict(),
            "search": {
                "truncated": self.search_truncated,
                "attempt_count": self.search_attempt_count,
                "max_alses": self.search_budget[0],
                "max_endpoint_attempts": self.search_budget[1],
                "max_path_states": self.search_budget[2],
            },
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
    max_search_states: int | None = (
        search_config.LIMITED_SEARCH_LIMITS.als_chain_states
    ),
    truncated_out: list | None = None,
) -> tuple[ALSDeduction, ...]:
    """Cammini ALS-RCC puri, classificati sempre come ALS Chain."""

    from collections import deque

    if max_alses is None:
        max_alses = max(4, len(graph.als_nodes))
    else:
        max_alses = max(4, int(max_alses))
    if max_results is not None:
        max_results = max(1, int(max_results))
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
        technique_id = "als.chain"
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
            if (
                max_search_states is not None
                and searched_states > max_search_states
            ):
                if truncated_out is not None:
                    truncated_out.append("als_chain_max_search_states")
                break
            if len(path) >= max_alses:
                if truncated_out is not None and any(
                    neighbor not in path
                    for neighbor in graph.neighbors(path[-1])
                ):
                    truncated_out.append("als_chain_max_alses")
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
        if (
            max_search_states is not None
            and searched_states > max_search_states
        ):
            break

    deductions = _deduplicate(results)
    if (
        max_results is not None
        and len(deductions) > max_results
        and truncated_out is not None
    ):
        truncated_out.append("als_chain_result_limit")
    return deductions if max_results is None else deductions[:max_results]


def find_als_aics(
    graph,
    *,
    max_results: int = 32,
    max_alses: int = DEFAULT_MAX_AIC_ALSES,
    max_search_attempts: int = DEFAULT_MAX_AIC_SEARCH_ATTEMPTS,
    max_path_states: int = DEFAULT_MAX_AIC_PATH_STATES,
    max_path_edges: int | None = (
        search_config.LIMITED_SEARCH_LIMITS.als_aic_path_edges
    ),
    truncated_out: list | None = None,
) -> tuple[ALSAICDeduction, ...]:
    """Cerca AIC miste con almeno un vero ALSNode multicella.

    Se ``truncated_out`` e' una lista, vi vengono aggiunti codici stabili
    per il limite di ALS, i tentativi, gli stati, la lunghezza dei cammini e
    il numero di risultati. Le cause sono disponibili anche senza deduzioni.
    """

    from . import logic_engine

    if max_results is not None:
        max_results = max(1, int(max_results))
    implication = ALSImplicationGraph(
        graph,
        require_multicell=True,
        max_alses=max_alses,
    )
    if implication.search_truncated and truncated_out is not None:
        truncated_out.append("als_aic_max_alses")
    if not implication.als_nodes:
        return ()

    results = []
    seen = set()
    allowed = implication.ALL_REASONS
    search_attempts = 0
    path_search_truncated = False

    def finalized(*, truncated=False):
        budget = (max_alses, max_search_attempts, max_path_states)
        return _deduplicate(
            replace(
                deduction,
                search_truncated=bool(
                    truncated
                    or implication.search_truncated
                    or path_search_truncated
                ),
                search_attempt_count=search_attempts,
                search_budget=budget,
            )
            for deduction in results
        )

    for target in implication.base_graph.all_candidates:
        target_on = logic_engine._node_literal(target, True)
        weak_nodes = tuple(sorted({
            logic_engine._literal_node(edge.target)
            for edge in implication.edges(
                target_on, implication.WEAK_REASONS
            )
            if not logic_engine.proof_model.literal_state(edge.target)
        }, key=logic_engine._node_key))
        if len(weak_nodes) < 2:
            continue

        for unordered in combinations(weak_nodes, 2):
            if not any(isinstance(node, ALSNode) for node in unordered):
                continue
            for first, second in (unordered, tuple(reversed(unordered))):
                if (
                    max_search_attempts is not None
                    and search_attempts >= max_search_attempts
                ):
                    if truncated_out is not None:
                        truncated_out.append("als_aic_max_search_attempts")
                    return finalized(truncated=True)
                search_attempts += 1
                path_data = implication.shortest_path(
                    logic_engine._node_literal(first, False),
                    logic_engine._node_literal(second, True),
                    allowed=allowed,
                    minimum_edges=3,
                    maximum_edges=max_path_edges,
                    require_als=True,
                    require_candidate=True,
                    max_states=max_path_states,
                )
                path_search_truncated = (
                    path_search_truncated
                    or implication.last_search_truncated
                )
                if truncated_out is not None:
                    truncated_out.extend(sorted(
                        implication.last_search_truncated_reasons
                    ))
                if path_data is None:
                    continue
                central, central_reasons = path_data
                central_nodes = [
                    logic_engine._literal_node(literal)
                    for literal in central
                ]
                if len(set(central_nodes)) != len(central_nodes):
                    continue
                if not any(isinstance(node, ALSNode) for node in central_nodes):
                    continue
                if not any(
                    not isinstance(node, ALSNode) for node in central_nodes
                ):
                    continue

                left_reason = implication.weak_reason(target, first)
                right_reason = implication.weak_reason(second, target)
                if left_reason is None or right_reason is None:
                    continue
                chain = (
                    logic_engine._node_literal(target, True),
                    *central,
                    logic_engine._node_literal(target, False),
                )
                reasons = (
                    left_reason,
                    *central_reasons,
                    right_reason,
                )
                try:
                    supports = implication.chain_supports(chain, reasons)
                except ValueError:
                    continue

                als_ids = tuple(dict.fromkeys(
                    node.als_id
                    for node in central_nodes
                    if isinstance(node, ALSNode)
                ))
                alses = tuple(graph.by_id[als_id] for als_id in als_ids)
                rccs = []
                for source, destination, reason in zip(
                    central, central[1:], central_reasons
                ):
                    if reason != "als-rcc":
                        continue
                    left = logic_engine._literal_node(source)
                    right = logic_engine._literal_node(destination)
                    rccs.extend(
                        rcc for rcc in graph.between(left.als_id, right.als_id)
                        if rcc.digit == left.digit == right.digit
                    )

                signature = target, tuple(
                    logic_engine._graph_literal_key(item) for item in central
                )
                if signature in seen:
                    continue
                seen.add(signature)
                results.append(ALSAICDeduction(
                    technique_id="chain.als_aic",
                    als_nodes=alses,
                    rccs=tuple(dict.fromkeys(rccs)),
                    eliminations=frozenset({target}),
                    chains=(tuple(chain),),
                    chain_reasons=(tuple(reasons),),
                    chain_supports=(tuple(supports),),
                    endpoint_digit=target[2],
                ))
                if max_results is not None and len(results) >= max_results:
                    if truncated_out is not None:
                        truncated_out.append("als_aic_result_limit")
                    return finalized(truncated=True)

    return finalized()


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
    max_search_states: int | None = (
        search_config.LIMITED_SEARCH_LIMITS.als_death_blossom_states
    ),
    truncated_out: list | None = None,
) -> tuple[ALSDeduction, ...]:
    """Cerca stem e un petal ALS per ognuno dei candidati della stem."""

    results = []
    if max_results is not None:
        max_results = max(1, int(max_results))
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
                if (
                    max_search_states is not None
                    and searched_states > max_search_states
                ):
                    if truncated_out is not None:
                        truncated_out.append(
                            "als_death_blossom_max_search_states"
                        )
                    return
                if max_results is not None and len(results) >= max_results:
                    if truncated_out is not None:
                        truncated_out.append(
                            "als_death_blossom_result_limit"
                        )
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
                    if max_results is not None and len(results) >= max_results:
                        return

            visit(0, (), None)
            if (
                max_search_states is not None
                and searched_states > max_search_states
            ):
                return _deduplicate(results)
            if max_results is not None and len(results) >= max_results:
                if truncated_out is not None:
                    truncated_out.append(
                        "als_death_blossom_result_limit"
                    )
                return _deduplicate(results)
    return _deduplicate(results)


def _deduplicate(deductions: Iterable) -> tuple:
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
    max_chain_states: int | None = (
        search_config.LIMITED_SEARCH_LIMITS.als_chain_states
    ),
    max_results: int = DEFAULT_MAX_RAW_RESULTS,
    max_aic_alses: int | None = DEFAULT_MAX_AIC_ALSES,
    max_aic_attempts: int | None = DEFAULT_MAX_AIC_SEARCH_ATTEMPTS,
    max_aic_path_states: int | None = DEFAULT_MAX_AIC_PATH_STATES,
    max_aic_path_edges: int | None = (
        search_config.LIMITED_SEARCH_LIMITS.als_aic_path_edges
    ),
    max_death_blossom_states: int | None = (
        search_config.LIMITED_SEARCH_LIMITS.als_death_blossom_states
    ),
    truncated_out: list | None = None,
) -> tuple:
    """Esegue una sola enumerazione e condivide il medesimo grafo RCC.

    Se ``truncated_out`` e' una lista, raccoglie uniformemente le cause di
    troncamento di ALS Chain, ALS-AIC, Death Blossom e del limite finale di
    inventario, anche quando nessun produttore restituisce deduzioni.
    """

    graph = ALSGraph(state, enumerate_als(state, max_cells=max_cells))
    truncated_reasons = []
    producers = (
        find_als_xz(graph),
        find_als_xy_wings(graph),
        find_als_chains(
            graph,
            max_alses=max_chain_alses,
            max_results=max_results,
            max_search_states=max_chain_states,
            truncated_out=truncated_reasons,
        ),
        find_als_aics(
            graph,
            max_results=(
                None if max_results is None else min(max_results, 32)
            ),
            max_alses=max_aic_alses,
            max_search_attempts=max_aic_attempts,
            max_path_states=max_aic_path_states,
            max_path_edges=max_aic_path_edges,
            truncated_out=truncated_reasons,
        ),
        find_death_blossoms(
            graph,
            max_results=max_results,
            max_search_states=max_death_blossom_states,
            truncated_out=truncated_reasons,
        ),
    )
    deductions = _deduplicate(
        deduction
        for group in producers
        for deduction in group
    )
    if max_results is not None and len(deductions) > max_results:
        truncated_reasons.append("als_result_limit")
    if truncated_out is not None:
        truncated_out.extend(sorted(set(truncated_reasons)))
    return deductions if max_results is None else deductions[:max_results]


__all__ = [
    "ALS",
    "ALSAICDeduction",
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
    "find_als_aics",
    "find_als_xy_wings",
    "find_als_xz",
    "find_death_blossoms",
]
