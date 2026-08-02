import unittest
from unittest import mock

import numpy as np

from sudoku_app.core import solver
from sudoku_app.core import techniques
from sudoku_app.core import technique_catalog
from sudoku_app.core import technique_registry
from sudoku_app.core.data_structure import SudokuState


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


@unittest.skip(
    "Taratura numerica SE/HoDoKu storica: rinviata esplicitamente a P18."
)
class LegacyRatingCalibrationTests(unittest.TestCase):
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
            "XY-Wing": 4.2,
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
            "Complete Forcing Tree": 13.0,
        }
        for name, rating in expected.items():
            with self.subTest(name=name):
                self.assertEqual(
                    techniques.TECHNIQUE_DIFFICULTY[name],
                    rating,
                )

    def test_registry_is_sorted_by_minimum_rating(self):
        ratings = [
            runner.minimum_difficulty
            for runner in technique_registry.TECHNIQUE_RUNNERS
        ]
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
            "technical_difficulty": 6.2,
            "frontier_move_count": 1,
        }]
        grading = solver.grade_difficulty(chain, "solved")
        self.assertEqual(grading["technical_difficulty"], 6.2)
        self.assertEqual(
            grading["technical_difficulty_label"],
            "Esperto",
        )
        self.assertEqual(grading["resolution_load"], 300)
        self.assertEqual(grading["resolution_load_level"], "Unfair")
        self.assertEqual(grading["hardest_technique"], "Aligned Pair Exclusion")
        self.assertEqual(grading["step_count"], 1)
        self.assertEqual(set(grading), {
            "technical_difficulty",
            "technical_difficulty_label",
            "hardest_technique",
            "resolution_load",
            "resolution_load_level",
            "perceived_difficulty",
            "step_count",
        })

    def test_fair_difficulty_label_boundaries(self):
        expected = {
            1.5: "Molto facile",
            1.6: "Facile",
            2.5: "Facile",
            2.6: "Medio",
            3.7: "Medio",
            3.8: "Difficile",
            4.7: "Difficile",
            4.8: "Molto difficile",
            5.8: "Molto difficile",
            5.9: "Esperto",
            6.8: "Esperto",
            6.9: "Diabolico",
            8.5: "Diabolico",
            8.6: "Estremo",
            9.0: "Estremo",
            9.5: "Incubo",
            9.6: "Oltre il limite",
        }

        for score, label in expected.items():
            with self.subTest(score=score):
                self.assertEqual(
                    solver.difficulty_label(score),
                    label,
                )

    def test_perceived_difficulty_does_not_promote_the_label(self):
        chain = [{
            "technique": "Hidden Single (Box)",
            "technical_difficulty": 1.2,
            "frontier_move_count": 1,
        } for _ in range(50)]

        grading = solver.grade_difficulty(chain, "solved")

        self.assertEqual(
            grading["technical_difficulty_label"],
            "Molto facile",
        )
        self.assertGreater(
            grading["perceived_difficulty"],
            grading["technical_difficulty"],
        )
        self.assertGreaterEqual(grading["perceived_difficulty"], 1.0)

    def test_perceived_scarcity_uses_distinct_outcomes(self):
        chain = [{
            "technique": "Direct Hidden Pair",
            "technical_difficulty": 2.0,
            "frontier_move_count": 1,
        }]

        grading = solver.grade_difficulty(chain, "solved")

        self.assertAlmostEqual(
            grading["perceived_difficulty"],
            2.0 + np.log10(2.0),
            places=2,
        )

    def test_hodoku_mapping_separates_fish_from_pairs(self):
        pair = techniques.technique_metadata("Naked Pair")
        x_wing = techniques.technique_metadata("X-Wing")
        skyscraper = techniques.technique_metadata("Skyscraper")

        self.assertEqual(pair["resolution_load"], 60)
        self.assertEqual(pair["resolution_load_level"], "Medium")
        self.assertEqual(x_wing["resolution_load"], 140)
        self.assertEqual(x_wing["resolution_load_level"], "Hard")
        self.assertEqual(skyscraper["resolution_load"], 130)
        self.assertEqual(skyscraper["resolution_load_level"], "Hard")

    def test_label_is_controlled_only_by_the_maximum_se_rating(self):
        def grading_for(technique):
            return solver.grade_difficulty([{
                "technique": technique,
                "technical_difficulty": techniques.TECHNIQUE_DIFFICULTY[
                    technique
                ],
                "frontier_move_count": 1,
            }], "solved")

        self.assertEqual(
            grading_for("Naked Pair")["technical_difficulty_label"],
            solver.difficulty_label(3.0),
        )
        self.assertEqual(
            grading_for("X-Wing")["technical_difficulty_label"],
            solver.difficulty_label(3.2),
        )
        self.assertEqual(
            grading_for("Skyscraper")["technical_difficulty_label"],
            solver.difficulty_label(6.6),
        )

    def test_hodoku_score_uses_sum_and_hardest_step_level(self):
        chain = [{
            "technique": "Hidden Single (Box)",
            "technical_difficulty": 1.2,
            "frontier_move_count": 2,
        } for _ in range(50)]
        chain.append({
            "technique": "X-Wing",
            "technical_difficulty": 3.2,
            "frontier_move_count": 1,
        })

        grading = solver.grade_difficulty(chain, "solved")

        self.assertEqual(grading["resolution_load"], 840)
        self.assertEqual(grading["resolution_load_level"], "Hard")
        self.assertEqual(grading["technical_difficulty_label"], "Medio")

    def test_perceived_difficulty_stays_on_an_se_like_scale(self):
        easy = solver.grade_difficulty([{
            "technique": "Last Value",
            "technical_difficulty": 1.0,
            "frontier_move_count": 4,
        }], "solved")
        hard = solver.grade_difficulty([{
            "technique": "Nested Forcing Chain",
            "technical_difficulty": 9.5,
            "frontier_move_count": 1,
        }], "solved")

        self.assertGreater(
            hard["perceived_difficulty"],
            easy["perceived_difficulty"],
        )
        self.assertEqual(easy["perceived_difficulty"], 1.0)
        self.assertLess(hard["perceived_difficulty"], 10.0)
        self.assertGreater(hard["perceived_difficulty"], 9.0)


class StructuralCatalogAlignmentTests(unittest.TestCase):
    """P14.1 verifica identità e famiglie, non la taratura numerica."""

    def test_generated_rating_view_is_derived_from_catalog(self):
        self.assertEqual(
            techniques.TECHNIQUE_DIFFICULTY,
            {
                definition.canonical_name: definition.base_difficulty
                for definition in technique_catalog.TECHNIQUE_DEFINITIONS
            },
        )

    def test_direct_moves_use_taxonomy_ids_and_semantic_engine(self):
        cases = (
            (
                techniques.naked_single,
                synthetic_state({(0, 0): {7}}),
                "single.naked",
            ),
            (
                lambda state: techniques.direct_hidden_subset(state, 2),
                synthetic_state({
                    (0, 0): {1, 2, 9},
                    (0, 1): {1, 2, 8},
                    (0, 2): {3, 9},
                    (0, 3): {3, 4},
                    (0, 4): {4, 5},
                }),
                "direct.hidden_pair",
            ),
        )
        for detector, state, technique_id in cases:
            with self.subTest(technique_id=technique_id):
                moves = detector(state)
                move = next(
                    item for item in moves
                    if item["technique_id"] == technique_id
                )
                definition = technique_catalog.technique_definition(
                    technique_id
                )
                self.assertEqual(move["technique"], definition.canonical_name)
                self.assertEqual(
                    move["inference_engine"],
                    definition.inference_engine,
                )


class LogicEngineTests(unittest.TestCase):
    def test_collection_caps_each_specific_technique(self):
        moves = [{
            "technique_id": "se.forcing_chain",
            "technique": "Forcing Chain",
            "family": "Catene forzanti",
            "difficulty": 7.0,
            "placements": [],
            "eliminations": [(index // 9, index % 9, 1)],
        } for index in range(20)]

        definition = technique_catalog.technique_definition(
            "se.forcing_chain"
        )
        runner = technique_registry.TechniqueRunner(
            detector_id=definition.detector_id,
            technique_ids=(definition.id,),
            function=lambda state: moves,
            engine_type=definition.engine_type,
            fallback_tier=definition.fallback_tier,
            minimum_difficulty=definition.base_difficulty,
            priority=definition.priority,
        )

        with (
            mock.patch.object(
                technique_registry,
                "ORDINARY_RUNNERS",
                (runner,),
            ),
            mock.patch.object(
                technique_registry,
                "NESTED_RUNNERS",
                (),
            ),
        ):
            collected, metadata = solver.collect_moves_for_analysis(
                object(),
                mode="deep",
            )

        self.assertEqual(
            len(collected),
            solver.MAX_LOGIC_ENGINE_MOVES_PER_TECHNIQUE,
        )
        self.assertEqual(metadata["capped_techniques"], ["Forcing Chain"])

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
            "Complete Forcing Tree",
        }
        registered = {
            technique_catalog.technique_definition(
                technique_id
            ).canonical_name
            for runner in technique_registry.TECHNIQUE_RUNNERS
            if runner.engine_type != "local"
            for technique_id in runner.technique_ids
        }
        self.assertTrue(expected <= set(techniques.TECHNIQUE_DIFFICULTY))
        self.assertTrue(expected <= registered)

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
            and move["technique_id"] == "sdp.empty_rectangle"
            for move in moves
        ))

    def test_generic_proof_labels_do_not_imply_a_specific_structure(self):
        state = synthetic_state({(0, 0): {1, 2}})
        six_literal_chain = [{
            "row": 0,
            "column": index % 2,
            "value": 1,
            "state": "on" if index % 2 == 0 else "off",
        } for index in range(6)]
        cases = [
            ("Forcing X-Chain", "forcing-chain", [six_literal_chain]),
            ("Forcing Chain", "forcing-chain", []),
            ("Bidirectional Cycle", "bidirectional-cycle", []),
        ]
        for parent, kind, chains in cases:
            with self.subTest(parent=parent, kind=kind):
                self.assertIsNone(
                    techniques._specific_logic_technique(
                        state,
                        parent,
                        {"logic": {"kind": kind, "chains": chains}},
                    ),
                )

        dynamic_cases = [
            ("Dynamic Forcing Chain", "dynamic-contradiction", "Dynamic Contradiction Forcing Chain"),
            ("Dynamic Forcing Chain Plus", "dynamic-cell-reduction", "Dynamic Cell Forcing Chain Plus"),
        ]
        for parent, kind, expected in dynamic_cases:
            with self.subTest(parent=parent, kind=kind):
                self.assertEqual(
                    techniques._specific_logic_technique(
                        state,
                        parent,
                        {"logic": {"kind": kind, "chains": []}},
                    ),
                    expected,
                )

        self.assertIsNone(
            techniques._specific_logic_technique(
                state,
                "Nested Forcing Chain",
                {"logic": {
                    "kind": "dynamic-region-reduction",
                    "chains": [],
                }},
            ),
        )

    def test_forcing_x_chain_rejects_unproven_three_node_near_miss(self):
        state = synthetic_state({
            (0, 0): {1},
            (0, 1): {1},
            (1, 1): {1},
        })
        moves = techniques.forcing_x_chain(state)
        self.assertEqual(moves, [])

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
            side_effect=lambda current_state, technique: (
                [deduction]
                if technique == "Dynamic Forcing Chain Plus"
                else []
            ),
        ) as finder:
            moves = techniques.dynamic_forcing_chain_plus(state)
        self.assertIn(
            mock.call(state, "Dynamic Forcing Chain Plus"),
            finder.call_args_list,
        )
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]["technique"], "Dynamic Forcing Chain Plus")
        self.assertEqual(moves[0]["technique_id"], "forcing.plus")
        self.assertEqual(moves[0]["placements"], [])
        self.assertEqual(moves[0]["eliminations"], [(0, 0, 7)])
        self.assertTrue(
            {"primary", "secondary"} <= set(moves[0]["highlight"])
        )

    def test_solver_records_the_complete_move_inventory(self):
        grid = SOLVED_GRID.copy()
        grid[0, 0] = 0
        moves = [{
            "technique_id": "single.last_value",
            "technique": "Last Value",
            "family": "Inserimenti diretti",
            "difficulty": 1.0,
            "description": "mossa scelta",
            "placements": [(0, 0, 5)],
            "eliminations": [],
            "highlight": {"primary": [(0, 0)], "secondary": [(0, 0)]},
        }, {
            "technique_id": "se.forcing_chain",
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
            "collect_moves_for_analysis",
            return_value=(moves, {
                "mode": "deep",
                "complete_inventory": True,
                "inventory_censored": False,
                "nested_fallback_used": False,
                "nested_fallback_attempted": False,
                "complete_tree_fallback_used": False,
                "complete_tree_fallback_attempted": False,
                "fallback_tier_used": 0,
                "fallback_stage": "ordinary",
                "fallback_reason": None,
            }),
        ) as collect_moves:
            _, chain, status = solver.solve_and_log(
                grid,
                analysis_mode="deep",
            )
        collect_moves.assert_called_once()
        self.assertEqual(
            collect_moves.call_args.kwargs["mode"],
            "deep",
        )
        self.assertEqual(status, "solved")
        self.assertEqual(chain[0]["available_move_count"], 2)
        self.assertEqual(chain[0]["frontier_move_count"], 1)
        self.assertEqual(chain[0]["available_by_technique"], {
            "Last Value": 1,
            "Forcing Chain": 1,
        })
        self.assertEqual(chain[0]["frontier_by_technique"], {
            "Last Value": 1,
        })
        self.assertNotIn("difficulty", chain[0])


if __name__ == "__main__":
    unittest.main()
