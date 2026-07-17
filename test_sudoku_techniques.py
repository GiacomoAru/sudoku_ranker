import unittest

import numpy as np

import sudoku_solver as solver
import sudoku_techniques as techniques
from sudoku_data_structure import SudokuState


SOLVED_GRID = np.array([
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


def synthetic_state(entries):
    """Create a state whose pencilmarks are controlled by the test."""
    state = SudokuState(np.zeros((9, 9), dtype=int))
    state.candidates = [[set() for _ in range(9)] for _ in range(9)]
    for (row, column), values in entries.items():
        state.candidates[row][column] = set(values)
    return state


class SERatingTests(unittest.TestCase):
    def test_official_fixed_ratings(self):
        expected = {
            "Last Value": 1.0,
            "Hidden Single (Box)": 1.2,
            "Hidden Single (Row/Column)": 1.5,
            "Direct Pointing": 1.7,
            "Direct Claiming": 1.9,
            "Direct Hidden Pair": 2.0,
            "Naked Single": 2.3,
            "Direct Hidden Triplet": 2.5,
            "Pointing": 2.6,
            "Claiming": 2.8,
            "Naked Pair": 3.0,
            "X-Wing": 3.2,
            "Hidden Pair": 3.4,
            "Naked Triple": 3.6,
            "Swordfish": 3.8,
            "Hidden Triple": 4.0,
            "Y-Wing": 4.2,
            "XYZ-Wing": 4.4,
            "Naked Quadruple": 5.0,
            "Jellyfish": 5.2,
            "Hidden Quadruple": 5.4,
            "BUG+1": 5.6,
            "BUG Type 2": 5.7,
            "BUG Type 4": 5.7,
            "BUG Type 3 (Pair)": 5.8,
            "BUG Type 3 (Triplet)": 5.9,
            "BUG Type 3 (Quad)": 6.0,
            "Aligned Pair Exclusion": 6.2,
            "Skyscraper": 6.6,
            "Two-String Kite": 6.6,
            "W-Wing": 7.0,
        }
        for name, rating in expected.items():
            with self.subTest(name=name):
                self.assertEqual(
                    techniques.TECHNIQUE_DIFFICULTY[name],
                    rating,
                )

    def test_registry_is_sorted_by_minimum_rating(self):
        ratings = [rating for rating, _ in techniques.TECHNIQUE_FUNCS]
        self.assertEqual(ratings, sorted(ratings))

    def test_move_uses_canonical_rating_not_legacy_literal(self):
        state = synthetic_state({(0, 0): {7}})
        move = techniques.naked_single(state)[0]
        self.assertEqual(move["difficulty"], 2.3)

    def test_last_value(self):
        grid = SOLVED_GRID.copy()
        grid[0, 0] = 0
        moves = techniques.last_value(SudokuState(grid))
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]["placements"], [(0, 0, 5)])
        self.assertEqual(moves[0]["difficulty"], 1.0)

    def test_hidden_single_rating_depends_on_house(self):
        state = synthetic_state({
            (0, 0): {9},
            (0, 3): {9},
            (3, 0): {9},
            (1, 1): {8},
            (0, 1): {8},
            (1, 4): {4},
            (3, 1): {8},
        })
        moves = techniques.hidden_single(state)
        self.assertTrue(any(
            move["technique"] == "Hidden Single (Box)"
            and move["placements"] == [(0, 0, 9)]
            and move["difficulty"] == 1.2
            for move in moves
        ))
        self.assertTrue(any(
            move["technique"] == "Hidden Single (Row/Column)"
            and move["placements"] == [(1, 1, 8)]
            and move["difficulty"] == 1.5
            for move in moves
        ))

    def test_direct_pointing_places_resulting_hidden_single(self):
        state = synthetic_state({
            (0, 0): {5},
            (0, 1): {5},
            (0, 3): {5},
            (0, 4): {5},
            (1, 3): {5},
        })
        moves = [
            move for move in techniques.direct_locked_candidates(state)
            if move["technique"] == "Direct Pointing"
        ]
        self.assertTrue(any(
            move["placements"] == [(1, 3, 5)]
            and set(move["eliminations"]) == {(0, 3, 5), (0, 4, 5)}
            and move["difficulty"] == 1.7
            for move in moves
        ))

    def test_direct_claiming_places_resulting_hidden_single(self):
        state = synthetic_state({
            (0, 0): {5},
            (0, 1): {5},
            (1, 0): {5},
            (1, 1): {5},
            (1, 3): {5},
        })
        moves = [
            move for move in techniques.direct_locked_candidates(state)
            if move["technique"] == "Direct Claiming"
        ]
        self.assertTrue(any(
            move["placements"] == [(1, 3, 5)]
            and set(move["eliminations"]) == {(1, 0, 5), (1, 1, 5)}
            and move["difficulty"] == 1.9
            for move in moves
        ))

    def test_direct_hidden_pair_places_resulting_hidden_single(self):
        state = synthetic_state({
            (0, 0): {1, 2, 9},
            (0, 1): {1, 2, 8},
            (0, 2): {3, 9},
            (0, 3): {3, 4},
            (0, 4): {4, 5},
        })
        moves = techniques.direct_hidden_subset(state, 2)
        self.assertTrue(any(
            move["placements"] == [(0, 2, 9)]
            and {(0, 0, 9), (0, 1, 8)} <= set(move["eliminations"])
            and move["difficulty"] == 2.0
            for move in moves
        ))

    def test_direct_hidden_triplet_places_resulting_hidden_single(self):
        state = synthetic_state({
            (0, 0): {1, 2, 6, 9},
            (0, 1): {2, 3, 8},
            (0, 2): {1, 3, 7},
            (0, 3): {4, 6},
            (0, 4): {4, 5},
        })
        moves = techniques.direct_hidden_subset(state, 3)
        self.assertTrue(any(
            move["placements"] == [(0, 3, 6)]
            and {
                (0, 0, 6),
                (0, 0, 9),
                (0, 1, 8),
                (0, 2, 7),
            } <= set(move["eliminations"])
            and move["difficulty"] == 2.5
            for move in moves
        ))

    def test_aligned_pair_exclusion(self):
        state = synthetic_state({
            (0, 0): {1, 2, 3},
            (1, 1): {1, 2, 3},
            (0, 1): {1, 2},
            (1, 0): {1, 3},
        })
        moves = techniques.aligned_pair_exclusion(state)
        self.assertTrue(any(
            set(move["eliminations"]) == {(0, 0, 1), (1, 1, 1)}
            and move["difficulty"] == 6.2
            for move in moves
        ))

    def test_grading_accepts_ratings_above_five(self):
        chain = [{
            "technique": "Aligned Pair Exclusion",
            "difficulty": 6.2,
            "perceived_difficulty": 10.0,
        }]
        grading = solver.grade_difficulty(chain, "solved")
        self.assertEqual(grading["max_difficulty"], 6.2)
        self.assertEqual(grading["max_level"], 6)
        self.assertEqual(grading["label"], "Estremo")
        self.assertIn(6, grading["histogram"])
        self.assertEqual(grading["se_histogram"], {6.2: 1})


if __name__ == "__main__":
    unittest.main()
