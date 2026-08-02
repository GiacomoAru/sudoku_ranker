"""Modello formale delle prove logiche del solver.

``ProofDAG`` e' la rappresentazione autorevole. Le catene lineari sono una
vista derivata e limitata, destinata esclusivamente a spiegazioni e UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping, Sequence
import hashlib
import json

from .als_nodes import ALSNode, als_node
from .group_nodes import GroupNode, group_node


Literal = tuple[int, int, int, bool]
GroupLiteral = tuple[GroupNode, bool]
ALSLiteral = tuple[ALSNode, bool]
ProofLiteral = Literal | GroupLiteral | ALSLiteral
Candidate = tuple[int, int, int]

PROOF_DAG_SCHEMA_VERSION = "1.3.0"
MAX_PRESENTATION_CHAINS = 16

NODE_KINDS = frozenset({
    "assumption",
    "static-implication",
    "grouped-implication",
    "dynamic-single",
    "advanced-rule",
    "common-conclusion",
    "contradiction",
    "branch",
    "nested-subproof",
})


def normalize_literal(value) -> ProofLiteral | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        state = value.get("state")
        is_on = state in {True, 1, "on", "true", "True"}
        if value.get("node_type") == "group" or "group" in value:
            raw_group = value.get("group", value)
            return group_node(raw_group), is_on
        if value.get("node_type") == "als" or "als_node" in value:
            raw_als = value.get("als_node", value)
            return als_node(raw_als), is_on
        literal = (
            int(value["row"]),
            int(value["column"]),
            int(value["value"]),
            is_on,
        )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) == 2 and isinstance(
            value[0], (GroupNode, ALSNode, Mapping)
        ):
            raw_node = value[0]
            if isinstance(raw_node, ALSNode) or (
                isinstance(raw_node, Mapping)
                and raw_node.get("node_type") == "als"
            ):
                return als_node(raw_node), bool(value[1])
            return group_node(raw_node), bool(value[1])
        if len(value) != 4:
            raise ValueError("Un letterale deve contenere quattro valori.")
        row, column, digit, state = value
        literal = (int(row), int(column), int(digit), bool(state))
    else:
        raise TypeError("Il letterale deve essere una mappa o una sequenza.")

    row, column, digit, _ = literal
    if not (0 <= row < 9 and 0 <= column < 9 and 1 <= digit <= 9):
        raise ValueError(f"Letterale Sudoku non valido: {literal!r}.")
    return literal


def is_group_literal(literal) -> bool:
    return (
        isinstance(literal, Sequence)
        and not isinstance(literal, (str, bytes))
        and len(literal) == 2
        and isinstance(literal[0], GroupNode)
    )


def is_als_literal(literal) -> bool:
    return (
        isinstance(literal, Sequence)
        and not isinstance(literal, (str, bytes))
        and len(literal) == 2
        and isinstance(literal[0], ALSNode)
    )


def literal_state(literal: ProofLiteral) -> bool:
    literal = normalize_literal(literal)
    return (
        literal[1]
        if is_group_literal(literal) or is_als_literal(literal)
        else literal[3]
    )


def literal_cells(literal: ProofLiteral) -> tuple[tuple[int, int], ...]:
    literal = normalize_literal(literal)
    if is_group_literal(literal) or is_als_literal(literal):
        return tuple(sorted(literal[0].cells))
    return ((literal[0], literal[1]),)


def literal_digit(literal: ProofLiteral) -> int:
    literal = normalize_literal(literal)
    return (
        literal[0].digit
        if is_group_literal(literal) or is_als_literal(literal)
        else literal[2]
    )


def literal_sort_key(literal: ProofLiteral):
    literal = normalize_literal(literal)
    if is_group_literal(literal):
        node, is_on = literal
        return (
            1,
            node.digit,
            tuple(sorted(node.cells)),
            node.house_ids,
            node.role,
            int(is_on),
        )
    if is_als_literal(literal):
        node, is_on = literal
        return (
            2,
            node.als_key,
            node.digit,
            tuple(sorted(node.occurrences)),
            int(is_on),
        )
    row, column, digit, is_on = literal
    return 0, row, column, digit, int(is_on)


def literal_record(literal: ProofLiteral | None):
    literal = normalize_literal(literal)
    if literal is None:
        return None
    if is_group_literal(literal):
        node, is_on = literal
        return {
            "node_type": "group",
            "group": node.to_dict(),
            "state": "on" if is_on else "off",
        }
    if is_als_literal(literal):
        node, is_on = literal
        return {
            "node_type": "als",
            "als_node": node.to_dict(),
            "state": "on" if is_on else "off",
        }
    row, column, value, is_on = literal
    return {
        "row": row,
        "column": column,
        "value": value,
        "state": "on" if is_on else "off",
    }


def _normalise_ids(values):
    return tuple(dict.fromkeys(int(value) for value in values or ()))


def _normalise_candidate(value) -> Candidate:
    if isinstance(value, Mapping):
        candidate = (
            int(value["row"]),
            int(value["column"]),
            int(value["value"]),
        )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) != 3:
            raise ValueError("Un candidato deve contenere tre valori.")
        candidate = tuple(int(item) for item in value)
    else:
        raise TypeError("Un candidato deve essere una mappa o una sequenza.")
    row, column, digit = candidate
    if not (0 <= row < 9 and 0 <= column < 9 and 1 <= digit <= 9):
        raise ValueError(f"Candidato Sudoku non valido: {candidate!r}.")
    return candidate


def _json_payload(payload):
    try:
        return json.loads(json.dumps(payload or {}, sort_keys=True))
    except (TypeError, ValueError) as error:
        raise TypeError("Il payload di un nodo deve essere JSON serializzabile.") from error


@dataclass(slots=True)
class ProofNode:
    id: int
    kind: str
    conclusion: ProofLiteral | None
    parents: tuple[int, ...]
    reason: str
    depth: int
    payload: dict = field(default_factory=dict)

    def __post_init__(self):
        self.id = int(self.id)
        self.kind = str(self.kind)
        self.conclusion = normalize_literal(self.conclusion)
        self.parents = _normalise_ids(self.parents)
        self.reason = str(self.reason or "unspecified")
        self.depth = int(self.depth)
        self.payload = _json_payload(self.payload)

        if self.id < 0:
            raise ValueError("L'id di un nodo non puo' essere negativo.")
        if self.kind not in NODE_KINDS:
            raise ValueError(f"Tipo di nodo prova sconosciuto: {self.kind!r}.")
        if self.depth < 0:
            raise ValueError("La profondita' di un nodo non puo' essere negativa.")
        if self.id in self.parents:
            raise ValueError("Un nodo non puo' essere parent di se stesso.")

    def to_dict(self):
        return {
            "id": self.id,
            "kind": self.kind,
            "conclusion": literal_record(self.conclusion),
            "parents": list(self.parents),
            "reason": self.reason,
            "depth": self.depth,
            "payload": _json_payload(self.payload),
        }

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, Mapping):
            raise TypeError("Un nodo serializzato deve essere una mappa.")
        return cls(
            id=value["id"],
            kind=value["kind"],
            conclusion=value.get("conclusion"),
            parents=tuple(value.get("parents", ())),
            reason=value.get("reason", "unspecified"),
            depth=value.get("depth", 0),
            payload=dict(value.get("payload", {}) or {}),
        )


@dataclass(frozen=True, slots=True)
class ImplicationEdgeSupport:
    """Supporto Sudoku autorevole di un arco del ``ProofDAG``."""

    source_id: int
    target_id: int
    support_candidates: tuple[Candidate, ...] = ()
    support_house_ids: tuple[int, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "source_id", int(self.source_id))
        object.__setattr__(self, "target_id", int(self.target_id))
        object.__setattr__(
            self,
            "support_candidates",
            tuple(sorted({
                _normalise_candidate(item)
                for item in self.support_candidates
            })),
        )
        object.__setattr__(
            self,
            "support_house_ids",
            tuple(sorted({int(item) for item in self.support_house_ids})),
        )
        if self.source_id < 0 or self.target_id < 0:
            raise ValueError("Gli id di supporto non possono essere negativi.")
        if self.source_id == self.target_id:
            raise ValueError("Un supporto richiede due nodi distinti.")
        if any(not 0 <= house_id < 27 for house_id in self.support_house_ids):
            raise ValueError("Gli id delle case devono essere compresi tra 0 e 26.")

    def to_dict(self):
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "support_candidates": [
                list(item) for item in self.support_candidates
            ],
            "support_house_ids": list(self.support_house_ids),
        }

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, Mapping):
            raise TypeError("Il supporto di un arco deve essere una mappa.")
        return cls(
            source_id=value["source_id"],
            target_id=value["target_id"],
            support_candidates=tuple(value.get("support_candidates", ())),
            support_house_ids=tuple(value.get("support_house_ids", ())),
        )


@dataclass(slots=True)
class ProofDAG:
    nodes: dict[int, ProofNode]
    roots: tuple[int, ...]
    conclusions: tuple[int, ...]
    nested_proofs: dict[int, "ProofDAG"] = field(default_factory=dict)
    edge_supports: tuple[ImplicationEdgeSupport, ...] = ()

    def __post_init__(self):
        self.nodes = {
            int(node_id): (
                node if isinstance(node, ProofNode) else ProofNode.from_dict(node)
            )
            for node_id, node in dict(self.nodes).items()
        }
        self.roots = _normalise_ids(self.roots)
        self.conclusions = _normalise_ids(self.conclusions)
        self.nested_proofs = {
            int(node_id): (
                nested
                if isinstance(nested, ProofDAG)
                else ProofDAG.from_dict(nested)
            )
            for node_id, nested in dict(self.nested_proofs).items()
        }
        self.edge_supports = tuple(sorted(
            (
                item
                if isinstance(item, ImplicationEdgeSupport)
                else ImplicationEdgeSupport.from_dict(item)
                for item in self.edge_supports
            ),
            key=lambda item: (item.source_id, item.target_id),
        ))
        self.validate()

    def validate(self):
        if any(node_id != node.id for node_id, node in self.nodes.items()):
            raise ValueError("Le chiavi dei nodi devono coincidere con i loro id.")

        known = set(self.nodes)
        referenced = set(self.roots) | set(self.conclusions)
        if not referenced <= known:
            raise ValueError("Root o conclusione riferisce un nodo inesistente.")
        for node in self.nodes.values():
            if not set(node.parents) <= known:
                raise ValueError(f"Il nodo {node.id} ha parent inesistenti.")

        dag_edges = {
            (parent_id, node.id)
            for node in self.nodes.values()
            for parent_id in node.parents
        }
        support_edges = {
            (item.source_id, item.target_id)
            for item in self.edge_supports
        }
        if len(support_edges) != len(self.edge_supports):
            raise ValueError("Il DAG contiene supporti duplicati per lo stesso arco.")
        if not support_edges <= dag_edges:
            raise ValueError("Un supporto riferisce un arco inesistente.")

        expected_roots = tuple(sorted(
            node.id for node in self.nodes.values() if not node.parents
        ))
        if tuple(sorted(self.roots)) != expected_roots:
            raise ValueError("Le roots non coincidono con i nodi senza parent.")

        visiting = set()
        visited = set()

        def visit(node_id):
            if node_id in visiting:
                raise ValueError("Il grafo della prova contiene un ciclo.")
            if node_id in visited:
                return
            visiting.add(node_id)
            for parent_id in self.nodes[node_id].parents:
                visit(parent_id)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in sorted(self.nodes):
            visit(node_id)

        for node in self.nodes.values():
            expected_depth = (
                0
                if not node.parents
                else 1 + max(self.nodes[parent].depth for parent in node.parents)
            )
            if node.depth != expected_depth:
                raise ValueError(
                    f"Profondita' incoerente per il nodo {node.id}: "
                    f"{node.depth}, attesa {expected_depth}."
                )

        for node_id, nested in self.nested_proofs.items():
            if node_id not in known:
                raise ValueError("Una sottoprova appartiene a un nodo inesistente.")
            if self.nodes[node_id].kind != "nested-subproof":
                raise ValueError("Le sottoprove richiedono un nodo nested-subproof.")
            nested.validate()
        return self

    def to_dict(self):
        return {
            "schema_version": PROOF_DAG_SCHEMA_VERSION,
            "nodes": {
                str(node_id): self.nodes[node_id].to_dict()
                for node_id in sorted(self.nodes)
            },
            "roots": list(self.roots),
            "conclusions": list(self.conclusions),
            "nested_proofs": {
                str(node_id): proof.to_dict()
                for node_id, proof in sorted(self.nested_proofs.items())
            },
            "edge_supports": [
                item.to_dict() for item in self.edge_supports
            ],
        }

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, Mapping):
            raise TypeError("Un ProofDAG serializzato deve essere una mappa.")
        nodes = value.get("nodes", {})
        if isinstance(nodes, Mapping):
            node_values = nodes.values()
        else:
            node_values = nodes
        parsed_nodes = {
            node.id: node
            for node in (ProofNode.from_dict(item) for item in node_values)
        }
        return cls(
            nodes=parsed_nodes,
            roots=tuple(value.get("roots", ())),
            conclusions=tuple(value.get("conclusions", ())),
            nested_proofs={
                int(node_id): cls.from_dict(nested)
                for node_id, nested in dict(
                    value.get("nested_proofs", {}) or {}
                ).items()
            },
            edge_supports=tuple(value.get("edge_supports", ())),
        )

    def _children(self):
        children = {node_id: [] for node_id in self.nodes}
        for node in self.nodes.values():
            for parent in node.parents:
                children[parent].append(node.id)
        return {
            node_id: tuple(sorted(values))
            for node_id, values in children.items()
        }

    def _derived_presentation_paths(self, max_chains):
        """Restituisce i path di nodi usati dalle viste lineari."""
        if isinstance(max_chains, bool) or int(max_chains) < 1:
            raise ValueError("max_chains deve essere positivo.")
        max_chains = min(int(max_chains), MAX_PRESENTATION_CHAINS)
        targets = sorted(
            node.id
            for node in self.nodes.values()
            if node.payload.get("chain_terminal")
            or node.kind == "contradiction"
        )
        paths = []
        seen = set()

        def parent_paths(node_id):
            node = self.nodes[node_id]
            if not node.parents:
                return [(node_id,)]
            paths = []
            for parent in node.parents:
                for prefix in parent_paths(parent):
                    paths.append(prefix + (node_id,))
                    if len(paths) >= max_chains:
                        return paths
            return paths

        for target in targets:
            for path in parent_paths(target):
                literals = []
                presentation_path = []
                for node_id in path:
                    node = self.nodes[node_id]
                    if (
                        node.conclusion is not None
                        and node.payload.get("presentation", True)
                    ):
                        if not literals or literals[-1] != node.conclusion:
                            literals.append(node.conclusion)
                            presentation_path.append(node_id)
                signature = tuple(literals)
                if signature and signature not in seen:
                    seen.add(signature)
                    paths.append(tuple(presentation_path))
                if len(paths) >= max_chains:
                    break
            if len(paths) >= max_chains:
                break
        return sorted(
            paths,
            key=lambda path: (
                -len(path),
                tuple(
                    literal_sort_key(self.nodes[node_id].conclusion)
                    for node_id in path
                ),
            ),
        )

    def derived_chains(self, max_chains=MAX_PRESENTATION_CHAINS):
        """Deriva viste lineari deterministiche senza renderle autorevoli."""
        return [
            [self.nodes[node_id].conclusion for node_id in path]
            for path in self._derived_presentation_paths(max_chains)
        ]

    def derived_chain_links(self, max_chains=MAX_PRESENTATION_CHAINS):
        """Deriva motivo e forza di ogni arco delle catene mostrate."""
        supports = {
            (item.source_id, item.target_id): item
            for item in self.edge_supports
        }
        result = []
        for path in self._derived_presentation_paths(max_chains):
            links = []
            for source_id, target_id in zip(path, path[1:]):
                source = self.nodes[source_id].conclusion
                target = self.nodes[target_id].conclusion
                source_state = literal_state(source)
                target_state = literal_state(target)
                if source_state and not target_state:
                    strength = "weak"
                elif not source_state and target_state:
                    strength = "strong"
                else:
                    strength = "non-alternating"
                support = supports.get((source_id, target_id))
                link = {
                    "source": literal_record(source),
                    "target": literal_record(target),
                    "reason": self.nodes[target_id].reason,
                    "strength": strength,
                }
                if support is not None:
                    link["support_candidates"] = [
                        list(item) for item in support.support_candidates
                    ]
                    link["support_house_ids"] = list(
                        support.support_house_ids
                    )
                links.append(link)
            result.append(links)
        return result

    def metrics(self):
        chains = self.derived_chains()
        displayed = {
            literal for chain in chains for literal in chain
        }
        assumptions = sum(
            node.kind == "assumption" for node in self.nodes.values()
        )
        branch_count = sum(
            int(node.payload.get("branch_count", 1))
            for node in self.nodes.values()
            if node.kind == "branch"
        )
        leaf_count = sum(
            node.kind == "contradiction" for node in self.nodes.values()
        )
        nested_metrics = [proof.metrics() for proof in self.nested_proofs.values()]
        children = self._children()
        fork_node_count = sum(
            len(node_children) > 1
            for node_children in children.values()
        )
        merge_node_count = sum(
            len(node.parents) > 1 for node in self.nodes.values()
        )
        max_parent_count = max(
            (len(node.parents) for node in self.nodes.values()),
            default=0,
        )
        template_count = max(
            (
                int(node.payload.get("template_count", 0))
                for node in self.nodes.values()
            ),
            default=0,
        )
        kraken_branch_count = max(
            (
                int(node.payload.get("kraken_branch_count", 0))
                for node in self.nodes.values()
            ),
            default=0,
        )
        group_nodes = {
            node.conclusion[0]
            for node in self.nodes.values()
            if (
                node.conclusion is not None
                and is_group_literal(node.conclusion)
            )
        }
        als_nodes_by_key = {
            node.conclusion[0].als_key: node.conclusion[0]
            for node in self.nodes.values()
            if (
                node.conclusion is not None
                and is_als_literal(node.conclusion)
            )
        }
        payload_alses = {}
        for proof_node in self.nodes.values():
            raw_als = proof_node.payload.get("als")
            if not isinstance(raw_als, Mapping):
                continue
            cells = tuple(sorted(
                tuple(cell) for cell in raw_als.get("cells", ())
            ))
            digits = tuple(sorted(int(value) for value in raw_als.get(
                "candidates", raw_als.get("digits", ())
            )))
            key = (int(raw_als.get("id", -1)), cells, digits)
            payload_alses[key] = cells
        local_rcc_count = max(
            sum(
                node.reason in {"als-rcc", "als-stem-rcc"}
                for node in self.nodes.values()
            ),
            max(
                (
                    int(node.payload.get("rcc_count", 0))
                    for node in self.nodes.values()
                ),
                default=0,
            ),
        )
        nested_depth = (
            1 + max(
                (metrics["nested_depth"] for metrics in nested_metrics),
                default=0,
            )
            if self.nested_proofs
            else 0
        )
        return {
            "proof_node_count": len(self.nodes) + sum(
                metrics["proof_node_count"] for metrics in nested_metrics
            ),
            "proof_edge_count": sum(
                len(node.parents) for node in self.nodes.values()
            ) + sum(
                metrics["proof_edge_count"] for metrics in nested_metrics
            ),
            "displayed_literal_count": len(displayed),
            "assumption_count": assumptions + sum(
                metrics["assumption_count"] for metrics in nested_metrics
            ),
            "chain_count": len(chains),
            "max_chain_length": max((len(chain) for chain in chains), default=0),
            "total_chain_length": sum(len(chain) for chain in chains),
            "branch_count": branch_count + sum(
                metrics["branch_count"] for metrics in nested_metrics
            ),
            "leaf_count": leaf_count + sum(
                metrics["leaf_count"] for metrics in nested_metrics
            ),
            "nested_depth": nested_depth,
            "nested_subproof_count": len(self.nested_proofs) + sum(
                metrics["nested_subproof_count"] for metrics in nested_metrics
            ),
            "group_node_count": len(group_nodes) + sum(
                metrics.get("group_node_count", 0)
                for metrics in nested_metrics
            ),
            "max_group_size": max(
                [len(node.cells) for node in group_nodes]
                + [
                    metrics.get("max_group_size", 0)
                    for metrics in nested_metrics
                ],
                default=0,
            ),
            "als_node_count": (
                len(als_nodes_by_key) + len(payload_alses)
            ) + sum(
                metrics.get("als_node_count", 0)
                for metrics in nested_metrics
            ),
            "als_cell_count": sum(
                len(node.cells) for node in als_nodes_by_key.values()
            ) + sum(len(cells) for cells in payload_alses.values()) + sum(
                metrics.get("als_cell_count", 0)
                for metrics in nested_metrics
            ),
            "rcc_count": local_rcc_count + sum(
                metrics.get("rcc_count", 0)
                for metrics in nested_metrics
            ),
            "fork_node_count": fork_node_count + sum(
                metrics.get("fork_node_count", 0)
                for metrics in nested_metrics
            ),
            "merge_node_count": merge_node_count + sum(
                metrics.get("merge_node_count", 0)
                for metrics in nested_metrics
            ),
            "max_parent_count": max(
                [max_parent_count]
                + [
                    metrics.get("max_parent_count", 0)
                    for metrics in nested_metrics
                ]
            ),
            "template_count": template_count + sum(
                metrics.get("template_count", 0)
                for metrics in nested_metrics
            ),
            "kraken_branch_count": kraken_branch_count + sum(
                metrics.get("kraken_branch_count", 0)
                for metrics in nested_metrics
            ),
        }

    def primary_cells(self):
        cells = set()
        for node in self.nodes.values():
            if (
                node.conclusion is None
                or node.kind == "common-conclusion"
            ):
                continue
            cells.update(literal_cells(node.conclusion))
        return sorted(cells)

    def select_conclusions(self, *, placements=(), eliminations=()):
        """Allinea i nodi conclusivi a una Move eventualmente filtrata."""
        wanted = {
            (int(row), int(column), int(value), True): "placement"
            for row, column, value in placements
        }
        wanted.update({
            (int(row), int(column), int(value), False): "elimination"
            for row, column, value in eliminations
        })
        nodes = dict(self.nodes)
        selected = []
        existing = {}
        evidence = []

        for node_id in self.conclusions:
            node = nodes[node_id]
            evidence.extend(node.parents)
            if node.conclusion in wanted:
                selected.append(node_id)
                existing[node.conclusion] = node_id
            elif node.kind == "common-conclusion":
                nodes.pop(node_id)

        if not evidence:
            evidence = [
                node.id
                for node in nodes.values()
                if node.payload.get("chain_terminal")
                or node.kind == "contradiction"
            ]
        evidence = list(dict.fromkeys(evidence or self.roots))

        for literal, action in sorted(wanted.items()):
            if literal in existing:
                continue
            node_id = max(nodes, default=-1) + 1
            parents = tuple(evidence)
            depth = (
                0
                if not parents
                else 1 + max(nodes[parent].depth for parent in parents)
            )
            nodes[node_id] = ProofNode(
                id=node_id,
                kind="common-conclusion",
                conclusion=literal,
                parents=parents,
                reason=action,
                depth=depth,
                payload={"action": action, "presentation": False},
            )
            selected.append(node_id)

        # Il DAG normalizzato contiene soltanto gli antenati necessari alle
        # conclusioni selezionate. Questo evita che prove indipendenti di
        # conclusioni filtrate restino nella vista autorevole.
        required = set()

        def keep_ancestors(node_id):
            if node_id in required:
                return
            required.add(node_id)
            for parent_id in nodes[node_id].parents:
                keep_ancestors(parent_id)

        for node_id in selected:
            keep_ancestors(node_id)
        nodes = {
            node_id: node
            for node_id, node in nodes.items()
            if node_id in required
        }
        roots = tuple(sorted(
            node.id for node in nodes.values() if not node.parents
        ))
        return ProofDAG(
            nodes=nodes,
            roots=roots,
            conclusions=tuple(sorted(selected)),
            nested_proofs={
                node_id: nested
                for node_id, nested in self.nested_proofs.items()
                if node_id in nodes
            },
            edge_supports=tuple(
                item
                for item in self.edge_supports
                if item.source_id in nodes and item.target_id in nodes
            ),
        )

    def signature(self):
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def digest(self):
        return hashlib.sha256(self.signature().encode("utf-8")).hexdigest()

    @classmethod
    def from_chains(
        cls,
        *,
        assumptions=(),
        chains=(),
        reasons=(),
        chain_reasons=(),
        chain_supports=(),
        proof_kind="unspecified",
        placements=(),
        eliminations=(),
    ):
        """Converte prove lineari legacy in un DAG formale."""
        nodes = {}
        next_id = 0
        assumption_ids = {}
        reason_set = {str(reason) for reason in reasons or ()}
        chain_reason_lists = [
            tuple(str(reason) for reason in raw_reasons)
            for raw_reasons in chain_reasons or ()
        ]
        chain_support_lists = [
            tuple(raw_supports)
            for raw_supports in chain_supports or ()
        ]
        if chain_reason_lists and len(chain_reason_lists) != len(chains):
            raise ValueError(
                "chain_reasons deve contenere una sequenza per ogni catena."
            )
        if chain_support_lists and len(chain_support_lists) != len(chains):
            raise ValueError(
                "chain_supports deve contenere una sequenza per ogni catena."
            )

        edge_supports = []

        def support_values(raw):
            if isinstance(raw, ImplicationEdgeSupport):
                return raw.support_candidates, raw.support_house_ids
            if not isinstance(raw, Mapping):
                raise TypeError("Il supporto di una catena deve essere una mappa.")
            return (
                tuple(raw.get("support_candidates", ())),
                tuple(raw.get("support_house_ids", ())),
            )

        def add(kind, conclusion, parents=(), reason="unspecified", payload=None):
            nonlocal next_id
            parents = _normalise_ids(parents)
            depth = 0 if not parents else 1 + max(nodes[parent].depth for parent in parents)
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

        for raw in assumptions or ():
            literal = normalize_literal(raw)
            if literal not in assumption_ids:
                assumption_ids[literal] = add(
                    "assumption",
                    literal,
                    reason="assumption",
                    payload={"presentation": True},
                )

        terminal_ids = []
        dedicated_evidence = {}
        for chain_index, raw_chain in enumerate(chains or ()):
            literals = [normalize_literal(item) for item in raw_chain]
            if not literals:
                continue
            ordered_reasons = (
                chain_reason_lists[chain_index]
                if chain_reason_lists
                else ()
            )
            if ordered_reasons and len(ordered_reasons) != len(literals) - 1:
                raise ValueError(
                    "Ogni catena deve avere esattamente un motivo per arco."
                )
            ordered_supports = (
                chain_support_lists[chain_index]
                if chain_support_lists
                else ()
            )
            if ordered_supports and len(ordered_supports) != len(literals) - 1:
                raise ValueError(
                    "Ogni catena deve avere esattamente un supporto per arco."
                )
            parent = None
            for index, literal in enumerate(literals):
                if index == 0 and literal in assumption_ids:
                    node_id = assumption_ids[literal]
                else:
                    edge_reason = (
                        ordered_reasons[index - 1]
                        if index > 0 and ordered_reasons
                        else (sorted(reason_set)[0] if reason_set else proof_kind)
                    )
                    if (
                        is_als_literal(literal)
                        or (
                            index > 0
                            and is_als_literal(literals[index - 1])
                        )
                    ):
                        kind = "advanced-rule"
                    elif any(
                        reason.startswith("advanced")
                        for reason in (edge_reason,)
                    ):
                        kind = "advanced-rule"
                    elif edge_reason == "dynamic":
                        kind = "dynamic-single"
                    elif (
                        is_group_literal(literal)
                        or (
                            index > 0
                            and is_group_literal(literals[index - 1])
                        )
                    ):
                        kind = "grouped-implication"
                    else:
                        kind = "static-implication"
                    node_id = add(
                        kind,
                        literal,
                        parents=(() if parent is None else (parent,)),
                        reason=edge_reason,
                        payload={"presentation": True},
                    )
                if parent is not None:
                    candidates, house_ids = support_values(
                        ordered_supports[index - 1]
                        if ordered_supports
                        else {}
                    )
                    edge_supports.append(ImplicationEdgeSupport(
                        source_id=parent,
                        target_id=node_id,
                        support_candidates=candidates,
                        support_house_ids=house_ids,
                    ))
                parent = node_id
            nodes[parent].payload["chain_terminal"] = True
            terminal_ids.append(parent)

            # Le endpoint-AIC possono provare più eliminazioni indipendenti
            # con lo stesso percorso centrale. Ogni conclusione resta legata
            # al terminale della propria catena di contraddizione esplicita.
            if (
                proof_kind in {"endpoint-aic", "grouped-endpoint-aic"}
                and not is_group_literal(literals[0])
                and not is_group_literal(literals[-1])
                and not is_als_literal(literals[0])
                and not is_als_literal(literals[-1])
                and literals[0][:3] == literals[-1][:3]
                and literals[0][3] != literals[-1][3]
            ):
                dedicated_evidence.setdefault(literals[-1], parent)
            elif (
                proof_kind == "grouped-endpoint-aic"
                and is_group_literal(literals[0])
                and is_group_literal(literals[-1])
                and literals[0][0] == literals[-1][0]
                and literals[0][1]
                and not literals[-1][1]
            ):
                for candidate in literals[0][0].candidates:
                    dedicated_evidence.setdefault((*candidate, False), parent)

        conclusion_specs = []
        for action, items, state in (
            ("placement", placements, True),
            ("elimination", eliminations, False),
        ):
            conclusion_specs.extend(
                (action, (row, column, value, state))
                for row, column, value in sorted(
                    set(tuple(item) for item in items)
                )
            )

        needs_common_evidence = any(
            literal not in dedicated_evidence
            for _, literal in conclusion_specs
        )
        evidence = ()
        if needs_common_evidence:
            evidence = tuple(dict.fromkeys(
                terminal_ids or assumption_ids.values()
            ))
            if len(evidence) > 1:
                evidence = (add(
                    "branch",
                    None,
                    parents=evidence,
                    reason="common-branches",
                    payload={
                        "branch_count": len(evidence),
                        "presentation": False,
                    },
                ),)
            if "contradiction" in str(proof_kind):
                evidence = (add(
                    "contradiction",
                    None,
                    parents=evidence,
                    reason=str(proof_kind),
                    payload={"presentation": False},
                ),)

        conclusion_ids = []
        for action, literal in conclusion_specs:
            parents = (
                (dedicated_evidence[literal],)
                if literal in dedicated_evidence
                else evidence
            )
            conclusion_ids.append(add(
                "common-conclusion",
                literal,
                parents=parents,
                reason=action,
                payload={"action": action, "presentation": False},
            ))

        roots = tuple(sorted(
            node.id for node in nodes.values() if not node.parents
        ))
        return cls(
            nodes=nodes,
            roots=roots,
            conclusions=tuple(conclusion_ids),
            nested_proofs={},
            edge_supports=tuple(edge_supports),
        )


def proof_dag(value) -> ProofDAG | None:
    if value is None:
        return None
    if isinstance(value, ProofDAG):
        return value
    return ProofDAG.from_dict(value)


def proof_structural_family(value) -> str:
    """Famiglia piu' specifica presente nella prova, in ordine tassonomico."""
    dag = proof_dag(value)
    if dag is None:
        return "candidate"
    if any(
        (
            node.conclusion is not None
            and is_als_literal(node.conclusion)
        )
        or node.payload.get("node_type") in {"als", "als-stem"}
        for node in dag.nodes.values()
    ):
        return "als"
    if any(
        (
            node.conclusion is not None
            and is_group_literal(node.conclusion)
        )
        or node.payload.get("node_type") == "group"
        for node in dag.nodes.values()
    ):
        return "group"
    return "candidate"


def dependency_shape(value) -> str:
    """Distingue una catena lineare da un DAG con merge/fork riconvergente."""
    dag = proof_dag(value)
    if dag is None:
        return "chain"
    return (
        "net"
        if any(len(node.parents) > 1 for node in dag.nodes.values())
        or proof_has_fork_and_merge(dag)
        else "chain"
    )


def proof_has_fork_and_merge(value) -> bool:
    """Rileva due rami di uno stesso fork che raggiungono un discendente."""
    dag = proof_dag(value)
    if dag is None:
        return False
    children = dag._children()

    def descendants(start):
        found = set()
        stack = list(children.get(start, ()))
        while stack:
            node_id = stack.pop()
            if node_id in found:
                continue
            found.add(node_id)
            stack.extend(children.get(node_id, ()))
        return found

    for branch_ids in children.values():
        if len(branch_ids) < 2:
            continue
        branch_descendants = [
            {branch_id, *descendants(branch_id)}
            for branch_id in branch_ids
        ]
        for index, left in enumerate(branch_descendants):
            if any(left & right for right in branch_descendants[index + 1:]):
                return True
    return False


def logic_payload(dag, *, kind: str, reasons=(), extra=None) -> dict:
    """Serializza una prova formale senza ricostruirla da viste lineari."""
    from . import proof_schema

    dag = proof_dag(dag)
    if dag is None:
        raise ValueError("logic_payload richiede un ProofDAG.")
    assumptions = [
        literal_record(node.conclusion)
        for node in sorted(dag.nodes.values(), key=lambda item: item.id)
        if node.kind == "assumption" and node.conclusion is not None
    ]
    payload = {
        "schema_version": proof_schema.PROOF_SCHEMA_VERSION,
        "kind": str(kind),
        "assumptions": assumptions,
        "chains": [
            [literal_record(literal) for literal in chain]
            for chain in dag.derived_chains()
        ],
        "chain_links": dag.derived_chain_links(),
        "reasons": sorted({str(reason) for reason in reasons or ()}),
        "proof_dag": dag.to_dict(),
        "dag_digest": dag.digest(),
    }
    payload.update(dict(extra or {}))
    payload["metrics"] = proof_schema.normalize_proof_metrics(payload)
    return payload


def classify_proof_structure(value, *, forcing_context: bool = False) -> str:
    """Applica la precedenza specifica e poi la forma chain/net P15."""
    family = proof_structural_family(value)
    if not forcing_context and family != "candidate":
        return family
    return dependency_shape(value)


__all__ = [
    "ALSLiteral",
    "ALSNode",
    "Candidate",
    "GroupLiteral",
    "GroupNode",
    "ImplicationEdgeSupport",
    "Literal",
    "MAX_PRESENTATION_CHAINS",
    "NODE_KINDS",
    "PROOF_DAG_SCHEMA_VERSION",
    "ProofDAG",
    "ProofLiteral",
    "ProofNode",
    "is_group_literal",
    "is_als_literal",
    "literal_cells",
    "literal_digit",
    "literal_record",
    "literal_sort_key",
    "literal_state",
    "normalize_literal",
    "proof_dag",
    "proof_has_fork_and_merge",
    "proof_structural_family",
    "dependency_shape",
    "classify_proof_structure",
    "logic_payload",
]
