"""Coloring parametrico sul grafo delle coppie coniugate.

Il modulo non ricostruisce strong link parallele: usa la vista X di
``StaticImplicationGraph`` e colora bipartitamente ogni sua componente a
cifra singola. Le conclusioni Simple e Multi Colors conservano sia il pattern
strutturale sia catene alternate ``peer``/``x`` convertibili in ``ProofDAG``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from itertools import combinations
from typing import Iterable, TypeAlias

from .data_structure import peers
from . import logic_engine
from . import proof as proof_model
from . import proof_schema


Candidate: TypeAlias = tuple[int, int, int]
Literal: TypeAlias = tuple[int, int, int, bool]
ColorLink: TypeAlias = tuple[Candidate, Candidate]

TECHNIQUE_NAMES = {
    "color.simple.trap": "Simple Colors: Color Trap",
    "color.simple.wrap": "Simple Colors: Color Wrap",
    "color.multi.type1": "Multi Colors Type 1",
    "color.multi.type2": "Multi Colors Type 2",
}


def _candidate(value) -> Candidate:
    row, column, digit = value
    candidate = int(row), int(column), int(digit)
    if not (
        0 <= candidate[0] < 9
        and 0 <= candidate[1] < 9
        and 1 <= candidate[2] <= 9
    ):
        raise ValueError(f"Candidato coloring non valido: {candidate!r}.")
    return candidate


def _link(first, second) -> ColorLink:
    first = _candidate(first)
    second = _candidate(second)
    if first == second or first[2] != second[2]:
        raise ValueError("Un color link richiede due candidati distinti uguali.")
    return tuple(sorted((first, second)))


def _sees(first: Candidate, second: Candidate) -> bool:
    return (
        first[2] == second[2]
        and first[:2] != second[:2]
        and second[:2] in peers(first[0], first[1])
    )


def _literal(candidate: Candidate, is_on: bool) -> Literal:
    return candidate[0], candidate[1], candidate[2], bool(is_on)


@dataclass(frozen=True, slots=True)
class ColorComponent:
    """Componente connessa e bipartita del grafo delle conjugate pair."""

    digit: int
    component_id: int
    colors: tuple[frozenset[Candidate], frozenset[Candidate]]
    links: tuple[ColorLink, ...]

    def __post_init__(self):
        if self.digit not in range(1, 10):
            raise ValueError("La cifra della componente deve essere 1-9.")
        if self.component_id < 0:
            raise ValueError("component_id non può essere negativo.")
        if len(self.colors) != 2 or not all(self.colors):
            raise ValueError("Una componente deve avere due colori non vuoti.")
        if self.colors[0] & self.colors[1]:
            raise ValueError("I due colori devono essere disgiunti.")
        if any(
            candidate[2] != self.digit
            for candidate in self.nodes
        ):
            raise ValueError("Tutti i nodi devono usare la cifra della componente.")
        if not self.links:
            raise ValueError("Una componente coloring richiede almeno un link.")
        for first, second in self.links:
            if (
                first not in self.nodes
                or second not in self.nodes
                or self.color_of(first) == self.color_of(second)
            ):
                raise ValueError("Ogni strong link deve attraversare i due colori.")

    @property
    def nodes(self) -> frozenset[Candidate]:
        return self.colors[0] | self.colors[1]

    def color_of(self, candidate: Candidate) -> int:
        candidate = _candidate(candidate)
        if candidate in self.colors[0]:
            return 0
        if candidate in self.colors[1]:
            return 1
        raise KeyError(f"Il candidato {candidate!r} non appartiene alla componente.")

    def path(self, source: Candidate, target: Candidate) -> tuple[Candidate, ...]:
        """Cammino strong minimo e deterministico fra due nodi."""
        source = _candidate(source)
        target = _candidate(target)
        if source not in self.nodes or target not in self.nodes:
            raise KeyError("Gli estremi del cammino devono essere nella componente.")
        if source == target:
            return (source,)

        adjacency = {candidate: set() for candidate in self.nodes}
        for first, second in self.links:
            adjacency[first].add(second)
            adjacency[second].add(first)

        queue = deque([source])
        parent: dict[Candidate, Candidate | None] = {source: None}
        while queue:
            current = queue.popleft()
            for neighbour in sorted(adjacency[current]):
                if neighbour in parent:
                    continue
                parent[neighbour] = current
                if neighbour == target:
                    queue.clear()
                    break
                queue.append(neighbour)

        if target not in parent:
            raise ValueError("La componente dichiarata non è connessa.")
        result = []
        current = target
        while current is not None:
            result.append(current)
            current = parent[current]
        return tuple(reversed(result))

    def to_dict(self) -> dict:
        return {
            "component_id": self.component_id,
            "digit": self.digit,
            "colors": [
                [list(candidate) for candidate in sorted(color)]
                for color in self.colors
            ],
            "links": [
                [list(first), list(second)]
                for first, second in self.links
            ],
        }


@dataclass(frozen=True, slots=True)
class ColoringPattern:
    """Pattern autorevole usato per classificare una deduzione coloring."""

    technique_id: str
    digit: int
    components: tuple[ColorComponent, ...]
    triggers: frozenset[Candidate]
    weak_links: tuple[ColorLink, ...] = ()
    eliminated_component_id: int | None = None
    eliminated_color: int | None = None

    def __post_init__(self):
        if self.technique_id not in TECHNIQUE_NAMES:
            raise ValueError(f"Tecnica coloring sconosciuta: {self.technique_id!r}.")
        if self.digit not in range(1, 10):
            raise ValueError("La cifra del pattern deve essere 1-9.")
        expected_count = 1 if self.technique_id.startswith("color.simple") else 2
        if len(self.components) != expected_count:
            raise ValueError(
                f"{self.technique_id} richiede {expected_count} componenti."
            )
        if len({item.component_id for item in self.components}) != len(
            self.components
        ):
            raise ValueError("Le componenti del pattern devono essere distinte.")
        if any(item.digit != self.digit for item in self.components):
            raise ValueError("Tutte le componenti devono usare la stessa cifra.")
        component_nodes = set().union(*(item.nodes for item in self.components))
        if not self.triggers <= component_nodes:
            raise ValueError("I trigger devono appartenere alle componenti.")
        if (self.eliminated_component_id is None) != (
            self.eliminated_color is None
        ):
            raise ValueError("Componente e colore eliminato vanno dichiarati insieme.")
        if self.eliminated_color not in (None, 0, 1):
            raise ValueError("Il colore eliminato deve essere 0 oppure 1.")
        if self.eliminated_component_id is not None and not any(
            item.component_id == self.eliminated_component_id
            for item in self.components
        ):
            raise ValueError("La componente eliminata non appartiene al pattern.")

    @property
    def technique_name(self) -> str:
        return TECHNIQUE_NAMES[self.technique_id]

    def to_dict(self) -> dict:
        return {
            "technique_id": self.technique_id,
            "digit": self.digit,
            "components": [item.to_dict() for item in self.components],
            "triggers": [list(item) for item in sorted(self.triggers)],
            "weak_links": [
                [list(first), list(second)]
                for first, second in self.weak_links
            ],
            "eliminated_component_id": self.eliminated_component_id,
            "eliminated_color": self.eliminated_color,
        }


@dataclass(frozen=True, slots=True)
class ColoringDeduction:
    pattern: ColoringPattern
    eliminations: frozenset[Candidate]
    chains: tuple[tuple[Literal, ...], ...]
    chain_reasons: tuple[tuple[str, ...], ...]
    equivalent_pattern_count: int = 1

    def __post_init__(self):
        if not self.eliminations:
            raise ValueError("Una deduzione coloring deve eliminare candidati.")
        if any(item[2] != self.pattern.digit for item in self.eliminations):
            raise ValueError("Le eliminazioni devono usare la cifra colorata.")
        if len(self.chains) != len(self.chain_reasons) or not self.chains:
            raise ValueError("Ogni deduzione richiede catene e motivi allineati.")
        for chain, reasons in zip(self.chains, self.chain_reasons):
            if len(chain) < 4 or len(reasons) != len(chain) - 1:
                raise ValueError("Catena coloring incompleta.")
            if chain[0][:3] != chain[-1][:3] or not chain[0][3] or chain[-1][3]:
                raise ValueError("Una catena coloring deve provare X ON -> X OFF.")
            if any(reason not in {"peer", "x"} for reason in reasons):
                raise ValueError("Coloring supporta soltanto archi peer/x.")
        if self.equivalent_pattern_count < 1:
            raise ValueError("equivalent_pattern_count deve essere positivo.")

    @property
    def technique_name(self) -> str:
        return self.pattern.technique_name

    def to_dict(self) -> dict:
        payload = self.pattern.to_dict()
        payload.update({
            "eliminations": [
                list(item) for item in sorted(self.eliminations)
            ],
            "equivalent_pattern_count": self.equivalent_pattern_count,
        })
        return payload

    def proof_payload(self) -> dict:
        kind = self.pattern.technique_id.replace(".", "-") + "-contradiction"
        assumptions = tuple(dict.fromkeys(chain[0] for chain in self.chains))
        dag = proof_model.ProofDAG.from_chains(
            assumptions=assumptions,
            chains=self.chains,
            reasons=("peer", "x"),
            chain_reasons=self.chain_reasons,
            proof_kind=kind,
            eliminations=self.eliminations,
        )
        return proof_schema.normalize_proof({
            "kind": kind,
            "reasons": ["peer", "x"],
            "proof_dag": dag.to_dict(),
        }, eliminations=self.eliminations)


def conjugate_pair_components(
    state,
    digit: int,
    *,
    graph: logic_engine.StaticImplicationGraph | None = None,
) -> tuple[ColorComponent, ...]:
    """Colora bipartitamente le componenti X forti della cifra."""
    digit = int(digit)
    if digit not in range(1, 10):
        raise ValueError("digit deve essere compreso tra 1 e 9.")
    graph = graph or logic_engine.static_implication_graph(state)
    links = tuple(_link(*pair) for pair in graph.conjugate_pairs(digit))
    adjacency: dict[Candidate, set[Candidate]] = {}
    for first, second in links:
        adjacency.setdefault(first, set()).add(second)
        adjacency.setdefault(second, set()).add(first)

    components = []
    visited = set()
    for start in sorted(adjacency):
        if start in visited:
            continue
        colors = {start: 0}
        queue = deque([start])
        bipartite = True
        while queue:
            current = queue.popleft()
            visited.add(current)
            for neighbour in sorted(adjacency[current]):
                wanted = 1 - colors[current]
                if neighbour not in colors:
                    colors[neighbour] = wanted
                    queue.append(neighbour)
                elif colors[neighbour] != wanted:
                    bipartite = False
        if not bipartite:
            continue

        nodes = frozenset(colors)
        component_links = tuple(
            link for link in links
            if link[0] in nodes and link[1] in nodes
        )
        components.append(ColorComponent(
            digit=digit,
            component_id=len(components),
            colors=(
                frozenset(item for item, color in colors.items() if color == 0),
                frozenset(item for item, color in colors.items() if color == 1),
            ),
            links=component_links,
        ))
    return tuple(components)


def _implication_path(
    component: ColorComponent,
    source: Candidate,
    target: Candidate,
    initial_state: bool,
) -> tuple[tuple[Literal, ...], tuple[str, ...]]:
    cells = component.path(source, target)
    state = bool(initial_state)
    literals = [_literal(cells[0], state)]
    reasons = []
    for candidate in cells[1:]:
        reason = "peer" if state else "x"
        state = not state
        reasons.append(reason)
        literals.append(_literal(candidate, state))
    return tuple(literals), tuple(reasons)


def _all_candidates(graph, digit: int) -> frozenset[Candidate]:
    return frozenset(
        candidate
        for candidate in graph.all_candidates
        if candidate[2] == digit
    )


def _visible_candidates(source, candidates: Iterable[Candidate]):
    return tuple(sorted(item for item in candidates if _sees(source, item)))


def _same_color_conflicts(component: ColorComponent, color: int):
    nodes = sorted(component.colors[color])
    return tuple(
        _link(first, second)
        for first, second in combinations(nodes, 2)
        if _sees(first, second)
    )


def find_simple_colors(
    state,
    digit: int,
    *,
    graph: logic_engine.StaticImplicationGraph | None = None,
) -> tuple[ColoringDeduction, ...]:
    """Trova Color Trap e Color Wrap nelle singole componenti."""
    graph = graph or logic_engine.static_implication_graph(state)
    components = conjugate_pair_components(state, digit, graph=graph)
    candidates = _all_candidates(graph, int(digit))
    deductions = []

    for component in components:
        trap_targets = []
        trap_chains = []
        trap_reasons = []
        trap_triggers = set()
        for target in sorted(candidates - component.nodes):
            visible_zero = _visible_candidates(target, component.colors[0])
            visible_one = _visible_candidates(target, component.colors[1])
            if not visible_zero or not visible_one:
                continue
            witness_zero = visible_zero[0]
            witness_one = visible_one[0]
            body, reasons = _implication_path(
                component, witness_zero, witness_one, False
            )
            chain = (
                (_literal(target, True),)
                + body
                + (_literal(target, False),)
            )
            trap_targets.append(target)
            trap_chains.append(chain)
            trap_reasons.append(("peer",) + reasons + ("peer",))
            trap_triggers.update((witness_zero, witness_one))

        if trap_targets:
            deductions.append(ColoringDeduction(
                pattern=ColoringPattern(
                    technique_id="color.simple.trap",
                    digit=int(digit),
                    components=(component,),
                    triggers=frozenset(trap_triggers),
                ),
                eliminations=frozenset(trap_targets),
                chains=tuple(trap_chains),
                chain_reasons=tuple(trap_reasons),
            ))

        for color in (0, 1):
            conflicts = _same_color_conflicts(component, color)
            if not conflicts:
                continue
            first, second = conflicts[0]
            body, reasons = _implication_path(
                component, second, first, False
            )
            chain = (
                (_literal(first, True), _literal(second, False))
                + body[1:]
            )
            deductions.append(ColoringDeduction(
                pattern=ColoringPattern(
                    technique_id="color.simple.wrap",
                    digit=int(digit),
                    components=(component,),
                    triggers=frozenset(
                        candidate for link in conflicts for candidate in link
                    ),
                    weak_links=conflicts,
                    eliminated_component_id=component.component_id,
                    eliminated_color=color,
                ),
                eliminations=component.colors[color],
                chains=(chain,),
                chain_reasons=(("peer",) + reasons,),
            ))
    return tuple(deductions)


def _weak_links(
    first: Iterable[Candidate],
    second: Iterable[Candidate],
) -> tuple[ColorLink, ...]:
    return tuple(sorted({
        _link(left, right)
        for left in first
        for right in second
        if _sees(left, right)
    }))


def _multi_type_1(
    graph,
    digit: int,
    first: ColorComponent,
    second: ColorComponent,
) -> list[ColoringDeduction]:
    candidates = _all_candidates(graph, digit)
    uncolored = candidates - first.nodes - second.nodes
    deductions = []
    for first_color in (0, 1):
        for second_color in (0, 1):
            weak_links = _weak_links(
                first.colors[first_color], second.colors[second_color]
            )
            if not weak_links:
                continue
            first_trigger, second_trigger = weak_links[0]
            if first_trigger not in first.nodes:
                first_trigger, second_trigger = second_trigger, first_trigger

            targets = []
            chains = []
            chain_reasons = []
            triggers = {candidate for link in weak_links for candidate in link}
            for target in sorted(uncolored):
                first_supports = _visible_candidates(
                    target, first.colors[1 - first_color]
                )
                second_supports = _visible_candidates(
                    target, second.colors[1 - second_color]
                )
                if not first_supports or not second_supports:
                    continue
                first_support = first_supports[0]
                second_support = second_supports[0]
                first_body, first_reasons = _implication_path(
                    first, first_support, first_trigger, False
                )
                second_body, second_reasons = _implication_path(
                    second, second_trigger, second_support, False
                )
                chain = (
                    (_literal(target, True),)
                    + first_body
                    + (_literal(second_trigger, False),)
                    + second_body[1:]
                    + (_literal(target, False),)
                )
                reasons = (
                    ("peer",)
                    + first_reasons
                    + ("peer",)
                    + second_reasons
                    + ("peer",)
                )
                targets.append(target)
                chains.append(chain)
                chain_reasons.append(reasons)
                triggers.update((first_support, second_support))

            if targets:
                deductions.append(ColoringDeduction(
                    pattern=ColoringPattern(
                        technique_id="color.multi.type1",
                        digit=digit,
                        components=(first, second),
                        triggers=frozenset(triggers),
                        weak_links=weak_links,
                    ),
                    eliminations=frozenset(targets),
                    chains=tuple(chains),
                    chain_reasons=tuple(chain_reasons),
                ))
    return deductions


def _multi_type_2(
    digit: int,
    victim: ColorComponent,
    forcing: ColorComponent,
) -> list[ColoringDeduction]:
    deductions = []
    for victim_color in (0, 1):
        links_zero = _weak_links(
            victim.colors[victim_color], forcing.colors[0]
        )
        links_one = _weak_links(
            victim.colors[victim_color], forcing.colors[1]
        )
        witnesses = []
        for zero_link in links_zero:
            victim_zero = next(
                item for item in zero_link if item in victim.nodes
            )
            forcing_zero = next(
                item for item in zero_link if item in forcing.nodes
            )
            for one_link in links_one:
                victim_one = next(
                    item for item in one_link if item in victim.nodes
                )
                forcing_one = next(
                    item for item in one_link if item in forcing.nodes
                )
                if victim_zero != victim_one:
                    witnesses.append((
                        victim_zero,
                        forcing_zero,
                        victim_one,
                        forcing_one,
                    ))
        if not witnesses:
            continue

        victim_zero, forcing_zero, victim_one, forcing_one = min(witnesses)
        forcing_body, forcing_reasons = _implication_path(
            forcing, forcing_zero, forcing_one, False
        )
        victim_body, victim_reasons = _implication_path(
            victim, victim_one, victim_zero, False
        )
        chain = (
            (_literal(victim_zero, True), _literal(forcing_zero, False))
            + forcing_body[1:]
            + (_literal(victim_one, False),)
            + victim_body[1:]
        )
        reasons = (
            ("peer",)
            + forcing_reasons
            + ("peer",)
            + victim_reasons
        )
        deductions.append(ColoringDeduction(
            pattern=ColoringPattern(
                technique_id="color.multi.type2",
                digit=digit,
                components=(victim, forcing),
                triggers=frozenset({
                    victim_zero, forcing_zero, victim_one, forcing_one,
                }),
                weak_links=tuple(sorted({
                    _link(victim_zero, forcing_zero),
                    _link(victim_one, forcing_one),
                })),
                eliminated_component_id=victim.component_id,
                eliminated_color=victim_color,
            ),
            eliminations=victim.colors[victim_color],
            chains=(chain,),
            chain_reasons=(reasons,),
        ))
    return deductions


def find_multi_colors(
    state,
    digit: int,
    *,
    graph: logic_engine.StaticImplicationGraph | None = None,
) -> tuple[ColoringDeduction, ...]:
    """Trova Multi Colors Type 1 e Type 2 fra componenti distinte."""
    digit = int(digit)
    graph = graph or logic_engine.static_implication_graph(state)
    components = conjugate_pair_components(state, digit, graph=graph)
    deductions = []
    for first, second in combinations(components, 2):
        deductions.extend(_multi_type_1(graph, digit, first, second))
        deductions.extend(_multi_type_2(digit, first, second))
        deductions.extend(_multi_type_2(digit, second, first))
    return tuple(deductions)


def _deduction_rank(deduction: ColoringDeduction) -> tuple:
    pattern = deduction.pattern
    return (
        len(pattern.components),
        sum(len(item.nodes) for item in pattern.components),
        sum(len(item.links) for item in pattern.components),
        sum(len(chain) for chain in deduction.chains),
        tuple(item.component_id for item in pattern.components),
        tuple(sorted(pattern.triggers)),
    )


def consolidate_coloring_deductions(
    deductions: Iterable[ColoringDeduction],
) -> list[ColoringDeduction]:
    """Conserva una sola prova per tecnica ed esito equivalente."""
    best = {}
    counts = {}
    for deduction in deductions:
        signature = (
            deduction.pattern.technique_id,
            tuple(sorted(deduction.eliminations)),
        )
        counts[signature] = (
            counts.get(signature, 0) + deduction.equivalent_pattern_count
        )
        previous = best.get(signature)
        if previous is None or _deduction_rank(deduction) < _deduction_rank(previous):
            best[signature] = deduction
    return sorted(
        (
            replace(item, equivalent_pattern_count=counts[signature])
            for signature, item in best.items()
        ),
        key=lambda item: (
            tuple(TECHNIQUE_NAMES).index(item.pattern.technique_id),
            tuple(sorted(item.eliminations)),
            _deduction_rank(item),
        ),
    )


def find_all_coloring(state) -> list[ColoringDeduction]:
    """Esegue tutte le classificazioni P11 sul grafo statico condiviso."""
    graph = logic_engine.static_implication_graph(state)
    deductions = []
    for digit in range(1, 10):
        deductions.extend(find_simple_colors(state, digit, graph=graph))
        deductions.extend(find_multi_colors(state, digit, graph=graph))
    return consolidate_coloring_deductions(deductions)


__all__ = [
    "Candidate",
    "ColorComponent",
    "ColoringDeduction",
    "ColoringPattern",
    "TECHNIQUE_NAMES",
    "conjugate_pair_components",
    "consolidate_coloring_deductions",
    "find_all_coloring",
    "find_multi_colors",
    "find_simple_colors",
]
