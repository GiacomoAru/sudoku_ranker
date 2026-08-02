"""Grafo degli Almost Locked Set e dei loro RCC.

Il modulo contiene soltanto la relazione strutturale fra ALS.  Enumerazione,
tecniche e classificazione restano in :mod:`sudoku_app.core.als`, così ogni
consumer usa la stessa definizione autorevole di Restricted Common Candidate.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from itertools import combinations
from typing import Iterable

from .data_structure import peers
from .als_nodes import ALSNode


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


class ALSImplicationGraph:
    """Estensione tipizzata del grafo statico con proposizioni ALS.

    Il grafo candidato di P12 resta autorevole per X/Y. Questa vista aggiunge
    soltanto i link ALS, senza duplicare o modificare il grafo memorizzato in
    cache: puo' quindi essere usata da detector diversi con budget propri.
    """

    WEAK_REASONS = frozenset({"peer", "y", "als-weak", "als-rcc"})
    ALL_REASONS = frozenset({
        "peer", "x", "y", "als-weak", "als-rcc", "als-strong",
    })

    def __init__(
        self,
        graph: ALSGraph,
        *,
        require_multicell: bool = True,
        max_alses: int = 64,
    ):
        from . import logic_engine

        self.als_graph = graph
        self.state = graph.state
        self.base_graph = logic_engine.static_implication_graph(graph.state)
        eligible_alses = tuple(sorted((
            als
            for als in graph.als_nodes
            if not require_multicell or len(als.cells) >= 2
        ), key=lambda als: (
            len(als.cells),
            tuple(sorted(als.cells)),
            tuple(sorted(als.candidates)),
        )))
        max_alses = max(1, int(max_alses))
        selected_alses = eligible_alses[:max_alses]
        self.search_truncated = len(selected_alses) < len(eligible_alses)
        self.als_nodes = tuple(
            ALSNode.from_als(als, graph.state, digit)
            for als in selected_alses
            for digit in sorted(als.candidates)
        )
        self.by_als_digit = {
            (node.als_id, node.digit): node for node in self.als_nodes
        }

        raw = defaultdict(dict)

        def add_edge(
            source,
            target,
            reason,
            *,
            support_candidates=(),
            support_house_ids=(),
        ):
            support = raw[source].setdefault(
                (target, reason),
                {"candidates": set(), "houses": set()},
            )
            support["candidates"].update(support_candidates)
            support["houses"].update(support_house_ids)

        for source, edges in self.base_graph.adjacency.items():
            for edge in edges:
                add_edge(
                    source,
                    edge.target,
                    edge.reason,
                    support_candidates=edge.support_candidates,
                    support_house_ids=edge.support_house_ids,
                )

        # Se una cifra dell'ALS e' falsa, tutte le altre cifre dell'ALS sono
        # vere almeno una volta: N celle rimangono con esattamente N cifre.
        for als in selected_alses:
            support = tuple(sorted(
                (row, column, digit)
                for row, column in als.cells
                for digit in self.state.candidates[row][column]
                if digit in als.candidates
            ))
            for first_digit in sorted(als.candidates):
                first = self.by_als_digit[(als.id, first_digit)]
                for second_digit in sorted(als.candidates - {first_digit}):
                    second = self.by_als_digit[(als.id, second_digit)]
                    add_edge(
                        logic_engine._node_literal(first, False),
                        logic_engine._node_literal(second, True),
                        "als-strong",
                        support_candidates=support,
                        support_house_ids=(als.house_id,),
                    )

        # Gli RCC sono weak link fra due proposizioni ALS della stessa cifra.
        for rcc in graph.rccs:
            first = self.by_als_digit.get((rcc.left_als_id, rcc.digit))
            second = self.by_als_digit.get((rcc.right_als_id, rcc.digit))
            if first is None or second is None:
                continue
            house_ids = self.base_graph._visibility_house_ids(first, second)
            add_edge(
                logic_engine._node_literal(first, True),
                logic_engine._node_literal(second, False),
                "als-rcc",
                support_candidates=rcc.support_candidates,
                support_house_ids=house_ids,
            )
            add_edge(
                logic_engine._node_literal(second, True),
                logic_engine._node_literal(first, False),
                "als-rcc",
                support_candidates=rcc.support_candidates,
                support_house_ids=house_ids,
            )

        candidates_by_digit = defaultdict(list)
        for candidate in self.base_graph.all_candidates:
            candidates_by_digit[candidate[2]].append(candidate)
        for node in self.als_nodes:
            for candidate in candidates_by_digit[node.digit]:
                if not self.base_graph._node_visibility(node, candidate):
                    continue
                support = (*node.candidates, candidate)
                house_ids = self.base_graph._visibility_house_ids(
                    node, candidate
                )
                add_edge(
                    logic_engine._node_literal(node, True),
                    logic_engine._node_literal(candidate, False),
                    "als-weak",
                    support_candidates=support,
                    support_house_ids=house_ids,
                )
                add_edge(
                    logic_engine._node_literal(candidate, True),
                    logic_engine._node_literal(node, False),
                    "als-weak",
                    support_candidates=support,
                    support_house_ids=house_ids,
                )

        self.adjacency = {
            source: tuple(
                logic_engine.Edge(
                    target=target,
                    reason=reason,
                    support_candidates=tuple(sorted(support["candidates"])),
                    support_house_ids=tuple(sorted(support["houses"])),
                )
                for (target, reason), support in sorted(
                    targets.items(),
                    key=lambda item: (
                        logic_engine._graph_literal_key(item[0][0]),
                        item[0][1],
                    ),
                )
            )
            for source, targets in raw.items()
        }
        self.nodes = tuple(sorted(
            (*self.base_graph.all_candidates, *self.als_nodes),
            key=logic_engine._node_key,
        ))

    def edges(self, source, allowed=ALL_REASONS):
        allowed = frozenset(allowed)
        return tuple(
            edge for edge in self.adjacency.get(source, ())
            if edge.reason in allowed
        )

    def edge(self, source, target, reason):
        return next((
            edge
            for edge in self.adjacency.get(source, ())
            if edge.target == target and edge.reason == reason
        ), None)

    def weak_reason(self, first, second):
        from . import logic_engine
        source = logic_engine._node_literal(first, True)
        target = logic_engine._node_literal(second, False)
        for reason in sorted(self.WEAK_REASONS):
            if self.edge(source, target, reason) is not None:
                return reason
        return None

    def shortest_path(
        self,
        source,
        target,
        *,
        allowed=ALL_REASONS,
        minimum_edges=1,
        maximum_edges=14,
        require_als=True,
        require_candidate=True,
        max_states=32_768,
    ):
        from . import logic_engine

        self.last_search_truncated = False
        start_node = logic_engine._literal_node(source)
        start_state = (
            source,
            isinstance(start_node, ALSNode),
            not isinstance(start_node, ALSNode),
        )
        queue = deque([(start_state, 0)])
        parent = {start_state: None}
        parent_reason = {}

        while queue and len(parent) <= max_states:
            (current, used_als, used_candidate), depth = queue.popleft()
            if (
                current == target
                and depth >= minimum_edges
                and (used_als or not require_als)
                and (used_candidate or not require_candidate)
            ):
                states = []
                cursor = (current, used_als, used_candidate)
                while cursor is not None:
                    states.append(cursor)
                    cursor = parent[cursor]
                states.reverse()
                return (
                    [state[0] for state in states],
                    [parent_reason[state] for state in states[1:]],
                )
            if maximum_edges is not None and depth >= maximum_edges:
                continue
            for edge in self.edges(current, allowed):
                node = logic_engine._literal_node(edge.target)
                next_state = (
                    edge.target,
                    used_als or isinstance(node, ALSNode),
                    used_candidate or not isinstance(node, ALSNode),
                )
                if next_state in parent:
                    continue
                parent[next_state] = (current, used_als, used_candidate)
                parent_reason[next_state] = edge.reason
                queue.append((next_state, depth + 1))
        self.last_search_truncated = bool(queue)
        return None

    def chain_supports(self, literals, reasons):
        if len(reasons) != len(literals) - 1:
            raise ValueError("Numero di archi ALS-AIC incoerente.")
        result = []
        for source, target, reason in zip(literals, literals[1:], reasons):
            edge = self.edge(source, target, reason)
            if edge is None:
                raise ValueError("La ALS-AIC contiene un arco non validato.")
            result.append({
                "support_candidates": edge.support_candidates,
                "support_house_ids": edge.support_house_ids,
            })
        return tuple(result)


__all__ = [
    "ALSGraph",
    "ALSImplicationGraph",
    "Candidate",
    "Cell",
    "RCC",
    "restricted_common_candidates",
]
