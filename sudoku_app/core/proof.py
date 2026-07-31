"""Modello formale delle prove logiche del solver.

``ProofDAG`` e' la rappresentazione autorevole. Le catene lineari sono una
vista derivata e limitata, destinata esclusivamente a spiegazioni e UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping, Sequence
import hashlib
import json


Literal = tuple[int, int, int, bool]

PROOF_DAG_SCHEMA_VERSION = "1.0.0"
MAX_PRESENTATION_CHAINS = 16

NODE_KINDS = frozenset({
    "assumption",
    "static-implication",
    "dynamic-single",
    "advanced-rule",
    "common-conclusion",
    "contradiction",
    "branch",
    "nested-subproof",
})


def normalize_literal(value) -> Literal | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        state = value.get("state")
        is_on = state in {True, 1, "on", "true", "True"}
        literal = (
            int(value["row"]),
            int(value["column"]),
            int(value["value"]),
            is_on,
        )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
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


def literal_record(literal: Literal | None):
    literal = normalize_literal(literal)
    if literal is None:
        return None
    row, column, value, is_on = literal
    return {
        "row": row,
        "column": column,
        "value": value,
        "state": "on" if is_on else "off",
    }


def _normalise_ids(values):
    return tuple(dict.fromkeys(int(value) for value in values or ()))


def _json_payload(payload):
    try:
        return json.loads(json.dumps(payload or {}, sort_keys=True))
    except (TypeError, ValueError) as error:
        raise TypeError("Il payload di un nodo deve essere JSON serializzabile.") from error


@dataclass(slots=True)
class ProofNode:
    id: int
    kind: str
    conclusion: Literal | None
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


@dataclass(slots=True)
class ProofDAG:
    nodes: dict[int, ProofNode]
    roots: tuple[int, ...]
    conclusions: tuple[int, ...]
    nested_proofs: dict[int, "ProofDAG"] = field(default_factory=dict)

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

    def derived_chains(self, max_chains=MAX_PRESENTATION_CHAINS):
        """Deriva viste lineari deterministiche senza renderle autorevoli."""
        if isinstance(max_chains, bool) or int(max_chains) < 1:
            raise ValueError("max_chains deve essere positivo.")
        max_chains = min(int(max_chains), MAX_PRESENTATION_CHAINS)
        targets = sorted(
            node.id
            for node in self.nodes.values()
            if node.payload.get("chain_terminal")
            or node.kind == "contradiction"
        )
        chains = []
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
                for node_id in path:
                    node = self.nodes[node_id]
                    if (
                        node.conclusion is not None
                        and node.payload.get("presentation", True)
                    ):
                        if not literals or literals[-1] != node.conclusion:
                            literals.append(node.conclusion)
                signature = tuple(literals)
                if signature and signature not in seen:
                    seen.add(signature)
                    chains.append(list(signature))
                if len(chains) >= max_chains:
                    break
            if len(chains) >= max_chains:
                break
        return sorted(chains, key=lambda chain: (-len(chain), tuple(chain)))

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
        }

    def primary_cells(self):
        return sorted({
            (node.conclusion[0], node.conclusion[1])
            for node in self.nodes.values()
            if node.conclusion is not None
            and node.kind not in {"common-conclusion"}
        })

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

        roots = tuple(sorted(
            node.id for node in nodes.values() if not node.parents
        ))
        return ProofDAG(
            nodes=nodes,
            roots=roots,
            conclusions=tuple(sorted(selected)),
            nested_proofs=dict(self.nested_proofs),
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
        proof_kind="unspecified",
        placements=(),
        eliminations=(),
    ):
        """Converte prove lineari legacy in un DAG formale."""
        nodes = {}
        next_id = 0
        assumption_ids = {}
        reason_set = {str(reason) for reason in reasons or ()}

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
        for raw_chain in chains or ():
            literals = [normalize_literal(item) for item in raw_chain]
            if not literals:
                continue
            parent = None
            for index, literal in enumerate(literals):
                if index == 0 and literal in assumption_ids:
                    node_id = assumption_ids[literal]
                else:
                    if any(
                        reason.startswith("advanced")
                        for reason in reason_set
                    ):
                        kind = "advanced-rule"
                    elif "dynamic" in reason_set:
                        kind = "dynamic-single"
                    else:
                        kind = "static-implication"
                    node_id = add(
                        kind,
                        literal,
                        parents=(() if parent is None else (parent,)),
                        reason=(sorted(reason_set)[0] if reason_set else proof_kind),
                        payload={"presentation": True},
                    )
                parent = node_id
            nodes[parent].payload["chain_terminal"] = True
            terminal_ids.append(parent)

        evidence = tuple(dict.fromkeys(terminal_ids or assumption_ids.values()))
        if len(evidence) > 1:
            evidence = (add(
                "branch",
                None,
                parents=evidence,
                reason="common-branches",
                payload={"branch_count": len(evidence), "presentation": False},
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
        for action, items, state in (
            ("placement", placements, True),
            ("elimination", eliminations, False),
        ):
            for row, column, value in sorted(set(tuple(item) for item in items)):
                conclusion_ids.append(add(
                    "common-conclusion",
                    (row, column, value, state),
                    parents=evidence,
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
        )


def proof_dag(value) -> ProofDAG | None:
    if value is None:
        return None
    if isinstance(value, ProofDAG):
        return value
    return ProofDAG.from_dict(value)


__all__ = [
    "Literal",
    "MAX_PRESENTATION_CHAINS",
    "NODE_KINDS",
    "PROOF_DAG_SCHEMA_VERSION",
    "ProofDAG",
    "ProofNode",
    "literal_record",
    "normalize_literal",
    "proof_dag",
]
