"""Motore logico per catene, cicli e forcing del solver Sudoku.

Il modulo lavora sui *letterali candidato* ``(riga, colonna, valore, stato)``:
``stato=True`` significa che il candidato e' assunto vero, ``False`` che e'
assunto falso. Le implicazioni statiche sono di due tipi:

* X: stesso valore in celle che si vedono;
* Y: valori diversi nella stessa cella.

Le propagazioni dinamiche applicano le esclusioni a una copia locale dei
candidati e scoprono nuovi single. I livelli Plus aggiungono locking, coppie
e X-Wing. Il Complete Forcing Tree usa invece una ricerca ricorsiva completa
per casi, senza troncare profondita', nodi o rami. I limiti di presentazione
non modificano la prova autorevole. Nessuna funzione modifica lo
``SudokuState`` ricevuto.

L'API pubblica e' intenzionalmente piccola: ``find_logic_deductions``
restituisce deduzioni neutrali. ``sudoku_app.core.techniques`` le converte nel
formato Move usato dal resto del progetto.
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict, deque
from copy import deepcopy
from dataclasses import dataclass
from itertools import chain, combinations
from threading import RLock

from .data_structure import UNITS, UNIT_KINDS, peers
from .group_nodes import GroupNode
from . import proof as proof_model
from . import proof_schema


Candidate = tuple[int, int, int]
Literal = tuple[int, int, int, bool]
ImplicationNode = Candidate | GroupNode
GroupLiteral = tuple[GroupNode, bool]
GraphLiteral = Literal | GroupLiteral

# Limiti espliciti di output e delle viste lineari.
MAX_DEDUCTIONS_PER_TECHNIQUE = 16 # limite massimo non valicabile
MAX_NESTED_DEDUCTIONS = 2 # limite massimo non valicabile
MAX_COMPLETE_TREE_DEDUCTIONS = 1 # limite massimo non valicabile
MAX_STATIC_CYCLE_EDGES = 16
STORE_COMPLETE_FORCING_TREE_PROOF = False

if not (
    1
    <= MAX_COMPLETE_TREE_DEDUCTIONS
    <= MAX_NESTED_DEDUCTIONS
    <= MAX_DEDUCTIONS_PER_TECHNIQUE
):
    raise ValueError(
        "I limiti devono rispettare: Complete Tree <= Nested <= generale."
    )

DEFAULT_MAX_DEDUCTIONS_PER_TECHNIQUE = MAX_DEDUCTIONS_PER_TECHNIQUE

# Alias mantenuti per compatibilita' con eventuali import esistenti.
MAX_TECHNIQUES = MAX_DEDUCTIONS_PER_TECHNIQUE
MAX_NESTED_TECHNIQUES = MAX_NESTED_DEDUCTIONS
MAX_COMPLETE_TREE_TECHNIQUES = MAX_COMPLETE_TREE_DEDUCTIONS

_NESTED_TECHNIQUE = "Nested Forcing Chain"
_COMPLETE_TREE_TECHNIQUE = "Complete Forcing Tree"


# Le tecniche restano raggruppate per le preparazioni esplicite di batch.
# Una richiesta ordinaria calcola però soltanto la tecnica necessaria; grafi,
# closure e propagazioni già richieste vengono riutilizzati nello stesso stato.
LOGIC_TECHNIQUE_BATCHES = {
    "static": (
        "Bidirectional X-Cycle",
        "XY-Chain",
        "Bidirectional Y-Cycle",
        "Forcing X-Chain",
        "Forcing Chain",
        "AIC",
        "Bidirectional Cycle",
        "Grouped Chain",
    ),
    "multiple": (
        "Nishio",
        "Cell Forcing Chain",
        "Region Forcing Chain",
    ),
    "dynamic": (
        "Dynamic Forcing Chain",
        "Dynamic Forcing Chain Plus",
    ),
    "nested": (
        "Nested Forcing Chain",
    ),
    "complete_tree": (
        "Complete Forcing Tree",
    ),
}

_LOGIC_TECHNIQUE_TO_BATCH = {
    technique: batch
    for batch, techniques in LOGIC_TECHNIQUE_BATCHES.items()
    for technique in techniques
}

_LOGIC_TECHNIQUE_ORDER = tuple(
    technique
    for batch in ("static", "multiple", "dynamic")
    for technique in LOGIC_TECHNIQUE_BATCHES[batch]
)

_UNITS_BY_CELL: dict[tuple[int, int], tuple[int, ...]] = {}
for _unit_index, _unit in enumerate(UNITS):
    for _cell in _unit:
        _UNITS_BY_CELL.setdefault(_cell, []).append(_unit_index)
_UNITS_BY_CELL = {
    cell: tuple(indexes) for cell, indexes in _UNITS_BY_CELL.items()
}

_UNIT_INDEXES = tuple(
    tuple(row * 9 + column for row, column in unit)
    for unit in UNITS
)
_PEER_INDEXES = tuple(
    tuple(sorted(
        peer_row * 9 + peer_column
        for peer_row, peer_column in peers(row, column)
    ))
    for row in range(9)
    for column in range(9)
)
_DIGIT_BITS = tuple(1 << value for value in range(1, 10))


def _visible_unit_reference(unit_index):
    """Restituisce nome italiano e indice 1-9 della casa Sudoku."""
    kind = UNIT_KINDS[unit_index]

    if kind == "row":
        return "riga", unit_index + 1
    if kind == "col":
        return "colonna", unit_index - 8
    return "box", unit_index - 17


def _literal(candidate: Candidate, is_on: bool) -> Literal:
    return candidate[0], candidate[1], candidate[2], is_on


def _candidate(literal: Literal) -> Candidate:
    return literal[0], literal[1], literal[2]


def _opposite(literal: Literal) -> Literal:
    return literal[0], literal[1], literal[2], not literal[3]


def _node_literal(node: ImplicationNode, is_on: bool) -> GraphLiteral:
    if isinstance(node, GroupNode):
        return node, bool(is_on)
    return _literal(node, is_on)


def _literal_node(literal: GraphLiteral) -> ImplicationNode:
    if proof_model.is_group_literal(literal):
        return literal[0]
    return _candidate(literal)


def _graph_opposite(literal: GraphLiteral) -> GraphLiteral:
    return _node_literal(_literal_node(literal), not proof_model.literal_state(literal))


def _node_candidates(node: ImplicationNode) -> tuple[Candidate, ...]:
    return node.candidates if isinstance(node, GroupNode) else (node,)


def _node_digit(node: ImplicationNode) -> int:
    return node.digit if isinstance(node, GroupNode) else node[2]


def _node_key(node: ImplicationNode):
    if isinstance(node, GroupNode):
        return (
            1,
            node.digit,
            tuple(sorted(node.cells)),
            node.house_ids,
            node.role,
        )
    return 0, *node


def _graph_literal_key(literal: GraphLiteral):
    return _node_key(_literal_node(literal)) + (
        int(proof_model.literal_state(literal)),
    )


def _candidate_key(candidate: Candidate) -> tuple[int, int, int]:
    return candidate


def _literal_key(literal: Literal) -> tuple[int, int, int, int]:
    return literal[0], literal[1], literal[2], int(literal[3])


def _sees(first: Candidate, second: Candidate) -> bool:
    """True se i candidati uguali appartengono a celle peer distinte."""
    if first[2] != second[2] or first[:2] == second[:2]:
        return False
    return second[:2] in peers(first[0], first[1])


def _conflict_reason(first: Candidate, second: Candidate) -> str | None:
    """Tipo di weak link diretto fra due candidati, se esiste."""
    if first[:2] == second[:2] and first[2] != second[2]:
        return "y"
    if _sees(first, second):
        return "peer"
    return None


def _candidate_map(state) -> dict[tuple[int, int], set[int]]:
    return {
        (row, column): set(state.candidates[row][column])
        for row in range(9)
        for column in range(9)
        if state.grid[row, column] == 0
        and state.candidates[row][column]
    }


def _fingerprint(state) -> tuple:
    grid = tuple(int(state.grid[row, column]) for row in range(9) for column in range(9))
    masks = []
    for row in range(9):
        for column in range(9):
            mask = 0
            for value in state.candidates[row][column]:
                mask |= 1 << value
            masks.append(mask)
    return grid, tuple(masks)


def _literal_record(literal: GraphLiteral) -> dict:
    return proof_model.literal_record(literal)


def _proof(
    kind: str,
    assumptions,
    chains,
    reasons=None,
    chain_reasons=(),
    chain_supports=(),
    *,
    placements=(),
    eliminations=(),
) -> dict:
    dag = proof_model.ProofDAG.from_chains(
        assumptions=assumptions,
        chains=chains,
        reasons=reasons,
        chain_reasons=chain_reasons,
        chain_supports=chain_supports,
        proof_kind=kind,
        placements=placements,
        eliminations=eliminations,
    )
    proof = {
        "schema_version": proof_schema.PROOF_SCHEMA_VERSION,
        "kind": kind,
        "assumptions": [
            _literal_record(item) for item in assumptions
        ],
        "chains": [
            [_literal_record(item) for item in chain]
            for chain in dag.derived_chains()
        ],
        "chain_links": dag.derived_chain_links(),
        "reasons": sorted(set(reasons or ())),
        "proof_dag": dag.to_dict(),
        "dag_digest": dag.digest(),
    }
    proof["metrics"] = proof_schema.normalize_proof_metrics(proof)
    return proof


def _deduction(
    *,
    description: str,
    placements=(),
    eliminations=(),
    assumptions=(),
    chains=(),
    reasons=(),
    chain_reasons=(),
    chain_supports=(),
    kind: str,
) -> dict:
    placements = sorted(set(placements), key=_candidate_key)
    eliminations = sorted(set(eliminations), key=_candidate_key)
    chain_list = [list(chain) for chain in chains if chain]
    primary = sorted({
        cell
        for chain in chain_list
        for literal in chain
        for cell in proof_model.literal_cells(literal)
    } | {
        cell
        for literal in assumptions
        for cell in proof_model.literal_cells(literal)
    })
    return {
        "description": description,
        "placements": placements,
        "eliminations": eliminations,
        "primary": primary,
        "logic": _proof(
            kind,
            assumptions,
            chain_list,
            reasons,
            chain_reasons=chain_reasons,
            chain_supports=chain_supports,
            placements=placements,
            eliminations=eliminations,
        ),
    }


@dataclass(frozen=True)
class Edge:
    target: GraphLiteral
    reason: str  # "peer" (debole), "x" (forte) oppure "y"
    support_candidates: tuple[Candidate, ...] = ()
    support_house_ids: tuple[int, ...] = ()


class StaticImplicationGraph:
    """Grafo delle implicazioni statiche X/Y dello stato corrente."""

    def __init__(self, candidates: dict[tuple[int, int], set[int]]):
        self.candidates = {
            cell: set(values) for cell, values in candidates.items()
        }
        self.all_candidates = sorted(
            (
                (row, column, value)
                for (row, column), values in self.candidates.items()
                for value in values
            ),
            key=_candidate_key,
        )
        adjacency: dict[Literal, dict[tuple[Literal, str], dict[str, set]]] = (
            defaultdict(dict)
        )

        def add_edge(
            source,
            target,
            reason,
            *,
            support_candidates=(),
            support_house_ids=(),
        ):
            support = adjacency[source].setdefault(
                (target, reason),
                {"candidates": set(), "houses": set()},
            )
            support["candidates"].update(support_candidates)
            support["houses"].update(support_house_ids)

        # Collegamenti Y: un candidato ON spegne gli altri nella cella;
        # in una cella bivalue un candidato OFF accende l'altro.
        for (row, column), values in self.candidates.items():
            ordered = sorted(values)
            for value in ordered:
                source = (row, column, value)
                for other in ordered:
                    if other != value:
                        target = (row, column, other)
                        add_edge(
                            _literal(source, True),
                            _literal(target, False),
                            "y",
                            support_candidates=(source, target),
                        )
            if len(ordered) == 2:
                first = (row, column, ordered[0])
                second = (row, column, ordered[1])
                add_edge(
                    _literal(first, False),
                    _literal(second, True),
                    "y",
                    support_candidates=(first, second),
                )
                add_edge(
                    _literal(second, False),
                    _literal(first, True),
                    "y",
                    support_candidates=(first, second),
                )

        # Collegamenti deboli universali: un candidato ON spegne lo stesso
        # valore in tutti i peer. Sono usati sia dalle catene X sia dalle Y.
        available = {
            candidate for candidate in self.all_candidates
        }
        for candidate in self.all_candidates:
            row, column, value = candidate
            for peer_row, peer_column in peers(row, column):
                other = (peer_row, peer_column, value)
                if other in available:
                    house_ids = set(_UNITS_BY_CELL[candidate[:2]]) & set(
                        _UNITS_BY_CELL[other[:2]]
                    )
                    add_edge(
                        _literal(candidate, True),
                        _literal(other, False),
                        "peer",
                        support_candidates=(candidate, other),
                        support_house_ids=house_ids,
                    )

        # Collegamenti X forti: due sole posizioni di un valore in una casa.
        for unit_index, unit in enumerate(UNITS):
            for value in range(1, 10):
                positions = [
                    (row, column, value)
                    for row, column in unit
                    if value in self.candidates.get((row, column), ())
                ]
                if len(positions) == 2:
                    first, second = positions
                    add_edge(
                        _literal(first, False),
                        _literal(second, True),
                        "x",
                        support_candidates=(first, second),
                        support_house_ids=(unit_index,),
                    )
                    add_edge(
                        _literal(second, False),
                        _literal(first, True),
                        "x",
                        support_candidates=(first, second),
                        support_house_ids=(unit_index,),
                    )

        self.adjacency = {
            source: tuple(
                Edge(
                    target,
                    reason,
                    tuple(sorted(support["candidates"])),
                    tuple(sorted(support["houses"])),
                )
                for (target, reason), support in sorted(
                    targets.items(),
                    key=lambda item: (
                        _literal_key(item[0][0]),
                        item[0][1],
                    ),
                )
            )
            for source, targets in adjacency.items()
        }
        self.group_nodes: tuple[GroupNode, ...] = ()
        self.grouped_adjacency = None

    @staticmethod
    def _node_visibility(first: ImplicationNode, second: ImplicationNode):
        if _node_digit(first) != _node_digit(second):
            return False
        first_cells = {candidate[:2] for candidate in _node_candidates(first)}
        second_cells = {
            candidate[:2] for candidate in _node_candidates(second)
        }
        if first_cells & second_cells:
            return False
        return all(
            right in peers(*left)
            for left in first_cells
            for right in second_cells
        )

    @staticmethod
    def _visibility_house_ids(
        first: ImplicationNode,
        second: ImplicationNode,
    ):
        house_ids = set()
        for left in _node_candidates(first):
            for right in _node_candidates(second):
                house_ids.update(
                    set(_UNITS_BY_CELL[left[:2]])
                    & set(_UNITS_BY_CELL[right[:2]])
                )
        return tuple(sorted(house_ids))

    def _ensure_grouped_adjacency(self):
        if self.grouped_adjacency is not None:
            return

        potential_groups = {}
        for digit in range(1, 10):
            for line_id in range(18):
                line = set(UNITS[line_id])
                for box_id in range(18, 27):
                    segment = line & set(UNITS[box_id])
                    cells = frozenset(
                        cell
                        for cell in segment
                        if digit in self.candidates.get(cell, ())
                    )
                    if len(cells) < 2:
                        continue
                    role = (
                        "row-segment" if line_id < 9 else "column-segment"
                    )
                    node = GroupNode(
                        digit=digit,
                        cells=cells,
                        house_ids=tuple(
                            house_id
                            for house_id, unit in enumerate(UNITS)
                            if cells <= set(unit)
                        ),
                        role=role,
                    )
                    potential_groups[(digit, cells)] = node

        strong_specs = set()
        for house_id, unit in enumerate(UNITS):
            unit_cells = set(unit)
            for digit in range(1, 10):
                positions = frozenset(
                    cell
                    for cell in unit_cells
                    if digit in self.candidates.get(cell, ())
                )
                if len(positions) < 3:
                    continue
                for (group_digit, cells), group in potential_groups.items():
                    if group_digit != digit or not cells < positions:
                        continue
                    other_cells = positions - cells
                    if len(other_cells) == 1:
                        row, column = next(iter(other_cells))
                        other: ImplicationNode = (row, column, digit)
                    else:
                        other = potential_groups.get((digit, other_cells))
                        if other is None:
                            continue
                    ordered = tuple(sorted((group, other), key=_node_key))
                    strong_specs.add((ordered[0], ordered[1], house_id))

        raw: dict[
            GraphLiteral,
            dict[tuple[GraphLiteral, str], dict[str, set]],
        ] = defaultdict(dict)

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

        for source, edges in self.adjacency.items():
            for edge in edges:
                add_edge(
                    source,
                    edge.target,
                    edge.reason,
                    support_candidates=edge.support_candidates,
                    support_house_ids=edge.support_house_ids,
                )

        for first, second, house_id in strong_specs:
            support_candidates = (
                *_node_candidates(first),
                *_node_candidates(second),
            )
            add_edge(
                _node_literal(first, False),
                _node_literal(second, True),
                "group-strong",
                support_candidates=support_candidates,
                support_house_ids=(house_id,),
            )
            add_edge(
                _node_literal(second, False),
                _node_literal(first, True),
                "group-strong",
                support_candidates=support_candidates,
                support_house_ids=(house_id,),
            )

        # Ogni intersezione linea-box con almeno due candidati e' una vera
        # proposizione OR e puo' fungere anche da endpoint di una prova. Non
        # la scartiamo solo perche' nello stato corrente non partecipa a un
        # link forte; gli archi forti restano comunque limitati alle
        # partizioni esatte costruite sopra.
        grouped_nodes = tuple(sorted(potential_groups.values(), key=_node_key))
        candidates_by_digit = {
            digit: tuple(
                candidate
                for candidate in self.all_candidates
                if candidate[2] == digit
            )
            for digit in range(1, 10)
        }
        for group in grouped_nodes:
            for candidate in candidates_by_digit[group.digit]:
                if not self._node_visibility(group, candidate):
                    continue
                support_candidates = (
                    *group.candidates,
                    candidate,
                )
                house_ids = self._visibility_house_ids(group, candidate)
                add_edge(
                    _node_literal(group, True),
                    _node_literal(candidate, False),
                    "group-weak",
                    support_candidates=support_candidates,
                    support_house_ids=house_ids,
                )
                add_edge(
                    _node_literal(candidate, True),
                    _node_literal(group, False),
                    "group-weak",
                    support_candidates=support_candidates,
                    support_house_ids=house_ids,
                )

        for first, second in combinations(grouped_nodes, 2):
            if not self._node_visibility(first, second):
                continue
            support_candidates = (
                *first.candidates,
                *second.candidates,
            )
            house_ids = self._visibility_house_ids(first, second)
            add_edge(
                _node_literal(first, True),
                _node_literal(second, False),
                "group-weak",
                support_candidates=support_candidates,
                support_house_ids=house_ids,
            )
            add_edge(
                _node_literal(second, True),
                _node_literal(first, False),
                "group-weak",
                support_candidates=support_candidates,
                support_house_ids=house_ids,
            )

        self.group_nodes = grouped_nodes
        self.grouped_adjacency = {
            source: tuple(
                Edge(
                    target,
                    reason,
                    tuple(sorted(support["candidates"])),
                    tuple(sorted(support["houses"])),
                )
                for (target, reason), support in sorted(
                    targets.items(),
                    key=lambda item: (
                        _graph_literal_key(item[0][0]),
                        item[0][1],
                    ),
                )
            )
            for source, targets in raw.items()
        }

    def edges(self, source: Literal, allowed: frozenset[str]):
        return (
            edge for edge in self.adjacency.get(source, ())
            if edge.reason in allowed
        )

    def edge(self, source: Literal, target: Literal, reason: str):
        for edge in self.adjacency.get(source, ()):
            if edge.target == target and edge.reason == reason:
                return edge
        return None

    def chain_supports(self, literals, reasons):
        """Supporti autorevoli degli archi di un percorso del grafo."""
        if len(reasons) != len(literals) - 1:
            raise ValueError("Il numero di supporti deve coincidere con gli archi.")
        result = []
        for source, target, reason in zip(literals, literals[1:], reasons):
            edge = self.edge(source, target, reason)
            if edge is None:
                raise ValueError("Il percorso contiene un arco assente dal grafo.")
            result.append({
                "support_candidates": edge.support_candidates,
                "support_house_ids": edge.support_house_ids,
            })
        return tuple(result)

    def grouped_edges(
        self,
        source: GraphLiteral,
        allowed: frozenset[str],
    ):
        self._ensure_grouped_adjacency()
        return (
            edge
            for edge in self.grouped_adjacency.get(source, ())
            if edge.reason in allowed
        )

    def grouped_edge(
        self,
        source: GraphLiteral,
        target: GraphLiteral,
        reason: str,
    ):
        self._ensure_grouped_adjacency()
        for edge in self.grouped_adjacency.get(source, ()):
            if edge.target == target and edge.reason == reason:
                return edge
        return None

    def grouped_chain_supports(self, literals, reasons):
        if len(reasons) != len(literals) - 1:
            raise ValueError("Il numero di supporti deve coincidere con gli archi.")
        result = []
        for source, target, reason in zip(literals, literals[1:], reasons):
            edge = self.grouped_edge(source, target, reason)
            if edge is None:
                raise ValueError("Il percorso grouped contiene un arco assente.")
            result.append({
                "support_candidates": edge.support_candidates,
                "support_house_ids": edge.support_house_ids,
            })
        return tuple(result)

    def grouped_shortest_path(
        self,
        source: GraphLiteral,
        target: GraphLiteral,
        *,
        allowed: frozenset[str],
        minimum_edges: int = 1,
        maximum_edges: int | None = None,
        require_group: bool = True,
    ):
        """Cammino minimo sul grafo condiviso candidato/gruppo."""
        start_group = isinstance(_literal_node(source), GroupNode)
        start_state = source, start_group
        queue = deque([(start_state, 0)])
        parent = {start_state: None}
        parent_reason = {}

        while queue:
            (current, used_group), depth = queue.popleft()
            if (
                current == target
                and depth >= minimum_edges
                and (used_group or not require_group)
            ):
                states = []
                cursor = current, used_group
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
            for edge in self.grouped_edges(current, allowed):
                next_group = used_group or isinstance(
                    _literal_node(edge.target), GroupNode
                )
                next_state = edge.target, next_group
                if next_state in parent:
                    continue
                parent[next_state] = current, used_group
                parent_reason[next_state] = edge.reason
                queue.append((next_state, depth + 1))
        return None

    def grouped_weak_reason(
        self,
        first: ImplicationNode,
        second: ImplicationNode,
    ) -> str | None:
        source = _node_literal(first, True)
        target = _node_literal(second, False)
        for reason in ("peer", "y", "group-weak"):
            if self.grouped_edge(source, target, reason) is not None:
                return reason
        return None

    def grouped_cycles(
        self,
        *,
        allowed: frozenset[str],
        maximum_edges: int | None = MAX_STATIC_CYCLE_EDGES,
    ):
        self._ensure_grouped_adjacency()
        nodes: tuple[ImplicationNode, ...] = tuple(sorted(
            (*self.all_candidates, *self.group_nodes),
            key=_node_key,
        ))
        seen_cycles = set()
        for start_node in nodes:
            start = _node_literal(start_node, True)
            path = [start]
            path_reasons = []
            visited = {start}

            def visit(current):
                if (
                    maximum_edges is not None
                    and len(path_reasons) >= maximum_edges
                ):
                    return
                for edge in self.grouped_edges(current, allowed):
                    target = edge.target
                    if target == start:
                        if len(path_reasons) + 1 < 4:
                            continue
                        literals = path + [start]
                        if not any(
                            isinstance(_literal_node(item), GroupNode)
                            for item in literals
                        ):
                            continue
                        reasons = path_reasons + [edge.reason]
                        signature = self._grouped_cycle_signature(
                            literals, reasons
                        )
                        if signature not in seen_cycles:
                            seen_cycles.add(signature)
                            yield list(literals), list(reasons)
                        continue
                    if target in visited:
                        continue
                    if (
                        proof_model.literal_state(target)
                        and _node_key(_literal_node(target))
                        < _node_key(start_node)
                    ):
                        continue
                    visited.add(target)
                    path.append(target)
                    path_reasons.append(edge.reason)
                    yield from visit(target)
                    path_reasons.pop()
                    path.pop()
                    visited.remove(target)

            yield from visit(start)

    @staticmethod
    def _grouped_cycle_signature(literals, reasons):
        edges = []
        for source, target, reason in zip(literals, literals[1:], reasons):
            endpoints = tuple(sorted(
                (_node_key(_literal_node(source)), _node_key(_literal_node(target)))
            ))
            edges.append((endpoints, reason))
        return tuple(sorted(edges))

    def conjugate_pairs(self, digit: int):
        """Restituisce gli archi X forti non orientati per una cifra.

        Coloring usa questa vista invece di ricostruire una seconda volta le
        coppie coniugate dalle case. Gli archi duplicati fra due celle che
        condividono più case vengono consolidati dal grafo autorevole.
        """
        digit = int(digit)
        if digit not in range(1, 10):
            raise ValueError("digit deve essere compreso tra 1 e 9.")

        pairs = set()
        for source, edges in self.adjacency.items():
            if source[2] != digit or source[3]:
                continue
            for edge in edges:
                target = edge.target
                if (
                    edge.reason != "x"
                    or target[2] != digit
                    or not target[3]
                ):
                    continue
                first = _candidate(source)
                second = _candidate(target)
                pairs.add(tuple(sorted((first, second))))
        return tuple(sorted(pairs))

    def shortest_path(
        self,
        source: Literal,
        target: Literal,
        *,
        allowed: frozenset[str],
        required: frozenset[str] = frozenset(),
        minimum_edges: int = 1,
        maximum_edges: int | None = None,
    ):
        """Cammino minimo che rispetta i tipi di collegamento richiesti."""
        start_state = source, frozenset()
        queue = deque([(start_state, 0)])
        parent = {start_state: None}
        parent_reason = {}

        while queue:
            (current, used), depth = queue.popleft()
            if (
                current == target
                and depth >= minimum_edges
                and required <= used
            ):
                states = []
                cursor = current, used
                while cursor is not None:
                    states.append(cursor)
                    cursor = parent[cursor]
                states.reverse()
                literals = [state[0] for state in states]
                reasons = [
                    parent_reason[state] for state in states[1:]
                ]
                return literals, reasons

            if maximum_edges is not None and depth >= maximum_edges:
                continue

            for edge in self.edges(current, allowed):
                next_used = used | {edge.reason}
                next_state = edge.target, next_used
                if next_state in parent:
                    continue
                parent[next_state] = current, used
                parent_reason[next_state] = edge.reason
                queue.append((next_state, depth + 1))
        return None

    def closure(self, source: Literal, allowed: frozenset[str]):
        """Tutti i letterali raggiungibili, conservando una prova minima."""
        queue = deque([source])
        parent: dict[Literal, Literal | None] = {source: None}
        reason: dict[Literal, str] = {}
        while queue:
            current = queue.popleft()
            for edge in self.edges(current, allowed):
                if edge.target in parent:
                    continue
                parent[edge.target] = current
                reason[edge.target] = edge.reason
                queue.append(edge.target)
        return StaticClosure(source, parent, reason)

    def cycles(
        self,
        *,
        allowed: frozenset[str],
        required: frozenset[str],
        maximum_edges: int | None = MAX_STATIC_CYCLE_EDGES,
    ):
        """Enumera cicli semplici alternati, in ordine deterministico.

        Si usa il candidato ON minimo del ciclo come rappresentante canonico,
        riducendo drasticamente i duplicati senza perdere pattern.
        """
        seen_cycles = set()
        for candidate in self.all_candidates:
            start = _literal(candidate, True)
            path = [start]
            path_reasons = []
            visited = {start}

            def visit(current: Literal):
                if (
                    maximum_edges is not None
                    and len(path_reasons) >= maximum_edges
                ):
                    return
                for edge in self.edges(current, allowed):
                    target = edge.target
                    if target == start:
                        if len(path_reasons) + 1 < 4:
                            continue
                        reasons = path_reasons + [edge.reason]
                        if not required <= set(reasons):
                            continue
                        literals = path + [start]
                        signature = self._cycle_signature(literals, reasons)
                        if signature not in seen_cycles:
                            seen_cycles.add(signature)
                            yield list(literals), list(reasons)
                        continue
                    if target in visited:
                        continue
                    # Il letterale ON minimo rende canonica la rotazione.
                    if target[3] and _candidate(target) < candidate:
                        continue
                    visited.add(target)
                    path.append(target)
                    path_reasons.append(edge.reason)
                    yield from visit(target)
                    path_reasons.pop()
                    path.pop()
                    visited.remove(target)

            yield from visit(start)

    @staticmethod
    def _cycle_signature(literals, reasons):
        edges = []
        for source, target, reason in zip(literals, literals[1:], reasons):
            endpoints = tuple(sorted((_candidate(source), _candidate(target))))
            edges.append((endpoints, reason))
        return tuple(sorted(edges))


class StaticClosure:
    def __init__(self, source, parent, reason):
        self.source = source
        self.parent = parent
        self.reason = reason

    @property
    def literals(self):
        return set(self.parent)

    def path(self, target: Literal):
        if target not in self.parent:
            return []
        result = []
        current = target
        while current is not None:
            result.append(current)
            current = self.parent[current]
        result.reverse()
        return result


class PropagationResult:
    def __init__(self, source: Literal):
        self.source = source
        self.on: set[Literal] = set()
        self.off: set[Literal] = set()
        self.parents: dict[Literal, tuple[Literal, ...]] = {source: ()}
        self.features: dict[Literal, frozenset[str]] = {source: frozenset()}
        self.reasons: dict[Literal, str] = {source: "assumption"}
        self.contradiction = False
        self.contradiction_literals: tuple[Literal, ...] = ()
        self.contradiction_features: frozenset[str] = frozenset()

    @property
    def literals(self):
        return self.on | self.off

    def add(self, literal, parents, reason, features):
        collection = self.on if literal[3] else self.off
        collection.add(literal)
        self.parents.setdefault(literal, tuple(parents))
        self.features.setdefault(literal, frozenset(features))
        self.reasons.setdefault(literal, reason)

    def set_contradiction(self, literals, features):
        self.contradiction = True
        self.contradiction_literals = tuple(literals)
        self.contradiction_features = frozenset(features)

    def proof_literals(self, targets):
        ordered = []
        seen = set()

        def add(literal):
            if literal in seen:
                return
            for parent in self.parents.get(literal, ()):
                add(parent)
            seen.add(literal)
            ordered.append(literal)

        for target in targets:
            add(target)
        return ordered

    def path(self, target: Literal):
        return self.proof_literals([target])

    def contradiction_path(self):
        targets = self.contradiction_literals or (self.source,)
        return self.proof_literals(targets)


class DynamicPropagator:
    """Propagazione locale di un'assunzione senza backtracking."""

    def __init__(self, grid, candidates):
        self.grid = grid
        self.initial = {
            cell: set(values) for cell, values in candidates.items()
        }
        self.initial_positions = self._positions_by_unit(self.initial)
        self.initial_graph = StaticImplicationGraph(self.initial)
        self.initial_advanced = {
            (candidate, rule)
            for candidate, rule, _ in self._advanced_eliminations(self.initial)
        }

    @staticmethod
    def _positions_by_unit(candidates):
        result = {}
        for unit_index, unit in enumerate(UNITS):
            for value in range(1, 10):
                result[unit_index, value] = tuple(
                    (row, column)
                    for row, column in unit
                    if value in candidates.get((row, column), ())
                )
        return result

    def _unit_has_solved(self, unit_index, value):
        return any(
            int(self.grid[row, column]) == value
            for row, column in UNITS[unit_index]
        )

    def propagate(self, source: Literal, *, mode="dynamic", advanced_level=0):
        work = {cell: set(values) for cell, values in self.initial.items()}
        result = PropagationResult(source)
        queue = deque([(source, (), "assumption", frozenset())])

        while True:
            while queue and not result.contradiction:
                literal, parents, reason, features = queue.popleft()
                row, column, value, is_on = literal
                opposite_set = result.off if is_on else result.on
                same_set = result.on if is_on else result.off
                if literal in same_set:
                    continue
                opposite = _opposite(literal)
                if opposite in opposite_set:
                    combined = set(features) | set(result.features.get(opposite, ()))
                    result.set_contradiction((opposite, literal), combined)
                    break

                result.add(literal, parents, reason, features)
                cell = (row, column)
                candidate = (row, column, value)

                if is_on:
                    if value not in work.get(cell, set()):
                        result.set_contradiction((literal,), features)
                        break

                    if mode != "nishio":
                        for other in sorted(work.get(cell, set()) - {value}):
                            queue.append((
                                (row, column, other, False),
                                (literal,),
                                "y",
                                features,
                            ))
                    for peer_row, peer_column in sorted(peers(row, column)):
                        if value in work.get((peer_row, peer_column), set()):
                            queue.append((
                                (peer_row, peer_column, value, False),
                                (literal,),
                                "x",
                                features,
                            ))
                    continue

                values = work.get(cell)
                if not values or value not in values:
                    continue
                before_count = len(values)
                values.remove(value)

                if mode != "nishio":
                    if not values:
                        result.set_contradiction(
                            (literal,), set(features) | {"dynamic"}
                        )
                        break
                    if len(values) == 1:
                        remaining = next(iter(values))
                        static = len(self.initial.get(cell, ())) == 2 and before_count == 2
                        next_features = set(features)
                        if not static:
                            next_features.add("dynamic")
                        false_parents = tuple(
                            item for item in result.off
                            if item[:2] == cell
                        ) or (literal,)
                        queue.append((
                            (row, column, remaining, True),
                            false_parents,
                            "y" if static else "cell-single",
                            frozenset(next_features),
                        ))

                for unit_index in _UNITS_BY_CELL[cell]:
                    if self._unit_has_solved(unit_index, value):
                        continue
                    positions = [
                        (unit_row, unit_column)
                        for unit_row, unit_column in UNITS[unit_index]
                        if value in work.get((unit_row, unit_column), ())
                    ]
                    initial_count = len(self.initial_positions[unit_index, value])
                    if not positions and initial_count:
                        next_features = set(features)
                        if initial_count != 2:
                            next_features.add("dynamic")
                        result.set_contradiction((literal,), next_features)
                        break
                    if len(positions) == 1:
                        target_row, target_column = positions[0]
                        static = initial_count == 2
                        next_features = set(features)
                        if not static:
                            next_features.add("dynamic")
                        false_parents = tuple(
                            item for item in result.off
                            if item[2] == value
                            and item[:2] in UNITS[unit_index]
                        ) or (literal,)
                        queue.append((
                            (target_row, target_column, value, True),
                            false_parents,
                            "x" if static else "unit-single",
                            frozenset(next_features),
                        ))
                if result.contradiction:
                    break

            if result.contradiction or not advanced_level:
                break

            advanced = self._advanced_eliminations(work)
            pending = []
            for candidate, rule, support in advanced:
                # Una regola già applicabile prima dell'assunzione non è una
                # conseguenza della catena e non può essere usata come Plus.
                if (candidate, rule) in self.initial_advanced:
                    continue
                if candidate[2] in work.get(candidate[:2], ()):
                    parents = tuple(
                        literal for literal in result.literals
                        if _candidate(literal) in support
                        and literal != source
                    )
                    # Il pattern deve dipendere da almeno una conseguenza
                    # dell'ipotesi; in caso contrario è solo una tecnica
                    # locale già disponibile nel ramo.
                    if not parents:
                        changed = tuple(
                            literal for literal in result.off
                            if literal != source
                        )
                        if not changed:
                            continue
                        parents = changed
                    parent_features = set().union(
                        *(result.features.get(parent, frozenset()) for parent in parents)
                    )
                    pending.append((
                        _literal(candidate, False),
                        parents,
                        rule,
                        frozenset(parent_features | {"advanced"}),
                    ))
            if not pending:
                break
            queue.extend(pending)

        return result

    def _advanced_eliminations(self, work):
        """Prime inferenze FC+: locking, pair e X-Wing."""
        found: dict[Candidate, tuple[str, set[Candidate]]] = {}

        def add(candidate, rule, support):
            if candidate[2] in work.get(candidate[:2], ()):
                found.setdefault(candidate, (rule, set(support)))

        # Pointing e claiming.
        for unit_index, (unit, kind) in enumerate(zip(UNITS, UNIT_KINDS)):
            for value in range(1, 10):
                positions = [
                    (row, column, value)
                    for row, column in unit
                    if value in work.get((row, column), ())
                ]
                if len(positions) < 2:
                    continue
                support = set(positions)
                if kind == "box":
                    rows = {item[0] for item in positions}
                    columns = {item[1] for item in positions}
                    if len(rows) == 1:
                        row = next(iter(rows))
                        for column in range(9):
                            if (row, column) not in {item[:2] for item in positions}:
                                add((row, column, value), "advanced-locking", support)
                    if len(columns) == 1:
                        column = next(iter(columns))
                        for row in range(9):
                            if (row, column) not in {item[:2] for item in positions}:
                                add((row, column, value), "advanced-locking", support)
                elif kind in ("row", "col"):
                    boxes = {3 * (item[0] // 3) + item[1] // 3 for item in positions}
                    if len(boxes) == 1:
                        box = next(iter(boxes))
                        for row, column in UNITS[18 + box]:
                            if (row, column) not in {item[:2] for item in positions}:
                                add((row, column, value), "advanced-locking", support)

        # Naked e hidden pair.
        for unit in UNITS:
            cells = [cell for cell in unit if work.get(cell)]
            bivalue = [cell for cell in cells if len(work[cell]) == 2]
            for first, second in combinations(bivalue, 2):
                if work[first] != work[second]:
                    continue
                digits = set(work[first])
                support = {
                    (first[0], first[1], value) for value in digits
                } | {
                    (second[0], second[1], value) for value in digits
                }
                for cell in cells:
                    if cell in (first, second):
                        continue
                    for value in digits:
                        add((cell[0], cell[1], value), "advanced-naked-pair", support)

            digit_positions = {}
            for value in range(1, 10):
                positions = tuple(cell for cell in cells if value in work[cell])
                if len(positions) == 2:
                    digit_positions[value] = positions
            for first_value, second_value in combinations(sorted(digit_positions), 2):
                if digit_positions[first_value] != digit_positions[second_value]:
                    continue
                pair_cells = digit_positions[first_value]
                support = {
                    (cell[0], cell[1], value)
                    for cell in pair_cells
                    for value in (first_value, second_value)
                }
                for cell in pair_cells:
                    for value in work[cell] - {first_value, second_value}:
                        add((cell[0], cell[1], value), "advanced-hidden-pair", support)

        # X-Wing per righe e per colonne.
        for value in range(1, 10):
            row_positions = {}
            for row in range(9):
                columns = tuple(
                    column for column in range(9)
                    if value in work.get((row, column), ())
                )
                if len(columns) == 2:
                    row_positions[row] = columns
            for first_row, second_row in combinations(sorted(row_positions), 2):
                if row_positions[first_row] != row_positions[second_row]:
                    continue
                columns = row_positions[first_row]
                support = {
                    (row, column, value)
                    for row in (first_row, second_row)
                    for column in columns
                }
                for row in range(9):
                    if row not in (first_row, second_row):
                        for column in columns:
                            add((row, column, value), "advanced-x-wing", support)

            column_positions = {}
            for column in range(9):
                rows = tuple(
                    row for row in range(9)
                    if value in work.get((row, column), ())
                )
                if len(rows) == 2:
                    column_positions[column] = rows
            for first_column, second_column in combinations(sorted(column_positions), 2):
                if column_positions[first_column] != column_positions[second_column]:
                    continue
                rows = column_positions[first_column]
                support = {
                    (row, column, value)
                    for column in (first_column, second_column)
                    for row in rows
                }
                for column in range(9):
                    if column not in (first_column, second_column):
                        for row in rows:
                            add((row, column, value), "advanced-x-wing", support)

        return [
            (candidate, rule, support)
            for candidate, (rule, support) in sorted(found.items())
        ]


@dataclass(frozen=True)
class _CompleteForcingTreeProofNode:
    """Nodo del DAG di prova prodotto dal Complete Forcing Tree."""

    assumption: Literal | None = None
    propagations: tuple[Literal, ...] = ()
    contradiction: bool = False
    contradiction_reason: str | None = None
    branch_cell: tuple[int, int] | None = None
    children: tuple["_CompleteForcingTreeProofNode", ...] = ()


def _mask_values(mask: int):
    for value in range(1, 10):
        if mask & (1 << value):
            yield value


def _single_mask_value(mask: int) -> int | None:
    if mask <= 0 or mask & (mask - 1):
        return None
    return mask.bit_length() - 1


def _nested_state_masks(grid, candidates) -> tuple[int, ...]:
    masks = []

    for row in range(9):
        for column in range(9):
            solved_value = int(grid[row, column])

            if solved_value:
                masks.append(1 << solved_value)
                continue

            mask = 0
            for value in candidates.get((row, column), ()):
                mask |= 1 << int(value)
            masks.append(mask)

    return tuple(masks)


def _technique_result_limit(technique, max_results):
    """Applica i limiti di output senza limitare la ricerca interna."""
    requested = _normalise_max_results(max_results)
    if technique == _COMPLETE_TREE_TECHNIQUE:
        hard_limit = MAX_COMPLETE_TREE_DEDUCTIONS
    elif technique == _NESTED_TECHNIQUE:
        hard_limit = MAX_NESTED_DEDUCTIONS
    else:
        hard_limit = MAX_DEDUCTIONS_PER_TECHNIQUE

    if requested is None:
        return hard_limit

    return min(requested, hard_limit)


class CompleteForcingTreeSearch:
    """Ricerca completa per contraddizione sui vincoli Sudoku.

    Ogni ramo assegna almeno una cella e lo spazio degli stati Sudoku e'
    finito. Le cache memorizzano stati soddisfacibili e prove contraddittorie
    gia' calcolate.
    """

    def __init__(self, grid, candidates):
        self.initial_masks = _nested_state_masks(grid, candidates)
        self._solution_cache: dict[tuple[int, ...], tuple[int, ...] | None] = {}
        self._proof_cache: dict[
            tuple[int, ...],
            _CompleteForcingTreeProofNode | None,
        ] = {}

    @staticmethod
    def _choose_branch_cell(masks: tuple[int, ...]) -> int | None:
        choices = (
            (mask.bit_count(), index)
            for index, mask in enumerate(masks)
            if mask.bit_count() > 1
        )
        return min(choices, default=(0, None))[1]

    @staticmethod
    def _apply_assumption(work, assumption, note, queue):
        row, column, value, is_on = assumption
        index = row * 9 + column
        bit = 1 << value
        old_mask = work[index]

        if is_on:
            if not old_mask & bit:
                return (
                    f"R{row + 1}C{column + 1} non ammette il valore {value}."
                )
            new_mask = bit
        else:
            if not old_mask & bit:
                return None
            new_mask = old_mask & ~bit

        if new_mask == old_mask:
            return None

        for removed_value in _mask_values(old_mask & ~new_mask):
            note((row, column, removed_value, False))

        work[index] = new_mask

        if not new_mask:
            return (
                f"R{row + 1}C{column + 1} resta senza candidati."
            )

        if _single_mask_value(new_mask) is not None:
            queue.append(index)
            note((row, column, _single_mask_value(new_mask), True))

        return None

    def _propagate(self, masks, assumption=None, *, record_trace=True):
        work = list(masks)
        trace = []
        seen_trace = set()
        queue = deque()
        processed_singletons = set()

        def note(literal):
            if not record_trace or literal == assumption or literal in seen_trace:
                return
            seen_trace.add(literal)
            trace.append(literal)

        for index, mask in enumerate(work):
            if _single_mask_value(mask) is not None:
                queue.append(index)

        if assumption is not None:
            contradiction = self._apply_assumption(
                work,
                assumption,
                note,
                queue,
            )
            if contradiction is not None:
                return None, tuple(trace), contradiction

        while True:
            while queue:
                index = queue.popleft()
                mask = work[index]
                value = _single_mask_value(mask)

                if value is None:
                    continue

                singleton_key = index, mask
                if singleton_key in processed_singletons:
                    continue
                processed_singletons.add(singleton_key)

                row, column = divmod(index, 9)
                bit = 1 << value

                for peer_index in _PEER_INDEXES[index]:
                    peer_mask = work[peer_index]
                    if not peer_mask & bit:
                        continue

                    peer_row, peer_column = divmod(peer_index, 9)
                    new_mask = peer_mask & ~bit
                    work[peer_index] = new_mask
                    note((peer_row, peer_column, value, False))

                    if not new_mask:
                        return (
                            None,
                            tuple(trace),
                            f"R{peer_row + 1}C{peer_column + 1} resta "
                            "senza candidati.",
                        )

                    remaining = _single_mask_value(new_mask)
                    if remaining is not None:
                        note((peer_row, peer_column, remaining, True))
                        queue.append(peer_index)

            hidden_single_found = False

            for unit_index, unit in enumerate(_UNIT_INDEXES):
                for value, bit in zip(range(1, 10), _DIGIT_BITS):
                    positions = [
                        index for index in unit
                        if work[index] & bit
                    ]

                    if not positions:
                        unit_name, visible_index = _visible_unit_reference(
                            unit_index
                        )
                        return (
                            None,
                            tuple(trace),
                            f"Il valore {value} non ha posizioni nella "
                            f"{unit_name} {visible_index}.",
                        )

                    if len(positions) != 1:
                        continue

                    index = positions[0]
                    if work[index] == bit:
                        continue

                    old_mask = work[index]
                    row, column = divmod(index, 9)

                    for removed_value in _mask_values(old_mask & ~bit):
                        note((row, column, removed_value, False))

                    work[index] = bit
                    note((row, column, value, True))
                    queue.append(index)
                    hidden_single_found = True

            if not hidden_single_found:
                break

        return tuple(work), tuple(trace), None

    def _find_solution(self, masks):
        propagated, _, contradiction = self._propagate(
            masks,
            record_trace=False,
        )

        if contradiction is not None:
            return None

        cached = self._solution_cache.get(propagated, ...)
        if cached is not ...:
            return cached

        branch_index = self._choose_branch_cell(propagated)

        if branch_index is None:
            self._solution_cache[propagated] = propagated
            return propagated

        for value in _mask_values(propagated[branch_index]):
            child = list(propagated)
            child[branch_index] = 1 << value
            solution = self._find_solution(tuple(child))

            if solution is not None:
                self._solution_cache[propagated] = solution
                return solution

        self._solution_cache[propagated] = None
        return None

    @staticmethod
    def _attach_context(core, assumption, propagations):
        return _CompleteForcingTreeProofNode(
            assumption=assumption,
            propagations=propagations,
            contradiction=core.contradiction,
            contradiction_reason=core.contradiction_reason,
            branch_cell=core.branch_cell,
            children=core.children,
        )

    def _prove_unsatisfiable(self, masks, assumption=None):
        propagated, trace, contradiction = self._propagate(
            masks,
            assumption=assumption,
            record_trace=True,
        )

        if contradiction is not None:
            return _CompleteForcingTreeProofNode(
                assumption=assumption,
                propagations=trace,
                contradiction=True,
                contradiction_reason=contradiction,
            )

        cached = self._proof_cache.get(propagated, ...)
        if cached is not ...:
            if cached is None:
                return None
            return self._attach_context(cached, assumption, trace)

        branch_index = self._choose_branch_cell(propagated)

        if branch_index is None:
            self._proof_cache[propagated] = None
            return None

        row, column = divmod(branch_index, 9)
        children = []

        for value in _mask_values(propagated[branch_index]):
            child_assumption = (row, column, value, True)
            child_proof = self._prove_unsatisfiable(
                propagated,
                assumption=child_assumption,
            )

            if child_proof is None:
                self._proof_cache[propagated] = None
                return None

            children.append(child_proof)

        core = _CompleteForcingTreeProofNode(
            branch_cell=(row, column),
            children=tuple(children),
        )
        self._proof_cache[propagated] = core
        return self._attach_context(core, assumption, trace)

    @staticmethod
    def _longest_chain(node):
        local = []

        if node.assumption is not None:
            local.append(node.assumption)
        local.extend(node.propagations)

        if node.contradiction or not node.children:
            return local

        child_chain = max(
            (
                CompleteForcingTreeSearch._longest_chain(child)
                for child in node.children
            ),
            key=len,
            default=[],
        )
        return local + child_chain

    @staticmethod
    def _proof_metrics(node):
        def visit(current):
            local_length = len(current.propagations)
            local_assumption_count = 0
            if current.assumption is not None:
                local_length += 1
                local_assumption_count = 1

            if current.contradiction or not current.children:
                return {
                    "chain_count": 1,
                    "proof_node_count": max(local_length, 1),
                    "assumption_count": local_assumption_count,
                    "max_chain_length": local_length,
                    "total_chain_length": local_length,
                    "nested_depth": 0,
                    "branch_count": 0,
                    "leaf_count": 1,
                    "nested_subproof_count": 0,
                }

            child_metrics = [visit(child) for child in current.children]
            chain_count = sum(
                item["chain_count"] for item in child_metrics
            )

            return {
                "chain_count": chain_count,
                "proof_node_count": local_length + 1 + sum(
                    item["proof_node_count"] for item in child_metrics
                ),
                "assumption_count": (
                    local_assumption_count
                    + sum(
                        item["assumption_count"]
                        for item in child_metrics
                    )
                ),
                "max_chain_length": local_length + max(
                    item["max_chain_length"] for item in child_metrics
                ),
                "total_chain_length": (
                    local_length * chain_count
                    + sum(
                        item["total_chain_length"]
                        for item in child_metrics
                    )
                ),
                "nested_depth": 0,
                "branch_count": len(current.children) + sum(
                    item["branch_count"] for item in child_metrics
                ),
                "leaf_count": sum(
                    item["leaf_count"] for item in child_metrics
                ),
                "nested_subproof_count": 0,
            }

        structural = visit(node)
        structural["proof_edge_count"] = max(
            structural["proof_node_count"] - 1,
            0,
        )
        return proof_schema.normalize_proof_metrics({
            "assumptions": (
                (node.assumption,)
                if node.assumption is not None
                else ()
            ),
            "chains": (
                CompleteForcingTreeSearch._longest_chain(node),
            ),
            "metrics": structural,
        })

    @staticmethod
    def _serialize_proof(root):
        nodes = []
        node_ids = {}

        def visit(node):
            identity = id(node)
            if identity in node_ids:
                return node_ids[identity]

            node_id = len(nodes)
            node_ids[identity] = node_id
            nodes.append(None)
            child_ids = [visit(child) for child in node.children]

            record = {
                "id": node_id,
                "assumption": (
                    _literal_record(node.assumption)
                    if node.assumption is not None
                    else None
                ),
                "propagations": [
                    _literal_record(literal)
                    for literal in node.propagations
                ],
                "contradiction": node.contradiction,
                "contradiction_reason": node.contradiction_reason,
                "branch_cell": (
                    {
                        "row": node.branch_cell[0],
                        "column": node.branch_cell[1],
                    }
                    if node.branch_cell is not None
                    else None
                ),
                "children": child_ids,
            }
            nodes[node_id] = record
            return node_id

        root_id = visit(root)
        return {
            "kind": "complete-forcing-tree-proof-dag",
            "root": root_id,
            "nodes": nodes,
        }

    @staticmethod
    def _formal_proof_dag(root, conclusion):
        """Converte l'intero albero dei casi nel DAG autorevole P06."""
        nodes = {}
        next_id = 0

        def add(kind, literal, parents, reason, payload=None):
            nonlocal next_id
            parents = tuple(dict.fromkeys(parents))
            depth = (
                0
                if not parents
                else 1 + max(nodes[parent].depth for parent in parents)
            )
            node = proof_model.ProofNode(
                id=next_id,
                kind=kind,
                conclusion=literal,
                parents=parents,
                reason=reason,
                depth=depth,
                payload=payload or {},
            )
            nodes[node.id] = node
            next_id += 1
            return node.id

        def visit(current, parent=None):
            cursor = parent
            if current.assumption is not None:
                cursor = add(
                    "assumption",
                    current.assumption,
                    (() if cursor is None else (cursor,)),
                    "case-assumption",
                    {"presentation": True},
                )

            for literal in current.propagations:
                cursor = add(
                    "dynamic-single",
                    literal,
                    (() if cursor is None else (cursor,)),
                    "complete-tree-propagation",
                    {"presentation": True},
                )

            if current.contradiction:
                contradiction_id = add(
                    "contradiction",
                    None,
                    (() if cursor is None else (cursor,)),
                    current.contradiction_reason or "contradiction",
                    {"presentation": False},
                )
                return (contradiction_id,)

            if not current.children:
                return (() if cursor is None else (cursor,))

            branch_id = add(
                "branch",
                None,
                (() if cursor is None else (cursor,)),
                "complete-case-split",
                {
                    "branch_cell": list(current.branch_cell or ()),
                    "branch_count": len(current.children),
                    "presentation": False,
                },
            )
            leaves = []
            for child in current.children:
                leaves.extend(visit(child, branch_id))
            return tuple(leaves)

        evidence = tuple(dict.fromkeys(visit(root)))
        row, column, value = conclusion
        conclusion_id = add(
            "common-conclusion",
            (row, column, value, False),
            evidence,
            "elimination",
            {"action": "elimination", "presentation": False},
        )
        roots = tuple(sorted(
            node.id for node in nodes.values() if not node.parents
        ))
        return proof_model.ProofDAG(
            nodes=nodes,
            roots=roots,
            conclusions=(conclusion_id,),
            nested_proofs={},
        )

    def find_deductions(self, max_results):
        collector = _DeductionCollector(max_results)
        solution = self._find_solution(self.initial_masks)

        if solution is None:
            return collector.results

        branch_cells = sorted(
            (
                (mask.bit_count(), index)
                for index, mask in enumerate(self.initial_masks)
                if mask.bit_count() > 1
            )
        )

        for _, index in branch_cells:
            if collector.full:
                break

            row, column = divmod(index, 9)
            solution_value = _single_mask_value(solution[index])

            for value in _mask_values(self.initial_masks[index]):
                if collector.full:
                    break
                if value == solution_value:
                    continue

                candidate = (row, column, value)
                assumption = _literal(candidate, True)
                proof = self._prove_unsatisfiable(
                    self.initial_masks,
                    assumption=assumption,
                )

                if proof is None:
                    # Il ramo e' soddisfacibile: il puzzle potrebbe avere
                    # piu' soluzioni oppure non essere una deduzione.
                    continue

                representative_chain = self._longest_chain(proof)
                deduction = _deduction(
                    description=(
                        f"Assumere R{row + 1}C{column + 1}={value} "
                        "richiede l'esplorazione completa di tutte le "
                        "alternative residue e conduce sempre a "
                        "contraddizione: il candidato e' eliminato."
                    ),
                    eliminations=(candidate,),
                    assumptions=(assumption,),
                    chains=(representative_chain,),
                    reasons=(
                        "dynamic",
                        "complete-tree",
                        "complete-search",
                    ),
                    kind="complete-forcing-tree-contradiction",
                )
                formal_dag = self._formal_proof_dag(proof, candidate)
                deduction["logic"]["proof_dag"] = formal_dag.to_dict()
                deduction["logic"]["dag_digest"] = formal_dag.digest()
                deduction["logic"]["chains"] = [
                    [
                        proof_model.literal_record(literal)
                        for literal in chain
                    ]
                    for chain in formal_dag.derived_chains()
                ]
                deduction["logic"]["chain_links"] = (
                    formal_dag.derived_chain_links()
                )
                if STORE_COMPLETE_FORCING_TREE_PROOF:
                    deduction["logic"]["proof_tree"] = (
                        self._serialize_proof(proof)
                    )
                deduction["logic"]["metrics"] = (
                    proof_schema.normalize_proof_metrics(
                        deduction["logic"]
                    )
                )
                deduction["logic"]["complete"] = True
                deduction["logic"]["exhaustive"] = True
                deduction["logic"]["proof_tree_stored"] = bool(
                    STORE_COMPLETE_FORCING_TREE_PROOF
                )

                if collector.add(deduction):
                    break

        return collector.results


class _DeductionCollector:
    """Accumula soltanto esiti distinti e si ferma al limite richiesto."""

    def __init__(self, max_results):
        self.max_results = _normalise_max_results(max_results)
        self.results = []
        self._seen = set()

    @property
    def full(self):
        return (
            self.max_results is not None
            and len(self.results) >= self.max_results
        )

    def add(self, deduction):
        signature = (
            tuple(deduction["placements"]),
            tuple(deduction["eliminations"]),
        )

        if signature == ((), ()) or signature in self._seen:
            return self.full

        self._seen.add(signature)
        self.results.append(deduction)
        return self.full


def _normalise_max_results(max_results):
    """Valida la richiesta; ``None`` usa il massimo configurato."""
    if max_results is None:
        return None

    if isinstance(max_results, bool):
        raise TypeError("max_results deve essere un intero positivo o None.")

    max_results = int(max_results)

    if max_results < 1:
        raise ValueError("max_results deve essere maggiore di zero.")

    return max_results


class LogicEngine:
    """Facade che calcola e memorizza le deduzioni per uno stato immutato."""

    def __init__(self, state):
        self.grid = state.grid.copy()
        self.candidates = _candidate_map(state)
        self.graph = StaticImplicationGraph(self.candidates)
        self.propagator = DynamicPropagator(self.grid, self.candidates)

        # Per ogni tecnica conserva il risultato più ampio già calcolato.
        # ``None`` in _result_limits indica che l'enumerazione si e'
        # esaurita naturalmente prima del limite configurato.
        self._results = {}
        self._result_limits = {}
        self._prepared_batches = set()

        # Queste cache contengono strutture riutilizzabili nello stesso stato.
        # Non ampliano mai il livello richiesto: ogni livello dinamico ha una
        # chiave distinta e viene calcolato solo quando serve davvero.
        self._propagation_cache = {}
        self._closure_cache = {}
        self._complete_forcing_tree_search = None
        self._lock = RLock()

    def _propagate(self, source, *, mode="dynamic", advanced_level=0):
        """Propaga esattamente al livello richiesto e ne riusa il risultato."""
        key = source, mode, int(advanced_level)

        if key not in self._propagation_cache:
            self._propagation_cache[key] = self.propagator.propagate(
                source,
                mode=mode,
                advanced_level=int(advanced_level),
            )

        return self._propagation_cache[key]

    def _closure(self, source, allowed):
        key = source, frozenset(allowed)

        if key not in self._closure_cache:
            self._closure_cache[key] = self.graph.closure(source, key[1])

        return self._closure_cache[key]

    @staticmethod
    def _matches_feature_tier(features, required_feature):
        features = set(features)

        if required_feature == "dynamic":
            return (
                "dynamic" in features
                and "advanced" not in features
                and "nested" not in features
            )

        if required_feature == "advanced":
            return "advanced" in features and "nested" not in features

        if required_feature == "nested":
            return "nested" in features

        return required_feature in features

    @staticmethod
    def _method_name(technique):
        return (
            "_find_"
            + technique.lower()
            .replace("+", "_plus")
            .replace(" ", "_")
            .replace("-", "_")
            .replace("(", "")
            .replace(")", "")
        )

    def _cache_covers(self, technique, max_results):
        if technique not in self._results:
            return False

        stored_limit = self._result_limits[technique]

        if stored_limit is None:
            return True

        if max_results is None:
            return False

        return stored_limit >= max_results

    def _store_result(self, technique, deductions, requested_limit):
        # Se la ricerca restituisce meno del limite, l'enumerazione è
        # terminata naturalmente e il risultato è completo.
        stored_limit = (
            None
            if requested_limit is None
            or len(deductions) < requested_limit
            else requested_limit
        )

        previous_limit = self._result_limits.get(technique, -1)

        if previous_limit is None:
            return

        if (
            technique not in self._results
            or stored_limit is None
            or previous_limit < stored_limit
        ):
            self._results[technique] = deductions
            self._result_limits[technique] = stored_limit

    def _compute(self, technique, max_results):
        max_results = _technique_result_limit(technique, max_results)

        if self._cache_covers(technique, max_results):
            return

        method = getattr(self, self._method_name(technique), None)

        if method is None:
            raise KeyError(f"Tecnica logica sconosciuta: {technique}")

        deductions = self._deduplicate(
            method(max_results=max_results),
            max_results=max_results,
        )
        self._store_result(technique, deductions, max_results)

    def prepare(
        self,
        target="all",
        max_results=DEFAULT_MAX_DEDUCTIONS_PER_TECHNIQUE,
    ):
        """
        Prepara una tecnica oppure un batch esplicito.

        Il limite viene passato dentro la ricerca, quindi le enumerazioni si
        interrompono appena hanno prodotto il numero richiesto di esiti
        distinti. Una cache calcolata con un limite maggiore soddisfa anche
        richieste successive con un limite minore.
        """
        max_results = _normalise_max_results(max_results)

        with self._lock:
            if target in _LOGIC_TECHNIQUE_TO_BATCH:
                self._compute(target, max_results)
                return

            if target == "all":
                batch_names = (
                    "static",
                    "multiple",
                    "dynamic",
                )
            elif target in LOGIC_TECHNIQUE_BATCHES:
                batch_names = (target,)
            else:
                raise KeyError(
                    f"Tecnica o batch logico sconosciuto: {target}"
                )

            for batch_name in batch_names:
                batch_key = batch_name, max_results

                if batch_key in self._prepared_batches:
                    continue

                for technique in LOGIC_TECHNIQUE_BATCHES[batch_name]:
                    self._compute(technique, max_results)

                self._prepared_batches.add(batch_key)

    def get_cached(
        self,
        technique,
        max_results=DEFAULT_MAX_DEDUCTIONS_PER_TECHNIQUE,
    ):
        max_results = _technique_result_limit(technique, max_results)

        if not self._cache_covers(technique, max_results):
            raise KeyError(
                f"La tecnica {technique!r} non è nella cache con "
                "un limite sufficiente."
            )

        result = self._results[technique]

        if max_results is None:
            return deepcopy(result)

        return deepcopy(result[:max_results])

    def find(
        self,
        technique: str,
        max_results=DEFAULT_MAX_DEDUCTIONS_PER_TECHNIQUE,
    ):
        self.prepare(technique, max_results=max_results)
        return self.get_cached(technique, max_results=max_results)

    @staticmethod
    def _deduplicate(deductions, max_results=None):
        collector = _DeductionCollector(max_results)

        for deduction in deductions:
            if collector.add(deduction):
                break

        return collector.results

    def _cycle_deductions(
        self,
        technique,
        allowed,
        required,
        *,
        max_results,
    ):
        collector = _DeductionCollector(max_results)

        for literals, reasons in self.graph.cycles(
            allowed=frozenset(allowed),
            required=frozenset(required),
            maximum_edges=MAX_STATIC_CYCLE_EDGES,
        ):
            body = literals[:-1]
            supports = self.graph.chain_supports(literals, reasons)
            eliminations = set()

            # In un Continuous Nice Loop ogni weak link viene reso strong
            # dal percorso alternato restante. Le sole conclusioni lecite
            # sono quindi quelle fornite dalle case/celle di tali weak link.
            for source, target, reason, support in zip(
                literals,
                literals[1:],
                reasons,
                supports,
            ):
                if not source[3] or target[3]:
                    continue
                endpoints = {_candidate(source), _candidate(target)}
                if reason == "peer":
                    digit = source[2]
                    for house_id in support["support_house_ids"]:
                        for row, column in UNITS[house_id]:
                            candidate = (row, column, digit)
                            if (
                                candidate not in endpoints
                                and digit in self.candidates.get(
                                    (row, column), ()
                                )
                            ):
                                eliminations.add(candidate)
                elif reason == "y" and source[:2] == target[:2]:
                    row, column = source[:2]
                    for digit in self.candidates.get((row, column), ()):
                        candidate = (row, column, digit)
                        if candidate not in endpoints:
                            eliminations.add(candidate)

            if not eliminations:
                continue

            if collector.add(_deduction(
                description=(
                    f"Il {technique} alterna {len(body)} implicazioni: "
                    "ogni weak link e' resa strong dal resto del loop e "
                    "rimuove i candidati aggiuntivi dal proprio supporto."
                ),
                eliminations=sorted(eliminations),
                assumptions=(body[0],),
                chains=(literals,),
                reasons=reasons,
                chain_reasons=(reasons,),
                chain_supports=(supports,),
                kind="bidirectional-cycle",
            )):
                break

        return collector.results

    def _find_bidirectional_x_cycle(self, *, max_results):
        return self._cycle_deductions(
            "Bidirectional X-Cycle",
            {"peer", "x"},
            {"peer", "x"},
            max_results=max_results,
        )

    def _find_bidirectional_y_cycle(self, *, max_results):
        return self._cycle_deductions(
            "Bidirectional Y-Cycle",
            {"peer", "y"},
            {"peer", "y"},
            max_results=max_results,
        )

    def _find_bidirectional_cycle(self, *, max_results):
        return self._cycle_deductions(
            "Bidirectional Cycle",
            {"peer", "x", "y"},
            {"x", "y"},
            max_results=max_results,
        )

    def _forcing_deductions(
        self,
        technique,
        allowed,
        required,
        *,
        max_results,
        eliminations_only=False,
    ):
        collector = _DeductionCollector(max_results)

        for candidate in self.graph.all_candidates:
            for source_state in (True, False):
                source = _literal(candidate, source_state)
                target = _opposite(source)
                path_data = self.graph.shortest_path(
                    source,
                    target,
                    allowed=frozenset(allowed),
                    required=frozenset(required),
                    minimum_edges=3,
                )

                if not path_data:
                    continue

                path, reasons = path_data

                if source_state:
                    placements = ()
                    eliminations = (candidate,)
                    conclusion = "deve essere falso"
                else:
                    if eliminations_only:
                        continue
                    placements = (candidate,)
                    eliminations = ()
                    conclusion = "deve essere vero"

                if collector.add(_deduction(
                    description=(
                        f"Assumere R{candidate[0]+1}C{candidate[1]+1}="
                        f"{candidate[2]} "
                        f"{('vero' if source_state else 'falso')} "
                        f"implica il contrario: il candidato {conclusion}."
                    ),
                    placements=placements,
                    eliminations=eliminations,
                    assumptions=(source,),
                    chains=(path,),
                    reasons=reasons,
                    chain_reasons=(reasons,),
                    chain_supports=(
                        self.graph.chain_supports(path, reasons),
                    ),
                    kind="forcing-chain",
                )):
                    return collector.results

        return collector.results

    def _endpoint_deductions(
        self,
        technique,
        *,
        allowed,
        required,
        subtype,
        max_results,
    ):
        """Catene strong-ended; la conclusione nasce dai due endpoint.

        Per ogni eliminazione ``T`` si conserva nel DAG la prova esplicita
        ``T on -> A off -> ... -> B on -> T off``. Il percorso centrale e'
        la AIC, mentre i due archi esterni documentano la conclusione.
        """
        collector = _DeductionCollector(max_results)
        candidates = self.graph.all_candidates
        allowed = frozenset(allowed)
        required = frozenset(required)

        for first_index, first in enumerate(candidates):
            for second in candidates[first_index + 1:]:
                same_digit = first[2] == second[2]
                if subtype == "x" and not same_digit:
                    continue
                if subtype == "aic1" and not same_digit:
                    continue
                if subtype == "aic2" and same_digit:
                    continue
                if (
                    subtype == "aic2"
                    and second[:2] not in peers(first[0], first[1])
                ):
                    continue

                targets = [
                    candidate
                    for candidate in candidates
                    if candidate not in {first, second}
                    and _conflict_reason(candidate, first)
                    and _conflict_reason(candidate, second)
                ]
                if not targets:
                    continue

                path_data = self.graph.shortest_path(
                    _literal(first, False),
                    _literal(second, True),
                    allowed=allowed,
                    required=required,
                    minimum_edges=3,
                    maximum_edges=MAX_STATIC_CYCLE_EDGES - 2,
                )
                if path_data is None:
                    continue
                central, central_reasons = path_data
                central_candidates = [_candidate(item) for item in central]
                if len(set(central_candidates)) != len(central_candidates):
                    continue
                all_one_digit = len({item[2] for item in central}) == 1
                if subtype == "x" and not all_one_digit:
                    continue
                if subtype in {"aic1", "aic2"} and all_one_digit:
                    continue

                chains = []
                chain_reasons = []
                chain_supports = []
                for target in targets:
                    left_reason = _conflict_reason(target, first)
                    right_reason = _conflict_reason(second, target)
                    proof_chain = (
                        _literal(target, True),
                        *central,
                        _literal(target, False),
                    )
                    reasons = (
                        left_reason,
                        *central_reasons,
                        right_reason,
                    )
                    try:
                        supports = self.graph.chain_supports(
                            proof_chain, reasons
                        )
                    except ValueError:
                        continue
                    chains.append(proof_chain)
                    chain_reasons.append(reasons)
                    chain_supports.append(supports)

                if not chains:
                    continue
                eliminations = tuple(_candidate(chain[0]) for chain in chains)
                endpoint_text = (
                    f"R{first[0]+1}C{first[1]+1}={first[2]} e "
                    f"R{second[0]+1}C{second[1]+1}={second[2]}"
                )
                if collector.add(_deduction(
                    description=(
                        f"La {technique} collega gli endpoint {endpoint_text}: "
                        "ogni candidato in weak link con entrambi e' falso."
                    ),
                    eliminations=eliminations,
                    assumptions=tuple(chain[0] for chain in chains),
                    chains=chains,
                    reasons=tuple(sorted(set(chain(
                        *chain_reasons
                    )))),
                    chain_reasons=chain_reasons,
                    chain_supports=chain_supports,
                    kind="endpoint-aic",
                )):
                    return collector.results

        return collector.results

    def _find_forcing_x_chain(self, *, max_results):
        return self._endpoint_deductions(
            "X-Chain",
            allowed={"peer", "x"},
            required={"peer", "x"},
            subtype="x",
            max_results=max_results,
        )

    def _find_xy_chain(self, *, max_results):
        # Le conclusioni ON restano cicli discontinui generali. Il limite
        # viene applicato dopo questo filtro, non prima.
        return self._forcing_deductions(
            "XY-Chain",
            {"peer", "y"},
            {"peer", "y"},
            max_results=max_results,
            eliminations_only=True,
        )

    def _find_forcing_chain(self, *, max_results):
        return self._forcing_deductions(
            "Forcing Chain",
            {"peer", "x", "y"},
            {"x", "y"},
            max_results=max_results,
        )

    def _find_aic(self, *, max_results):
        subtype_results = []
        for subtype in ("aic1", "aic2"):
            subtype_results.append(self._endpoint_deductions(
                "AIC",
                allowed={"peer", "x", "y"},
                required={"x", "y"},
                subtype=subtype,
                max_results=max_results,
            ))
        deductions = []
        for index in range(max(map(len, subtype_results), default=0)):
            deductions.extend(
                results[index]
                for results in subtype_results
                if index < len(results)
            )
        return self._deduplicate(deductions, max_results=max_results)

    @staticmethod
    def _contains_group(literals):
        return any(
            isinstance(_literal_node(literal), GroupNode)
            for literal in literals
        )

    def _grouped_endpoint_deductions(self, subtype, *, max_results):
        collector = _DeductionCollector(max_results)
        self.graph._ensure_grouped_adjacency()
        nodes: tuple[ImplicationNode, ...] = tuple(sorted(
            (*self.graph.all_candidates, *self.graph.group_nodes),
            key=_node_key,
        ))
        allowed = frozenset({
            "peer", "x", "y", "group-weak", "group-strong",
        })
        pair_targets = defaultdict(set)
        weak_reasons = frozenset({"peer", "y", "group-weak"})
        target_nodes: tuple[ImplicationNode, ...] = tuple(sorted(
            (*self.graph.all_candidates, *self.graph.group_nodes),
            key=_node_key,
        ))
        for target_node in target_nodes:
            weak_nodes = tuple(sorted({
                _literal_node(edge.target)
                for edge in self.graph.grouped_edges(
                    _node_literal(target_node, True), weak_reasons
                )
                if not proof_model.literal_state(edge.target)
            }, key=_node_key))
            for first, second in combinations(weak_nodes, 2):
                pair_targets[(first, second)].add(target_node)

        for first_index, first in enumerate(nodes):
            for second in nodes[first_index + 1:]:
                same_digit = _node_digit(first) == _node_digit(second)
                if subtype == "x" and not same_digit:
                    continue
                if subtype == "aic" and same_digit:
                    continue
                targets = sorted(
                    pair_targets.get((first, second), ()), key=_node_key
                )
                if not targets:
                    continue
                path_data = self.graph.grouped_shortest_path(
                    _node_literal(first, False),
                    _node_literal(second, True),
                    allowed=allowed,
                    minimum_edges=3,
                    maximum_edges=MAX_STATIC_CYCLE_EDGES - 2,
                    require_group=True,
                )
                if path_data is None:
                    continue
                central, central_reasons = path_data
                central_nodes = [_literal_node(item) for item in central]
                if len(set(central_nodes)) != len(central_nodes):
                    continue
                if not self._contains_group(central):
                    continue
                all_one_digit = len({
                    _node_digit(item) for item in central_nodes
                }) == 1
                if subtype == "x" and not all_one_digit:
                    continue
                if subtype == "aic" and all_one_digit:
                    continue

                chains = []
                chain_reasons = []
                chain_supports = []
                for target in targets:
                    left_reason = self.graph.grouped_weak_reason(target, first)
                    right_reason = self.graph.grouped_weak_reason(second, target)
                    proof_chain = (
                        _node_literal(target, True),
                        *central,
                        _node_literal(target, False),
                    )
                    reasons = (
                        left_reason,
                        *central_reasons,
                        right_reason,
                    )
                    supports = self.graph.grouped_chain_supports(
                        proof_chain, reasons
                    )
                    chains.append(proof_chain)
                    chain_reasons.append(reasons)
                    chain_supports.append(supports)
                technique = (
                    "Grouped X-Chain" if subtype == "x" else "Grouped AIC"
                )
                eliminations = {
                    candidate
                    for target in targets
                    for candidate in _node_candidates(target)
                }
                if collector.add(_deduction(
                    description=(
                        f"La {technique} usa {sum(isinstance(node, GroupNode) for node in central_nodes)} "
                        "nodi di gruppo e rende impossibili i candidati in "
                        "weak link con entrambi gli endpoint."
                    ),
                    eliminations=eliminations,
                    assumptions=tuple(item[0] for item in chains),
                    chains=chains,
                    reasons=tuple(sorted(set(chain(*chain_reasons)))),
                    chain_reasons=chain_reasons,
                    chain_supports=chain_supports,
                    kind="grouped-endpoint-aic",
                )):
                    return collector.results
        return collector.results

    def _grouped_forcing_deductions(self, *, max_results):
        collector = _DeductionCollector(max_results)

        def ranked_results():
            # Le strong discontinuity che risolvono piu' alternative della
            # stessa cella sono la forma piu' informativa del medesimo loop.
            # Il ranking non cambia le prove: rende solo equo il limite della
            # vista rispetto ai molti esiti atomici possibili.
            return sorted(
                collector.results,
                key=lambda item: (
                    -len(item.get("placements", ()))
                    - len(item.get("eliminations", ())),
                    tuple(item.get("placements", ())),
                    tuple(item.get("eliminations", ())),
                ),
            )

        allowed = frozenset({
            "peer", "x", "y", "group-weak", "group-strong",
        })
        for candidate in self.graph.all_candidates:
            for source_state in (True, False):
                source = _node_literal(candidate, source_state)
                path_data = self.graph.grouped_shortest_path(
                    source,
                    _graph_opposite(source),
                    allowed=allowed,
                    minimum_edges=3,
                    maximum_edges=MAX_STATIC_CYCLE_EDGES,
                    require_group=True,
                )
                if path_data is None:
                    continue
                path, reasons = path_data
                if source_state:
                    placements, eliminations = (), (candidate,)
                else:
                    # Una strong discontinuity rende vero il candidato. Per
                    # i Nice Loop esprimiamo l'effetto locale come rimozione
                    # delle alternative nella cella: e' la forma canonica
                    # usata anche dal corpus HoDoKu e conserva esattamente la
                    # conseguenza logica del loop.
                    placements = ()
                    eliminations = tuple(
                        (candidate[0], candidate[1], digit)
                        for digit in sorted(
                            self.candidates.get(candidate[:2], ())
                        )
                        if digit != candidate[2]
                    )
                if collector.add(_deduction(
                    description=(
                        "Il Grouped Nice Loop chiude una contraddizione sul "
                        f"candidato R{candidate[0]+1}C{candidate[1]+1}="
                        f"{candidate[2]}."
                    ),
                    placements=placements,
                    eliminations=eliminations,
                    assumptions=(source,),
                    chains=(path,),
                    reasons=reasons,
                    chain_reasons=(reasons,),
                    chain_supports=(
                        self.graph.grouped_chain_supports(path, reasons),
                    ),
                    kind="grouped-forcing-chain",
                )):
                    return ranked_results()
        return ranked_results()

    def _grouped_loop_eliminations(self, literals, reasons):
        eliminations = set()
        for source, target, reason in zip(
            literals, literals[1:], reasons
        ):
            if (
                not proof_model.literal_state(source)
                or proof_model.literal_state(target)
            ):
                continue
            first = _literal_node(source)
            second = _literal_node(target)
            members = {
                *_node_candidates(first),
                *_node_candidates(second),
            }
            if reason == "y" and not isinstance(first, GroupNode):
                row, column, _ = first
                for digit in self.candidates.get((row, column), ()):
                    candidate = (row, column, digit)
                    if candidate not in members:
                        eliminations.add(candidate)
                continue
            for candidate in self.graph.all_candidates:
                if candidate in members:
                    continue
                if (
                    self.graph.grouped_weak_reason(candidate, first)
                    and self.graph.grouped_weak_reason(candidate, second)
                ):
                    eliminations.add(candidate)
        return eliminations

    def _grouped_cycle_deductions(self, *, max_results):
        collector = _DeductionCollector(max_results)
        allowed = frozenset({
            "peer", "x", "y", "group-weak", "group-strong",
        })
        for literals, reasons in self.graph.grouped_cycles(
            allowed=allowed,
            maximum_edges=MAX_STATIC_CYCLE_EDGES,
        ):
            eliminations = self._grouped_loop_eliminations(literals, reasons)
            if not eliminations:
                continue
            body = literals[:-1]
            supports = self.graph.grouped_chain_supports(literals, reasons)
            if collector.add(_deduction(
                description=(
                    "Il Grouped Continuous Nice Loop rende strong ogni weak "
                    "link e applica la visibilità completa dei gruppi."
                ),
                eliminations=sorted(eliminations),
                assumptions=(body[0],),
                chains=(literals,),
                reasons=reasons,
                chain_reasons=(reasons,),
                chain_supports=(supports,),
                kind="grouped-cycle",
            )):
                break
        return collector.results

    def _find_grouped_chain(self, *, max_results):
        buckets = (
            self._grouped_endpoint_deductions("x", max_results=max_results),
            self._grouped_endpoint_deductions("aic", max_results=max_results),
            self._grouped_forcing_deductions(max_results=max_results),
            self._grouped_cycle_deductions(max_results=max_results),
        )
        deductions = []
        for index in range(max(map(len, buckets), default=0)):
            deductions.extend(
                bucket[index]
                for bucket in buckets
                if index < len(bucket)
            )
        return self._deduplicate(deductions, max_results=max_results)

    def _multiple_deductions(
        self,
        technique,
        source_groups,
        kind,
        *,
        max_results,
    ):
        collector = _DeductionCollector(max_results)
        allowed = frozenset({"peer", "x", "y"})

        for label, candidates in source_groups:
            if len(candidates) < 3:
                continue

            sources = [_literal(candidate, True) for candidate in candidates]
            closures = [self._closure(source, allowed) for source in sources]
            common = set.intersection(*(
                closure.literals for closure in closures
            ))

            for literal in sorted(common, key=_literal_key):
                candidate = _candidate(literal)

                if candidate not in self.graph.all_candidates:
                    continue

                if _opposite(literal) in common:
                    continue

                chains = [closure.path(literal) for closure in closures]

                if literal[3]:
                    placements, eliminations = (candidate,), ()
                    conclusion = (
                        f"R{candidate[0]+1}C{candidate[1]+1}="
                        f"{candidate[2]}"
                    )
                else:
                    placements, eliminations = (), (candidate,)
                    conclusion = (
                        f"il candidato {candidate[2]} in "
                        f"R{candidate[0]+1}C{candidate[1]+1}"
                    )

                if collector.add(_deduction(
                    description=(
                        f"Ogni alternativa di {label} implica "
                        f"{conclusion}; la conclusione e' quindi "
                        "indipendente dall'alternativa."
                    ),
                    placements=placements,
                    eliminations=eliminations,
                    assumptions=sources,
                    chains=chains,
                    reasons=("peer", "x", "y"),
                    kind=kind,
                )):
                    return collector.results

        return collector.results

    def _find_cell_forcing_chain(self, *, max_results):
        return self._multiple_deductions(
            "Cell Forcing Chain",
            self._cell_source_groups(),
            "cell-forcing-chain",
            max_results=max_results,
        )

    def _find_region_forcing_chain(self, *, max_results):
        return self._multiple_deductions(
            "Region Forcing Chain",
            self._region_source_groups(),
            "region-forcing-chain",
            max_results=max_results,
        )

    def _cell_source_groups(self):
        for (row, column), values in sorted(self.candidates.items()):
            candidates = [
                (row, column, value)
                for value in sorted(values)
            ]
            yield f"R{row+1}C{column+1}", candidates

    def _region_source_groups(self):
        for unit_index, (unit, kind) in enumerate(
            zip(UNITS, UNIT_KINDS)
        ):
            for value in range(1, 10):
                candidates = [
                    (row, column, value)
                    for row, column in unit
                    if value in self.candidates.get(
                        (row, column),
                        (),
                    )
                ]
                unit_name, visible_index = _visible_unit_reference(
                    unit_index
                )
                yield (
                    f"{unit_name} {visible_index} per il valore {value}",
                    candidates,
                )

    def _binary_dynamic(
        self,
        technique,
        *,
        required_feature,
        advanced_level,
        max_results,
        collector=None,
    ):
        collector = collector or _DeductionCollector(max_results)

        for candidate in self.graph.all_candidates:
            if collector.full:
                break

            source_on = _literal(candidate, True)
            source_off = _literal(candidate, False)
            on_result = self._propagate(
                source_on,
                mode="dynamic",
                advanced_level=advanced_level,
            )
            off_result = self._propagate(
                source_off,
                mode="dynamic",
                advanced_level=advanced_level,
            )

            if (
                on_result.contradiction
                and not off_result.contradiction
                and self._matches_feature_tier(
                    on_result.contradiction_features,
                    required_feature,
                )
            ):
                collector.add(_deduction(
                    description=(
                        f"L'ipotesi R{candidate[0]+1}C{candidate[1]+1}="
                        f"{candidate[2]} conduce a una contraddizione "
                        "dinamica."
                    ),
                    eliminations=(candidate,),
                    assumptions=(source_on,),
                    chains=(on_result.contradiction_path(),),
                    reasons=on_result.contradiction_features,
                    kind="dynamic-contradiction",
                ))
                continue

            if (
                off_result.contradiction
                and not on_result.contradiction
                and self._matches_feature_tier(
                    off_result.contradiction_features,
                    required_feature,
                )
            ):
                collector.add(_deduction(
                    description=(
                        f"Escludere {candidate[2]} da "
                        f"R{candidate[0]+1}C{candidate[1]+1} conduce "
                        "a una contraddizione dinamica."
                    ),
                    placements=(candidate,),
                    assumptions=(source_off,),
                    chains=(off_result.contradiction_path(),),
                    reasons=off_result.contradiction_features,
                    kind="dynamic-contradiction",
                ))
                continue

            if on_result.contradiction or off_result.contradiction:
                continue

            common = on_result.literals & off_result.literals

            for literal in sorted(common, key=_literal_key):
                combined_features = (
                    set(on_result.features.get(literal, ()))
                    | set(off_result.features.get(literal, ()))
                )

                if not self._matches_feature_tier(
                    combined_features,
                    required_feature,
                ):
                    continue

                target = _candidate(literal)

                if target not in self.graph.all_candidates:
                    continue

                if literal[3]:
                    placements, eliminations = (target,), ()
                    conclusion = "deve essere vero"
                else:
                    placements, eliminations = (), (target,)
                    conclusion = "deve essere falso"

                if collector.add(_deduction(
                    description=(
                        f"Sia assumendo sia escludendo {candidate[2]} in "
                        f"R{candidate[0]+1}C{candidate[1]+1}, il candidato "
                        f"{target[2]} in R{target[0]+1}C{target[1]+1} "
                        f"{conclusion}."
                    ),
                    placements=placements,
                    eliminations=eliminations,
                    assumptions=(source_on, source_off),
                    chains=(
                        on_result.path(literal),
                        off_result.path(literal),
                    ),
                    reasons=combined_features,
                    kind="dynamic-reduction",
                )):
                    break

        return collector.results

    def _multiple_dynamic(
        self,
        technique,
        *,
        required_feature,
        advanced_level,
        max_results,
        collector=None,
    ):
        """Riduzioni dinamiche comuni a tutte le scelte di cella o casa."""
        collector = collector or _DeductionCollector(max_results)
        groups = chain(
            (
                ("cell", label, candidates)
                for label, candidates in self._cell_source_groups()
            ),
            (
                ("region", label, candidates)
                for label, candidates in self._region_source_groups()
            ),
        )

        for source_kind, label, candidates in groups:
            if collector.full:
                break

            if len(candidates) < 3:
                continue

            sources = [_literal(candidate, True) for candidate in candidates]
            outcomes = [
                self._propagate(
                    source,
                    mode="dynamic",
                    advanced_level=advanced_level,
                )
                for source in sources
            ]

            # Un ramo contraddittorio produce prima una riduzione binaria più
            # semplice; non si usa il principio di esplosione nell'incrocio.
            if any(outcome.contradiction for outcome in outcomes):
                continue

            common = set.intersection(*(
                outcome.literals for outcome in outcomes
            ))

            for literal in sorted(common, key=_literal_key):
                target = _candidate(literal)

                if target not in self.graph.all_candidates:
                    continue

                features = set().union(*(
                    outcome.features.get(literal, frozenset())
                    for outcome in outcomes
                ))

                if not self._matches_feature_tier(
                    features,
                    required_feature,
                ):
                    continue

                if literal[3]:
                    placements, eliminations = (target,), ()
                    conclusion = "deve essere vero"
                else:
                    placements, eliminations = (), (target,)
                    conclusion = "deve essere falso"

                if collector.add(_deduction(
                    description=(
                        f"Ogni alternativa dinamica di {label} implica "
                        f"che {target[2]} in "
                        f"R{target[0]+1}C{target[1]+1} {conclusion}."
                    ),
                    placements=placements,
                    eliminations=eliminations,
                    assumptions=sources,
                    chains=tuple(
                        outcome.path(literal)
                        for outcome in outcomes
                    ),
                    reasons=features,
                    kind=f"dynamic-{source_kind}-reduction",
                )):
                    break

        return collector.results

    def _find_nishio(self, *, max_results):
        collector = _DeductionCollector(max_results)

        for candidate in self.graph.all_candidates:
            if collector.full:
                break

            source_on = _literal(candidate, True)
            source_off = _literal(candidate, False)
            on_outcome = self._propagate(source_on, mode="nishio")
            off_outcome = self._propagate(source_off, mode="nishio")

            if on_outcome.contradiction and not off_outcome.contradiction:
                collector.add(_deduction(
                    description=(
                        f"L'ipotesi Nishio "
                        f"R{candidate[0]+1}C{candidate[1]+1}="
                        f"{candidate[2]} esaurisce una casa per quel "
                        "valore."
                    ),
                    eliminations=(candidate,),
                    assumptions=(source_on,),
                    chains=(on_outcome.contradiction_path(),),
                    reasons=("x", "dynamic"),
                    kind="nishio",
                ))
            elif (
                off_outcome.contradiction
                and not on_outcome.contradiction
            ):
                collector.add(_deduction(
                    description=(
                        f"L'esclusione Nishio di {candidate[2]} in "
                        f"R{candidate[0]+1}C{candidate[1]+1} esaurisce "
                        "una casa: il candidato deve essere vero."
                    ),
                    placements=(candidate,),
                    assumptions=(source_off,),
                    chains=(off_outcome.contradiction_path(),),
                    reasons=("x", "dynamic"),
                    kind="nishio",
                ))

        return collector.results

    def _dynamic_tier(
        self,
        technique,
        *,
        required_feature,
        advanced_level,
        max_results,
    ):
        collector = _DeductionCollector(max_results)
        self._binary_dynamic(
            technique,
            required_feature=required_feature,
            advanced_level=advanced_level,
            max_results=max_results,
            collector=collector,
        )

        if not collector.full:
            self._multiple_dynamic(
                technique,
                required_feature=required_feature,
                advanced_level=advanced_level,
                max_results=max_results,
                collector=collector,
            )

        return collector.results

    def _find_dynamic_forcing_chain(self, *, max_results):
        return self._dynamic_tier(
            "Dynamic Forcing Chain",
            required_feature="dynamic",
            advanced_level=0,
            max_results=max_results,
        )

    def _find_dynamic_forcing_chain_plus(self, *, max_results):
        return self._dynamic_tier(
            "Dynamic Forcing Chain Plus",
            required_feature="advanced",
            advanced_level=1,
            max_results=max_results,
        )

    def _find_nested_forcing_chain(self, *, max_results):
        # Il vero nested riutilizzabile verra' introdotto dalla relativa
        # patch. Non deve mai delegare alla ricerca esaustiva completa.
        return []

    def _find_complete_forcing_tree(self, *, max_results):
        max_results = _technique_result_limit(
            _COMPLETE_TREE_TECHNIQUE,
            max_results,
        )

        if self._complete_forcing_tree_search is None:
            self._complete_forcing_tree_search = CompleteForcingTreeSearch(
                self.grid,
                self.candidates,
            )

        return self._complete_forcing_tree_search.find_deductions(
            max_results=max_results,
        )


# Cache LRU indicizzata dal contenuto logico dello stato, non dall'identità
# dell'oggetto Python. Anche due SudokuState distinti ma equivalenti possono
# quindi riutilizzare lo stesso motore già preparato.
_ENGINE_CACHE_MAXSIZE = 8
_ENGINE_CACHE = OrderedDict()
_ENGINE_CACHE_LOCK = RLock()
_ENGINE_CACHE_HITS = 0
_ENGINE_CACHE_MISSES = 0


def _engine_for(state):
    global _ENGINE_CACHE_HITS, _ENGINE_CACHE_MISSES

    fingerprint = _fingerprint(state)
    with _ENGINE_CACHE_LOCK:
        engine = _ENGINE_CACHE.get(fingerprint)
        if engine is not None:
            _ENGINE_CACHE_HITS += 1
            _ENGINE_CACHE.move_to_end(fingerprint)
            return engine

        _ENGINE_CACHE_MISSES += 1
        engine = LogicEngine(state)
        _ENGINE_CACHE[fingerprint] = engine
        _ENGINE_CACHE.move_to_end(fingerprint)

        while len(_ENGINE_CACHE) > _ENGINE_CACHE_MAXSIZE:
            _ENGINE_CACHE.popitem(last=False)

        return engine


def prepare_logic_cache(
    state,
    technique=None,
    batch=None,
    max_results=DEFAULT_MAX_DEDUCTIONS_PER_TECHNIQUE,
):
    """Prepara soltanto la tecnica o il batch richiesto.

    ``max_results`` viene applicato durante la ricerca e resta soggetto ai
    limiti globali del Logic Engine. Le strutture comuni già calcolate per lo
    stesso stato vengono riutilizzate, senza promuovere implicitamente una
    richiesta Dynamic a Plus o Nested.
    """
    if technique is not None and batch is not None:
        raise ValueError("Usa technique oppure batch, non entrambi.")

    engine = _engine_for(state)
    target = technique if technique is not None else (batch or "all")
    engine.prepare(target, max_results=max_results)
    return engine


def get_cached_logic_deductions(
    state,
    technique: str,
    max_results=DEFAULT_MAX_DEDUCTIONS_PER_TECHNIQUE,
):
    """Legge una tecnica già preparata con un limite sufficiente."""
    return _engine_for(state).get_cached(
        technique,
        max_results=max_results,
    )


def find_logic_deductions(
    state,
    technique: str,
    max_results=DEFAULT_MAX_DEDUCTIONS_PER_TECHNIQUE,
):
    """Cerca una tecnica fermandosi agli esiti distinti richiesti."""
    return _engine_for(state).find(
        technique,
        max_results=max_results,
    )


def static_implication_graph(state):
    """Vista pubblica e condivisa del grafo statico dello stato."""
    return _engine_for(state).graph


def clear_logic_cache(state=None):
    """Svuota tutta la cache o soltanto la firma dello stato indicato."""
    global _ENGINE_CACHE_HITS, _ENGINE_CACHE_MISSES

    with _ENGINE_CACHE_LOCK:
        if state is None:
            _ENGINE_CACHE.clear()
            _ENGINE_CACHE_HITS = 0
            _ENGINE_CACHE_MISSES = 0
            return

        _ENGINE_CACHE.pop(_fingerprint(state), None)


def logic_cache_info():
    """Restituisce statistiche leggere della cache globale."""
    with _ENGINE_CACHE_LOCK:
        return {
            "size": len(_ENGINE_CACHE),
            "maxsize": _ENGINE_CACHE_MAXSIZE,
            "hits": _ENGINE_CACHE_HITS,
            "misses": _ENGINE_CACHE_MISSES,
            "prepared_batches": sum(
                len(engine._prepared_batches)
                for engine in _ENGINE_CACHE.values()
            ),
            "cached_techniques": sum(
                len(engine._results)
                for engine in _ENGINE_CACHE.values()
            ),
            "cached_propagations": sum(
                len(engine._propagation_cache)
                for engine in _ENGINE_CACHE.values()
            ),
        }


__all__ = [
    "Candidate",
    "CompleteForcingTreeSearch",
    "Literal",
    "DEFAULT_MAX_DEDUCTIONS_PER_TECHNIQUE",
    "LOGIC_TECHNIQUE_BATCHES",
    "MAX_DEDUCTIONS_PER_TECHNIQUE",
    "MAX_COMPLETE_TREE_DEDUCTIONS",
    "MAX_COMPLETE_TREE_TECHNIQUES",
    "MAX_NESTED_DEDUCTIONS",
    "MAX_NESTED_TECHNIQUES",
    "MAX_STATIC_CYCLE_EDGES",
    "MAX_TECHNIQUES",
    "STORE_COMPLETE_FORCING_TREE_PROOF",
    "LogicEngine",
    "StaticImplicationGraph",
    "clear_logic_cache",
    "find_logic_deductions",
    "get_cached_logic_deductions",
    "logic_cache_info",
    "prepare_logic_cache",
    "static_implication_graph",
]
