import copy
import unittest
from unittest import mock

import numpy as np

from sudoku_app.core import logic_engine
from sudoku_app.core import move_presentation
from sudoku_app.core import proof
from sudoku_app.core import proof_schema
from sudoku_app.core import solver
from sudoku_app.core import technique_catalog
from sudoku_app.core import techniques
from sudoku_app.core.data_structure import SudokuState


class ProofDAGTests(unittest.TestCase):
    def test_chain_conversion_is_acyclic_and_round_trips_all_parents(self):
        dag = proof.ProofDAG.from_chains(
            assumptions=[(0, 0, 1, True)],
            chains=[
                [(0, 0, 1, True), (0, 1, 1, False)],
                [(0, 0, 1, True), (1, 0, 1, False)],
            ],
            reasons=["peer"],
            proof_kind="dynamic-cell-reduction",
            eliminations=[(1, 1, 1)],
        )

        serialized = dag.to_dict()
        restored = proof.ProofDAG.from_dict(serialized)

        self.assertEqual(restored.signature(), dag.signature())
        self.assertEqual(restored.derived_chains(), dag.derived_chains())
        self.assertTrue(any(
            len(node["parents"]) == 2
            for node in serialized["nodes"].values()
        ))
        self.assertEqual(restored.validate(), restored)

    def test_cycle_is_rejected(self):
        first = proof.ProofNode(
            0, "static-implication", (0, 0, 1, True), (1,), "x", 1, {}
        )
        second = proof.ProofNode(
            1, "static-implication", (0, 1, 1, False), (0,), "x", 1, {}
        )
        with self.assertRaisesRegex(ValueError, "ciclo"):
            proof.ProofDAG(
                nodes={0: first, 1: second},
                roots=(),
                conclusions=(1,),
            )

    def test_serialized_chains_and_metrics_are_derived_from_dag(self):
        normalized = proof_schema.normalize_proof({
            "kind": "forcing-chain",
            "assumptions": [],
            "chains": [[
                (0, 0, 1, True),
                (0, 1, 1, False),
                (1, 1, 1, True),
            ]],
        }, eliminations=[(2, 2, 1)])
        tampered = copy.deepcopy(normalized)
        tampered["chains"] = []
        tampered["metrics"] = {
            field: 512 for field in proof_schema.PROOF_METRIC_FIELDS
        }

        restored = proof_schema.normalize_proof(tampered)

        self.assertEqual(restored["chains"], normalized["chains"])
        self.assertEqual(restored["metrics"], normalized["metrics"])

    def test_presentation_cap_does_not_truncate_the_authoritative_dag(self):
        chains = [
            [
                (index // 9, index % 9, 1, True),
                (index // 9, index % 9, 2, False),
            ]
            for index in range(32)
        ]
        dag = proof.ProofDAG.from_chains(chains=chains)

        self.assertEqual(sum(
            bool(node.payload.get("chain_terminal"))
            for node in dag.nodes.values()
        ), 32)
        self.assertEqual(len(dag.derived_chains()), 16)

    def test_nested_proof_is_serialized_under_its_owner(self):
        nested = proof.ProofDAG.from_chains(
            chains=[[(0, 0, 1, True)]],
        )
        owner = proof.ProofNode(
            0,
            "nested-subproof",
            (1, 1, 2, False),
            (),
            "nested-inference",
            0,
            {"chain_terminal": True},
        )
        dag = proof.ProofDAG(
            nodes={0: owner},
            roots=(0,),
            conclusions=(0,),
            nested_proofs={0: nested},
        )

        restored = proof.ProofDAG.from_dict(dag.to_dict())
        self.assertIn(0, restored.nested_proofs)
        self.assertEqual(restored.metrics()["nested_depth"], 1)
        self.assertEqual(restored.metrics()["nested_subproof_count"], 1)

    def test_deduplication_selects_the_smaller_dag(self):
        state = SudokuState(np.zeros((9, 9), dtype=int))
        state.candidates = [[set() for _ in range(9)] for _ in range(9)]
        state.candidates[0][0] = {1}

        def deduction(chain):
            return {
                "description": "Prova controllata",
                "placements": [],
                "eliminations": [(0, 0, 1)],
                "primary": [(item[0], item[1]) for item in chain],
                "logic": proof_schema.normalize_proof({
                    "kind": "dynamic-contradiction",
                    "assumptions": [chain[0]],
                    "chains": [chain],
                }, eliminations=[(0, 0, 1)]),
            }

        small = deduction([(0, 0, 1, True)])
        large = deduction([
            (0, 0, 1, True),
            (0, 1, 1, False),
            (0, 2, 1, True),
        ])
        with mock.patch.object(
            techniques.logic_engine,
            "find_logic_deductions",
            return_value=[large, small],
        ):
            move = techniques._logic_moves(
                state,
                "Dynamic Forcing Chain",
            )[0]

        self.assertEqual(
            move["logic"]["metrics"]["proof_node_count"],
            small["logic"]["metrics"]["proof_node_count"],
        )
        self.assertEqual(move["proof_count"], 2)


class MovePresentationTests(unittest.TestCase):
    def test_common_formatters_use_sudoku_coordinates(self):
        self.assertEqual(move_presentation.format_cell(2, 6), "R3C7")
        self.assertEqual(
            move_presentation.format_cells([(2, 6), (0, 0), (2, 6)]),
            "R1C1 e R3C7",
        )

    def test_build_move_normalizes_roles_and_explanation(self):
        move = techniques._build_move(
            technique="Naked Single",
            family="ignored",
            difficulty=2.3,
            description="Un solo candidato rimane",
            placements=[(2, 6, 4)],
            eliminations=[],
            primary=[(2, 6), (0, 0), (2, 6)],
            secondary=[(8, 8)],
        )

        self.assertEqual(move["highlight"]["primary"], [(0, 0), (2, 6)])
        self.assertEqual(move["highlight"]["secondary"], [(2, 6)])
        self.assertIn("Naked Single", move["description"])
        self.assertIn("R3C7", move["description"])
        self.assertIn("Di conseguenza", move["description"])

    def test_description_and_highlight_do_not_affect_solver_order(self):
        definition = technique_catalog.technique_definition("single.naked")
        base = {
            "technique_id": definition.id,
            "technique": definition.canonical_name,
            "placements": [(0, 0, 1)],
            "eliminations": [],
        }
        first = dict(base, description="A", highlight={"primary": [], "secondary": []})
        second = dict(
            base,
            description="Testo totalmente differente",
            highlight={"primary": [(8, 8)], "secondary": [(7, 7)]},
        )

        self.assertEqual(
            solver._move_sort_key(first),
            solver._move_sort_key(second),
        )
        self.assertEqual(
            solver._technical_difficulty_score(first),
            solver._technical_difficulty_score(second),
        )


class ComputationLimitTests(unittest.TestCase):
    def test_solver_limits_are_clean_powers_or_multiples_of_two(self):
        self.assertEqual(logic_engine.MAX_STATIC_CYCLE_EDGES, 16)
        self.assertEqual(proof.MAX_PRESENTATION_CHAINS, 16)
        self.assertEqual(solver.MAX_SOLVER_STEPS, 8_192)
        self.assertEqual(solver.MAX_MOVES_PER_TECHNIQUE, 16)
        self.assertEqual(solver.MAX_LOGIC_ENGINE_MOVES_PER_TECHNIQUE, 8)

    def test_complete_tree_has_no_internal_state_or_dag_budget(self):
        self.assertFalse(
            hasattr(logic_engine, "MAX_COMPLETE_TREE_SEARCH_STATES")
        )
        self.assertFalse(hasattr(proof, "MAX_PROOF_DAG_NODES"))

    def test_solver_step_limit_is_hard_and_explicit(self):
        self.assertEqual(
            solver._normalise_solver_step_limit(8_192),
            8_192,
        )
        with self.assertRaises(ValueError):
            solver._normalise_solver_step_limit(8_193)


if __name__ == "__main__":
    unittest.main()
