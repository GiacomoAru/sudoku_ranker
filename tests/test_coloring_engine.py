import unittest

import numpy as np

from sudoku_app.archive import repository as archive
from sudoku_app.core import coloring
from sudoku_app.core import logic_engine
from sudoku_app.core import technique_catalog
from sudoku_app.core import techniques
from sudoku_app.core.data_structure import SudokuState, backtracking_solve, peers
from sudoku_app.core.proof import ProofDAG
from tests.solver_corpus import load_hodoku_cases


def hodoku_case(code):
    return next(
        item for item in load_hodoku_cases() if item.base_code == code
    )


def sees(first, second):
    return (
        first[2] == second[2]
        and first[:2] != second[:2]
        and second[:2] in peers(*first[:2])
    )


def transformed_candidate_state(state, transform, digit_map=lambda value: value):
    result = SudokuState(np.zeros((9, 9), dtype=int))
    result.candidates = [[set() for _ in range(9)] for _ in range(9)]
    for row in range(9):
        for column in range(9):
            target_row, target_column = transform(row, column)
            result.candidates[target_row][target_column] = {
                digit_map(value)
                for value in state.candidates[row][column]
            }
    return result


class ColoringGraphTests(unittest.TestCase):
    def test_catalog_exposes_all_p11_techniques_and_x_chain_parents(self):
        expected = {
            "color.simple.trap": ("Simple Colors: Color Trap", 4.0),
            "color.simple.wrap": ("Simple Colors: Color Wrap", 4.1),
            "color.multi.type1": ("Multi Colors Type 1", 4.4),
            "color.multi.type2": ("Multi Colors Type 2", 4.5),
        }
        for technique_id, (name, rating) in expected.items():
            with self.subTest(technique_id=technique_id):
                definition = technique_catalog.technique_definition(
                    technique_id
                )
                self.assertEqual(definition.canonical_name, name)
                self.assertEqual(definition.base_difficulty, rating)
                self.assertEqual(definition.detector_id, "coloring")
                self.assertEqual(definition.engine_type, "logic")
                self.assertEqual(definition.rating_kind, "pseudo_se")
                self.assertIn(
                    definition.se_equivalent_parent_id,
                    {"se.forcing_x_chain", "se.bidirectional_x_cycle"},
                )

    def test_components_reuse_the_cached_static_graph_and_are_bipartite(self):
        state = hodoku_case("0500").build_state()
        graph = logic_engine.static_implication_graph(state)
        self.assertIs(graph, logic_engine.static_implication_graph(state))

        components = coloring.conjugate_pair_components(
            state, 1, graph=graph
        )
        self.assertEqual([len(item.nodes) for item in components], [8, 2])
        self.assertEqual(
            set(graph.conjugate_pairs(1)),
            {
                link
                for component in components
                for link in component.links
            },
        )
        for component in components:
            self.assertFalse(component.colors[0] & component.colors[1])
            self.assertEqual(
                component.colors[0] | component.colors[1],
                component.nodes,
            )
            for first, second in component.links:
                self.assertNotEqual(
                    component.color_of(first),
                    component.color_of(second),
                )

    def test_transposition_and_digit_permutation_preserve_color_trap(self):
        state = hodoku_case("0500").build_state()
        original = next(
            item for item in coloring.find_simple_colors(state, 1)
            if item.pattern.technique_id == "color.simple.trap"
        )

        transpose = lambda row, column: (column, row)
        transformed = transformed_candidate_state(
            state,
            transpose,
            lambda value: 9 if value == 1 else (1 if value == 9 else value),
        )
        mapped = next(
            item for item in coloring.find_simple_colors(transformed, 9)
            if item.pattern.technique_id == "color.simple.trap"
        )
        self.assertEqual(
            mapped.eliminations,
            frozenset(
                (column, row, 9)
                for row, column, _ in original.eliminations
            ),
        )


class SimpleColorsTests(unittest.TestCase):
    def test_hodoku_color_trap_eliminates_only_uncolored_common_targets(self):
        case = hodoku_case("0500")
        deduction = next(
            item
            for item in coloring.find_simple_colors(
                case.build_state(), case.focus_candidates[0]
            )
            if item.pattern.technique_id == "color.simple.trap"
        )
        self.assertEqual(
            deduction.eliminations,
            frozenset(case.expected_eliminations),
        )
        component = deduction.pattern.components[0]
        for target in deduction.eliminations:
            self.assertNotIn(target, component.nodes)
            self.assertTrue(any(sees(target, item) for item in component.colors[0]))
            self.assertTrue(any(sees(target, item) for item in component.colors[1]))

    def test_hodoku_color_wrap_eliminates_the_entire_conflicting_color(self):
        case = hodoku_case("0501")
        deduction = next(
            item
            for item in coloring.find_simple_colors(
                case.build_state(), case.focus_candidates[0]
            )
            if item.pattern.technique_id == "color.simple.wrap"
        )
        pattern = deduction.pattern
        component = pattern.components[0]
        self.assertEqual(
            deduction.eliminations,
            frozenset(case.expected_eliminations),
        )
        self.assertEqual(
            deduction.eliminations,
            component.colors[pattern.eliminated_color],
        )
        self.assertTrue(all(sees(*link) for link in pattern.weak_links))
        self.assertTrue(
            all(
                component.color_of(first) == component.color_of(second)
                for first, second in pattern.weak_links
            )
        )
        self.assertFalse(
            component.colors[1 - pattern.eliminated_color]
            & deduction.eliminations
        )


class MultiColorsTests(unittest.TestCase):
    def test_hodoku_multi_type_1_uses_distinct_components(self):
        case = hodoku_case("0502")
        deductions = [
            item
            for item in coloring.find_multi_colors(
                case.build_state(), case.focus_candidates[0]
            )
            if item.pattern.technique_id == "color.multi.type1"
        ]
        type_two = frozenset(hodoku_case("0503").expected_eliminations)
        expected = frozenset(case.expected_eliminations) - type_two
        self.assertEqual(
            frozenset().union(*(item.eliminations for item in deductions)),
            expected,
        )
        self.assertEqual(len(deductions), 2)
        for deduction in deductions:
            first, second = deduction.pattern.components
            self.assertNotEqual(first.component_id, second.component_id)
            self.assertFalse(first.nodes & second.nodes)
            self.assertTrue(deduction.pattern.weak_links)
            self.assertTrue(all(sees(*link) for link in deduction.pattern.weak_links))
            self.assertTrue(
                deduction.eliminations.isdisjoint(first.nodes | second.nodes)
            )

    def test_hodoku_multi_type_2_eliminates_one_full_color(self):
        case = hodoku_case("0503")
        deduction = next(
            item
            for item in coloring.find_multi_colors(
                case.build_state(), case.focus_candidates[0]
            )
            if item.pattern.technique_id == "color.multi.type2"
        )
        pattern = deduction.pattern
        victim = next(
            item for item in pattern.components
            if item.component_id == pattern.eliminated_component_id
        )
        forcing = next(
            item for item in pattern.components
            if item.component_id != pattern.eliminated_component_id
        )
        self.assertEqual(
            deduction.eliminations,
            frozenset(case.expected_eliminations),
        )
        self.assertEqual(
            deduction.eliminations,
            victim.colors[pattern.eliminated_color],
        )
        victim_triggers = pattern.triggers & victim.nodes
        forcing_triggers = pattern.triggers & forcing.nodes
        self.assertGreaterEqual(len(victim_triggers), 2)
        self.assertEqual(
            {forcing.color_of(item) for item in forcing_triggers},
            {0, 1},
        )


class ColoringProofAndPersistenceTests(unittest.TestCase):
    def test_proofs_are_authoritative_alternating_x_chains(self):
        for code in ("0500", "0501", "0503"):
            case = hodoku_case(code)
            moves = [
                item for item in techniques.coloring(case.build_state())
                if item["color_digit"] in case.focus_candidates
            ]
            self.assertTrue(moves)
            for move in moves:
                with self.subTest(code=code, technique=move["technique_id"]):
                    dag = ProofDAG.from_dict(move["logic"]["proof_dag"])
                    self.assertEqual(dag.to_dict(), move["logic"]["proof_dag"])
                    self.assertEqual(
                        move["se_equivalent_parent_id"],
                        "se.forcing_x_chain",
                    )
                    for chain, links in zip(
                        move["logic"]["chains"],
                        move["logic"]["chain_links"],
                    ):
                        self.assertEqual(
                            (chain[0]["row"], chain[0]["column"], chain[0]["value"]),
                            (chain[-1]["row"], chain[-1]["column"], chain[-1]["value"]),
                        )
                        self.assertEqual(chain[0]["state"], "on")
                        self.assertEqual(chain[-1]["state"], "off")
                        self.assertEqual(
                            [item["strength"] for item in links],
                            [
                                "weak" if index % 2 == 0 else "strong"
                                for index in range(len(links))
                            ],
                        )
                        self.assertTrue(all(
                            (link["reason"], link["strength"])
                            in {("peer", "weak"), ("x", "strong")}
                            for link in links
                        ))

    def test_official_color_moves_never_remove_the_solution_value(self):
        for code in ("0500", "0501", "0502", "0503"):
            case = hodoku_case(code)
            state = case.build_state()
            solution = backtracking_solve(state.grid.copy())
            self.assertIsNotNone(solution)
            for deduction in coloring.find_all_coloring(state):
                if deduction.pattern.digit not in case.focus_candidates:
                    continue
                with self.subTest(code=code, technique=deduction.technique_name):
                    self.assertTrue(all(
                        int(solution[row, column]) != value
                        for row, column, value in deduction.eliminations
                    ))

    def test_move_and_archive_keep_the_coloring_pattern(self):
        case = hodoku_case("0500")
        move = next(
            item for item in techniques.coloring(case.build_state())
            if item["technique_id"] == "color.simple.trap"
        )
        self.assertEqual(move["color_digit"], 1)
        self.assertEqual(move["color_component_count"], 1)
        self.assertGreater(move["color_node_count"], 1)
        self.assertEqual(
            move["coloring_pattern"]["technique_id"],
            "color.simple.trap",
        )

        solved = (
            "534678912672195348198342567859761423426853791"
            "713924856961537284287419635345286179"
        )
        compact = archive._compact_analysis_for_storage({
            "name": "coloring-payload",
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
            restored["chain"][0]["coloring_pattern"],
            move["coloring_pattern"],
        )


if __name__ == "__main__":
    unittest.main()
