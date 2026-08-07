"""Regressioni P16 per vere Nested Forcing Chains."""

import unittest

import numpy as np

from sudoku_app.core import nested_forcing
from sudoku_app.core import proof
from sudoku_app.core import technique_classification
from sudoku_app.core import techniques
from sudoku_app.core.data_structure import SudokuState
from sudoku_app.core.logic_engine import LogicEngine


SOLVED = (
    "534678912672195348198342567859761423426853791"
    "713924856961537284287419635345286179"
)


def nested_state(*, near_miss=False):
    """Stato minimo: un ramo ha bisogno della sottocatena, l'altro no."""
    grid = np.array([int(value) for value in SOLVED], dtype=int).reshape(9, 9)
    entries = {
        (0, 5): {4, 5},
        (0, 8): {4, 5},
        (8, 8): {1, 2, 4},
        (7, 5): {1, 2, 4},
        (7, 6): {1, 4},
        (7, 7): {2, 6} if near_miss else {2, 4},
    }
    for cell in entries:
        grid[cell] = 0
    state = SudokuState(grid)
    state.candidates = [[set() for _ in range(9)] for _ in range(9)]
    for (row, column), values in entries.items():
        state.candidates[row][column] = set(values)
    return state


def node(
    node_id,
    conclusion,
    parents=(),
    *,
    kind="static-implication",
    reason="synthetic",
    payload=None,
    depth=None,
):
    return proof.ProofNode(
        id=node_id,
        kind=kind,
        conclusion=conclusion,
        parents=parents,
        reason=reason,
        depth=(0 if not parents else 1) if depth is None else depth,
        payload=dict(payload or {"presentation": True}),
    )


def leaf_proof(target, *, reason="nested-inference"):
    return proof.ProofDAG(
        nodes={
            0: node(0, (4, 4, 8, True), kind="assumption"),
            1: node(
                1,
                target,
                (0,),
                kind="common-conclusion",
                reason=reason,
            ),
        },
        roots=(0,),
        conclusions=(1,),
    )


def wrap_nested(target, nested):
    return proof.ProofDAG(
        nodes={
            0: node(0, (3, 3, 7, True), kind="assumption"),
            1: node(
                1,
                target,
                (0,),
                kind="nested-subproof",
                reason="nested-inference",
                payload={
                    "node_type": "nested-inference",
                    "presentation": True,
                },
            ),
        },
        roots=(0,),
        conclusions=(1,),
        nested_proofs={1: nested},
    )


def double_proof(nested):
    target = (7, 5, 4, False)
    return proof.ProofDAG(
        nodes={
            0: node(0, (0, 5, 4, True), kind="assumption"),
            1: node(1, target, (0,)),
            2: node(2, (0, 5, 4, False), kind="assumption"),
            3: node(
                3,
                target,
                (2,),
                kind="nested-subproof",
                reason="nested-inference",
                payload={
                    "node_type": "nested-inference",
                    "presentation": True,
                },
            ),
            4: node(
                4,
                target,
                (1, 3),
                kind="common-conclusion",
                depth=2,
            ),
        },
        roots=(0, 2),
        conclusions=(4,),
        nested_proofs={3: nested},
    )


def multiple_proof(assumptions, nested):
    target = (7, 5, 4, False)
    nodes = {}
    terminals = []
    nested_proofs = {}
    next_id = 0
    for branch_index, assumption in enumerate(assumptions):
        root_id = next_id
        nodes[root_id] = node(root_id, assumption, kind="assumption")
        next_id += 1
        terminal_id = next_id
        if branch_index == 1:
            nodes[terminal_id] = node(
                terminal_id,
                target,
                (root_id,),
                kind="nested-subproof",
                reason="nested-inference",
                payload={
                    "node_type": "nested-inference",
                    "presentation": True,
                },
            )
            nested_proofs[terminal_id] = nested
        else:
            nodes[terminal_id] = node(
                terminal_id,
                target,
                (root_id,),
            )
        terminals.append(terminal_id)
        next_id += 1
    nodes[next_id] = node(
        next_id,
        target,
        tuple(terminals),
        kind="common-conclusion",
        depth=2,
    )
    return proof.ProofDAG(
        nodes=nodes,
        roots=tuple(range(0, next_id, 2)),
        conclusions=(next_id,),
        nested_proofs=nested_proofs,
    )


def contradiction_proof(nested):
    target = (7, 5, 4, False)
    source = (0, 5, 4, True)
    return proof.ProofDAG(
        nodes={
            0: node(0, source, kind="assumption"),
            1: node(
                1,
                target,
                (0,),
                kind="nested-subproof",
                reason="nested-inference",
                payload={
                    "node_type": "nested-inference",
                    "presentation": True,
                },
            ),
            2: node(
                2,
                None,
                (1,),
                kind="contradiction",
                depth=2,
            ),
            3: node(
                3,
                (0, 5, 4, False),
                (2,),
                kind="common-conclusion",
                depth=3,
            ),
        },
        roots=(0,),
        conclusions=(3,),
        nested_proofs={1: nested},
    )


class NestedForcingEngineTests(unittest.TestCase):
    def test_p16_budgets_are_explicit(self):
        self.assertEqual(nested_forcing.MAX_NESTED_DEPTH, 2)
        self.assertEqual(nested_forcing.MAX_NESTED_PROOF_NODES, 512)
        self.assertEqual(nested_forcing.MAX_NESTED_BRANCHES, 64)
        self.assertEqual(nested_forcing.MAX_NESTED_SUBPROOFS, 32)
        self.assertEqual(nested_forcing.MAX_NESTED_RESULTS, 2)
        self.assertEqual(nested_forcing.MAX_NESTED_PROOF_ATTEMPTS, 512)
        self.assertEqual(nested_forcing.MAX_NESTED_PREDECESSOR_EDGES, 4)

    def test_real_nested_proves_one_internal_inference(self):
        state = nested_state()
        engine = LogicEngine(state)
        deductions = engine.find("Nested Forcing Chain", max_results=2)

        self.assertEqual(len(deductions), 2)
        metadata = engine.search_metadata("Nested Forcing Chain")
        self.assertTrue(metadata["search_truncated"])
        self.assertIn(
            "nested_result_limit",
            metadata["truncated_reasons"],
        )
        deduction = next(
            item for item in deductions
            if item["eliminations"] == [(7, 5, 4)]
        )
        self.assertEqual(deduction["eliminations"], [(7, 5, 4)])
        self.assertEqual(deduction["logic"]["kind"], "nested-double")
        self.assertFalse(deduction["logic"]["complete"])
        self.assertFalse(deduction["logic"]["exhaustive"])
        self.assertEqual(
            technique_classification.classify_logic_technique(
                state,
                "Nested Forcing Chain",
                deduction,
            ),
            "Nested Double Forcing Chain",
        )

        dag = proof.proof_dag(deduction["logic"]["proof_dag"])
        self.assertEqual(dag.metrics()["nested_depth"], 1)
        self.assertEqual(dag.metrics()["nested_subproof_count"], 1)
        self.assertTrue(any(
            item["logic"]["metrics"]["nested_depth"] == 2
            for item in deductions
        ))
        self.assertEqual(len(dag.nested_proofs), 1)
        owner_id, subproof = next(iter(dag.nested_proofs.items()))
        owner = dag.nodes[owner_id]
        self.assertEqual(owner.kind, "nested-subproof")
        self.assertEqual(owner.payload["node_type"], "nested-inference")
        self.assertIn(
            owner.conclusion,
            {subproof.nodes[item].conclusion for item in subproof.conclusions},
        )
        self.assertEqual(
            {subproof.nodes[item].conclusion for item in subproof.roots},
            {(0, 5, 5, True), (7, 5, 4, True)},
        )
        self.assertIsNone(engine._complete_forcing_tree_search)

        moves = techniques.nested_forcing_chain(state)
        self.assertEqual(len(moves), 2)
        self.assertEqual(
            {move["technique_id"] for move in moves},
            {"nested.double"},
        )
        self.assertEqual(
            {move["technique"] for move in moves},
            {"Nested Double Forcing Chain"},
        )
        self.assertEqual(
            {move["engine_type"] for move in moves},
            {"nested"},
        )

    def test_missing_subchain_is_a_near_miss(self):
        state = nested_state(near_miss=True)
        engine = LogicEngine(state)

        self.assertEqual(engine.find("Nested Forcing Chain", 2), [])
        self.assertEqual(techniques.nested_forcing_chain(state), [])
        self.assertIsNone(engine._complete_forcing_tree_search)

    def test_memo_key_cycle_guard_and_hard_limits(self):
        state = nested_state()
        engine = nested_forcing.NestedForcingEngine(
            state.grid,
            {
                (row, column): set(state.candidates[row][column])
                for row in range(9)
                for column in range(9)
                if state.candidates[row][column]
            },
        )
        assumptions = ((0, 5, 5, True),)
        target = (7, 5, 4, False)
        budget = nested_forcing.NestedBudget()
        result = engine.prove(
            assumptions,
            target,
            remaining_depth=1,
            budget=budget,
        )

        self.assertIsNotNone(result)
        self.assertEqual(len(engine._proof_memo), 1)
        key = next(iter(engine._proof_memo))
        self.assertEqual(len(key), 5)
        self.assertEqual(key[0], engine.state_fingerprint)
        self.assertEqual(key[1], assumptions)
        self.assertEqual(key[2], target)
        self.assertEqual(key[3], 1)
        self.assertEqual(key[4], nested_forcing.NESTED_RULE_PROFILE_ID)

        guarded = nested_forcing.NestedForcingEngine(
            state.grid,
            engine.candidates,
        )
        guarded_key = (
            guarded.state_fingerprint,
            assumptions,
            target,
            1,
            nested_forcing.NESTED_RULE_PROFILE_ID,
        )
        guarded._cycle_guard.add(guarded_key)
        self.assertIsNone(guarded.prove(
            assumptions,
            target,
            remaining_depth=1,
            budget=nested_forcing.NestedBudget(),
        ))

        small_engine = nested_forcing.NestedForcingEngine(
            state.grid,
            engine.candidates,
        )
        small_budget = nested_forcing.NestedBudget(max_nodes=1)
        self.assertIsNone(small_engine.prove(
            assumptions,
            target,
            remaining_depth=1,
            budget=small_budget,
        ))
        self.assertTrue(small_budget.truncated)
        self.assertIsNotNone(small_engine.prove(
            assumptions,
            target,
            remaining_depth=1,
            budget=nested_forcing.NestedBudget(),
        ))
        limited = nested_forcing.NestedForcingEngine(
            state.grid,
            engine.candidates,
        )
        branch_budget = nested_forcing.NestedBudget(max_branches=0)
        self.assertIsNone(limited.prove(
            assumptions,
            target,
            remaining_depth=1,
            budget=branch_budget,
        ))
        self.assertTrue(branch_budget.truncated)

        attempts_engine = nested_forcing.NestedForcingEngine(
            state.grid,
            engine.candidates,
        )
        attempts_budget = nested_forcing.NestedBudget(max_attempts=0)
        self.assertIsNone(attempts_engine.prove(
            assumptions,
            target,
            remaining_depth=1,
            budget=attempts_budget,
        ))
        self.assertTrue(attempts_budget.truncated)


class NestedClassificationTests(unittest.TestCase):
    def test_all_four_specific_names_remain_separate(self):
        target = (7, 5, 4, False)
        subproof = leaf_proof(target)
        cases = (
            ("nested-contradiction", contradiction_proof(subproof), "nested.contradiction"),
            ("nested-double", double_proof(subproof), "nested.double"),
            (
                "nested-cell",
                multiple_proof((
                    (0, 0, 1, True),
                    (0, 0, 2, True),
                    (0, 0, 3, True),
                ), subproof),
                "nested.cell",
            ),
            (
                "nested-region",
                multiple_proof((
                    (0, 0, 1, True),
                    (0, 3, 1, True),
                    (0, 6, 1, True),
                ), subproof),
                "nested.region",
            ),
        )
        for kind, dag, expected in cases:
            with self.subTest(kind=kind):
                self.assertEqual(
                    technique_classification.classify_nested_forcing({
                        "kind": kind,
                        "proof_dag": dag.to_dict(),
                    }),
                    expected,
                )

    def test_depth_two_is_preserved_and_depth_three_is_rejected(self):
        target = (7, 5, 4, False)
        depth_two = double_proof(wrap_nested(target, leaf_proof(target)))
        logic = {
            "kind": "nested-double",
            "proof_dag": depth_two.to_dict(),
            "complete": False,
            "exhaustive": False,
        }

        self.assertEqual(depth_two.metrics()["nested_depth"], 2)
        self.assertEqual(depth_two.metrics()["nested_subproof_count"], 2)
        self.assertEqual(
            technique_classification.classify_nested_forcing(logic),
            "nested.double",
        )
        restored = proof.ProofDAG.from_dict(depth_two.to_dict())
        self.assertEqual(restored.metrics()["nested_depth"], 2)
        self.assertEqual(restored.metrics()["nested_subproof_count"], 2)

        depth_three = double_proof(
            wrap_nested(target, wrap_nested(target, leaf_proof(target)))
        )
        logic["proof_dag"] = depth_three.to_dict()
        self.assertEqual(depth_three.metrics()["nested_depth"], 3)
        self.assertIsNone(
            technique_classification.classify_nested_forcing(logic)
        )

    def test_nested_label_rejects_generic_complete_and_malformed_proofs(self):
        self.assertIsNone(technique_classification.classify_nested_forcing({
            "kind": "dynamic-region-reduction",
            "proof_dag": leaf_proof((7, 5, 4, False)).to_dict(),
        }))

        target = (7, 5, 4, False)
        valid = double_proof(leaf_proof(target))
        for flag in ("complete", "exhaustive"):
            with self.subTest(flag=flag):
                self.assertIsNone(
                    technique_classification.classify_nested_forcing({
                        "kind": "nested-double",
                        "proof_dag": valid.to_dict(),
                        flag: True,
                    })
                )

        mismatch = double_proof(leaf_proof((7, 5, 3, False)))
        self.assertIsNone(
            technique_classification.classify_nested_forcing({
                "kind": "nested-double",
                "proof_dag": mismatch.to_dict(),
            })
        )

        complete_tree = double_proof(
            leaf_proof(target, reason="complete-tree-search")
        )
        self.assertIsNone(
            technique_classification.classify_nested_forcing({
                "kind": "nested-double",
                "proof_dag": complete_tree.to_dict(),
            })
        )

        disconnected = double_proof(leaf_proof(target))
        disconnected.nodes[4] = node(
            4,
            target,
            (1,),
            kind="common-conclusion",
            depth=2,
        )
        self.assertIsNone(
            technique_classification.classify_nested_forcing({
                "kind": "nested-double",
                "proof_dag": disconnected.to_dict(),
            })
        )


if __name__ == "__main__":
    unittest.main()
