import unittest
from unittest import mock

import numpy as np

from sudoku_app.archive import repository
from sudoku_app.core import logic_engine
from sudoku_app.core import solver
from sudoku_app.core import technique_registry
from sudoku_app.core import techniques
from sudoku_app.core.data_structure import SudokuState


class CompleteForcingTreeTests(unittest.TestCase):
    @staticmethod
    def _near_solved_state():
        solved = (
            "534678912672195348198342567859761423426853791"
            "713924856961537284287419635345286179"
        )
        grid = np.array([int(value) for value in solved]).reshape(9, 9)
        grid[0, 0] = 0
        state = SudokuState(grid)
        state.candidates = [
            [set() for _ in range(9)]
            for _ in range(9)
        ]
        state.candidates[0][0] = {5, 6}
        return state

    def setUp(self):
        logic_engine.clear_logic_cache()

    def test_complete_tree_uses_its_own_public_identity(self):
        self.assertFalse(hasattr(logic_engine, "_CompleteNestedSearch"))
        deductions = logic_engine.find_logic_deductions(
            self._near_solved_state(),
            "Complete Forcing Tree",
            max_results=8,
        )

        self.assertEqual(len(deductions), 1)
        self.assertEqual(
            deductions[0]["logic"]["kind"],
            "complete-forcing-tree-contradiction",
        )
        self.assertEqual(deductions[0]["logic"]["metrics"]["nested_depth"], 0)

    def test_complete_adapter_emits_one_tier_two_conclusion(self):
        moves = techniques.complete_forcing_tree(
            self._near_solved_state()
        )

        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]["technique_id"], "forcing.complete_tree")
        self.assertEqual(moves[0]["technique"], "Complete Forcing Tree")
        self.assertEqual(moves[0]["engine_type"], "complete_tree")
        self.assertEqual(moves[0]["fallback_tier"], 2)
        self.assertEqual(moves[0]["conclusion_count"], 1)
        self.assertIn("albero completo di casi", moves[0]["description"])
        self.assertEqual(moves[0]["highlight"]["secondary"], [(0, 0)])
        self.assertIn("proof_dag", moves[0]["logic"])
        compact = moves[0]["logic"]["presentation_proof"]
        self.assertFalse(compact["authoritative"])
        self.assertEqual(
            compact["proof_dag_digest"],
            moves[0]["logic"]["dag_digest"],
        )
        self.assertIn("proof_hits", moves[0]["logic"]["search_cache"])

    def test_human_branch_prefers_a_bivalue_cell_on_equal_arity(self):
        search = logic_engine.CompleteForcingTreeSearch(
            self._near_solved_state().grid,
            {(0, 0): {5, 6}},
        )

        branch = search._choose_human_branch(search.initial_masks)

        self.assertEqual(branch.kind, "cell")
        self.assertEqual(branch.cell, (0, 0))
        self.assertEqual(
            branch.alternatives,
            ((0, 0, 5, True), (0, 0, 6, True)),
        )

    def test_human_branch_uses_a_bilocal_digit_before_trivalue_cells(self):
        solved = (
            "534678912672195348198342567859761423426853791"
            "713924856961537284287419635345286179"
        )
        masks = tuple(1 << int(value) for value in solved)
        masks = list(masks)
        masks[0] = (1 << 3) | (1 << 5) | (1 << 9)
        masks[1] = (1 << 3) | (1 << 5) | (1 << 9)

        branch = logic_engine.CompleteForcingTreeSearch._choose_human_branch(
            tuple(masks)
        )

        self.assertEqual(branch.kind, "house-digit")
        self.assertEqual(len(branch.alternatives), 2)
        self.assertEqual(branch.house_id, 0)

    def test_fail_first_order_is_deterministic_and_keeps_all_cases(self):
        state = self._near_solved_state()
        search = logic_engine.CompleteForcingTreeSearch(
            state.grid,
            {(0, 0): {5, 6}},
        )
        branch = search._choose_human_branch(search.initial_masks)

        ordered = search._ordered_branch_alternatives(
            search.initial_masks,
            branch,
        )

        self.assertEqual(ordered[0], (0, 0, 6, True))
        self.assertEqual(set(ordered), set(branch.alternatives))

    def test_formal_branch_records_the_human_question_and_all_cases(self):
        alternatives = ((0, 0, 3, True), (0, 1, 3, True))
        children = tuple(
            logic_engine._CompleteForcingTreeProofNode(
                assumption=literal,
                contradiction=True,
                contradiction_reason="fixture",
            )
            for literal in alternatives
        )
        proof = logic_engine._CompleteForcingTreeProofNode(
            branch_kind="house-digit",
            branch_house_id=0,
            branch_digit=3,
            branch_alternatives=alternatives,
            children=children,
        )

        dag = logic_engine.CompleteForcingTreeSearch._formal_proof_dag(
            proof,
            (1, 1, 4),
        ).to_dict()
        branch = next(
            node for node in dag["nodes"].values()
            if node["kind"] == "branch"
        )

        self.assertEqual(branch["payload"]["branch_kind"], "house-digit")
        self.assertEqual(branch["payload"]["branch_digit"], 3)
        self.assertEqual(len(branch["payload"]["alternatives"]), 2)

    def test_nested_does_not_execute_the_complete_search(self):
        engine = logic_engine.LogicEngine(self._near_solved_state())

        self.assertEqual(engine.find("Nested Forcing Chain", max_results=8), [])
        self.assertIsNone(engine._complete_forcing_tree_search)

    def test_old_complete_result_is_read_with_the_new_identity(self):
        restored = repository._restore_move({
            "technique": "Nested Contradiction Forcing Chain",
            "placements": [],
            "eliminations": [[0, 0, 6]],
            "highlight": {"primary": [], "secondary": []},
            "logic": {"kind": "nested-complete-contradiction"},
        })

        self.assertEqual(restored["technique_id"], "forcing.complete_tree")
        self.assertEqual(restored["technique"], "Complete Forcing Tree")
        self.assertEqual(restored["fallback_tier"], 2)
        self.assertEqual(
            restored["logic"]["kind"],
            "complete-forcing-tree-contradiction",
        )

    def test_solver_records_the_real_complete_tree_as_third_tier(self):
        runner = technique_registry.RUNNER_BY_DETECTOR_ID[
            "complete_forcing_tree"
        ]
        with (
            mock.patch.object(technique_registry, "ORDINARY_RUNNERS", ()),
            mock.patch.object(technique_registry, "NESTED_RUNNERS", ()),
            mock.patch.object(
                technique_registry,
                "COMPLETE_TREE_RUNNERS",
                (runner,),
            ),
        ):
            moves, metadata = solver.collect_moves_for_analysis(
                self._near_solved_state(),
                mode="deep",
            )

        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]["technique_id"], "forcing.complete_tree")
        self.assertEqual(metadata["fallback_tier_used"], 2)
        self.assertEqual(metadata["fallback_stage"], "complete_tree")

    def test_external_cancellation_is_truncated_and_discards_results(self):
        runner = technique_registry.RUNNER_BY_DETECTOR_ID[
            "complete_forcing_tree"
        ]
        state = self._near_solved_state()
        with (
            mock.patch.object(technique_registry, "ORDINARY_RUNNERS", ()),
            mock.patch.object(technique_registry, "NESTED_RUNNERS", ()),
            mock.patch.object(
                technique_registry,
                "COMPLETE_TREE_RUNNERS",
                (runner,),
            ),
        ):
            moves, metadata = solver.collect_moves_for_analysis(
                state,
                mode="deep",
                cancellation_check=lambda: True,
            )

        self.assertEqual(moves, [])
        self.assertFalse(metadata["certified"])
        search = metadata["detector_searches"][0]
        self.assertEqual(search["completion"], "truncated")
        self.assertIn("external_cancellation", search["truncated_reasons"])

    def test_solver_exposes_external_cancellation_as_its_own_status(self):
        runner = technique_registry.RUNNER_BY_DETECTOR_ID[
            "complete_forcing_tree"
        ]
        with (
            mock.patch.object(technique_registry, "ORDINARY_RUNNERS", ()),
            mock.patch.object(technique_registry, "NESTED_RUNNERS", ()),
            mock.patch.object(
                technique_registry,
                "COMPLETE_TREE_RUNNERS",
                (runner,),
            ),
        ):
            _, chain, status = solver.solve_and_log(
                self._near_solved_state().grid,
                analysis_mode="deep",
                cancellation_check=lambda: True,
            )

        self.assertEqual(chain, [])
        self.assertEqual(status, "cancelled")

    def test_cancelled_search_does_not_poison_a_later_complete_search(self):
        runner = technique_registry.RUNNER_BY_DETECTOR_ID[
            "complete_forcing_tree"
        ]
        state = self._near_solved_state()
        cancellation = {"requested": True}

        def cancellation_check():
            return cancellation["requested"]

        patches = (
            mock.patch.object(technique_registry, "ORDINARY_RUNNERS", ()),
            mock.patch.object(technique_registry, "NESTED_RUNNERS", ()),
            mock.patch.object(
                technique_registry,
                "COMPLETE_TREE_RUNNERS",
                (runner,),
            ),
        )
        with patches[0], patches[1], patches[2]:
            cancelled, _ = solver.collect_moves_for_analysis(
                state,
                mode="deep",
                cancellation_check=cancellation_check,
            )
            cancellation["requested"] = False
            completed, metadata = solver.collect_moves_for_analysis(
                state,
                mode="deep",
                cancellation_check=cancellation_check,
            )

        self.assertEqual(cancelled, [])
        self.assertEqual(len(completed), 1)
        self.assertTrue(metadata["certified"])


if __name__ == "__main__":
    unittest.main()
