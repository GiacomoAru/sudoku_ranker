import unittest
from dataclasses import replace

import numpy as np

from sudoku_app.core import exocet
from sudoku_app.core import exclusion
from sudoku_app.core import logic_engine
from sudoku_app.core import proof as proof_model
from sudoku_app.core import search_config
from sudoku_app.core import technique_catalog
from sudoku_app.core import techniques
from sudoku_app.core.data_structure import SudokuState


SOLUTION = (
    "534678912672195348198342567859761423426853791"
    "713924856961537284287419635345286179"
)


def synthetic_state(candidate_map):
    state = SudokuState(np.zeros((9, 9), dtype=int))
    state.candidates = [
        [set() for _ in range(9)]
        for _ in range(9)
    ]
    for (row, column), values in candidate_map.items():
        state.candidates[row][column] = set(values)
    return state


def exocet_state(*, cover_near_miss=False):
    candidates = {
        (0, 1): {3, 4, 5},
        (0, 2): {4, 5, 7},
        (1, 5): {1, 3, 4, 5, 7},
        (2, 8): {3, 4, 5, 6, 7},
        (2, 5): {2, 8},
        (1, 8): {2, 8},
        (4, 0): {4, 9},
        (5, 5): {5, 8},
        (6, 8): {7, 9},
    }
    if cover_near_miss:
        candidates.update({
            (3, 0): {3, 9},
            (4, 5): {3, 8},
            (5, 8): {3, 6},
        })
    else:
        candidates.update({
            (3, 0): {3, 9},
            (3, 5): {3, 8},
        })
    return synthetic_state(candidates)


class ModernAlignedExclusionTests(unittest.TestCase):
    def test_non_aligned_pair_has_its_own_modern_identity(self):
        state = synthetic_state({
            (0, 0): {1, 2},
            (1, 4): {4, 5},
            (0, 4): {1, 4},
            (1, 0): {1, 5},
        })

        move = next(
            item for item in techniques.aligned_pair_exclusion(state)
            if item["technique_id"]
            == "exclusion.aligned_pair.type2"
            and item["base_cells"] == [(0, 0), (1, 4)]
        )

        self.assertEqual(move["aligned_pair_type"], 2)
        self.assertEqual(move["eliminations"], [(0, 0, 1)])
        self.assertEqual(len(move["excluder_als"]), 2)
        self.assertIn("proof_dag", move["logic"])
        dag = proof_model.ProofDAG.from_dict(move["logic"]["proof_dag"])
        als_ids = {
            item["id"] for item in move["excluder_als"]
        }
        referenced = {
            als_id
            for node in dag.nodes.values()
            for als_id in node.payload.get("als_ids", ())
        }
        self.assertLessEqual(referenced, als_ids)

    def test_degree_four_uses_the_parametric_engine(self):
        state = synthetic_state({
            (0, 0): {1, 2},
            (1, 4): {3, 4},
            (5, 6): {5, 6},
            (8, 3): {7, 8},
            (0, 4): {1, 3},
            (1, 0): {1, 4},
        })

        pattern = next(
            item for item in exclusion.enumerate_aligned_exclusions(state, 4)
            if item.base_cells
            == ((0, 0), (1, 4), (5, 6), (8, 3))
        )
        self.assertEqual(pattern.eliminations, ((0, 0, 1),))
        digit_map = {
            1: 6, 2: 7, 3: 8, 4: 9, 5: 2,
            6: 1, 7: 3, 8: 5, 9: 4,
        }
        solution = np.array([
            digit_map[int(value)] for value in SOLUTION
        ]).reshape(9, 9)
        self.assertNotEqual(int(solution[0, 0]), 1)
        move = next(
            item for item in techniques.generalized_aligned_exclusion(state)
            if item["exclusion_degree"] == 4
        )

        self.assertEqual(move["technique_id"], "exclusion.aligned_set")
        self.assertEqual(move["exclusion_degree"], 4)
        self.assertEqual(move["eliminations"], [(0, 0, 1)])

    def test_aligned_budget_propagates_a_typed_truncation(self):
        state = synthetic_state({
            (0, 0): {1, 2},
            (1, 4): {3, 4},
            (0, 4): {1, 3},
            (1, 0): {1, 4},
        })
        limits = replace(
            search_config.LIMITED_SEARCH_LIMITS,
            aligned_base_combinations=1,
        )
        search_config.bind_search_limits(state, limits)

        techniques.aligned_pair_exclusion(state)
        metadata = techniques.detector_search_metadata(
            state,
            "aligned_pair_exclusion",
        )

        self.assertTrue(metadata["search_truncated"])
        self.assertIn(
            "aligned_base_combinations",
            metadata["truncated_reasons"],
        )


class JuniorExocetTests(unittest.TestCase):
    def test_rule_one_preserves_the_full_structural_payload(self):
        state = exocet_state()

        move = techniques.junior_exocet(state)[0]

        self.assertEqual(move["technique_id"], "pattern.jexocet.rule1")
        self.assertEqual(
            move["eliminations"],
            [(1, 5, 1), (2, 8, 6)],
        )
        pattern = move["exocet"]
        for key in (
            "base_cells",
            "base_digits",
            "target_cells",
            "companion_cells",
            "mirror_cells",
            "cross_line_house_ids",
            "s_cells",
            "cover_house_ids",
            "escape_cells",
        ):
            self.assertIn(key, pattern)
        self.assertIn("proof_dag", move["logic"])
        proof_model.ProofDAG.from_dict(move["logic"]["proof_dag"])

    def test_rule_one_eliminations_are_sound_against_the_solution(self):
        solution = np.array([int(value) for value in SOLUTION]).reshape(9, 9)
        move = techniques.junior_exocet(exocet_state())[0]

        self.assertTrue(all(
            int(solution[row, column]) != value
            for row, column, value in move["eliminations"]
        ))

    def test_three_independent_cover_houses_are_a_near_miss(self):
        patterns = exocet.enumerate_jexocet_rule1(
            exocet_state(cover_near_miss=True)
        )

        self.assertFalse(any(
            pattern.base_cells == ((0, 1), (0, 2))
            and pattern.target_cells == ((1, 5), (2, 8))
            for pattern in patterns
        ))

    def test_column_oriented_pattern_is_the_exact_transpose(self):
        row_state = exocet_state()
        candidate_map = {
            (column, row): set(row_state.candidates[row][column])
            for row in range(9)
            for column in range(9)
            if row_state.candidates[row][column]
        }

        move = techniques.junior_exocet(
            synthetic_state(candidate_map)
        )[0]

        self.assertEqual(move["exocet"]["orientation"], "column")
        self.assertEqual(
            move["eliminations"],
            [(5, 1, 1), (8, 2, 6)],
        )

    def test_ambiguous_rules_remain_planned(self):
        self.assertEqual(
            technique_catalog.technique_definition(
                "pattern.jexocet.rule1"
            ).implementation_status,
            "implemented",
        )
        for technique_id in (
            "pattern.jexocet.compatible_digit",
            "pattern.jexocet.rule3",
            "pattern.jexocet.rule4",
            "pattern.jexocet.rule5",
            "pattern.jexocet.rule8",
        ):
            self.assertEqual(
                technique_catalog.technique_definition(
                    technique_id
                ).implementation_status,
                "planned",
            )

    def test_pattern_budget_propagates_typed_truncation(self):
        state = exocet_state()
        limits = replace(
            search_config.LIMITED_SEARCH_LIMITS,
            exocet_results=1,
        )
        search_config.bind_search_limits(state, limits)

        techniques.junior_exocet(state)
        metadata = techniques.detector_search_metadata(
            state,
            "junior_exocet",
        )

        self.assertTrue(metadata["search_truncated"])
        self.assertIn("exocet_results", metadata["truncated_reasons"])


class BowmansBingoTests(unittest.TestCase):
    PUZZLE = (
        "534670900600190348198340567859761420426850701"
        "000924856900537284280409600040286070"
    )

    def setUp(self):
        logic_engine.clear_logic_cache()

    def test_positive_assertion_colors_and_solves_every_candidate(self):
        grid = np.array([
            int(value) for value in self.PUZZLE
        ]).reshape(9, 9)
        state = SudokuState(grid)

        move = techniques.bowmans_bingo(state)[0]

        self.assertEqual(move["technique_id"], "forcing.bowmans_bingo")
        coverage = move["logic"]["global_coverage"]
        self.assertTrue(coverage["complete_solution"])
        self.assertEqual(coverage["uncolored_candidates"], [])
        self.assertEqual(coverage["ambiguous_cells"], [])
        self.assertFalse(coverage["contradiction"])
        self.assertEqual(coverage["start_assertion"]["state"], "on")
        self.assertEqual(len(move["placements"]), 23)
        dag = proof_model.ProofDAG.from_dict(move["logic"]["proof_dag"])
        self.assertEqual(len(dag.conclusions), 23)
        solved = grid.copy()
        for row, column, value in move["placements"]:
            solved[row, column] = value
        self.assertEqual(
            "".join(str(int(value)) for value in solved.flat),
            SOLUTION,
        )

    def test_disconnected_singletons_do_not_form_a_global_bingo(self):
        grid = np.array([int(value) for value in SOLUTION]).reshape(9, 9)
        grid[0, 0] = 0
        grid[8, 8] = 0

        deductions = logic_engine.find_logic_deductions(
            SudokuState(grid),
            "Bowman's Bingo",
        )

        self.assertEqual(deductions, [])

    def test_attempt_budget_is_typed_and_does_not_create_partial_moves(self):
        grid = np.array([
            int(value) for value in self.PUZZLE
        ]).reshape(9, 9)
        state = SudokuState(grid)
        limits = replace(
            search_config.LIMITED_SEARCH_LIMITS,
            bowmans_attempts=1,
        )
        search_config.bind_search_limits(state, limits)

        moves = techniques.bowmans_bingo(state)
        metadata = techniques.detector_search_metadata(
            state,
            "bowmans_bingo",
        )

        self.assertEqual(moves, [])
        self.assertTrue(metadata["search_truncated"])
        self.assertIn("bowmans_attempts", metadata["truncated_reasons"])


if __name__ == "__main__":
    unittest.main()
