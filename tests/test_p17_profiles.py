"""Contratti conclusivi P17 per policy, profili d'inferenza e limiti."""

import unittest
from unittest import mock

import numpy as np

from sudoku_app.core import logic_engine
from sudoku_app.core import search_config
from sudoku_app.core import solver
from sudoku_app.core import technique_registry as registry
from sudoku_app.core.data_structure import SudokuState
from tests.test_technique_registry import make_move, make_runner


def candidate_state(entries):
    state = SudokuState(np.zeros((9, 9), dtype=int))
    state.candidates = [[set() for _ in range(9)] for _ in range(9)]
    for cell, values in entries.items():
        state.candidates[cell[0]][cell[1]] = set(values)
    return state


class InferenceProfileTests(unittest.TestCase):
    def test_profiles_keep_modern_rule_boundaries(self):
        dynamic = search_config.DYNAMIC_PROFILE
        plus = search_config.DYNAMIC_PLUS_PROFILE
        nested = search_config.NESTED_LEVEL_2_PROFILE

        self.assertTrue(dynamic.allow_dynamic_singles)
        self.assertFalse(dynamic.advanced_rule_ids)
        self.assertEqual(
            plus.advanced_rule_ids,
            ("locked-candidates", "subsets", "basic-fish"),
        )
        self.assertTrue(nested.allow_nested_subproofs)
        self.assertEqual(nested.max_nested_depth, 2)

    def test_dynamic_cannot_use_plus_rules(self):
        state = candidate_state({
            (0, 0): {1},
            (0, 3): {1},
            (3, 0): {1},
            (3, 3): {1},
            (1, 0): {1},
        })
        propagator = logic_engine.DynamicPropagator(
            state.grid,
            logic_engine._candidate_map(state),
        )

        dynamic = propagator._advanced_eliminations(
            propagator.initial,
            search_config.DYNAMIC_PROFILE,
        )
        plus = propagator._advanced_eliminations(
            propagator.initial,
            search_config.DYNAMIC_PLUS_PROFILE,
        )

        self.assertEqual(dynamic, [])
        self.assertTrue(any(rule == "advanced-x-wing" for _, rule, _ in plus))

    def test_plus_proof_declares_profile_and_rules_used(self):
        state = candidate_state({(0, 0): {1, 2}})
        engine = logic_engine.LogicEngine(state)
        engine._find_dynamic_forcing_chain_plus = lambda max_results: [{
            "description": "prova Plus controllata",
            "placements": [],
            "eliminations": [(0, 0, 1)],
            "logic": {
                "proof_dag": {
                    "nodes": {
                        "0": {"reason": "assumption"},
                        "1": {"reason": "advanced-x-wing"},
                    },
                },
            },
        }]

        deduction = engine.find("Dynamic Forcing Chain Plus")[0]

        self.assertEqual(
            deduction["logic"]["inference_profile_id"],
            "dynamic_plus",
        )
        self.assertEqual(
            deduction["logic"]["inference_rules_used"],
            ["advanced-x-wing"],
        )


class SearchLimitTests(unittest.TestCase):
    def setUp(self):
        logic_engine.clear_logic_cache()

    @staticmethod
    def forcing_state():
        return candidate_state({
            (0, 8): {1},
            (0, 4): {1},
            (3, 4): {1},
            (3, 7): {1},
            (1, 7): {1},
        })

    def test_limited_and_unlimited_are_explicit_and_immutable(self):
        limited = search_config.search_limits("limited")
        unlimited = search_config.search_limits("unlimited")

        self.assertEqual(limited.static_cycle_edges, 16)
        self.assertEqual(limited.nested_attempts, 512)
        self.assertIsNone(unlimited.static_cycle_edges)
        self.assertIsNone(unlimited.nested_attempts)
        with self.assertRaises(AttributeError):
            limited.logic_results = 1

    def test_unlimited_removes_internal_result_truncation(self):
        limited_state = self.forcing_state()
        custom_limited = search_config.SearchLimits(
            **{
                **search_config.LIMITED_SEARCH_LIMITS.to_dict(),
                "logic_results": 1,
            }
        )
        search_config.bind_search_limits(limited_state, custom_limited)
        limited_results = logic_engine.find_logic_deductions(
            limited_state,
            "Forcing X-Chain",
        )
        limited_metadata = logic_engine.logic_search_metadata(
            limited_state,
            "Forcing X-Chain",
        )

        unlimited_state = self.forcing_state()
        search_config.bind_search_limits(unlimited_state, "unlimited")
        unlimited_results = logic_engine.find_logic_deductions(
            unlimited_state,
            "Forcing X-Chain",
        )
        unlimited_metadata = logic_engine.logic_search_metadata(
            unlimited_state,
            "Forcing X-Chain",
        )

        self.assertEqual(len(limited_results), 1)
        self.assertIn(
            "logic_result_limit",
            limited_metadata["truncated_reasons"],
        )
        self.assertGreaterEqual(len(unlimited_results), len(limited_results))
        self.assertNotIn(
            "logic_result_limit",
            unlimited_metadata["truncated_reasons"],
        )

    def test_solver_exposes_the_active_limit_contract(self):
        state = SudokuState(np.arange(81).reshape(9, 9) % 9 + 1)
        runner = make_runner(
            "single.last_value",
            lambda current: [make_move("single.last_value")],
        )
        with (
            mock.patch.object(registry, "ORDINARY_RUNNERS", (runner,)),
            mock.patch.object(registry, "NESTED_RUNNERS", ()),
            mock.patch.object(registry, "COMPLETE_TREE_RUNNERS", ()),
        ):
            _, metadata = solver.collect_moves_for_analysis(
                state,
                mode="deep",
                search_limits="unlimited",
            )

        self.assertEqual(metadata["search_limits_mode"], "unlimited")
        self.assertIsNone(metadata["search_limits"]["fish_results"])
        self.assertIn("dynamic_plus", metadata["inference_profiles"])


class SearchPolicyProfileTests(unittest.TestCase):
    RUNNERS = (
        make_runner(
            "single.last_value",
            lambda state: [make_move("single.last_value")],
        ),
        make_runner(
            "single.naked",
            lambda state: [make_move("single.naked")],
        ),
        make_runner(
            "subset.naked.4",
            lambda state: [make_move("subset.naked.4")],
        ),
        make_runner(
            "fish.basic.2",
            lambda state: [make_move("fish.basic.2")],
        ),
    )

    def collect_ids(self, mode, window=1.0):
        state = SudokuState(np.arange(81).reshape(9, 9) % 9 + 1)
        with (
            mock.patch.object(registry, "ORDINARY_RUNNERS", self.RUNNERS),
            mock.patch.object(registry, "NESTED_RUNNERS", ()),
            mock.patch.object(registry, "COMPLETE_TREE_RUNNERS", ()),
        ):
            moves, metadata = solver.collect_moves_for_analysis(
                state,
                mode=mode,
                profile_difficulty_window=window,
            )
        return {move["technique_id"] for move in moves}, metadata

    def test_all_five_search_policies_have_distinct_contracts(self):
        superficial, _ = self.collect_ids("superficial")
        smart_profile, _ = self.collect_ids("smart_profile", window=1.0)
        full_profile, _ = self.collect_ids("full_profile", window=3.0)
        smart_deep, smart_metadata = self.collect_ids("smart_deep")
        deep, _ = self.collect_ids("deep")

        self.assertEqual(superficial, {"single.last_value"})
        self.assertEqual(
            smart_profile,
            {"single.last_value", "single.naked"},
        )
        self.assertEqual(full_profile, {
            "single.last_value",
            "single.naked",
            "subset.naked.4",
            "fish.basic.2",
        })
        self.assertEqual(smart_deep, {
            "single.last_value",
            "single.naked",
            "subset.naked.4",
        })
        self.assertEqual(deep, full_profile)
        self.assertLess(
            smart_metadata["scanned_runner_count"],
            len(self.RUNNERS),
        )


if __name__ == "__main__":
    unittest.main()
