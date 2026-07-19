"""Motore logico per catene, cicli e forcing del solver Sudoku.

Il modulo lavora sui *letterali candidato* ``(riga, colonna, valore, stato)``:
``stato=True`` significa che il candidato e' assunto vero, ``False`` che e'
assunto falso.  Le implicazioni statiche sono di due tipi:

* X: stesso valore in celle che si vedono;
* Y: valori diversi nella stessa cella.

Le propagazioni dinamiche applicano le esclusioni a una copia locale dei
candidati e scoprono quindi nuovi single.  I livelli Plus aggiungono locking,
coppie e X-Wing; il livello nested puo' usare una catena statica come
sotto-prova.  Nessuna funzione modifica il ``SudokuState`` ricevuto.

L'API pubblica e' intenzionalmente piccola: ``find_logic_deductions``
restituisce deduzioni neutrali.  ``sudoku_techniques`` le converte nel formato
Move usato dal resto del progetto, mantenendo le interfacce storiche.
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict, deque
from copy import deepcopy
from dataclasses import dataclass
from itertools import combinations
from threading import RLock

from sudoku_data_structure import UNITS, UNIT_KINDS, peers


Candidate = tuple[int, int, int]
Literal = tuple[int, int, int, bool]


# Le tecniche sono raggruppate in batch con strutture e propagazioni comuni.
# La prima richiesta di una tecnica prepara l'intero batch; le richieste
# successive dello stesso stato leggono esclusivamente i risultati in cache.
LOGIC_TECHNIQUE_BATCHES = {
    "static": (
        "Bidirectional X-Cycle",
        "XY-Chain",
        "Bidirectional Y-Cycle",
        "Forcing X-Chain",
        "Forcing Chain",
        "Bidirectional Cycle",
    ),
    "multiple": (
        "Nishio",
        "Cell Forcing Chain",
        "Region Forcing Chain",
    ),
    "dynamic": (
        "Dynamic Forcing Chain",
        "Dynamic Forcing Chain Plus",
        "Nested Forcing Chain",
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


def _literal(candidate: Candidate, is_on: bool) -> Literal:
    return candidate[0], candidate[1], candidate[2], is_on


def _candidate(literal: Literal) -> Candidate:
    return literal[0], literal[1], literal[2]


def _opposite(literal: Literal) -> Literal:
    return literal[0], literal[1], literal[2], not literal[3]


def _candidate_key(candidate: Candidate) -> tuple[int, int, int]:
    return candidate


def _literal_key(literal: Literal) -> tuple[int, int, int, int]:
    return literal[0], literal[1], literal[2], int(literal[3])


def _sees(first: Candidate, second: Candidate) -> bool:
    """True se i candidati uguali appartengono a celle peer distinte."""
    if first[2] != second[2] or first[:2] == second[:2]:
        return False
    return second[:2] in peers(first[0], first[1])


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


def _literal_record(literal: Literal) -> dict:
    row, column, value, is_on = literal
    return {
        "row": row,
        "column": column,
        "value": value,
        "state": "on" if is_on else "off",
    }


def _proof(kind: str, assumptions, chains, reasons=None) -> dict:
    return {
        "kind": kind,
        "assumptions": [_literal_record(item) for item in assumptions],
        "chains": [
            [_literal_record(item) for item in chain]
            for chain in chains
        ],
        "reasons": sorted(set(reasons or ())),
    }


def _deduction(
    *,
    description: str,
    placements=(),
    eliminations=(),
    assumptions=(),
    chains=(),
    reasons=(),
    kind: str,
) -> dict:
    placements = sorted(set(placements), key=_candidate_key)
    eliminations = sorted(set(eliminations), key=_candidate_key)
    chain_list = [list(chain) for chain in chains if chain]
    primary = sorted({
        (literal[0], literal[1])
        for chain in chain_list
        for literal in chain
    } | {
        (literal[0], literal[1]) for literal in assumptions
    })
    return {
        "description": description,
        "placements": placements,
        "eliminations": eliminations,
        "primary": primary,
        "logic": _proof(kind, assumptions, chain_list, reasons),
    }


@dataclass(frozen=True)
class Edge:
    target: Literal
    reason: str  # "peer" (debole), "x" (forte) oppure "y"


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
        adjacency: dict[Literal, set[tuple[Literal, str]]] = defaultdict(set)

        # Collegamenti Y: un candidato ON spegne gli altri nella cella;
        # in una cella bivalue un candidato OFF accende l'altro.
        for (row, column), values in self.candidates.items():
            ordered = sorted(values)
            for value in ordered:
                source = (row, column, value)
                for other in ordered:
                    if other != value:
                        adjacency[_literal(source, True)].add(
                            (_literal((row, column, other), False), "y")
                        )
            if len(ordered) == 2:
                first = (row, column, ordered[0])
                second = (row, column, ordered[1])
                adjacency[_literal(first, False)].add((_literal(second, True), "y"))
                adjacency[_literal(second, False)].add((_literal(first, True), "y"))

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
                    adjacency[_literal(candidate, True)].add(
                        (_literal(other, False), "peer")
                    )

        # Collegamenti X forti: due sole posizioni di un valore in una casa.
        for unit in UNITS:
            for value in range(1, 10):
                positions = [
                    (row, column, value)
                    for row, column in unit
                    if value in self.candidates.get((row, column), ())
                ]
                if len(positions) == 2:
                    first, second = positions
                    adjacency[_literal(first, False)].add((_literal(second, True), "x"))
                    adjacency[_literal(second, False)].add((_literal(first, True), "x"))

        self.adjacency = {
            source: tuple(
                Edge(target, reason)
                for target, reason in sorted(
                    targets,
                    key=lambda item: (_literal_key(item[0]), item[1]),
                )
            )
            for source, targets in adjacency.items()
        }

    def edges(self, source: Literal, allowed: frozenset[str]):
        return (
            edge for edge in self.adjacency.get(source, ())
            if edge.reason in allowed
        )

    def shortest_path(
        self,
        source: Literal,
        target: Literal,
        *,
        allowed: frozenset[str],
        required: frozenset[str] = frozenset(),
        minimum_edges: int = 1,
        maximum_edges: int = 16,
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

            if depth >= maximum_edges:
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
        maximum_edges: int = 14,
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
                if len(path_reasons) >= maximum_edges:
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
        body = tuple(literals[:-1])
        pairs = tuple(zip(body, reasons))
        rotations = [pairs[index:] + pairs[:index] for index in range(len(pairs))]
        reverse_body = tuple(reversed(body))
        reverse_reasons = tuple(reversed(reasons))
        reverse_pairs = tuple(zip(reverse_body, reverse_reasons))
        rotations.extend(
            reverse_pairs[index:] + reverse_pairs[:index]
            for index in range(len(reverse_pairs))
        )
        return min(rotations)


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
            nested = []
            if advanced_level >= 2 and not advanced:
                nested = self._nested_implications(work)

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
            for literal, path in nested:
                candidate = _candidate(literal)
                if literal[3] or candidate[2] in work.get(candidate[:2], ()):
                    pending.append((
                        literal,
                        (source,),
                        "nested-chain",
                        frozenset({"nested"}),
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

    def _nested_implications(self, work):
        """Trova sotto-catene statiche nel ramo dinamico corrente."""
        graph = StaticImplicationGraph(work)
        result = []
        for candidate in graph.all_candidates:
            for source_state in (True, False):
                source = _literal(candidate, source_state)
                target = _opposite(source)
                path_data = graph.shortest_path(
                    source,
                    target,
                    allowed=frozenset({"peer", "x", "y"}),
                    required=frozenset({"x", "y"}),
                    minimum_edges=3,
                    maximum_edges=12,
                )
                if path_data:
                    path, _ = path_data
                    baseline = self.initial_graph.shortest_path(
                        source,
                        target,
                        allowed=frozenset({"peer", "x", "y"}),
                        required=frozenset({"x", "y"}),
                        minimum_edges=3,
                        maximum_edges=12,
                    )
                    if baseline:
                        continue
                    result.append((target, path))
            if result:
                # Una sotto-prova per ciclo e' sufficiente a proseguire la
                # propagazione; le iterazioni successive possono trovarne altre.
                break
        return result


class LogicEngine:
    """Facade che calcola e memorizza le deduzioni per uno stato immutato."""

    def __init__(self, state):
        self.grid = state.grid.copy()
        self.candidates = _candidate_map(state)
        self.graph = StaticImplicationGraph(self.candidates)
        self.propagator = DynamicPropagator(self.grid, self.candidates)
        self._results = {}
        self._prepared_batches = set()
        self._propagation_cache = {}
        self._closure_cache = {}
        self._lock = RLock()

    def _propagate(self, source, *, mode="dynamic", advanced_level=0):
        # I tre livelli dinamici condividono la stessa propagazione massima.
        # Le deduzioni vengono poi attribuite a Dynamic, Plus o Nested in
        # base alle feature minime della prova. Questo evita tre esplorazioni
        # quasi identiche per ogni assunzione. Nishio resta separato.
        effective_level = 2 if mode == "dynamic" else advanced_level
        key = source, mode, effective_level
        if key not in self._propagation_cache:
            self._propagation_cache[key] = self.propagator.propagate(
                source,
                mode=mode,
                advanced_level=effective_level,
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

    def _compute(self, technique):
        method = getattr(self, self._method_name(technique), None)
        if method is None:
            raise KeyError(f"Tecnica logica sconosciuta: {technique}")
        self._results[technique] = self._deduplicate(method())

    def prepare(self, batch="all"):
        """Precalcola un batch logico una sola volta per questo stato.

        ``batch`` può essere ``static``, ``multiple``, ``dynamic``, ``all``
        oppure il nome di una tecnica. Le chiamate successive non eseguono
        ricerca: leggono soltanto ``self._results``.
        """
        if batch in _LOGIC_TECHNIQUE_TO_BATCH:
            batch = _LOGIC_TECHNIQUE_TO_BATCH[batch]

        if batch == "all":
            batch_names = ("static", "multiple", "dynamic")
        elif batch in LOGIC_TECHNIQUE_BATCHES:
            batch_names = (batch,)
        else:
            raise KeyError(f"Batch logico sconosciuto: {batch}")

        with self._lock:
            for batch_name in batch_names:
                if batch_name in self._prepared_batches:
                    continue
                for technique in LOGIC_TECHNIQUE_BATCHES[batch_name]:
                    if technique not in self._results:
                        self._compute(technique)
                self._prepared_batches.add(batch_name)

    def get_cached(self, technique):
        if technique not in self._results:
            raise KeyError(
                f"La tecnica {technique!r} non è ancora nella cache logica."
            )
        return deepcopy(self._results[technique])

    def find(self, technique: str):
        self.prepare(technique)
        return self.get_cached(technique)

    @staticmethod
    def _deduplicate(deductions):
        result = []
        seen = set()
        for deduction in deductions:
            signature = (
                tuple(deduction["placements"]),
                tuple(deduction["eliminations"]),
            )
            if signature == ((), ()) or signature in seen:
                continue
            seen.add(signature)
            result.append(deduction)
        return result

    def _cycle_deductions(self, technique, allowed, required):
        result = []
        seen_eliminations = set()
        for literals, reasons in self.graph.cycles(
            allowed=frozenset(allowed),
            required=frozenset(required),
        ):
            body = literals[:-1]
            chain_cells = {(item[0], item[1]) for item in body}
            on_candidates = [_candidate(item) for item in body if item[3]]
            off_candidates = [_candidate(item) for item in body if not item[3]]
            eliminations = []
            for candidate in self.graph.all_candidates:
                if candidate[:2] in chain_cells:
                    continue
                if (
                    any(_sees(candidate, item) for item in on_candidates)
                    and any(_sees(candidate, item) for item in off_candidates)
                ):
                    eliminations.append(candidate)
            signature = tuple(eliminations)
            if not eliminations or signature in seen_eliminations:
                continue
            seen_eliminations.add(signature)
            result.append(_deduction(
                description=(
                    f"Il {technique} alterna {len(body)} implicazioni: "
                    "i candidati che vedono entrambi i colori del ciclo "
                    "sono impossibili."
                ),
                eliminations=eliminations,
                assumptions=(body[0],),
                chains=(literals,),
                reasons=reasons,
                kind="bidirectional-cycle",
            ))
        return result

    def _find_bidirectional_x_cycle(self):
        return self._cycle_deductions(
            "Bidirectional X-Cycle", {"peer", "x"}, {"peer", "x"}
        )

    def _find_bidirectional_y_cycle(self):
        return self._cycle_deductions(
            "Bidirectional Y-Cycle", {"peer", "y"}, {"peer", "y"}
        )

    def _find_bidirectional_cycle(self):
        return self._cycle_deductions(
            "Bidirectional Cycle", {"peer", "x", "y"}, {"x", "y"}
        )

    def _forcing_deductions(self, technique, allowed, required):
        result = []
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
                    placements = (candidate,)
                    eliminations = ()
                    conclusion = "deve essere vero"
                result.append(_deduction(
                    description=(
                        f"Assumere R{candidate[0]+1}C{candidate[1]+1}="
                        f"{candidate[2]} {('vero' if source_state else 'falso')} "
                        f"implica il contrario: il candidato {conclusion}."
                    ),
                    placements=placements,
                    eliminations=eliminations,
                    assumptions=(source,),
                    chains=(path,),
                    reasons=reasons,
                    kind="forcing-chain",
                ))
        return result

    def _find_forcing_x_chain(self):
        return self._forcing_deductions(
            "Forcing X-Chain", {"peer", "x"}, {"peer", "x"}
        )

    def _find_xy_chain(self):
        # Una XY-Chain è la forcing chain puramente bivalue: i link deboli
        # passano fra celle peer e i link forti Y cambiano candidato dentro
        # la cella. Le conclusioni ON restano cicli discontinui generali;
        # il nome moderno XY-Chain è riservato alle eliminazioni canoniche.
        return [
            deduction
            for deduction in self._forcing_deductions(
                "XY-Chain", {"peer", "y"}, {"peer", "y"}
            )
            if deduction["eliminations"]
        ]

    def _find_forcing_chain(self):
        return self._forcing_deductions(
            "Forcing Chain", {"peer", "x", "y"}, {"x", "y"}
        )

    def _multiple_deductions(self, technique, source_groups, kind):
        result = []
        allowed = frozenset({"peer", "x", "y"})
        for label, candidates in source_groups:
            if len(candidates) < 3:
                continue
            sources = [_literal(candidate, True) for candidate in candidates]
            closures = [self._closure(source, allowed) for source in sources]
            common = set.intersection(*(closure.literals for closure in closures))
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
                        f"R{candidate[0]+1}C{candidate[1]+1}={candidate[2]}"
                    )
                else:
                    placements, eliminations = (), (candidate,)
                    conclusion = (
                        f"il candidato {candidate[2]} in "
                        f"R{candidate[0]+1}C{candidate[1]+1}"
                    )
                result.append(_deduction(
                    description=(
                        f"Ogni alternativa di {label} implica {conclusion}; "
                        "la conclusione e' quindi indipendente dall'alternativa."
                    ),
                    placements=placements,
                    eliminations=eliminations,
                    assumptions=sources,
                    chains=chains,
                    reasons=("peer", "x", "y"),
                    kind=kind,
                ))
        return result

    def _find_cell_forcing_chain(self):
        return self._multiple_deductions(
            "Cell Forcing Chain",
            self._cell_source_groups(),
            "cell-forcing-chain",
        )

    def _find_region_forcing_chain(self):
        return self._multiple_deductions(
            "Region Forcing Chain",
            self._region_source_groups(),
            "region-forcing-chain",
        )

    def _cell_source_groups(self):
        groups = []
        for (row, column), values in sorted(self.candidates.items()):
            candidates = [(row, column, value) for value in sorted(values)]
            groups.append((f"R{row+1}C{column+1}", candidates))
        return groups

    def _region_source_groups(self):
        groups = []
        for unit_index, (unit, kind) in enumerate(zip(UNITS, UNIT_KINDS)):
            for value in range(1, 10):
                candidates = [
                    (row, column, value)
                    for row, column in unit
                    if value in self.candidates.get((row, column), ())
                ]
                groups.append((
                    f"{kind} {unit_index + 1 if kind == 'row' else unit_index - 8 if kind == 'col' else unit_index - 17} per il valore {value}",
                    candidates,
                ))
        return groups

    def _binary_dynamic(self, technique, *, required_feature, advanced_level):
        result = []
        for candidate in self.graph.all_candidates:
            source_on = _literal(candidate, True)
            source_off = _literal(candidate, False)
            on_result = self._propagate(
                source_on, mode="dynamic", advanced_level=advanced_level
            )
            off_result = self._propagate(
                source_off, mode="dynamic", advanced_level=advanced_level
            )

            if (
                on_result.contradiction
                and not off_result.contradiction
                and self._matches_feature_tier(
                    on_result.contradiction_features, required_feature
                )
            ):
                result.append(_deduction(
                    description=(
                        f"L'ipotesi R{candidate[0]+1}C{candidate[1]+1}="
                        f"{candidate[2]} conduce a una contraddizione dinamica."
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
                    off_result.contradiction_features, required_feature
                )
            ):
                result.append(_deduction(
                    description=(
                        f"Escludere {candidate[2]} da R{candidate[0]+1}"
                        f"C{candidate[1]+1} conduce a una contraddizione dinamica."
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
                    combined_features, required_feature
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
                result.append(_deduction(
                    description=(
                        f"Sia assumendo sia escludendo {candidate[2]} in "
                        f"R{candidate[0]+1}C{candidate[1]+1}, il candidato "
                        f"{target[2]} in R{target[0]+1}C{target[1]+1} "
                        f"{conclusion}."
                    ),
                    placements=placements,
                    eliminations=eliminations,
                    assumptions=(source_on, source_off),
                    chains=(on_result.path(literal), off_result.path(literal)),
                    reasons=combined_features,
                    kind="dynamic-reduction",
                ))
        return result

    def _multiple_dynamic(self, technique, *, required_feature, advanced_level):
        """Riduzioni dinamiche comuni a tutte le scelte di cella o casa."""
        result = []
        groups = [
            ("cell", label, candidates)
            for label, candidates in self._cell_source_groups()
        ] + [
            ("region", label, candidates)
            for label, candidates in self._region_source_groups()
        ]
        for source_kind, label, candidates in groups:
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
            common = set.intersection(*(outcome.literals for outcome in outcomes))
            for literal in sorted(common, key=_literal_key):
                target = _candidate(literal)
                if target not in self.graph.all_candidates:
                    continue
                features = set().union(*(
                    outcome.features.get(literal, frozenset())
                    for outcome in outcomes
                ))
                if not self._matches_feature_tier(features, required_feature):
                    continue
                if literal[3]:
                    placements, eliminations = (target,), ()
                    conclusion = "deve essere vero"
                else:
                    placements, eliminations = (), (target,)
                    conclusion = "deve essere falso"
                result.append(_deduction(
                    description=(
                        f"Ogni alternativa dinamica di {label} implica che "
                        f"{target[2]} in R{target[0]+1}C{target[1]+1} "
                        f"{conclusion}."
                    ),
                    placements=placements,
                    eliminations=eliminations,
                    assumptions=sources,
                    chains=tuple(
                        outcome.path(literal) for outcome in outcomes
                    ),
                    reasons=features,
                    kind=f"dynamic-{source_kind}-reduction",
                ))
        return result

    def _find_nishio(self):
        result = []
        for candidate in self.graph.all_candidates:
            source_on = _literal(candidate, True)
            source_off = _literal(candidate, False)
            on_outcome = self._propagate(source_on, mode="nishio")
            off_outcome = self._propagate(source_off, mode="nishio")
            if on_outcome.contradiction and not off_outcome.contradiction:
                result.append(_deduction(
                    description=(
                        f"L'ipotesi Nishio R{candidate[0]+1}C{candidate[1]+1}="
                        f"{candidate[2]} esaurisce una casa per quel valore."
                    ),
                    eliminations=(candidate,),
                    assumptions=(source_on,),
                    chains=(on_outcome.contradiction_path(),),
                    reasons=("x", "dynamic"),
                    kind="nishio",
                ))
            elif off_outcome.contradiction and not on_outcome.contradiction:
                result.append(_deduction(
                    description=(
                        f"L'esclusione Nishio di {candidate[2]} in "
                        f"R{candidate[0]+1}C{candidate[1]+1} esaurisce una "
                        "casa: il candidato deve essere vero."
                    ),
                    placements=(candidate,),
                    assumptions=(source_off,),
                    chains=(off_outcome.contradiction_path(),),
                    reasons=("x", "dynamic"),
                    kind="nishio",
                ))
        return result

    def _find_dynamic_forcing_chain(self):
        return self._binary_dynamic(
            "Dynamic Forcing Chain",
            required_feature="dynamic",
            advanced_level=0,
        ) + self._multiple_dynamic(
            "Dynamic Forcing Chain",
            required_feature="dynamic",
            advanced_level=0,
        )

    def _find_dynamic_forcing_chain_plus(self):
        return self._binary_dynamic(
            "Dynamic Forcing Chain Plus",
            required_feature="advanced",
            advanced_level=1,
        ) + self._multiple_dynamic(
            "Dynamic Forcing Chain Plus",
            required_feature="advanced",
            advanced_level=1,
        )

    def _find_nested_forcing_chain(self):
        return self._binary_dynamic(
            "Nested Forcing Chain",
            required_feature="nested",
            advanced_level=2,
        ) + self._multiple_dynamic(
            "Nested Forcing Chain",
            required_feature="nested",
            advanced_level=2,
        )


# Cache LRU indicizzata dal contenuto logico dello stato, non dall'identità
# dell'oggetto Python. Anche due SudokuState distinti ma equivalenti possono
# quindi riutilizzare lo stesso motore già preparato.
_ENGINE_CACHE_MAXSIZE = 32
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


def prepare_logic_cache(state, technique=None, batch=None):
    """Prepara la cache logica dello stato e restituisce il motore.

    Se viene fornita ``technique``, viene preparato il batch che la contiene.
    Con ``batch`` si può richiedere esplicitamente ``static``, ``multiple``,
    ``dynamic`` o ``all``. Senza argomenti prepara l'inventario completo.
    """
    if technique is not None and batch is not None:
        raise ValueError("Usa technique oppure batch, non entrambi.")

    engine = _engine_for(state)
    target = technique if technique is not None else (batch or "all")
    engine.prepare(target)
    return engine


def get_cached_logic_deductions(state, technique: str):
    """Legge una tecnica già preparata senza avviare alcuna ricerca."""
    return _engine_for(state).get_cached(technique)


def find_logic_deductions(state, technique: str):
    """Prepara il batch della tecnica e ne restituisce le deduzioni."""
    engine = prepare_logic_cache(state, technique=technique)
    return engine.get_cached(technique)


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
    "Literal",
    "LOGIC_TECHNIQUE_BATCHES",
    "LogicEngine",
    "StaticImplicationGraph",
    "clear_logic_cache",
    "find_logic_deductions",
    "get_cached_logic_deductions",
    "logic_cache_info",
    "prepare_logic_cache",
]
