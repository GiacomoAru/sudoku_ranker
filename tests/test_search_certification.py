"""Test per gli stati FOUND/EXHAUSTED/TRUNCATED e il flag `certified` (P17).

Copre due livelli:

* i motori con budget interno esplicito espongono cause tipizzate di
  troncamento anche quando non producono alcuna deduzione;
* ``solver._collect_from_runners``/``collect_moves_for_analysis`` derivano
  correttamente ``certified`` dal troncamento dei soli runner potenzialmente
  piu' semplici della mossa minima trovata.
"""

import json
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from sudoku_app.core import als, fish, kraken, solver, techniques, templates
from sudoku_app.core import technique_catalog as catalog
from sudoku_app.core import technique_registry as registry
from sudoku_app.core.data_structure import SudokuState
from tests.test_technique_registry import make_move, make_runner


def _dense_grid():
    """Puzzle poco risolto: garantisce abbastanza ALS multicella da poter
    superare un budget artificialmente basso senza dover risolvere nulla."""
    path = (
        Path(__file__).resolve().parent
        / "fixtures" / "solver_corpus" / "puzzles.json"
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    return document["cases"][-1]["puzzle"]


DENSE_GRID = _dense_grid()


class EngineTruncationSignalTests(unittest.TestCase):
    def setUp(self):
        grid = [
            [int(value) for value in DENSE_GRID[row * 9:(row + 1) * 9]]
            for row in range(9)
        ]
        self.state = SudokuState(grid)
        self.graph = als.ALSGraph(self.state, als.enumerate_als(self.state))

    def test_als_aic_reports_truncation_even_without_results(self):
        truncated_out = []
        results = als.find_als_aics(
            self.graph, max_alses=1, truncated_out=truncated_out
        )
        self.assertEqual(results, ())
        self.assertIn("als_aic_max_alses", truncated_out)

    def test_als_aic_is_not_truncated_with_a_generous_budget(self):
        truncated_out = []
        empty_graph = als.ALSGraph(self.state, ())
        als.find_als_aics(
            empty_graph, max_alses=10_000, truncated_out=truncated_out
        )
        self.assertEqual(truncated_out, [])

    def test_templates_reports_truncation_per_digit_even_when_filtered(self):
        truncated_out = []
        templates.find_templates(
            self.state, max_templates=1, truncated_out=truncated_out
        )
        self.assertTrue(truncated_out)

    def test_kraken_reports_truncation_even_without_results(self):
        truncated_out = []
        kraken.find_kraken(
            self.state, max_patterns=0, truncated_out=truncated_out
        )
        self.assertEqual(truncated_out, ["kraken_max_patterns"])

    def test_fish_reports_its_result_budget(self):
        state = SudokuState(np.zeros((9, 9), dtype=int))
        state.candidates = [[set() for _ in range(9)] for _ in range(9)]
        for row, column in ((0, 0), (0, 3), (3, 0), (3, 3), (1, 0)):
            state.candidates[row][column] = {1}

        truncated_out = []
        deductions = list(fish.find_fish(
            state,
            1,
            2,
            ("row",),
            ("column",),
            accepted_classes=("basic",),
            max_results=1,
            truncated_out=truncated_out,
        ))

        self.assertEqual(len(deductions), 1)
        self.assertEqual(truncated_out, ["fish_result_limit"])


class DetectorMetadataCacheTests(unittest.TestCase):
    def test_record_and_read_round_trip(self):
        grid = np.arange(81).reshape(9, 9) % 9 + 1
        state = SudokuState(grid)

        self.assertEqual(
            techniques.detector_search_metadata(state, "fake"), {}
        )
        techniques._record_search_truncated(state, "fake", True)
        self.assertEqual(
            techniques.detector_search_metadata(state, "fake"),
            {
                "completion": "truncated",
                "search_truncated": True,
                "truncated_reasons": ["unspecified_budget"],
            },
        )

    def test_incompatible_state_returns_empty_metadata_instead_of_raising(
        self,
    ):
        self.assertEqual(
            techniques.detector_search_metadata(object(), "fake"), {}
        )


class CertifiedFlagTests(unittest.TestCase):
    """Verifica isolata di ``_collect_from_runners`` con runner sintetici."""

    def setUp(self):
        grid = np.arange(81).reshape(9, 9) % 9 + 1
        self.state = SudokuState(grid)

    def _run(self, runners, mode="deep"):
        return solver._collect_from_runners(
            self.state,
            runners,
            mode=mode,
            profile_difficulty_window=1.5,
            canonical_transform=None,
            max_results=16,
        )

    def test_certified_true_when_no_detector_is_truncated(self):
        cheap = make_runner(
            "single.last_value",
            lambda state: [make_move("single.last_value")],
        )
        _, metadata = self._run((cheap,))
        self.assertFalse(metadata["truncated_before_best_difficulty"])
        self.assertEqual(metadata["truncated_detector_ids"], [])
        self.assertEqual(
            metadata["detector_searches"][0]["outcome"],
            "FOUND",
        )

    def test_certified_false_when_a_simpler_detector_truncates(self):
        def truncated_and_empty(state):
            techniques._record_search_truncated(state, "als", True)
            return []

        truncating = make_runner("als.xz.single", truncated_and_empty)
        expensive = make_runner(
            "forcing.dynamic",
            lambda state: [make_move("forcing.dynamic")],
        )
        moves, metadata = self._run((truncating, expensive))

        self.assertEqual(len(moves), 1)
        self.assertTrue(metadata["truncated_before_best_difficulty"])
        self.assertEqual(metadata["truncated_detector_ids"], ["als"])
        self.assertEqual(
            metadata["detector_searches"][0]["outcome"],
            "TRUNCATED",
        )

    def test_not_decertified_by_a_harder_detector_truncating(self):
        cheap = make_runner(
            "single.last_value",
            lambda state: [make_move("single.last_value")],
        )

        def truncated_and_empty(state):
            techniques._record_search_truncated(state, "als", True)
            return []

        harder_truncating = make_runner("als.xz.single", truncated_and_empty)
        _, metadata = self._run((cheap, harder_truncating), mode="deep")

        self.assertEqual(metadata["truncated_detector_ids"], ["als"])
        self.assertFalse(metadata["truncated_before_best_difficulty"])

    def test_result_limit_censors_inventory_without_decertifying_minimum(self):
        def limited_with_move(state):
            techniques._record_search_metadata(
                state,
                "als",
                truncated_reasons=("als_result_limit",),
            )
            return [make_move("als.chain")]

        runner = make_runner("als.chain", limited_with_move)
        moves, metadata = self._run((runner,))

        self.assertEqual(len(moves), 1)
        self.assertEqual(metadata["truncated_detector_ids"], ["als"])
        self.assertFalse(metadata["truncated_before_best_difficulty"])
        self.assertFalse(
            metadata["detector_searches"][0][
                "minimum_certification_affected"
            ]
        )

    def test_collect_moves_for_analysis_exposes_top_level_certified(self):
        with mock.patch.object(
            registry,
            "ORDINARY_RUNNERS",
            (
                make_runner(
                    "single.last_value",
                    lambda state: [make_move("single.last_value")],
                ),
            ),
        ):
            moves, metadata = solver.collect_moves_for_analysis(
                self.state, mode="deep"
            )
        self.assertTrue(moves)
        self.assertIn("certified", metadata)
        self.assertTrue(metadata["certified"])


if __name__ == "__main__":
    unittest.main()
