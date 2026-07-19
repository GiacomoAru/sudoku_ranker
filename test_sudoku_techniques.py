import unittest
from unittest import mock

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
            "Bidirectional X-Cycle": 6.5,
            "Bidirectional Y-Cycle": 6.5,
            "Remote Pair": 6.5,
            "XY-Chain": 6.5,
            "XY-Cycle": 6.5,
            "Forcing X-Chain": 6.6,
            "Skyscraper": 6.6,
            "Two-String Kite": 6.6,
            "Empty Rectangle": 6.6,
            "Turbot Fish": 6.6,
            "Forcing Chain": 7.0,
            "Alternating Inference Chain": 7.0,
            "Bidirectional Cycle": 7.0,
            "Continuous Nice Loop": 7.0,
            "W-Wing": 7.0,
            "Nishio": 7.5,
            "Cell Forcing Chain": 8.0,
            "Region Forcing Chain": 8.0,
            "Dynamic Forcing Chain": 8.5,
            "Dynamic Forcing Chain Plus": 9.0,
            "Nested Forcing Chain": 9.5,
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


class LogicEngineTests(unittest.TestCase):
    def test_all_declared_logic_engine_techniques_are_now_implemented(self):
        expected = {
            "Bidirectional X-Cycle",
            "Bidirectional Y-Cycle",
            "Forcing X-Chain",
            "Forcing Chain",
            "Bidirectional Cycle",
            "Nishio",
            "Cell Forcing Chain",
            "Region Forcing Chain",
            "Dynamic Forcing Chain",
            "Dynamic Forcing Chain Plus",
            "Nested Forcing Chain",
        }
        self.assertEqual(
            set(techniques.LOGIC_ENGINE_TECHNIQUE_RANGES),
            expected,
        )
        self.assertEqual(
            techniques.TECHNIQUES_REQUIRING_LOGIC_ENGINE,
            {},
        )
        self.assertTrue(expected <= set(techniques.TECHNIQUE_DIFFICULTY))

    def test_x_wing_is_not_duplicated_as_bidirectional_x_cycle(self):
        # Lo stesso grafo può spiegare questa eliminazione come ciclo X, ma
        # il nome strutturale X-Wing è più specifico e deve prevalere.
        state = synthetic_state({
            (0, 0): {1},
            (0, 3): {1},
            (3, 3): {1},
            (3, 0): {1},
            (0, 1): {1},
        })
        before = [[set(values) for values in row] for row in state.candidates]
        fish_moves = techniques.fish(state, 2)
        cycle_moves = techniques.bidirectional_x_cycle(state)
        self.assertTrue(any(
            move["technique"] == "X-Wing"
            and move["eliminations"] == [(0, 1, 1)]
            for move in fish_moves
        ))
        self.assertFalse(any(
            move["eliminations"] == [(0, 1, 1)]
            for move in cycle_moves
        ))
        self.assertEqual(state.candidates, before)

    def test_xy_chain_uses_modern_specific_name(self):
        state = synthetic_state({
            (0, 0): {1, 2},
            (3, 0): {2, 3},
            (3, 4): {3, 4},
            (1, 4): {1, 4},
            (1, 1): {1},
        })
        moves = techniques.xy_chain(state)
        self.assertTrue(any(
            move["technique"] == "XY-Chain"
            and move["eliminations"] == [(1, 1, 1)]
            and {"peer", "y"} <= set(move["logic"]["reasons"])
            for move in moves
        ))

    def test_remote_pair_is_recognised_as_xy_chain_subtype(self):
        state = synthetic_state({
            (0, 0): {1, 2},
            (3, 0): {1, 2},
            (3, 4): {1, 2},
            (1, 4): {1, 2},
            (1, 1): {1},
        })
        moves = techniques.xy_chain(state)
        self.assertTrue(any(
            move["technique"] == "Remote Pair"
            and move["eliminations"] == [(1, 1, 1)]
            and move["logic"]["parent_technique"] == "XY-Chain"
            for move in moves
        ))

    def test_empty_rectangle_has_dedicated_detector(self):
        state = synthetic_state({
            (0, 1): {1},
            (1, 0): {1},
            (0, 4): {1},
            (3, 4): {1},
            (3, 0): {1},
        })
        moves = techniques.empty_rectangle(state)
        self.assertTrue(any(
            move["technique"] == "Empty Rectangle"
            and move["eliminations"] == [(3, 0, 1)]
            and move["difficulty"] == 6.6
            for move in moves
        ))

    def test_general_proofs_are_classified_by_structure(self):
        state = synthetic_state({(0, 0): {1, 2}})
        six_literal_chain = [{
            "row": 0,
            "column": index % 2,
            "value": 1,
            "state": "on" if index % 2 == 0 else "off",
        } for index in range(6)]
        cases = [
            ("Forcing X-Chain", "forcing-chain", [six_literal_chain], "Turbot Fish"),
            ("Forcing Chain", "forcing-chain", [], "Alternating Inference Chain"),
            ("Bidirectional Cycle", "bidirectional-cycle", [], "Continuous Nice Loop"),
            ("Dynamic Forcing Chain", "dynamic-contradiction", [], "Dynamic Contradiction Forcing Chain"),
            ("Dynamic Forcing Chain Plus", "dynamic-cell-reduction", [], "Dynamic Cell Forcing Chain Plus"),
            ("Nested Forcing Chain", "dynamic-region-reduction", [], "Nested Region Forcing Chain"),
        ]
        for parent, kind, chains, expected in cases:
            with self.subTest(parent=parent, kind=kind):
                self.assertEqual(
                    techniques._specific_logic_technique(
                        state,
                        parent,
                        {"logic": {"kind": kind, "chains": chains}},
                    ),
                    expected,
                )

    def test_forcing_x_chain_detects_assumption_implying_its_opposite(self):
        state = synthetic_state({
            (0, 0): {1},
            (0, 1): {1},
            (1, 1): {1},
        })
        moves = techniques.forcing_x_chain(state)
        self.assertTrue(any(
            move["eliminations"] == [(0, 0, 1)]
            and move["difficulty"] == 6.6
            and move["logic"]["kind"] == "forcing-chain"
            for move in moves
        ))

    def test_logic_wrapper_preserves_move_interface(self):
        state = synthetic_state({(0, 0): {4, 7}})
        deduction = {
            "description": "prova controllata",
            "placements": [],
            "eliminations": [(0, 0, 7)],
            "primary": [(0, 0)],
            "logic": {"kind": "test", "assumptions": [], "chains": []},
        }
        with mock.patch.object(
            techniques.logic_engine,
            "find_logic_deductions",
            return_value=[deduction],
        ) as finder:
            moves = techniques.dynamic_forcing_chain_plus(state)
        finder.assert_called_once_with(state, "Dynamic Forcing Chain Plus")
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]["technique"], "Dynamic Forcing Chain Plus")
        self.assertEqual(moves[0]["difficulty"], 9.0)
        self.assertEqual(moves[0]["placements"], [])
        self.assertEqual(moves[0]["eliminations"], [(0, 0, 7)])
        self.assertEqual(
            set(moves[0]["highlight"]),
            {"primary", "secondary"},
        )

    def test_solver_records_the_complete_move_inventory(self):
        grid = SOLVED_GRID.copy()
        grid[0, 0] = 0
        moves = [{
            "technique": "Last Value",
            "family": "Inserimenti diretti",
            "difficulty": 1.0,
            "description": "mossa scelta",
            "placements": [(0, 0, 5)],
            "eliminations": [],
            "highlight": {"primary": [(0, 0)], "secondary": [(0, 0)]},
        }, {
            "technique": "Forcing Chain",
            "family": "Catene forzanti",
            "difficulty": 7.0,
            "description": "alternativa più difficile",
            "placements": [],
            "eliminations": [(0, 0, 5)],
            "highlight": {"primary": [(0, 0)], "secondary": [(0, 0)]},
        }]
        with mock.patch.object(
            solver,
            "collect_all_moves_full",
            return_value=moves,
        ) as collect_full:
            _, chain, status = solver.solve_and_log(grid)
        collect_full.assert_called_once()
        self.assertEqual(status, "solved")
        self.assertEqual(chain[0]["n_alternatives"], 2)
        self.assertEqual(chain[0]["n_best_alternatives"], 1)
        self.assertEqual(chain[0]["applicable_by_technique"], {
            "Last Value": 1,
            "Forcing Chain": 1,
        })


if __name__ == "__main__":
    unittest.main()
