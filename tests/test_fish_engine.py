import unittest

import numpy as np

from sudoku_app.core import fish
from sudoku_app.core import technique_catalog
from sudoku_app.core import techniques
from sudoku_app.core.data_structure import SudokuState, backtracking_solve
from sudoku_app.archive import repository as archive
from tests.solver_corpus import load_hodoku_cases


def synthetic_state(entries):
    state = SudokuState(np.zeros((9, 9), dtype=int))
    state.candidates = [[set() for _ in range(9)] for _ in range(9)]
    for (row, column), values in entries.items():
        state.candidates[row][column] = set(values)
    return state


def transformed_state(state, transform, digit_map=lambda value: value):
    result = synthetic_state({})
    for row in range(9):
        for column in range(9):
            target = transform(row, column)
            result.candidates[target[0]][target[1]] = {
                digit_map(value) for value in state.candidates[row][column]
            }
    return result


class FishClassificationTests(unittest.TestCase):
    def test_p10_catalog_exposes_all_requested_fish_families(self):
        expected = {
            "X-Wing", "Swordfish", "Jellyfish",
            "Finned X-Wing", "Sashimi X-Wing",
            "Finned Swordfish", "Sashimi Swordfish",
            "Finned Jellyfish", "Sashimi Jellyfish",
            "Franken X-Wing", "Franken Swordfish", "Franken Jellyfish",
            "Finned Franken Fish", "Sashimi Franken Fish",
            "Mutant X-Wing", "Mutant Swordfish", "Mutant Jellyfish",
            "Finned Mutant Fish", "Sashimi Mutant Fish",
            "Siamese Fish", "Endo-Finned Fish", "Cannibalistic Fish",
        }
        self.assertTrue(expected <= set(technique_catalog.TECHNIQUE_DIFFICULTY))

    def test_house_types_define_basic_franken_and_mutant(self):
        self.assertEqual(fish.classify_fish((0, 3), (9, 12)), "basic")
        self.assertEqual(fish.classify_fish((0, 20), (9, 12)), "franken")
        self.assertEqual(fish.classify_fish((0, 12), (9, 21)), "mutant")

    def test_pattern_structure_is_immutable_and_serializable(self):
        pattern = fish.FishPattern(
            digit=9,
            size=3,
            base_sets=(0, 4, 20),
            cover_sets=(14, 16, 19),
            fins=frozenset(),
            endo_fins=frozenset({(0, 7, 9), (0, 8, 9)}),
            cannibalistic_targets=frozenset({(0, 5, 9)}),
            fish_class="franken",
        )
        payload = pattern.to_dict()
        self.assertEqual(payload["fish_class"], "franken")
        self.assertEqual(
            payload["modifiers"], ["endo-finned", "cannibalistic"]
        )
        self.assertEqual(payload["base_set_types"], ["row", "row", "box"])


class FishInferenceTests(unittest.TestCase):
    def test_finned_target_must_see_every_fin(self):
        state = synthetic_state({
            (0, 0): {1},
            (0, 1): {1},  # fin
            (0, 3): {1},
            (3, 0): {1},
            (3, 3): {1},
            (1, 0): {1},  # vede la fin tramite il box
            (6, 3): {1},  # non vede la fin
        })
        deductions = [
            item
            for item in fish.find_fish(
                state,
                1,
                2,
                ("row",),
                ("column",),
                accepted_classes=("basic",),
            )
            if item.pattern.base_sets == (0, 3)
            and item.pattern.cover_sets == (9, 12)
        ]
        self.assertEqual(len(deductions), 1)
        deduction = deductions[0]
        self.assertEqual(deduction.pattern.fins, frozenset({(0, 1, 1)}))
        self.assertIn((1, 0, 1), deduction.eliminations)
        self.assertNotIn((6, 3, 1), deduction.eliminations)

    def test_sashimi_is_derived_from_the_body_after_removing_fins(self):
        state = synthetic_state({
            (0, 0): {1},
            (0, 1): {1},  # fin; nella base resta un solo body candidate
            (3, 0): {1},
            (3, 3): {1},
            (1, 0): {1},
        })
        deduction = next(
            item
            for item in fish.find_fish(
                state,
                1,
                2,
                ("row",),
                ("column",),
                accepted_classes=("basic",),
            )
            if item.pattern.base_sets == (0, 3)
            and item.pattern.cover_sets == (9, 12)
        )
        self.assertTrue(deduction.sashimi)
        self.assertEqual(deduction.technique_name, "Sashimi X-Wing")

    def test_hodoku_endo_fins_and_cannibalistic_target(self):
        case = next(
            item for item in load_hodoku_cases() if item.base_code == "0341"
        )
        deductions = [
            item
            for item in fish.find_fish(
                case.build_state(),
                9,
                3,
                ("row", "box"),
                ("column", "box"),
                accepted_classes=("franken",),
                max_results=2048,
            )
            if item.pattern.base_sets == (0, 4, 20)
            and set(item.pattern.cover_sets) == {14, 16, 19}
        ]
        self.assertEqual(len(deductions), 1)
        deduction = deductions[0]
        self.assertEqual(deduction.pattern.fins, frozenset())
        self.assertEqual(
            deduction.pattern.endo_fins,
            frozenset({(0, 7, 9), (0, 8, 9)}),
        )
        self.assertEqual(
            deduction.pattern.cannibalistic_targets,
            frozenset({(0, 5, 9)}),
        )
        self.assertEqual(deduction.eliminations, frozenset({(0, 5, 9)}))

    def test_hodoku_mutant_uses_mixed_house_types(self):
        case = next(
            item for item in load_hodoku_cases() if item.base_code == "0362"
        )
        target_mask = 1 << (6 * 9 + 5)
        deductions = list(fish.find_fish(
            case.build_state(),
            8,
            4,
            fish.HOUSE_TYPES,
            fish.HOUSE_TYPES,
            accepted_classes=("mutant",),
            max_results=4,
            target_mask=target_mask,
        ))
        deduction = next(
            item for item in deductions
            if item.eliminations == frozenset({(6, 5, 8)})
        )
        self.assertEqual(deduction.pattern.fish_class, "mutant")
        self.assertEqual(
            {fish.HOUSE_TYPE_BY_ID[item] for item in deduction.pattern.base_sets},
            {"row", "column"},
        )
        self.assertIn("box", {
            fish.HOUSE_TYPE_BY_ID[item] for item in deduction.pattern.cover_sets
        })

    def test_complex_gold_moves_never_remove_the_solution_value(self):
        cases = {
            item.base_code: item
            for item in load_hodoku_cases()
            if item.base_code in {"0331", "0362"}
        }
        for code, case in cases.items():
            with self.subTest(code=code):
                state = case.build_state()
                solution = backtracking_solve(state.grid)
                self.assertIsNotNone(solution)
                moves = techniques.generalized_fish(state)
                self.assertTrue(moves)
                for move in moves:
                    for row, column, value in move["eliminations"]:
                        self.assertNotEqual(int(solution[row, column]), value)


class FishSymmetryTests(unittest.TestCase):
    def setUp(self):
        self.state = synthetic_state({
            (0, 0): {1},
            (0, 3): {1},
            (3, 0): {1},
            (3, 3): {1},
            (1, 0): {1},
        })

    @staticmethod
    def outcome(state, base_types, cover_types, digit):
        deductions = list(fish.find_fish(
            state,
            digit,
            2,
            base_types,
            cover_types,
            accepted_classes=("basic",),
        ))
        return {
            elimination
            for deduction in deductions
            for elimination in deduction.eliminations
        }

    def test_transposition_and_digit_permutation_are_equivalent(self):
        original = self.outcome(self.state, ("row",), ("column",), 1)
        transposed = transformed_state(self.state, lambda row, column: (column, row))
        transposed_outcome = self.outcome(
            transposed, ("column",), ("row",), 1
        )
        relabelled = transformed_state(
            self.state,
            lambda row, column: (row, column),
            lambda value: 7 if value == 1 else value,
        )
        relabelled_outcome = self.outcome(
            relabelled, ("row",), ("column",), 7
        )
        self.assertIn((1, 0, 1), original)
        self.assertEqual(
            transposed_outcome,
            {(column, row, value) for row, column, value in original},
        )
        self.assertEqual(
            relabelled_outcome,
            {(row, column, 7) for row, column, _ in original},
        )

    def test_quarter_rotation_preserves_the_conclusion(self):
        rotated = transformed_state(
            self.state, lambda row, column: (column, 8 - row)
        )
        outcome = self.outcome(rotated, ("column",), ("row",), 1)
        original = self.outcome(self.state, ("row",), ("column",), 1)
        self.assertEqual(
            outcome,
            {(column, 8 - row, value) for row, column, value in original},
        )


class FishConsolidationTests(unittest.TestCase):
    @staticmethod
    def pattern(cover_sets, fin):
        return fish.FishPattern(
            digit=1,
            size=2,
            base_sets=(0, 3),
            cover_sets=cover_sets,
            fins=frozenset({fin}),
            endo_fins=frozenset(),
            cannibalistic_targets=frozenset(),
            fish_class="basic",
        )

    def test_duplicate_conclusions_keep_one_structural_proof(self):
        first = fish.FishDeduction(
            pattern=self.pattern((9, 12), (0, 1, 1)),
            eliminations=frozenset({(1, 0, 1)}),
            body=frozenset(),
            potential_targets=frozenset({(1, 0, 1)}),
        )
        second = fish.FishDeduction(
            pattern=self.pattern((9, 13), (0, 2, 1)),
            eliminations=frozenset({(1, 0, 1)}),
            body=frozenset(),
            potential_targets=frozenset({(1, 0, 1)}),
        )
        consolidated = fish.consolidate_fish_deductions(
            (first, second), allow_siamese=False
        )
        self.assertEqual(len(consolidated), 1)
        self.assertEqual(consolidated[0].equivalent_pattern_count, 2)

    def test_siamese_components_are_replaced_by_one_union(self):
        first = fish.FishDeduction(
            pattern=self.pattern((9, 12), (0, 1, 1)),
            eliminations=frozenset({(1, 0, 1)}),
            body=frozenset({(0, 0, 1)}),
            potential_targets=frozenset({(1, 0, 1)}),
        )
        second = fish.FishDeduction(
            pattern=self.pattern((9, 13), (0, 2, 1)),
            eliminations=frozenset({(2, 0, 1)}),
            body=frozenset({(0, 0, 1)}),
            potential_targets=frozenset({(2, 0, 1)}),
        )
        consolidated = fish.consolidate_fish_deductions((first, second))
        self.assertEqual(len(consolidated), 1)
        self.assertTrue(consolidated[0].is_siamese)
        self.assertEqual(consolidated[0].technique_name, "Siamese Fish")
        self.assertEqual(
            consolidated[0].eliminations,
            frozenset({(1, 0, 1), (2, 0, 1)}),
        )
        self.assertEqual(len(consolidated[0].components), 2)

    def test_move_keeps_the_authoritative_pattern_payload(self):
        state = synthetic_state({
            (0, 0): {1}, (0, 3): {1},
            (3, 0): {1}, (3, 3): {1},
            (1, 0): {1},
        })
        move = next(
            item for item in techniques.fish(state, 2)
            if item["technique_id"] == "fish.basic.2"
            and item["eliminations"] == [(1, 0, 1)]
        )
        self.assertEqual(move["fish_pattern"]["fish_class"], "basic")
        self.assertEqual(move["fish_size"], 2)
        self.assertEqual(move["base_set_count"], 2)
        self.assertEqual(move["cover_set_count"], 2)

        solved = (
            "534678912672195348198342567859761423426853791"
            "713924856961537284287419635345286179"
        )
        compact = archive._compact_analysis_for_storage({
            "name": "fish-payload",
            "original": "0" + solved[1:],
            "solved_grid": solved,
            "unique_solution": True,
            "uniqueness_status": "verified_unique",
            "chain": [move],
            "status": "solved",
            "analysis_mode": "deep",
        })
        restored = archive._restore_analysis(compact)
        self.assertEqual(
            restored["chain"][0]["fish_pattern"], move["fish_pattern"]
        )


if __name__ == "__main__":
    unittest.main()
