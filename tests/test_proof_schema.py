import copy
import unittest
from unittest import mock

import numpy as np

from sudoku_app.archive import repository as archive
from sudoku_app.core import logic_engine
from sudoku_app.core import proof_schema
from sudoku_app.core import solver
from sudoku_app.core import technique_catalog
from sudoku_app.core import techniques
from sudoku_app.core.data_structure import SudokuState


def literal(row, column, value, state="on"):
    return {
        "row": row,
        "column": column,
        "value": value,
        "state": state,
    }


class ProofMetricNormalizationTests(unittest.TestCase):
    def test_archive_migrates_p14_legacy_identity_without_recalibration(self):
        restored = archive._restore_move({
            "technique_id": "direct.hidden.2",
            "technique": "Direct Hidden Pair",
            "base_difficulty": 2.0,
            "placements": [[0, 0, 7]],
            "eliminations": [],
            "highlight": {},
        })

        self.assertEqual(restored["technique_id"], "direct.hidden_pair")
        self.assertEqual(restored["inference_engine"], "local")
        self.assertEqual(restored["base_difficulty"], 2.0)

    def test_displayed_chains_are_a_complete_fallback(self):
        first = literal(0, 0, 1)
        second = literal(0, 1, 1, "off")
        third = literal(1, 1, 1)

        metrics = proof_schema.normalize_proof_metrics({
            "assumptions": [first],
            "chains": [[first, second, third]],
        })

        self.assertEqual(metrics, {
            "metrics_version": proof_schema.PROOF_METRICS_VERSION,
            "proof_node_count": 3,
            "proof_edge_count": 2,
            "displayed_literal_count": 3,
            "assumption_count": 1,
            "chain_count": 1,
            "max_chain_length": 3,
            "total_chain_length": 3,
            "branch_count": 0,
            "leaf_count": 0,
            "nested_depth": 0,
            "nested_subproof_count": 0,
            "group_node_count": 0,
            "max_group_size": 0,
            "als_node_count": 0,
            "als_cell_count": 0,
            "rcc_count": 0,
            "fork_node_count": 0,
            "merge_node_count": 0,
            "max_parent_count": 0,
            "template_count": 0,
            "kraken_branch_count": 0,
        })

    def test_explicit_engine_metrics_are_authoritative(self):
        chain = [
            literal(0, 0, 1),
            literal(0, 1, 1, "off"),
            literal(0, 2, 1),
        ]
        metrics = proof_schema.normalize_proof_metrics({
            "assumptions": [chain[0]],
            "chains": [chain],
            "metrics": {
                "proof_node_count": 1,
                "chain_count": 0,
                "max_chain_length": 1,
                "branch_count": 7,
                "leaf_count": 4,
                "nested_subproof_count": 2,
            },
        })

        self.assertEqual(metrics["proof_node_count"], 1)
        self.assertEqual(metrics["chain_count"], 0)
        self.assertEqual(metrics["max_chain_length"], 1)
        self.assertEqual(metrics["total_chain_length"], 3)
        self.assertEqual(metrics["displayed_literal_count"], 3)
        self.assertEqual(metrics["branch_count"], 7)
        self.assertEqual(metrics["leaf_count"], 4)
        self.assertEqual(metrics["nested_subproof_count"], 2)

    def test_nesting_depth_is_converted_to_canonical_name(self):
        metrics = proof_schema.normalize_proof_metrics({
            "metrics": {"nesting_depth": 3},
        })

        self.assertEqual(metrics["nested_depth"], 3)
        self.assertNotIn("nesting_depth", metrics)

    def test_linear_chains_do_not_invent_tree_metrics(self):
        chain = [literal(0, column, 1) for column in range(5)]
        metrics = proof_schema.normalize_proof_metrics({
            "chains": [chain, list(reversed(chain))],
        })

        self.assertEqual(metrics["branch_count"], 0)
        self.assertEqual(metrics["leaf_count"], 0)
        self.assertEqual(metrics["nested_subproof_count"], 0)


class ProofPipelineTests(unittest.TestCase):
    def test_logic_engine_emits_versioned_proofs(self):
        proof = logic_engine._proof(
            "synthetic",
            ((0, 0, 1, True),),
            (((0, 0, 1, True), (0, 1, 1, False)),),
        )

        self.assertEqual(
            proof["schema_version"],
            proof_schema.PROOF_SCHEMA_VERSION,
        )
        self.assertEqual(
            proof["metrics"]["metrics_version"],
            proof_schema.PROOF_METRICS_VERSION,
        )

    def test_dag_metrics_replace_non_authoritative_serialized_metrics(self):
        state = SudokuState(np.zeros((9, 9), dtype=int))
        logic = proof_schema.normalize_proof({
            "kind": "dynamic-contradiction",
            "assumptions": [literal(0, 0, 1)],
            "chains": [[
                literal(0, 0, 1),
                literal(0, 1, 1, "off"),
            ]],
        }, eliminations=[(0, 0, 1)])
        expected = dict(logic["metrics"])
        logic["metrics"] = {
            field: 99
            for field in proof_schema.PROOF_METRIC_FIELDS
        }
        deduction = {
            "description": "Prova sintetica ramificata",
            "placements": [],
            "eliminations": [(0, 0, 1)],
            "primary": [(0, 0), (0, 1)],
            "logic": logic,
        }

        with mock.patch.object(
            techniques.logic_engine,
            "find_logic_deductions",
            return_value=[deduction],
        ):
            moves = techniques._logic_moves(
                state,
                "Dynamic Forcing Chain",
            )

        self.assertEqual(len(moves), 1)
        move = solver._prepare_move(moves[0])
        self.assertEqual(move["logic"]["metrics"], expected)
        self.assertEqual(move["difficulty_metrics"], expected)
        self.assertEqual(
            move["logic"]["schema_version"],
            proof_schema.PROOF_SCHEMA_VERSION,
        )

    def test_rating_does_not_depend_on_renderer_detail(self):
        definition = technique_catalog.resolve_technique(
            "Dynamic Contradiction Forcing Chain"
        )
        authoritative = proof_schema.normalize_proof({
            "kind": "dynamic-contradiction",
            "assumptions": [literal(0, 0, 1)],
            "chains": [[
                literal(0, 0, 1),
                literal(0, 1, 1, "off"),
                literal(0, 2, 1),
            ]],
        }, eliminations=[(0, 0, 1)])

        def move(chains, displayed_literal_count):
            logic = copy.deepcopy(authoritative)
            logic["chains"] = chains
            logic["metrics"]["displayed_literal_count"] = (
                displayed_literal_count
            )
            return {
                "technique_id": definition.id,
                "placements": [],
                "eliminations": [(0, 0, 1)],
                "logic": logic,
            }

        compact = move([[literal(0, 0, 1)]], 1)
        verbose = move([
            [literal(0, column, 1) for column in range(7)],
            [literal(row, 8, 2) for row in range(6)],
        ], 13)

        prepared_compact = solver._prepare_move(copy.deepcopy(compact))
        prepared_verbose = solver._prepare_move(copy.deepcopy(verbose))

        self.assertEqual(
            prepared_compact["difficulty_metrics"][
                "displayed_literal_count"
            ],
            prepared_verbose["difficulty_metrics"][
                "displayed_literal_count"
            ],
        )
        self.assertEqual(
            prepared_compact["difficulty_extra"],
            prepared_verbose["difficulty_extra"],
        )
        self.assertEqual(
            prepared_compact["technical_difficulty"],
            prepared_verbose["technical_difficulty"],
        )

    def test_branched_proof_has_deterministic_structural_counts(self):
        node = logic_engine._CompleteForcingTreeProofNode
        first_leaf = node(
            assumption=(1, 0, 1, True),
            propagations=((1, 1, 1, False),),
            contradiction=True,
        )
        second_leaf = node(
            assumption=(2, 0, 2, True),
            propagations=(
                (2, 1, 2, False),
                (2, 2, 2, True),
            ),
            contradiction=True,
        )
        root = node(
            assumption=(0, 0, 3, True),
            propagations=((0, 1, 3, False),),
            branch_cell=(1, 0),
            children=(first_leaf, second_leaf),
        )

        metrics = logic_engine.CompleteForcingTreeSearch._proof_metrics(root)

        self.assertEqual(metrics, {
            "metrics_version": proof_schema.PROOF_METRICS_VERSION,
            "proof_node_count": 8,
            "proof_edge_count": 7,
            "displayed_literal_count": 5,
            "assumption_count": 3,
            "chain_count": 2,
            "max_chain_length": 5,
            "total_chain_length": 9,
            "branch_count": 2,
            "leaf_count": 2,
            "nested_depth": 0,
            "nested_subproof_count": 0,
            "group_node_count": 0,
            "max_group_size": 0,
            "als_node_count": 0,
            "als_cell_count": 0,
            "rcc_count": 0,
            "fork_node_count": 0,
            "merge_node_count": 0,
            "max_parent_count": 0,
            "template_count": 0,
            "kraken_branch_count": 0,
        })

    def test_proof_metrics_survive_compact_archive_round_trip(self):
        solved = (
            "534678912672195348198342567859761423426853791"
            "713924856961537284287419635345286179"
        )
        original = "0" + solved[1:]
        definition = technique_catalog.resolve_technique(
            "Dynamic Contradiction Forcing Chain"
        )
        proof = proof_schema.normalize_proof({
            "kind": "dynamic-contradiction",
            "assumptions": [literal(0, 0, 5)],
            "chains": [[literal(0, 0, 5)]],
        }, placements=[(0, 0, 5)])
        metrics = proof["metrics"]
        move = {
            "technique_id": definition.id,
            "technique": definition.canonical_name,
            "family": technique_catalog.TECHNIQUE_FAMILY[
                definition.canonical_name
            ],
            "strategy": technique_catalog.TECHNIQUE_STRATEGY[
                definition.canonical_name
            ],
            "parent_id": definition.parent_id,
            "se_equivalent_parent_id": (
                definition.se_equivalent_parent_id
            ),
            "rating_kind": definition.rating_kind,
            "detector_id": definition.detector_id,
            "engine_type": definition.engine_type,
            "inference_engine": definition.inference_engine,
            "fallback_tier": definition.fallback_tier,
            "base_difficulty": definition.base_difficulty,
            "difficulty_extra": 0.4,
            "difficulty_metrics": metrics,
            "technical_difficulty": definition.base_difficulty + 0.4,
            "description": "Prova persistita",
            "placements": [(0, 0, 5)],
            "eliminations": [],
            "highlight": {
                "primary": [(0, 0)],
                "secondary": [(0, 0)],
            },
            "logic": proof,
            "proof_count": 1,
            "conclusion_count": 1,
            "step": 1,
            "grid_after": np.array(
                [int(value) for value in solved],
                dtype=int,
            ).reshape(9, 9),
            "available_move_count": 1,
            "frontier_move_count": 1,
            "effective_move_count": 1.0,
            "available_by_technique": {
                definition.canonical_name: 1,
            },
            "frontier_by_technique": {
                definition.canonical_name: 1,
            },
            "nested_fallback_used": False,
            "move_inventory_censored": False,
            "effective_move_count_is_lower_bound": False,
            "move_discovery_difficulty_is_upper_bound": False,
        }
        analysis = {
            "name": "round-trip-proof",
            "original": original,
            "solved_grid": solved,
            "unique_solution": True,
            "chain": [move],
            "status": "solved",
            "analysis_mode": "profile",
            "profile_difficulty_window": 1.5,
        }

        compact = archive._compact_analysis_for_storage(analysis)
        restored = archive._restore_analysis(compact)
        restored_move = restored["chain"][0]

        self.assertEqual(
            restored["uniqueness_status"],
            "verified_unique",
        )
        self.assertEqual(restored_move["technique_id"], definition.id)
        self.assertEqual(restored_move["detector_id"], definition.detector_id)
        self.assertEqual(restored_move["difficulty_metrics"], metrics)
        self.assertEqual(restored_move["logic"]["metrics"], metrics)
        self.assertEqual(
            restored_move["logic"]["proof_dag"],
            proof["proof_dag"],
        )
        self.assertEqual(
            restored_move["logic"]["chain_links"],
            proof["chain_links"],
        )
        self.assertEqual(restored_move["proof_count"], 1)
        self.assertEqual(restored_move["conclusion_count"], 1)
        self.assertFalse(restored_move["move_inventory_censored"])


if __name__ == "__main__":
    unittest.main()
