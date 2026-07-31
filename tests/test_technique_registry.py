import unittest
from dataclasses import FrozenInstanceError
from unittest import mock

import numpy as np

from sudoku_app.core import solver
from sudoku_app.core import technique_catalog as catalog
from sudoku_app.core import technique_registry as registry
from sudoku_app.core import techniques
from sudoku_app.core.data_structure import SudokuState


def make_runner(technique_id, function):
    definition = catalog.technique_definition(technique_id)
    return registry.TechniqueRunner(
        detector_id=definition.detector_id,
        technique_ids=(definition.id,),
        function=function,
        engine_type=definition.engine_type,
        fallback_tier=definition.fallback_tier,
        minimum_difficulty=definition.base_difficulty,
        priority=definition.priority,
    )


def make_move(technique_id, visible_name=None):
    definition = catalog.technique_definition(technique_id)
    return {
        "technique_id": definition.id,
        "technique": visible_name or definition.canonical_name,
        "difficulty": definition.base_difficulty,
        "placements": [],
        "eliminations": [(0, 0, 1)],
        "highlight": {"primary": [], "secondary": [(0, 0)]},
    }


class TechniqueRunnerTests(unittest.TestCase):
    def test_runner_is_immutable(self):
        runner = registry.RUNNER_BY_DETECTOR_ID["last_value"]
        with self.assertRaises(FrozenInstanceError):
            runner.fallback_tier = 2

    def test_registry_is_sorted_by_difficulty_and_priority(self):
        order = [
            (runner.minimum_difficulty, runner.priority)
            for runner in registry.TECHNIQUE_RUNNERS
        ]
        self.assertEqual(order, sorted(order))

    def test_fallback_partitions_are_explicit_and_disjoint(self):
        partitions = (
            registry.ORDINARY_RUNNERS,
            registry.NESTED_RUNNERS,
            registry.COMPLETE_TREE_RUNNERS,
        )
        self.assertTrue(all(
            runner.fallback_tier == tier
            for tier, runners in enumerate(partitions)
            for runner in runners
        ))
        flattened = tuple(
            runner
            for runners in partitions
            for runner in runners
        )
        self.assertEqual(
            {runner.detector_id for runner in flattened},
            {
                runner.detector_id
                for runner in registry.TECHNIQUE_RUNNERS
            },
        )
        self.assertEqual(len(flattened), len(registry.TECHNIQUE_RUNNERS))

    def test_every_runner_matches_catalog_metadata(self):
        for runner in registry.TECHNIQUE_RUNNERS:
            with self.subTest(detector_id=runner.detector_id):
                definitions = [
                    catalog.technique_definition(technique_id)
                    for technique_id in runner.technique_ids
                ]
                self.assertTrue(definitions)
                self.assertTrue(all(
                    definition.detector_id == runner.detector_id
                    and definition.engine_type == runner.engine_type
                    and definition.fallback_tier == runner.fallback_tier
                    for definition in definitions
                ))

    def test_function_name_does_not_classify_runner(self):
        def nested_forcing_chain(_state):
            return []

        local_runner = make_runner(
            "single.last_value",
            nested_forcing_chain,
        )
        self.assertEqual(
            solver._result_limit_for_runner(local_runner, 16),
            16,
        )

        def harmless_local_name(_state):
            return []

        nested_runner = make_runner(
            "nested.contradiction",
            harmless_local_name,
        )
        self.assertEqual(
            solver._result_limit_for_runner(nested_runner, 16),
            solver.MAX_NESTED_MOVES_PER_STEP,
        )

    def test_visible_rename_does_not_classify_move(self):
        local_move = make_move(
            "single.last_value",
            visible_name="Nested Forcing Chain renamed",
        )
        nested_move = make_move(
            "nested.contradiction",
            visible_name="Last Value renamed",
        )
        complete_move = make_move(
            "forcing.complete_tree",
            visible_name="Naked Single renamed",
        )

        self.assertEqual(solver._result_limit_for_move(local_move, 16), 16)
        self.assertEqual(
            solver._result_limit_for_move(nested_move, 16),
            solver.MAX_NESTED_MOVES_PER_STEP,
        )
        self.assertEqual(
            solver._result_limit_for_move(complete_move, 16),
            solver.MAX_COMPLETE_TREE_MOVES_PER_STEP,
        )
        self.assertEqual(solver._base_difficulty(local_move), 1.0)
        self.assertEqual(solver._base_difficulty(nested_move), 9.5)
        self.assertEqual(solver._base_difficulty(complete_move), 13.0)

    def test_pipeline_limits_are_explicit(self):
        self.assertEqual(solver.MAX_MOVES_PER_TECHNIQUE, 16)
        self.assertEqual(solver.MAX_LOGIC_ENGINE_MOVES_PER_TECHNIQUE, 8)
        self.assertEqual(solver.MAX_NESTED_MOVES_PER_STEP, 2)
        self.assertEqual(solver.MAX_COMPLETE_TREE_MOVES_PER_STEP, 1)

    def test_solver_has_no_runner_introspection_helpers(self):
        forbidden = (
            "_runner_metadata",
            "_metadata_strings",
            "_is_logic_engine_runner",
            "_is_nested_runner",
            "_partition_technique_functions",
        )
        self.assertTrue(all(
            not hasattr(solver, name)
            for name in forbidden
        ))
        self.assertFalse(hasattr(techniques, "TECHNIQUE_FUNCS"))
        self.assertFalse(hasattr(techniques, "TECHNIQUE_SPECS"))


class RegisteredCollectionTests(unittest.TestCase):
    def test_real_local_adapter_emits_registered_metadata(self):
        state = SudokuState(np.zeros((9, 9), dtype=int))
        state.candidates = [[set() for _ in range(9)] for _ in range(9)]
        state.candidates[0][0] = {7}
        naked_runner = registry.RUNNER_BY_DETECTOR_ID["naked_single"]

        with (
            mock.patch.object(
                registry,
                "ORDINARY_RUNNERS",
                (naked_runner,),
            ),
            mock.patch.object(registry, "NESTED_RUNNERS", ()),
        ):
            moves, _ = solver.collect_moves_for_analysis(
                state,
                mode="deep",
            )

        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]["technique_id"], "single.naked")
        self.assertEqual(moves[0]["detector_id"], "naked_single")
        self.assertEqual(moves[0]["engine_type"], "local")
        self.assertEqual(moves[0]["fallback_tier"], 0)

    def test_detector_cannot_emit_an_undeclared_technique(self):
        runner = make_runner("single.last_value", lambda _state: [])
        with self.assertRaises(ValueError):
            solver._validate_runner_move(
                runner,
                make_move("single.naked"),
            )

    def test_nested_runner_is_not_called_when_ordinary_move_exists(self):
        nested_calls = []
        complete_calls = []
        ordinary = make_runner(
            "single.last_value",
            lambda _state: [make_move("single.last_value")],
        )

        def collect_nested(_state):
            nested_calls.append(True)
            return [make_move("nested.contradiction")]

        nested = make_runner("nested.contradiction", collect_nested)
        complete = make_runner(
            "forcing.complete_tree",
            lambda _state: complete_calls.append(True),
        )

        with (
            mock.patch.object(registry, "ORDINARY_RUNNERS", (ordinary,)),
            mock.patch.object(registry, "NESTED_RUNNERS", (nested,)),
            mock.patch.object(registry, "COMPLETE_TREE_RUNNERS", (complete,)),
        ):
            moves, metadata = solver.collect_moves_for_analysis(
                object(),
                mode="deep",
            )

        self.assertEqual([move["technique_id"] for move in moves], [
            "single.last_value",
        ])
        self.assertFalse(nested_calls)
        self.assertFalse(complete_calls)
        self.assertFalse(metadata["nested_fallback_used"])
        self.assertEqual(metadata["fallback_tier_used"], 0)
        self.assertEqual(metadata["fallback_stage"], "ordinary")

    def test_nested_runner_is_used_from_explicit_fallback_partition(self):
        complete_calls = []
        ordinary = make_runner(
            "single.last_value",
            lambda _state: [],
        )
        nested = make_runner(
            "nested.contradiction",
            lambda _state: [make_move("nested.contradiction")],
        )
        complete = make_runner(
            "forcing.complete_tree",
            lambda _state: complete_calls.append(True),
        )

        with (
            mock.patch.object(registry, "ORDINARY_RUNNERS", (ordinary,)),
            mock.patch.object(registry, "NESTED_RUNNERS", (nested,)),
            mock.patch.object(registry, "COMPLETE_TREE_RUNNERS", (complete,)),
        ):
            moves, metadata = solver.collect_moves_for_analysis(
                object(),
                mode="deep",
            )

        self.assertEqual([move["technique_id"] for move in moves], [
            "nested.contradiction",
        ])
        self.assertTrue(metadata["nested_fallback_used"])
        self.assertTrue(metadata["nested_fallback_attempted"])
        self.assertFalse(metadata["complete_tree_fallback_attempted"])
        self.assertFalse(complete_calls)
        self.assertEqual(metadata["fallback_tier_used"], 1)
        self.assertEqual(metadata["fallback_stage"], "nested")
        self.assertEqual(moves[0]["detector_id"], "nested_forcing_chain")
        self.assertEqual(moves[0]["fallback_tier"], 1)

    def test_complete_tree_runs_only_after_ordinary_and_nested_are_empty(self):
        ordinary = make_runner("single.last_value", lambda _state: [])
        nested = make_runner("nested.contradiction", lambda _state: [])
        complete = make_runner(
            "forcing.complete_tree",
            lambda _state: [make_move("forcing.complete_tree")],
        )

        with (
            mock.patch.object(registry, "ORDINARY_RUNNERS", (ordinary,)),
            mock.patch.object(registry, "NESTED_RUNNERS", (nested,)),
            mock.patch.object(registry, "COMPLETE_TREE_RUNNERS", (complete,)),
        ):
            moves, metadata = solver.collect_moves_for_analysis(
                object(),
                mode="deep",
            )

        self.assertEqual(
            [move["technique_id"] for move in moves],
            ["forcing.complete_tree"],
        )
        self.assertTrue(metadata["nested_fallback_attempted"])
        self.assertFalse(metadata["nested_fallback_used"])
        self.assertTrue(metadata["complete_tree_fallback_attempted"])
        self.assertTrue(metadata["complete_tree_fallback_used"])
        self.assertEqual(metadata["fallback_tier_used"], 2)
        self.assertEqual(metadata["fallback_stage"], "complete_tree")
        self.assertEqual(
            metadata["fallback_reason"],
            "no_ordinary_or_nested_move",
        )

    def test_nested_and_complete_tree_results_use_their_own_caps(self):
        nested_moves = []
        for index in range(3):
            move = make_move("nested.contradiction")
            move["eliminations"] = [(0, index, 1)]
            nested_moves.append(move)

        nested = make_runner(
            "nested.contradiction",
            lambda _state: nested_moves,
        )
        with (
            mock.patch.object(registry, "ORDINARY_RUNNERS", ()),
            mock.patch.object(registry, "NESTED_RUNNERS", (nested,)),
            mock.patch.object(registry, "COMPLETE_TREE_RUNNERS", ()),
        ):
            moves, _ = solver.collect_moves_for_analysis(object(), mode="deep")

        self.assertEqual(len(moves), 2)

        complete_moves = []
        for index in range(3):
            move = make_move("forcing.complete_tree")
            move["eliminations"] = [(0, index, 1)]
            complete_moves.append(move)
        complete = make_runner(
            "forcing.complete_tree",
            lambda _state: complete_moves,
        )
        with (
            mock.patch.object(registry, "ORDINARY_RUNNERS", ()),
            mock.patch.object(registry, "NESTED_RUNNERS", ()),
            mock.patch.object(registry, "COMPLETE_TREE_RUNNERS", (complete,)),
        ):
            moves, _ = solver.collect_moves_for_analysis(object(), mode="deep")

        self.assertEqual(len(moves), 1)


if __name__ == "__main__":
    unittest.main()
