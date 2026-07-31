import unittest

import numpy as np

from sudoku_app.core import solver
from sudoku_app.core.technique_registry import RUNNER_BY_DETECTOR_ID
from tests.solver_corpus import (
    ACTIVE_TECHNIQUE_BINDINGS,
    PLANNED_HODOKU_CODES,
    canonical_outcome,
    load_hodoku_cases,
    load_puzzle_cases,
)


class SolverCorpusFormatTests(unittest.TestCase):
    def test_local_cases_are_unique_and_cover_active_and_planned_codes(self):
        cases = load_hodoku_cases()
        by_code = {case.base_code: case for case in cases}

        self.assertTrue(
            set(ACTIVE_TECHNIQUE_BINDINGS).isdisjoint(
                PLANNED_HODOKU_CODES
            )
        )
        self.assertEqual(len(by_code), len(cases))
        self.assertEqual(
            set(by_code),
            set(ACTIVE_TECHNIQUE_BINDINGS) | PLANNED_HODOKU_CODES,
        )

    def test_every_active_binding_names_a_registered_detector(self):
        self.assertLessEqual(len(ACTIVE_TECHNIQUE_BINDINGS), 64)
        for code, binding in ACTIVE_TECHNIQUE_BINDINGS.items():
            with self.subTest(code=code, detector=binding.detector_id):
                self.assertIn(binding.detector_id, RUNNER_BY_DETECTOR_ID)
                self.assertIn(
                    binding.technique_id,
                    RUNNER_BY_DETECTOR_ID[binding.detector_id].technique_ids,
                )


class TechniqueRegressionCorpusTests(unittest.TestCase):
    def test_active_hodoku_gold_cases(self):
        cases = {
            case.base_code: case
            for case in load_hodoku_cases()
        }
        for code, binding in ACTIVE_TECHNIQUE_BINDINGS.items():
            with self.subTest(code=code, detector=binding.detector_id):
                case = cases[code]
                state = case.build_state()
                expected = canonical_outcome(
                    state,
                    case.expected_eliminations,
                    case.expected_placements,
                )
                moves = solver._call_registered_runner(
                    RUNNER_BY_DETECTOR_ID[binding.detector_id],
                    state,
                )
                outcomes = {
                    canonical_outcome(
                        state,
                        move["eliminations"],
                        move["placements"],
                    )
                    for move in moves
                    if move["technique_id"] == binding.technique_id
                }
                self.assertIn(expected, outcomes)

    def test_bug_plus_one_visualizes_the_global_pattern(self):
        case = next(
            item for item in load_hodoku_cases() if item.base_code == "0610"
        )
        state = case.build_state()
        binding = ACTIVE_TECHNIQUE_BINDINGS["0610"]
        moves = solver._call_registered_runner(
            RUNNER_BY_DETECTOR_ID[binding.detector_id],
            state,
        )
        move = next(
            item for item in moves if item["technique_id"] == binding.technique_id
        )
        unsolved = {
            (row, column)
            for row in range(9)
            for column in range(9)
            if state.grid[row, column] == 0
        }
        effect = set(move["highlight"]["effect"])
        implication = set(move["highlight"]["implication"])

        self.assertEqual(len(effect), 1)
        self.assertEqual(effect | implication, unsolved)
        self.assertTrue(effect.isdisjoint(implication))


class EndToEndPuzzleCorpusTests(unittest.TestCase):
    def test_compact_public_domain_bank_is_solved_in_superficial_mode(self):
        cases = load_puzzle_cases()
        self.assertEqual(len(cases), 4)
        self.assertEqual(
            {case["tier"] for case in cases},
            {"easy", "medium", "hard", "diabolical"},
        )
        for case in cases:
            with self.subTest(case=case["id"], tier=case["tier"]):
                analysis = solver.analyse_puzzle(
                    case["puzzle"],
                    name=case["id"],
                    analysis_mode="superficial",
                )
                self.assertEqual(analysis["status"], "solved")
                self.assertTrue(analysis["unique_solution"])
                self.assertTrue(np.all(analysis["solved_grid"] != 0))
                self.assertGreater(len(analysis["chain"]), 0)


if __name__ == "__main__":
    unittest.main()
