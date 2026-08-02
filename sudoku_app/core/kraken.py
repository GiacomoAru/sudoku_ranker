"""Kraken Fish costruiti sopra FishPattern e grafo AIC condivisi."""

from __future__ import annotations

from dataclasses import dataclass, replace

from . import fish as fish_engine
from . import logic_engine
from . import proof
from .data_structure import UNITS


Candidate = tuple[int, int, int]

DEFAULT_MAX_KRAKEN_PATTERNS = 64
DEFAULT_MAX_KRAKEN_PATH_ATTEMPTS = 512
DEFAULT_MAX_KRAKEN_RESULTS = 16
DEFAULT_MAX_KRAKEN_PATH_EDGES = 12


@dataclass(frozen=True, slots=True)
class KrakenDeduction:
    technique_id: str
    fish: fish_engine.FishDeduction
    target: Candidate
    possibilities: tuple[Candidate, ...]
    paths: tuple[tuple[tuple, ...], ...]
    path_reasons: tuple[tuple[str, ...], ...]
    path_supports: tuple[tuple[dict, ...], ...]
    cover_set: int | None = None
    search_truncated: bool = False
    pattern_count: int = 0
    path_attempt_count: int = 0
    max_patterns: int = DEFAULT_MAX_KRAKEN_PATTERNS
    max_path_attempts: int = DEFAULT_MAX_KRAKEN_PATH_ATTEMPTS

    def __post_init__(self):
        if self.technique_id not in {
            "kraken.fish.type1", "kraken.fish.type2"
        }:
            raise ValueError("Tipo Kraken sconosciuto.")
        if not self.possibilities or len(self.paths) != len(self.possibilities):
            raise ValueError("Ogni possibilità Kraken richiede una prova.")
        if len(self.path_reasons) != len(self.paths):
            raise ValueError("Motivi e percorsi Kraken non coincidono.")
        if len(self.path_supports) != len(self.paths):
            raise ValueError("Supporti e percorsi Kraken non coincidono.")
        if self.target[2] != self.fish.pattern.digit:
            raise ValueError("Il target Kraken deve usare la cifra del fish.")
        for possibility, path, reasons in zip(
            self.possibilities, self.paths, self.path_reasons
        ):
            if (
                len(path) < 4
                or len(reasons) != len(path) - 1
                or path[0] != (*possibility, True)
                or path[-1] != (*self.target, False)
            ):
                raise ValueError("Percorso Kraken non valido.")
        if self.technique_id == "kraken.fish.type1" and set(
            self.possibilities
        ) != set(self.fish.pattern.all_fins):
            raise ValueError("Il Type 1 deve provare ogni fin del fish.")
        if self.technique_id == "kraken.fish.type2" and self.cover_set is None:
            raise ValueError("Il Type 2 richiede un cover set.")

    @property
    def eliminations(self) -> frozenset[Candidate]:
        return frozenset({self.target})

    @property
    def primary_cells(self):
        candidates = set(self.fish.body) | set(self.fish.pattern.all_fins)
        candidates.update(self.possibilities)
        candidates.add(self.target)
        return tuple(sorted({item[:2] for item in candidates}))

    def to_dict(self) -> dict:
        return {
            "technique_id": self.technique_id,
            "fish": self.fish.to_dict(),
            "target": list(self.target),
            "possibilities": [
                list(item) for item in self.possibilities
            ],
            "cover_set": self.cover_set,
            "branch_count": (
                len(self.possibilities) + 1
                if self.technique_id == "kraken.fish.type1"
                else len(self.possibilities)
            ),
            "paths": [
                [proof.literal_record(item) for item in path]
                for path in self.paths
            ],
            "search": {
                "truncated": self.search_truncated,
                "pattern_count": self.pattern_count,
                "path_attempt_count": self.path_attempt_count,
                "max_patterns": self.max_patterns,
                "max_path_attempts": self.max_path_attempts,
            },
        }

    def proof_payload(self) -> dict:
        nodes = {}
        edge_supports = []
        next_id = 0
        evidence = []
        pattern_payload = self.fish.to_dict()
        branch_count = self.to_dict()["branch_count"]

        if self.technique_id == "kraken.fish.type1":
            fin_off_ids = []
            for fin in sorted(self.fish.pattern.all_fins):
                node_id = next_id
                next_id += 1
                nodes[node_id] = proof.ProofNode(
                    node_id,
                    "assumption",
                    (*fin, False),
                    (),
                    "kraken-no-fin-case",
                    0,
                    {"presentation": True},
                )
                fin_off_ids.append(node_id)
            fish_id = next_id
            next_id += 1
            nodes[fish_id] = proof.ProofNode(
                fish_id,
                "advanced-rule",
                (*self.target, False),
                tuple(fin_off_ids),
                "kraken-fish-core",
                1,
                {
                    "node_type": "kraken-fish",
                    "fish_pattern": pattern_payload,
                    "case": "all-fins-off",
                    "kraken_branch_count": branch_count,
                    "chain_terminal": True,
                    "presentation": True,
                },
            )
            evidence.append(fish_id)
        else:
            context_id = next_id
            next_id += 1
            nodes[context_id] = proof.ProofNode(
                context_id,
                "advanced-rule",
                None,
                (),
                "kraken-cover-context",
                0,
                {
                    "node_type": "kraken-fish",
                    "fish_pattern": pattern_payload,
                    "cover_set": self.cover_set,
                    "kraken_branch_count": branch_count,
                    "presentation": False,
                },
            )
            evidence.append(context_id)

        for branch_index, (path, reasons, supports) in enumerate(zip(
            self.paths, self.path_reasons, self.path_supports
        )):
            parent = None
            for index, literal in enumerate(path):
                node_id = next_id
                next_id += 1
                reason = "assumption" if index == 0 else reasons[index - 1]
                parents = () if parent is None else (parent,)
                nodes[node_id] = proof.ProofNode(
                    node_id,
                    (
                        "assumption"
                        if index == 0
                        else "static-implication"
                    ),
                    literal,
                    parents,
                    reason,
                    index,
                    {
                        "branch_index": branch_index,
                        "chain_terminal": index == len(path) - 1,
                        "presentation": True,
                    },
                )
                if parent is not None:
                    support = supports[index - 1]
                    edge_supports.append(proof.ImplicationEdgeSupport(
                        source_id=parent,
                        target_id=node_id,
                        support_candidates=tuple(
                            support.get("support_candidates", ())
                        ),
                        support_house_ids=tuple(
                            support.get("support_house_ids", ())
                        ),
                    ))
                parent = node_id
            evidence.append(parent)

        conclusion_id = next_id
        nodes[conclusion_id] = proof.ProofNode(
            conclusion_id,
            "common-conclusion",
            (*self.target, False),
            tuple(evidence),
            "elimination",
            1 + max(nodes[parent].depth for parent in evidence),
            {"action": "elimination", "presentation": False},
        )
        dag = proof.ProofDAG(
            nodes=nodes,
            roots=tuple(sorted(
                node.id for node in nodes.values() if not node.parents
            )),
            conclusions=(conclusion_id,),
            edge_supports=tuple(edge_supports),
        )
        return proof.logic_payload(
            dag,
            kind=(
                "kraken-fish-type1"
                if self.technique_id == "kraken.fish.type1"
                else "kraken-fish-type2"
            ),
            reasons={
                reason for reasons in self.path_reasons for reason in reasons
            } | {"kraken-fish"},
            extra={
                "kraken_pattern": self.to_dict(),
                "search": self.to_dict()["search"],
            },
        )


def _candidate_patterns(state, *, max_patterns):
    seen = set()
    emitted = 0
    for size in (2, 3, 4):
        for digit in range(1, 10):
            for base_types, cover_types in (
                (("row",), ("column",)),
                (("column",), ("row",)),
            ):
                for deduction in fish_engine.find_fish(
                    state,
                    digit,
                    size,
                    base_types,
                    cover_types,
                    accepted_classes=("basic",),
                    max_fins=3,
                    max_endo_fins=1,
                    max_results=8,
                    require_direct_elimination=False,
                ):
                    pattern = deduction.pattern
                    if not pattern.all_fins:
                        continue
                    signature = (
                        pattern.digit,
                        pattern.size,
                        pattern.base_sets,
                        pattern.cover_sets,
                        tuple(sorted(pattern.all_fins)),
                    )
                    if signature in seen:
                        continue
                    seen.add(signature)
                    yield deduction
                    emitted += 1
                    if emitted >= max_patterns:
                        return


def find_kraken(
    state,
    *,
    max_results: int = DEFAULT_MAX_KRAKEN_RESULTS,
    max_patterns: int = DEFAULT_MAX_KRAKEN_PATTERNS,
    max_path_attempts: int = DEFAULT_MAX_KRAKEN_PATH_ATTEMPTS,
) -> tuple[KrakenDeduction, ...]:
    """Cerca Type 1 e Type 2 solo se ogni possibilità ha una prova AIC."""
    max_results = max(1, int(max_results))
    max_patterns = max(1, int(max_patterns))
    max_path_attempts = max(1, int(max_path_attempts))
    graph = logic_engine.static_implication_graph(state)
    results = []
    patterns = 0
    attempts = 0
    truncated = False
    seen = set()

    def prove(possibilities, target):
        nonlocal attempts, truncated
        paths = []
        reasons = []
        supports = []
        for possibility in possibilities:
            if attempts >= max_path_attempts:
                truncated = True
                return None
            attempts += 1
            path_data = graph.shortest_path(
                (*possibility, True),
                (*target, False),
                allowed=frozenset({"peer", "x", "y"}),
                minimum_edges=3,
                maximum_edges=DEFAULT_MAX_KRAKEN_PATH_EDGES,
            )
            if path_data is None:
                return None
            path, path_reasons = path_data
            paths.append(tuple(path))
            reasons.append(tuple(path_reasons))
            supports.append(tuple(graph.chain_supports(path, path_reasons)))
        return tuple(paths), tuple(reasons), tuple(supports)

    for fish in _candidate_patterns(state, max_patterns=max_patterns):
        patterns += 1
        pattern = fish.pattern
        targets = tuple(sorted(
            set(fish.potential_targets)
            - set(fish.eliminations)
            - set(pattern.all_fins)
            - set(fish.body)
        ))
        if not targets:
            continue

        fins = tuple(sorted(pattern.all_fins))
        for target in targets:
            path_data = prove(fins, target)
            if path_data is not None:
                signature = "kraken.fish.type1", target, fins
                if signature not in seen:
                    seen.add(signature)
                    results.append(KrakenDeduction(
                        "kraken.fish.type1",
                        fish,
                        target,
                        fins,
                        *path_data,
                    ))
            if len(results) >= max_results or truncated:
                break

            for cover_set in pattern.cover_sets:
                cover_candidates = {
                    candidate
                    for candidate in graph.all_candidates
                    if candidate[2] == pattern.digit
                    and candidate[:2] in UNITS[cover_set]
                }
                # Le possibilità del cover set devono essere esaustive senza
                # assumere già falsa la conclusione che si vuole provare.
                if target in cover_candidates:
                    continue
                possibilities = tuple(sorted(
                    cover_candidates | set(fins)
                ))
                if len(possibilities) < 2 or not set(fins) <= set(
                    possibilities
                ):
                    continue
                path_data = prove(possibilities, target)
                if path_data is None:
                    continue
                signature = (
                    "kraken.fish.type2", target, cover_set, possibilities
                )
                if signature in seen:
                    continue
                seen.add(signature)
                results.append(KrakenDeduction(
                    "kraken.fish.type2",
                    fish,
                    target,
                    possibilities,
                    *path_data,
                    cover_set=cover_set,
                ))
                if len(results) >= max_results:
                    break
            if len(results) >= max_results or truncated:
                break
        if len(results) >= max_results or truncated:
            break

    if patterns >= max_patterns:
        truncated = True
    return tuple(
        replace(
            deduction,
            search_truncated=truncated,
            pattern_count=patterns,
            path_attempt_count=attempts,
            max_patterns=max_patterns,
            max_path_attempts=max_path_attempts,
        )
        for deduction in results
    )


__all__ = [
    "Candidate",
    "DEFAULT_MAX_KRAKEN_PATH_ATTEMPTS",
    "DEFAULT_MAX_KRAKEN_PATH_EDGES",
    "DEFAULT_MAX_KRAKEN_PATTERNS",
    "DEFAULT_MAX_KRAKEN_RESULTS",
    "KrakenDeduction",
    "find_kraken",
]
