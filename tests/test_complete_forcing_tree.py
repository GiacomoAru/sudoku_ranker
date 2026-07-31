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


if __name__ == "__main__":
    unittest.main()
