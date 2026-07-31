import json
import unittest

import numpy as np

from sudoku_app.core import exclusion
from sudoku_app.core import sue_de_coq
from sudoku_app.core import techniques
from sudoku_app.core.data_structure import SudokuState, backtracking_solve
from tests.solver_corpus import load_puzzle_cases


def synthetic_state(entries):
    state = SudokuState(np.zeros((9, 9), dtype=int))
    state.candidates = [[set() for _ in range(9)] for _ in range(9)]
    for (row, column), values in entries.items():
        state.candidates[row][column] = set(values)
    return state


class GeneralizedSubsetTests(unittest.TestCase):
    def test_generalized_naked_quintuple(self):
        state = synthetic_state({
            (0, 0): {1, 2},
            (0, 1): {2, 3},
            (0, 2): {3, 4},
            (0, 3): {4, 5},
            (0, 4): {1, 5},
            (0, 5): {1, 7},
        })
        moves = techniques.naked_subset(state, 5)
        self.assertTrue(any(
            move["technique_id"] == "subset.naked.5"
            and move["eliminations"] == [(0, 5, 1)]
            for move in moves
        ))

    def test_generalized_naked_sextuple(self):
        state = synthetic_state({
            (0, 0): {1, 2},
            (0, 1): {2, 3},
            (0, 2): {3, 4},
            (0, 3): {4, 5},
            (0, 4): {5, 6},
            (0, 5): {1, 6},
            (0, 6): {1, 8},
        })
        moves = techniques.naked_subset(state, 6)
        self.assertTrue(any(
            move["technique_id"] == "subset.naked.6"
            and move["eliminations"] == [(0, 6, 1)]
            for move in moves
        ))

    def test_quintuple_rejects_six_digit_union(self):
        state = synthetic_state({
            (0, 0): {1, 2},
            (0, 1): {2, 3},
            (0, 2): {3, 4},
            (0, 3): {4, 5},
            (0, 4): {5, 6},
            (0, 5): {1, 7},
        })
        self.assertEqual(techniques.naked_subset(state, 5), [])


class AlignedExclusionTests(unittest.TestCase):
    def test_pair_enumerates_all_allowed_assignments(self):
        state = synthetic_state({
            (0, 0): {1, 2, 3},
            (1, 1): {1, 2, 3},
            (0, 1): {1, 2},
            (1, 0): {1, 3},
        })
        patterns = exclusion.enumerate_aligned_exclusions(state, 2)
        pattern = next(
            item for item in patterns
            if item.base_cells == ((0, 0), (1, 1))
        )
        self.assertEqual(
            set(pattern.eliminations),
            {(0, 0, 1), (1, 1, 1)},
        )
        self.assertEqual(pattern.allowed_assignment_count, 2)

    def test_triplet_enumerates_every_admissible_permutation(self):
        state = synthetic_state({
            (0, 0): {1, 2, 3, 4},
            (1, 1): {1, 2, 3, 4},
            (2, 2): {1, 2, 3, 4},
            (0, 1): {1, 2, 3},
            (0, 2): {1, 2, 4},
            (1, 0): {1, 3, 4},
        })
        moves = techniques.aligned_triplet_exclusion(state)
        move = next(
            item for item in moves
            if set(item["base_cells"])
            == {(0, 0), (1, 1), (2, 2)}
        )
        self.assertEqual(
            set(move["eliminations"]),
            {(0, 0, 1), (1, 1, 1), (2, 2, 1)},
        )
        self.assertEqual(move["allowed_assignment_count"], 6)
        json.dumps(move)

    def test_triplet_near_miss_preserves_supported_candidate(self):
        state = synthetic_state({
            (0, 0): {1, 2, 3, 4},
            (1, 1): {1, 2, 3, 4},
            (2, 2): {1, 2, 3, 4},
            (0, 1): {1, 2, 3},
            (0, 2): {1, 2, 4},
            (1, 0): {2, 3, 4},
        })
        patterns = exclusion.enumerate_aligned_exclusions(state, 3)
        intended = [
            pattern for pattern in patterns
            if pattern.base_cells == ((0, 0), (1, 1), (2, 2))
        ]
        self.assertFalse(any(
            (0, 0, 1) in pattern.eliminations
            for pattern in intended
        ))

    def test_fully_rejected_local_state_is_not_returned_as_a_move(self):
        state = synthetic_state({
            (0, 0): {1, 2},
            (1, 1): {1, 2},
            (0, 1): {1, 2},
            (1, 0): {1, 2},
        })
        self.assertEqual(
            exclusion.enumerate_aligned_exclusions(state, 2),
            (),
        )


class SueDeCoqTests(unittest.TestCase):
    def test_classic_pattern_has_disjoint_exact_cardinality_subsets(self):
        state = synthetic_state({
            (0, 0): {1, 2, 3},
            (0, 1): {2, 3, 4},
            (0, 3): {1, 2},
            (1, 0): {3, 4},
            (0, 4): {1, 5},
            (1, 1): {3, 5},
        })
        moves = techniques.sue_de_coq(state)
        move = next(
            item for item in moves
            if item["technique_id"] == "intersection.sue_de_coq"
            and set(item["eliminations"]) == {(0, 4, 1), (1, 1, 3)}
        )
        pattern = move["sue_de_coq"]
        self.assertEqual(pattern["line_extra_digits"], [])
        self.assertEqual(pattern["box_extra_digits"], [])
        self.assertTrue(
            set(pattern["line_core_digits"]).isdisjoint(
                pattern["box_core_digits"]
            )
        )

    def test_extended_pattern_accounts_for_each_extra_digit(self):
        state = synthetic_state({
            (0, 0): {1, 2, 3},
            (0, 1): {2, 3, 4},
            (0, 3): {1, 5},
            (0, 4): {2, 5},
            (1, 0): {3, 4},
            (0, 5): {1, 6},
            (1, 1): {3, 6},
        })
        moves = techniques.sue_de_coq(state)
        move = next(
            item for item in moves
            if item["technique_id"]
            == "intersection.sue_de_coq.extended"
            and set(item["eliminations"]) == {(0, 5, 1), (1, 1, 3)}
        )
        pattern = move["sue_de_coq"]
        self.assertEqual(pattern["line_extra_digits"], [5])
        self.assertEqual(len(pattern["line_cells"]), 2)
        json.dumps(move)

    def test_overlapping_core_digits_are_rejected(self):
        state = synthetic_state({
            (0, 0): {1, 2, 3},
            (0, 1): {2, 3, 4},
            (0, 3): {1, 2},
            (1, 0): {2, 3, 4},
            (0, 4): {1, 5},
            (1, 1): {3, 5},
        })
        patterns = sue_de_coq.enumerate_sue_de_coq(state)
        self.assertFalse(any(
            pattern.intersection_cells == ((0, 0), (0, 1))
            and pattern.line_cells == ((0, 3),)
            and pattern.box_cells == ((1, 0),)
            for pattern in patterns
        ))


class P09CorpusSoundnessTests(unittest.TestCase):
    def test_new_detectors_never_remove_the_unique_solution_value(self):
        detectors = (
            lambda state: techniques.naked_subset(state, 5),
            lambda state: techniques.naked_subset(state, 6),
            techniques.sue_de_coq,
            techniques.aligned_pair_exclusion,
            techniques.aligned_triplet_exclusion,
        )
        checked = 0
        for case in load_puzzle_cases():
            state = SudokuState(case["puzzle"])
            solution = backtracking_solve(state.grid)
            for detector in detectors:
                for move in detector(state):
                    for row, column, value in move["eliminations"]:
                        checked += 1
                        self.assertNotEqual(
                            int(solution[row, column]),
                            value,
                            (case["id"], move["technique_id"]),
                        )
        self.assertGreaterEqual(checked, 128)


if __name__ == "__main__":
    unittest.main()
