"""Vere Nested Forcing Chains con sottoprove legate a inferenze interne.

Il motore non cerca soluzioni complete. Una sottoprova assume la negazione
di un singolo target nel contesto della catena esterna e la propaga fino a
contraddizione. Il nodo che usa quel target possiede la sottoprova nel
``ProofDAG.nested_proofs``; una semplice propagazione lunga o ramificata non
puo' quindi essere classificata Nested.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import proof


Candidate = tuple[int, int, int]
Literal = tuple[int, int, int, bool]

MAX_NESTED_DEPTH = 2
MAX_NESTED_PROOF_NODES = 512
MAX_NESTED_BRANCHES = 64
MAX_NESTED_SUBPROOFS = 32
MAX_NESTED_RESULTS = 2
MAX_NESTED_PROOF_ATTEMPTS = 512
MAX_NESTED_PREDECESSOR_EDGES = 4
NESTED_RULE_PROFILE_ID = "p16-dynamic-subchain-v1"


def _literal_key(literal):
    return literal[0], literal[1], literal[2], int(literal[3])


def _opposite(literal):
    return literal[0], literal[1], literal[2], not literal[3]


def _candidate(literal):
    return literal[:3]


def _fingerprint(grid, candidates):
    grid_values = tuple(
        int(grid[row, column])
        for row in range(9)
        for column in range(9)
    )
    masks = []
    for row in range(9):
        for column in range(9):
            mask = 0
            for value in candidates.get((row, column), ()):
                mask |= 1 << int(value)
            masks.append(mask)
    return grid_values, tuple(masks)


@dataclass(slots=True)
class NestedBudget:
    max_depth: int = MAX_NESTED_DEPTH
    max_nodes: int = MAX_NESTED_PROOF_NODES
    max_branches: int = MAX_NESTED_BRANCHES
    max_subproofs: int = MAX_NESTED_SUBPROOFS
    max_results: int = MAX_NESTED_RESULTS
    max_attempts: int = MAX_NESTED_PROOF_ATTEMPTS
    branches_used: int = 0
    proof_nodes_used: int = 0
    subproofs_used: int = 0
    attempts_used: int = 0
    truncated: bool = False

    def take_attempt(self, count=1):
        count = max(0, int(count))
        if self.attempts_used + count > self.max_attempts:
            self.truncated = True
            return False
        self.attempts_used += count
        return True

    def take_branch(self, count=1):
        count = max(0, int(count))
        if self.branches_used + count > self.max_branches:
            self.truncated = True
            return False
        self.branches_used += count
        return True

    def take_subproof(self, dag):
        metrics = dag.metrics()
        proof_nodes = metrics["proof_node_count"]
        subproofs = 1 + metrics["nested_subproof_count"]
        if (
            self.subproofs_used + subproofs > self.max_subproofs
            or self.proof_nodes_used + proof_nodes > self.max_nodes
        ):
            self.truncated = True
            return False
        self.subproofs_used += subproofs
        self.proof_nodes_used += proof_nodes
        return True

    def to_dict(self):
        return {
            "max_depth": self.max_depth,
            "max_nodes": self.max_nodes,
            "max_branches": self.max_branches,
            "max_subproofs": self.max_subproofs,
            "max_results": self.max_results,
            "max_attempts": self.max_attempts,
            "branches_used": self.branches_used,
            "proof_nodes_used": self.proof_nodes_used,
            "subproofs_used": self.subproofs_used,
            "attempts_used": self.attempts_used,
            "truncated": self.truncated,
            "rule_profile_id": NESTED_RULE_PROFILE_ID,
        }


@dataclass(frozen=True, slots=True)
class NestedProofResult:
    assumptions: tuple[Literal, ...]
    target: Literal
    dag: proof.ProofDAG
    proof_kind: str


def _node_kind(reason, parents):
    if not parents or reason == "assumption":
        return "assumption"
    if reason in {"x", "y", "peer"}:
        return "static-implication"
    if reason in {"cell-single", "unit-single"}:
        return "dynamic-single"
    return "advanced-rule"


class _DAGAssembler:
    def __init__(self):
        self.nodes = {}
        self.nested_proofs = {}
        self.next_id = 0

    def add(self, kind, conclusion, parents=(), reason="unspecified", payload=None):
        parents = tuple(dict.fromkeys(int(parent) for parent in parents))
        depth = (
            0
            if not parents
            else 1 + max(self.nodes[parent].depth for parent in parents)
        )
        node_id = self.next_id
        self.next_id += 1
        self.nodes[node_id] = proof.ProofNode(
            id=node_id,
            kind=kind,
            conclusion=conclusion,
            parents=parents,
            reason=reason,
            depth=depth,
            payload=dict(payload or {}),
        )
        return node_id

    def add_result_path(
        self,
        result,
        targets,
        *,
        branch_index,
        substitute: NestedProofResult | None = None,
        contradiction=False,
    ):
        targets = tuple(targets)
        ordered = result.proof_literals(targets)
        ids = {}

        # Il contesto esterno deve rimanere un ancestor esplicito del nodo
        # Nested anche quando il percorso locale verso il target non lo usa
        # come parent immediato.
        for source in result.sources:
            if substitute is not None and source == substitute.target:
                continue
            ids[source] = self.add(
                "assumption",
                source,
                reason="assumption",
                payload={
                    "branch_index": branch_index,
                    "presentation": True,
                },
            )

        for literal in ordered:
            if literal in ids:
                continue
            if substitute is not None and literal == substitute.target:
                owner_id = self.add(
                    "nested-subproof",
                    literal,
                    parents=tuple(ids[source] for source in substitute.assumptions),
                    reason="nested-inference",
                    payload={
                        "branch_index": branch_index,
                        "node_type": "nested-inference",
                        "rule_profile_id": NESTED_RULE_PROFILE_ID,
                        "subproof_kind": substitute.proof_kind,
                        "chain_terminal": False,
                        "presentation": True,
                    },
                )
                self.nested_proofs[owner_id] = substitute.dag
                ids[literal] = owner_id
                continue

            parent_ids = tuple(
                ids[parent]
                for parent in result.parents.get(literal, ())
                if parent in ids
            )
            reason = result.reasons.get(literal, "assumption")
            ids[literal] = self.add(
                _node_kind(reason, parent_ids),
                literal,
                parents=parent_ids,
                reason=reason,
                payload={
                    "branch_index": branch_index,
                    "presentation": True,
                },
            )

        target_ids = tuple(ids[target] for target in targets if target in ids)
        if not target_ids:
            raise ValueError("Il ramo Nested non contiene il proprio target.")
        if contradiction:
            return self.add(
                "contradiction",
                None,
                parents=target_ids,
                reason="nested-branch-contradiction",
                payload={
                    "branch_index": branch_index,
                    "chain_terminal": True,
                    "presentation": False,
                },
            )
        terminal = target_ids[-1]
        self.nodes[terminal].payload["chain_terminal"] = True
        return terminal

    def add_nested_inference(self, result, nested, *, branch_index):
        context_ids = []
        for source in result.sources:
            context_ids.append(self.add(
                "assumption",
                source,
                reason="assumption",
                payload={
                    "branch_index": branch_index,
                    "presentation": True,
                },
            ))
        owner_id = self.add(
            "nested-subproof",
            nested.target,
            parents=context_ids,
            reason="nested-inference",
            payload={
                "branch_index": branch_index,
                "node_type": "nested-inference",
                "rule_profile_id": NESTED_RULE_PROFILE_ID,
                "subproof_kind": nested.proof_kind,
                "chain_terminal": True,
                "presentation": True,
            },
        )
        self.nested_proofs[owner_id] = nested.dag
        return owner_id

    def finish(self, conclusions):
        return proof.ProofDAG(
            nodes=self.nodes,
            roots=tuple(sorted(
                node.id for node in self.nodes.values() if not node.parents
            )),
            conclusions=tuple(conclusions),
            nested_proofs=self.nested_proofs,
        )


class NestedForcingEngine:
    """Ricerca locale e limitata di forcing chain con vere sottoprove."""

    def __init__(self, grid, candidates):
        # Import tardivo: logic_engine crea questa classe soltanto dopo avere
        # completato il proprio import, evitando un modulo parallelo del DAG.
        from . import logic_engine

        self.logic_engine = logic_engine
        self.grid = grid.copy()
        self.candidates = {
            cell: set(values) for cell, values in candidates.items()
        }
        self.state_fingerprint = _fingerprint(self.grid, self.candidates)
        self.propagator = logic_engine.DynamicPropagator(
            self.grid,
            self.candidates,
        )
        self.all_candidates = tuple(sorted(
            (
                (row, column, value)
                for (row, column), values in self.candidates.items()
                for value in values
            )
        ))
        self.outer_candidates = tuple(sorted(
            self.all_candidates,
            key=lambda candidate: (
                len(self.candidates.get(candidate[:2], ())),
                candidate,
            ),
        ))
        self._propagation_cache = {}
        self._proof_memo = {}
        self._cycle_guard = set()
        reverse_static = {}
        for source, edges in self.propagator.initial_graph.adjacency.items():
            for edge in edges:
                reverse_static.setdefault(edge.target, set()).add(source)
        self._reverse_static = {
            target: tuple(sorted(sources, key=_literal_key))
            for target, sources in reverse_static.items()
        }

    @staticmethod
    def _normalise_assumptions(assumptions):
        return tuple(sorted(set(assumptions), key=_literal_key))

    def _propagate(self, assumptions):
        assumptions = self._normalise_assumptions(assumptions)
        key = assumptions, NESTED_RULE_PROFILE_ID
        if key not in self._propagation_cache:
            self._propagation_cache[key] = (
                self.propagator.propagate_assumptions(
                    assumptions,
                    mode="dynamic",
                    advanced_level=0,
                )
            )
        return self._propagation_cache[key]

    @staticmethod
    def _uses_every_assumption(result, assumptions):
        targets = result.contradiction_literals or (result.source,)
        used = set(result.proof_literals(targets))
        return set(assumptions) <= used

    def _logical_predecessors(self, target):
        """Letterali locali che possono concorrere direttamente al target.

        Non si scelgono celle residue arbitrarie. Si parte dai predecessori
        immediati nella cella e nelle case del target, poi si risale soltanto
        il suo cono statico X/Y, con profondita' limitata. La propagazione
        puo' combinare uno di questi predecessori con il contesto dimostrato.
        """
        row, column, value, is_on = target
        cell = (row, column)
        predecessors = set()
        if is_on:
            predecessors.update(
                (row, column, other, False)
                for other in self.candidates.get(cell, ())
                if other != value
            )
            for unit_index in self.logic_engine._UNITS_BY_CELL[cell]:
                predecessors.update(
                    (other_row, other_column, value, False)
                    for other_row, other_column in self.logic_engine.UNITS[
                        unit_index
                    ]
                    if (
                        (other_row, other_column) != cell
                        and value in self.candidates.get(
                            (other_row, other_column), ()
                        )
                    )
                )
        else:
            predecessors.update(
                (row, column, other, True)
                for other in self.candidates.get(cell, ())
                if other != value
            )
            predecessors.update(
                (other_row, other_column, value, True)
                for other_row, other_column in self.logic_engine.peers(
                    row, column
                )
                if value in self.candidates.get(
                    (other_row, other_column), ()
                )
            )

        frontier = {target}
        visited = {target}
        for _ in range(MAX_NESTED_PREDECESSOR_EDGES):
            next_frontier = set()
            for literal in frontier:
                for source in self._reverse_static.get(literal, ()):
                    if source in visited:
                        continue
                    visited.add(source)
                    predecessors.add(source)
                    next_frontier.add(source)
            if not next_frontier:
                break
            frontier = next_frontier
        return tuple(sorted(predecessors, key=_literal_key))

    @staticmethod
    def _valid_subproof(value, budget):
        if value is None:
            return None
        metrics = value.dag.metrics()
        if (
            metrics["nested_depth"] > budget.max_depth - 1
            or 1 + metrics["nested_subproof_count"] > budget.max_subproofs
            or metrics["proof_node_count"] > budget.max_nodes
        ):
            budget.truncated = True
            return None
        return value

    def prove(self, assumptions, target, *, remaining_depth, budget):
        """Dimostra una singola inferenza nel contesto della catena esterna."""
        assumptions = self._normalise_assumptions(assumptions)
        target = tuple(target)
        remaining_depth = int(remaining_depth)
        if remaining_depth < 1 or remaining_depth > budget.max_depth:
            return None

        key = (
            self.state_fingerprint,
            assumptions,
            target,
            remaining_depth,
            NESTED_RULE_PROFILE_ID,
        )
        if key in self._proof_memo:
            cached = self._proof_memo[key]
            return (
                None
                if cached is None
                else self._valid_subproof(cached, budget)
            )
        if key in self._cycle_guard:
            return None
        self._cycle_guard.add(key)

        natural_failure = True
        try:
            base = self._propagate(assumptions)
            if base.contradiction or target in base.literals:
                self._proof_memo[key] = None
                return None

            opposite = _opposite(target)
            trial_assumptions = self._normalise_assumptions((
                *assumptions,
                opposite,
            ))
            if budget.take_attempt():
                trial = self._propagate(trial_assumptions)
                if (
                    trial.contradiction
                    and self._uses_every_assumption(trial, trial_assumptions)
                ):
                    if not budget.take_branch():
                        natural_failure = False
                        return None
                    dag = self.logic_engine._propagation_proof_dag(
                        ((
                            trial,
                            trial.contradiction_literals,
                            True,
                        ),),
                        target,
                        action="nested-inference",
                    )
                    result = NestedProofResult(
                        assumptions,
                        target,
                        dag,
                        "contradiction-subchain",
                    )
                    self._proof_memo[key] = result
                    return self._valid_subproof(result, budget)
            else:
                natural_failure = False

            # Profondita' 2: una sottoprova puo' a sua volta giustificare
            # una singola inferenza intermedia usata per raggiungere target.
            if remaining_depth > 1 and not budget.truncated:
                base_literals = set(base.literals) | set(assumptions)
                for intermediate in self._logical_predecessors(target):
                    if (
                        intermediate in base_literals
                        or intermediate in {target, opposite}
                    ):
                        continue
                    if not budget.take_attempt():
                        natural_failure = False
                        break
                    augmented = self._propagate((
                        *assumptions,
                        intermediate,
                    ))
                    if augmented.contradiction or target not in augmented.literals:
                        continue
                    nested = self.prove(
                        assumptions,
                        intermediate,
                        remaining_depth=remaining_depth - 1,
                        budget=budget,
                    )
                    if nested is None:
                        continue
                    assembler = _DAGAssembler()
                    terminal = assembler.add_result_path(
                        augmented,
                        (target,),
                        branch_index=0,
                        substitute=nested,
                    )
                    conclusion = assembler.add(
                        "common-conclusion",
                        target,
                        parents=(terminal,),
                        reason="nested-inference",
                        payload={
                            "action": "nested-inference",
                            "presentation": False,
                        },
                    )
                    result = NestedProofResult(
                        assumptions,
                        target,
                        assembler.finish((conclusion,)),
                        "nested-subchain",
                    )
                    self._proof_memo[key] = result
                    return self._valid_subproof(result, budget)

            if natural_failure:
                self._proof_memo[key] = None
            return None
        finally:
            self._cycle_guard.discard(key)

    @staticmethod
    def _effect(target):
        candidate = _candidate(target)
        return (
            ((candidate,), ())
            if target[3]
            else ((), (candidate,))
        )

    def _logic_payload(self, dag, kind, budget):
        metrics = dag.metrics()
        if (
            metrics["nested_depth"] < 1
            or metrics["nested_depth"] > budget.max_depth
            or metrics["nested_subproof_count"] < 1
            or metrics["nested_subproof_count"] > budget.max_subproofs
            or metrics["proof_node_count"] > budget.max_nodes
        ):
            return None
        return proof.logic_payload(
            dag,
            kind=kind,
            reasons=(node.reason for node in dag.nodes.values()),
            extra={
                "nested_search": budget.to_dict(),
                "rule_profile_id": NESTED_RULE_PROFILE_ID,
                "complete": False,
                "exhaustive": False,
            },
        )

    def _deduction(self, description, target, kind, dag, budget):
        logic = self._logic_payload(dag, kind, budget)
        if logic is None:
            return None
        placements, eliminations = self._effect(target)
        return {
            "description": description,
            "placements": sorted(placements),
            "eliminations": sorted(eliminations),
            "primary": dag.primary_cells(),
            "logic": logic,
        }

    def _common_dag(self, branches, target, *, action):
        assembler = _DAGAssembler()
        terminals = []
        for branch_index, (result, nested) in enumerate(branches):
            if target in result.literals:
                terminals.append(assembler.add_result_path(
                    result,
                    (target,),
                    branch_index=branch_index,
                ))
            elif nested is not None:
                terminals.append(assembler.add_nested_inference(
                    result,
                    nested,
                    branch_index=branch_index,
                ))
            else:
                raise ValueError("Ogni ramo deve dimostrare il target Nested.")
        conclusion = assembler.add(
            "common-conclusion",
            target,
            parents=terminals,
            reason=action,
            payload={"action": action, "presentation": False},
        )
        return assembler.finish((conclusion,))

    def _try_common(self, outcomes, target, budget):
        branches = []
        nested_count = 0
        for result in outcomes:
            if target in result.literals:
                branches.append((result, None))
                continue
            nested = self.prove(
                result.sources,
                target,
                remaining_depth=budget.max_depth,
                budget=budget,
            )
            if nested is None:
                return None
            nested_count += 1
            branches.append((result, nested))
        if not nested_count:
            return None
        for _, nested in branches:
            if nested is not None and not budget.take_subproof(nested.dag):
                return None
        if not budget.take_branch(len(branches)):
            return None
        return branches

    def _double_deductions(self, budget, *, max_results):
        results = []
        for candidate in self.outer_candidates:
            source_on = (*candidate, True)
            source_off = (*candidate, False)
            outcomes = (
                self._propagate((source_on,)),
                self._propagate((source_off,)),
            )
            if any(result.contradiction for result in outcomes):
                continue
            common = outcomes[0].literals & outcomes[1].literals
            targets = sorted(
                (outcomes[0].literals | outcomes[1].literals) - common,
                key=_literal_key,
            )
            for target in targets:
                if _candidate(target) == candidate:
                    continue
                branches = self._try_common(outcomes, target, budget)
                if branches is None:
                    if budget.truncated:
                        return results
                    continue
                action = "placement" if target[3] else "elimination"
                dag = self._common_dag(branches, target, action=action)
                deduction = self._deduction(
                    "I due stati del candidato producono la stessa "
                    "conclusione; almeno un ramo usa una vera sottocatena "
                    "per dimostrare una singola inferenza interna.",
                    target,
                    "nested-double",
                    dag,
                    budget,
                )
                if deduction is not None:
                    results.append(deduction)
                if len(results) >= max_results or budget.truncated:
                    return results
        return results

    def _contradiction_deductions(self, budget, *, max_results):
        results = []
        for candidate in self.outer_candidates:
            for source_state in (True, False):
                source = (*candidate, source_state)
                base = self._propagate((source,))
                if base.contradiction:
                    continue
                for target_candidate in self.all_candidates:
                    for target_state in (False, True):
                        target = (*target_candidate, target_state)
                        if target in base.literals or _candidate(target) == candidate:
                            continue
                        augmented = self._propagate((source, target))
                        if not augmented.contradiction:
                            continue
                        nested = self.prove(
                            (source,),
                            target,
                            remaining_depth=budget.max_depth,
                            budget=budget,
                        )
                        if nested is None:
                            if budget.truncated:
                                return results
                            continue
                        if not budget.take_subproof(nested.dag):
                            return results
                        if not budget.take_branch():
                            return results
                        assembler = _DAGAssembler()
                        terminal = assembler.add_result_path(
                            augmented,
                            augmented.contradiction_literals,
                            branch_index=0,
                            substitute=nested,
                            contradiction=True,
                        )
                        conclusion_literal = _opposite(source)
                        action = (
                            "placement" if conclusion_literal[3]
                            else "elimination"
                        )
                        conclusion = assembler.add(
                            "common-conclusion",
                            conclusion_literal,
                            parents=(terminal,),
                            reason=action,
                            payload={"action": action, "presentation": False},
                        )
                        deduction = self._deduction(
                            "L'ipotesi principale usa una vera sottocatena "
                            "per un'inferenza interna e solo allora raggiunge "
                            "la contraddizione.",
                            conclusion_literal,
                            "nested-contradiction",
                            assembler.finish((conclusion,)),
                            budget,
                        )
                        if deduction is not None:
                            results.append(deduction)
                        if len(results) >= max_results or budget.truncated:
                            return results
        return results

    def _source_groups(self, source_kind):
        if source_kind == "cell":
            for (row, column), values in sorted(self.candidates.items()):
                candidates = tuple(
                    (row, column, value) for value in sorted(values)
                )
                if len(candidates) >= 3:
                    yield f"R{row + 1}C{column + 1}", candidates
            return

        for unit_index, unit in enumerate(self.logic_engine.UNITS):
            for value in range(1, 10):
                candidates = tuple(
                    (row, column, value)
                    for row, column in unit
                    if value in self.candidates.get((row, column), ())
                )
                if len(candidates) >= 3:
                    yield f"casa {unit_index + 1} per {value}", candidates

    def _multiple_deductions(
        self,
        source_kind,
        budget,
        *,
        max_results,
    ):
        results = []
        for label, candidates in self._source_groups(source_kind):
            outcomes = tuple(
                self._propagate(((*candidate, True),))
                for candidate in candidates
            )
            if any(result.contradiction for result in outcomes):
                continue
            common = set.intersection(*(result.literals for result in outcomes))
            targets = sorted(
                set().union(*(result.literals for result in outcomes)) - common,
                key=_literal_key,
            )
            for target in targets:
                if _candidate(target) in candidates:
                    continue
                branches = self._try_common(outcomes, target, budget)
                if branches is None:
                    if budget.truncated:
                        return results
                    continue
                action = "placement" if target[3] else "elimination"
                dag = self._common_dag(branches, target, action=action)
                deduction = self._deduction(
                    f"Ogni alternativa di {label} produce la stessa "
                    "conclusione e almeno una la dimostra tramite una vera "
                    "sottocatena.",
                    target,
                    f"nested-{source_kind}",
                    dag,
                    budget,
                )
                if deduction is not None:
                    results.append(deduction)
                if len(results) >= max_results or budget.truncated:
                    return results
        return results

    def find_deductions(self, max_results=MAX_NESTED_RESULTS):
        max_results = min(max(1, int(max_results)), MAX_NESTED_RESULTS)
        budget = NestedBudget(max_results=max_results)
        results = []
        finders = (
            self._double_deductions,
            self._contradiction_deductions,
            lambda value, *, max_results: self._multiple_deductions(
                "cell", value, max_results=max_results
            ),
            lambda value, *, max_results: self._multiple_deductions(
                "region", value, max_results=max_results
            ),
        )
        seen = set()
        for finder in finders:
            if len(results) >= max_results or budget.truncated:
                break
            for deduction in finder(
                budget,
                max_results=max_results - len(results),
            ):
                signature = (
                    tuple(deduction["placements"]),
                    tuple(deduction["eliminations"]),
                )
                if signature in seen:
                    continue
                seen.add(signature)
                results.append(deduction)
                if len(results) >= max_results:
                    break
        return results


__all__ = [
    "MAX_NESTED_BRANCHES",
    "MAX_NESTED_DEPTH",
    "MAX_NESTED_PROOF_NODES",
    "MAX_NESTED_PROOF_ATTEMPTS",
    "MAX_NESTED_PREDECESSOR_EDGES",
    "MAX_NESTED_RESULTS",
    "MAX_NESTED_SUBPROOFS",
    "NESTED_RULE_PROFILE_ID",
    "NestedBudget",
    "NestedForcingEngine",
    "NestedProofResult",
]
