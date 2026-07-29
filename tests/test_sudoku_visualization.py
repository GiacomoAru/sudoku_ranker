import unittest

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from sudoku_app.core import visualization


def synthetic_move(step, difficulty, activity, outcomes, conclusions):
    return {
        "step": step,
        "technique": "Last Value",
        "family": "Inserimenti diretti",
        "technical_difficulty": difficulty,
        "resolution_load": 4,
        "perceived_difficulty": difficulty,
        "description": "mossa sintetica",
        "placements": [(0, 0, 1)],
        "eliminations": [],
        "frontier_move_count": outcomes,
        "available_move_count": activity,
        "frontier_by_technique": {"Last Value": outcomes},
        "available_by_technique": {"Last Value": activity},
    }


def synthetic_analysis(name, difficulties, activities):
    chain = [
        synthetic_move(
            step=index + 1,
            difficulty=difficulty,
            activity=activities[index],
            outcomes=index + 1,
            conclusions=(index + 1) * 2,
        )
        for index, difficulty in enumerate(difficulties)
    ]

    return {
        "name": name,
        "status": "solved",
        "analysis_mode": "profile",
        "profile_difficulty_window": 3.0,
        "chain": chain,
        "grading": {
            "technical_difficulty_label": "Facile",
            "technical_difficulty": max(difficulties),
            "resolution_load": 4 * len(chain),
            "resolution_load_level": "Easy",
            "perceived_difficulty": 2.0 + 0.1 * len(chain),
            "step_count": len(chain),
        },
    }


class AggregateDifficultyPlotTests(unittest.TestCase):
    def setUp(self):
        self.analyses = [
            synthetic_analysis("corta", [1.0, 2.0], [1, 2]),
            synthetic_analysis("lunga", [3.0, 4.0, 5.0], [3, 5, 7]),
        ]

    def tearDown(self):
        plt.close("all")

    def test_aggregate_chain_uses_only_active_puzzles_per_step(self):
        aggregate = visualization.aggregate_difficulty_chain(
            self.analyses
        )
        steps = aggregate["steps"]

        self.assertEqual(list(steps["puzzle_count"]), [2, 2, 1])
        self.assertEqual(list(steps["coverage"]), [1.0, 1.0, 0.5])
        self.assertEqual(
            list(steps["mean_technical_difficulty"]),
            [2.0, 3.0, 5.0],
        )
        self.assertEqual(
            list(steps["mean_frontier_move_count"]),
            [1.0, 2.0, 3.0],
        )
        self.assertEqual(
            aggregate["summary"]["mean_steps"],
            2.5,
        )
        self.assertEqual(
            aggregate["summary"]["mean_resolution_load"],
            10.0,
        )
        self.assertAlmostEqual(
            aggregate["summary"]["mean_perceived_difficulty"],
            2.25,
        )

    def test_average_histogram_is_per_puzzle(self):
        histogram = visualization.aggregate_difficulty_chain(
            self.analyses
        )["histogram"]

        self.assertEqual(
            list(histogram.loc[:4, "mean_steps"]),
            [0.5, 0.5, 0.5, 0.5, 0.5],
        )

    def test_histogram_levels_use_half_point_boundaries(self):
        analysis = synthetic_analysis(
            "confini",
            [1.2, 1.49, 1.5, 1.6, 2.49, 2.5],
            [1, 1, 1, 1, 1, 1],
        )
        histogram = visualization.aggregate_difficulty_chain(
            [analysis]
        )["histogram"]

        self.assertEqual(
            list(histogram.loc[:2, "total_steps"]),
            [2, 3, 1],
        )

        _, axes = visualization.plot_difficulty_chain(
            analysis,
            show=False,
        )
        bar_heights = [
            patch.get_height()
            for patch in axes[1].patches
        ]
        self.assertEqual(bar_heights[:3], [2.0, 3.0, 1.0])

    def test_plot_difficulty_chain_accepts_a_list(self):
        result = visualization.plot_difficulty_chain(
            self.analyses,
            show=False,
        )

        self.assertIsNotNone(result)
        figure, axes = result
        self.assertEqual(len(axes), 3)
        self.assertIn("2 puzzle", axes[0].get_title())
        self.assertIsNotNone(figure)


class AggregateHeatmapTests(unittest.TestCase):
    def setUp(self):
        self.analyses = [
            synthetic_analysis("corta", [1.0, 2.0], [1, 2]),
            synthetic_analysis("lunga", [3.0, 4.0, 5.0], [3, 5, 7]),
        ]

    def tearDown(self):
        plt.close("all")

    def test_heatmap_dataframe_averages_active_puzzles(self):
        dataframe = visualization.technique_activity_dataframe(
            self.analyses,
            depth="deep",
            view="extended",
            metric="moves",
        )

        self.assertEqual(
            list(dataframe.loc["Last Value"]),
            [2.0, 3.5, 7.0],
        )
        self.assertEqual(
            dataframe.attrs["active_puzzle_count"],
            [2, 2, 1],
        )
        self.assertEqual(
            dataframe.attrs["aggregation"],
            "mean_active_puzzles",
        )

    def test_plot_heatmap_accepts_a_list(self):
        result = visualization.plot_technique_activity(
            self.analyses,
            depth="deep",
            view="extended",
            metric="moves",
            scale="linear",
            annotate=True,
            show=False,
        )

        self.assertIsNotNone(result)
        _, axis, dataframe = result
        self.assertIn("media", axis.get_title().lower())
        self.assertEqual(dataframe.loc["Last Value", 2], 3.5)


if __name__ == "__main__":
    unittest.main()
