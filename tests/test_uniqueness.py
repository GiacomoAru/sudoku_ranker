import json
import unittest

import numpy as np

from sudoku_app.core import solver
from sudoku_app.core import technique_registry
from sudoku_app.core import techniques
from sudoku_app.core import uniqueness
from sudoku_app.core.data_structure import (
    UNIQUENESS_NOT_CHECKED,
    UNIQUENESS_VERIFIED,
    SudokuState,
)


LOOP_CELLS = (
    (0, 0), (0, 3),
    (1, 3), (1, 6),
    (2, 6), (2, 0),
)


def synthetic_state(entries, *, verified=True):
    state = SudokuState(
        np.zeros((9, 9), dtype=int),
        uniqueness_status=(
            UNIQUENESS_VERIFIED
            if verified
            else UNIQUENESS_NOT_CHECKED
        ),
    )
    state.candidates = [[set() for _ in range(9)] for _ in range(9)]
    for (row, column), values in entries.items():
        state.candidates[row][column] = set(values)
    return state


def loop_state(overrides=None, extras=None, *, verified=True):
    entries = {cell: {1, 2} for cell in LOOP_CELLS}
    entries.update(extras or {})
    entries.update(overrides or {})
    return synthetic_state(entries, verified=verified)


class UniquenessContextTests(unittest.TestCase):
    def test_state_copy_preserves_initial_givens_and_status(self):
        initial = np.zeros((9, 9), dtype=int)
        initial[0, 0] = 7
        state = SudokuState(
            initial,
            uniqueness_status=UNIQUENESS_VERIFIED,
        )
        state.place(0, 1, 8)

        copied = state.copy()

        self.assertTrue(copied.given_mask[0, 0])
        self.assertFalse(copied.given_mask[0, 1])
        self.assertEqual(copied.initial_grid[0, 1], 0)
        self.assertEqual(copied.uniqueness_status, UNIQUENESS_VERIFIED)

    def test_direct_solver_does_not_claim_uniqueness(self):
        solved = np.array([
            [5, 3, 4, 6, 7, 8, 9, 1, 2],
            [6, 7, 2, 1, 9, 5, 3, 4, 8],
            [1, 9, 8, 3, 4, 2, 5, 6, 7],
            [8, 5, 9, 7, 6, 1, 4, 2, 3],
            [4, 2, 6, 8, 5, 3, 7, 9, 1],
            [7, 1, 3, 9, 2, 4, 8, 5, 6],
            [9, 6, 1, 5, 3, 7, 2, 8, 4],
            [2, 8, 7, 4, 1, 9, 6, 3, 5],
            [3, 4, 5, 2, 8, 6, 1, 7, 9],
        ])
        state, _, status = solver.solve_and_log(solved)
        self.assertEqual(status, "solved")
        self.assertEqual(state.uniqueness_status, UNIQUENESS_NOT_CHECKED)

        analysis = solver.analyse_puzzle(solved)
        self.assertEqual(
            analysis["uniqueness_status"],
            UNIQUENESS_VERIFIED,
        )

    def test_registry_blocks_uniqueness_runner_when_not_checked(self):
        entries = {
            (0, 0): {1, 2, 3},
            (0, 3): {1, 2},
            (1, 0): {1, 2},
            (1, 3): {1, 2},
        }
        runner = technique_registry.RUNNER_BY_DETECTOR_ID["ur_type_1"]
        self.assertEqual(
            solver._call_registered_runner(
                runner,
                synthetic_state(entries, verified=False),
            ),
            [],
        )
        self.assertTrue(solver._call_registered_runner(
            runner,
            synthetic_state(entries, verified=True),
        ))

    def test_every_uniqueness_detector_is_silent_without_verification(self):
        entries = {
            (0, 0): {1, 2, 3},
            (0, 3): {1, 2, 4},
            (1, 0): {1, 2},
            (1, 3): {1, 2},
        }
        state = synthetic_state(entries, verified=False)
        detectors = (
            techniques.unique_rectangle_type1,
            techniques.unique_rectangle_type2,
            techniques.unique_rectangle_type3,
            techniques.unique_rectangle_type4,
            techniques.unique_rectangle_type5,
            techniques.unique_rectangle_type6,
            techniques.hidden_rectangle,
            techniques.avoidable_rectangle_type1,
            techniques.avoidable_rectangle_type2,
            techniques.unique_loops,
            techniques.bug_plus_one,
            techniques.bug_types_2_to_4,
        )
        for detector in detectors:
            with self.subTest(detector=detector.__name__):
                self.assertEqual(detector(state), [])


class RectangleCompletionTests(unittest.TestCase):
    def test_existing_unique_rectangle_types_keep_strict_near_misses(self):
        cases = (
            (
                techniques.unique_rectangle_type1,
                {
                    (0, 0): {1, 2, 3},
                    (0, 3): {1, 2},
                    (1, 0): {1, 2},
                    (1, 3): {1, 2},
                },
                {
                    (0, 0): {1, 2},
                    (0, 3): {1, 2},
                    (1, 0): {1, 2},
                    (1, 3): {1, 2},
                },
                "unique.ur.1",
            ),
            (
                techniques.unique_rectangle_type2,
                {
                    (0, 0): {1, 2, 3},
                    (0, 3): {1, 2, 3},
                    (1, 0): {1, 2},
                    (1, 3): {1, 2},
                    (0, 4): {3},
                },
                {
                    (0, 0): {1, 2, 3},
                    (0, 3): {1, 2, 4},
                    (1, 0): {1, 2},
                    (1, 3): {1, 2},
                    (0, 4): {3, 4},
                },
                "unique.ur.2",
            ),
            (
                techniques.unique_rectangle_type3,
                {
                    (0, 0): {1, 2, 3},
                    (0, 3): {1, 2, 4},
                    (1, 0): {1, 2},
                    (1, 3): {1, 2},
                    (0, 4): {3, 4},
                    (0, 5): {1, 3},
                },
                {
                    (0, 0): {1, 2, 3},
                    (0, 3): {1, 2, 4},
                    (1, 0): {1, 2},
                    (1, 3): {1, 2},
                    (0, 4): {3, 4, 5},
                    (0, 5): {1, 3},
                },
                "unique.ur.3",
            ),
            (
                techniques.unique_rectangle_type4,
                {
                    (0, 0): {1, 2, 3},
                    (0, 3): {1, 2, 4},
                    (1, 0): {1, 2},
                    (1, 3): {1, 2},
                    (0, 4): {2, 5},
                },
                {
                    (0, 0): {1, 2, 3},
                    (0, 3): {1, 2, 4},
                    (1, 0): {1, 2},
                    (1, 3): {1, 2},
                    (0, 4): {1, 2, 5},
                },
                "unique.ur.4",
            ),
            (
                techniques.unique_rectangle_type5,
                {
                    (0, 0): {1, 2, 3},
                    (0, 3): {1, 2},
                    (1, 0): {1, 2},
                    (1, 3): {1, 2, 3},
                    (0, 4): {3},
                },
                {
                    (0, 0): {1, 2, 3},
                    (0, 3): {1, 2},
                    (1, 0): {1, 2},
                    (1, 3): {1, 2, 4},
                    (0, 4): {3, 4},
                },
                "unique.ur.5",
            ),
        )

        for detector, positive, near_miss, technique_id in cases:
            with self.subTest(technique_id=technique_id):
                self.assertTrue(any(
                    move["technique_id"] == technique_id
                    for move in detector(synthetic_state(positive))
                ))
                self.assertFalse(any(
                    move["technique_id"] == technique_id
                    for move in detector(synthetic_state(near_miss))
                ))

    def test_unique_rectangle_type6_positive_and_near_miss(self):
        entries = {
            (0, 0): {1, 2, 3},
            (0, 3): {1, 2},
            (1, 0): {1, 2},
            (1, 3): {1, 2, 4},
        }
        moves = techniques.unique_rectangle_type6(
            synthetic_state(entries)
        )
        self.assertTrue(any(
            move["technique_id"] == "unique.ur.6"
            and (0, 0, 1) in move["eliminations"]
            and (1, 3, 1) in move["eliminations"]
            for move in moves
        ))

        near_miss = dict(entries)
        near_miss[(0, 5)] = {1, 2}
        self.assertEqual(
            techniques.unique_rectangle_type6(
                synthetic_state(near_miss)
            ),
            [],
        )

    def test_hidden_rectangle_positive_and_near_miss(self):
        entries = {
            (0, 0): {1, 2},
            (0, 3): {1, 2, 3},
            (1, 0): {1, 2, 4},
            (1, 3): {1, 2, 5},
        }
        moves = techniques.hidden_rectangle(synthetic_state(entries))
        self.assertTrue(any(
            move["technique_id"] == "unique.hidden_rectangle"
            and move["eliminations"]
            for move in moves
        ))

        near_miss = dict(entries)
        near_miss[(1, 5)] = {1, 2}
        near_miss[(2, 3)] = {1, 2}
        self.assertEqual(
            techniques.hidden_rectangle(synthetic_state(near_miss)),
            [],
        )

    def test_avoidable_rectangle_type1_uses_only_non_givens(self):
        state = synthetic_state({(1, 3): {1, 3}})
        state.place(0, 0, 1)
        state.place(1, 0, 2)
        state.place(0, 3, 2)
        state.candidates[1][3] = {1, 3}

        moves = techniques.avoidable_rectangle_type1(state)
        self.assertTrue(any(
            move["technique_id"] == "unique.avoidable.1"
            and move["eliminations"] == [(1, 3, 1)]
            for move in moves
        ))

        state.given_mask[0, 0] = True
        self.assertEqual(techniques.avoidable_rectangle_type1(state), [])

    def test_avoidable_rectangle_type2_positive_and_near_miss(self):
        state = synthetic_state({
            (0, 3): {2, 3},
            (1, 3): {1, 3},
            (2, 3): {3},
        })
        state.place(0, 0, 1)
        state.place(1, 0, 2)
        state.candidates[0][3] = {2, 3}
        state.candidates[1][3] = {1, 3}
        state.candidates[2][3] = {3}

        moves = techniques.avoidable_rectangle_type2(state)
        self.assertTrue(any(
            move["technique_id"] == "unique.avoidable.2"
            and move["eliminations"] == [(2, 3, 3)]
            for move in moves
        ))

        state.candidates[1][3] = {1, 4}
        self.assertEqual(techniques.avoidable_rectangle_type2(state), [])


class UniqueLoopTests(unittest.TestCase):
    def test_enumerator_canonicalizes_rotation_and_direction(self):
        state = loop_state({(0, 0): {1, 2, 3}})
        patterns = uniqueness.enumerate_unique_loops(state)
        self.assertEqual(len(patterns), 1)
        pattern = patterns[0]
        self.assertEqual(len(pattern.cells), 6)
        self.assertEqual(pattern.cells[0], min(LOOP_CELLS))
        self.assertEqual(len(set(pattern.cells)), len(pattern.cells))
        json.dumps(pattern.proof_payload(1))

    def test_type1_positive_near_miss_and_unverified(self):
        state = loop_state({(0, 0): {1, 2, 3}})
        moves = techniques.unique_loops(state)
        self.assertTrue(any(
            move["technique_id"] == "unique.loop.1"
            and set(move["eliminations"])
            == {(0, 0, 1), (0, 0, 2)}
            and move["logic"]["uniqueness_pattern"]["type"] == 1
            for move in moves
        ))
        self.assertEqual(
            techniques.unique_loops(loop_state({(2, 0): {1, 3}})),
            [],
        )
        self.assertEqual(
            techniques.unique_loops(
                loop_state({(0, 0): {1, 2, 3}}, verified=False)
            ),
            [],
        )

    def test_type2_positive_and_near_miss(self):
        state = loop_state(
            {
                (0, 0): {1, 2, 3},
                (0, 3): {1, 2, 3},
            },
            {(0, 4): {3}},
        )
        moves = techniques.unique_loops(state)
        self.assertTrue(any(
            move["technique_id"] == "unique.loop.2"
            and move["eliminations"] == [(0, 4, 3)]
            for move in moves
        ))
        self.assertFalse(any(
            move["technique_id"] == "unique.loop.2"
            for move in techniques.unique_loops(loop_state({
                (0, 0): {1, 2, 3},
                (0, 3): {1, 2, 4},
            }))
        ))

    def test_type3_positive_and_near_miss(self):
        state = loop_state(
            {
                (0, 0): {1, 2, 3},
                (0, 3): {1, 2, 4},
            },
            {
                (0, 4): {3, 4},
                (0, 5): {3},
            },
        )
        moves = techniques.unique_loops(state)
        self.assertTrue(any(
            move["technique_id"] == "unique.loop.3"
            and (0, 5, 3) in move["eliminations"]
            for move in moves
        ))
        self.assertFalse(any(
            move["technique_id"] == "unique.loop.3"
            for move in techniques.unique_loops(loop_state({
                (0, 0): {1, 2, 3},
                (0, 3): {1, 2, 4},
            }))
        ))

    def test_type4_positive_and_near_miss(self):
        state = loop_state(
            {
                (0, 0): {1, 2, 3},
                (0, 3): {1, 2, 4},
            },
            {(0, 4): {2, 5}},
        )
        moves = techniques.unique_loops(state)
        self.assertTrue(any(
            move["technique_id"] == "unique.loop.4"
            and set(move["eliminations"])
            == {(0, 0, 2), (0, 3, 2)}
            for move in moves
        ))
        self.assertFalse(any(
            move["technique_id"] == "unique.loop.4"
            for move in techniques.unique_loops(loop_state({
                (0, 0): {1, 2, 3},
                (0, 3): {1, 2, 4},
            }, {(0, 4): {1, 2}}))
        ))


if __name__ == "__main__":
    unittest.main()
