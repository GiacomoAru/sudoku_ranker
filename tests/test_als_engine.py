"""Regressioni P14 per ALS, RCC e generalized wings."""

import unittest

import numpy as np

from sudoku_app.core import proof, technique_catalog, technique_classification, techniques
from sudoku_app.core.als import ALS, enumerate_als, find_als_xz
from sudoku_app.core.als_graph import ALSGraph, restricted_common_candidates
from sudoku_app.core.als_nodes import ALSNode
from sudoku_app.core.data_structure import SudokuState, backtracking_solve
from tests.solver_corpus import load_hodoku_cases


def _candidate_state(values):
    state = SudokuState(np.zeros((9, 9), dtype=int))
    state.candidates = [[set() for _ in range(9)] for _ in range(9)]
    for cell, candidates in values.items():
        state.candidates[cell[0]][cell[1]] = set(candidates)
    return state


class ALSPrimitiveTests(unittest.TestCase):
    def test_catalog_exposes_every_p14_specific_name_on_one_detector(self):
        expected = {
            "als.xz.single",
            "als.xz.double",
            "als.xy_wing",
            "als.chain",
            "als.death_blossom",
            "chain.als_aic",
            "wing.wxyz",
            "wing.wxyz.double",
            "wing.vwxyz",
            "wing.vwxyz.double",
            "wing.uvwxyz",
            "wing.uvwxyz.double",
            "wing.tuvwxyz",
        }

        self.assertEqual(
            set(technique_catalog.TECHNIQUE_IDS_BY_DETECTOR["als"]),
            expected,
        )

    def test_als_validates_n_plus_one_and_round_trips(self):
        als = ALS(
            id=7,
            house_id=0,
            cells=frozenset({(0, 0), (0, 1)}),
            candidates=frozenset({1, 2, 3}),
        )

        self.assertEqual(ALS.from_dict(als.to_dict()), als)
        with self.assertRaises(ValueError):
            ALS(7, 0, frozenset({(0, 0), (0, 1)}), frozenset({1, 2}))

    def test_als_literal_round_trips_as_a_typed_proposition(self):
        node = ALSNode(
            als_id=7,
            house_id=0,
            cells=frozenset({(0, 0), (0, 1)}),
            digits=frozenset({1, 2, 3}),
            digit=2,
            occurrences=frozenset({(0, 1)}),
        )
        literal = (node, True)
        restored = proof.normalize_literal(proof.literal_record(literal))

        self.assertEqual(restored, literal)
        self.assertTrue(proof.is_als_literal(restored))


class ALSAICStructuralTests(unittest.TestCase):
    @staticmethod
    def _state(*, break_target_path=False):
        values = {
            (0, 0): {1, 5, 6},
            (0, 3): {1, 4},
            (0, 4): {2, 4},
            (3, 4): {2, 3},
            (3, 0): {1, 3},
        }
        if break_target_path:
            values[(0, 4)] = {2, 4, 7}
        return _candidate_state(values)

    def test_real_als_aic_mixes_candidate_and_multicell_als_nodes(self):
        move = next(
            move for move in techniques.als(self._state())
            if move["technique_id"] == "chain.als_aic"
            and move["eliminations"] == [(0, 0, 1)]
        )
        dag = proof.ProofDAG.from_dict(move["logic"]["proof_dag"])
        chain = dag.derived_chains()[0]

        self.assertTrue(any(proof.is_als_literal(item) for item in chain))
        self.assertTrue(any(
            proof.is_als_literal(item) and len(item[0].cells) >= 2
            for item in chain
        ))
        self.assertTrue(any(
            not proof.is_als_literal(item)
            and not proof.is_group_literal(item)
            for item in chain
        ))
        self.assertEqual(
            technique_classification.classify_als_aic(
                move["logic"], eliminations=move["eliminations"]
            ),
            "chain.als_aic",
        )
        self.assertEqual(proof.proof_structural_family(dag), "als")
        self.assertEqual(proof.dependency_shape(dag), "chain")
        self.assertGreaterEqual(move["logic"]["metrics"]["als_cell_count"], 2)
        self.assertEqual(
            move["als_pattern"]["search"],
            {
                "truncated": False,
                "attempt_count": move["logic"]["search"]["attempt_count"],
                "max_alses": 64,
                "max_endpoint_attempts": 256,
                "max_path_states": 2048,
            },
        )

    def test_broken_multicell_als_does_not_keep_the_target_conclusion(self):
        self.assertFalse(any(
            move["technique_id"] == "chain.als_aic"
            and (0, 0, 1) in move["eliminations"]
            for move in techniques.als(self._state(break_target_path=True))
        ))
        with self.assertRaises(ValueError):
            ALS(7, 0, frozenset({(0, 0), (1, 0)}), frozenset({1, 2, 3}))

    def test_equivalent_single_cell_als_is_deduplicated_across_houses(self):
        state = _candidate_state({(0, 0): {1, 2}})
        nodes = enumerate_als(state)

        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].cells, frozenset({(0, 0)}))
        self.assertEqual(nodes[0].house_id, 0)

    def test_rcc_requires_every_occurrence_to_see_every_other_occurrence(self):
        state = _candidate_state({
            (0, 0): {1, 2},
            (0, 1): {1, 3},
            (1, 0): {1, 4},
            (4, 4): {1, 5},
        })
        left = ALS(1, 0, frozenset({(0, 0), (0, 1)}), frozenset({1, 2, 3}))
        visible = ALS(2, 9, frozenset({(1, 0)}), frozenset({1, 4}))
        hidden = ALS(3, 4, frozenset({(4, 4)}), frozenset({1, 5}))

        self.assertEqual(
            [rcc.digit for rcc in restricted_common_candidates(left, visible, state)],
            [1],
        )
        self.assertEqual(
            restricted_common_candidates(left, hidden, state),
            (),
        )

    def test_overlap_is_valid_only_when_it_does_not_contain_the_rcc(self):
        state = _candidate_state({
            (0, 0): {1, 3},
            (0, 1): {2, 3},
            (1, 0): {2, 3},
        })
        row_als = ALS(1, 0, frozenset({(0, 0), (0, 1)}), frozenset({1, 2, 3}))
        col_als = ALS(2, 9, frozenset({(0, 0), (1, 0)}), frozenset({1, 2, 3}))

        self.assertEqual(
            [rcc.digit for rcc in restricted_common_candidates(row_als, col_als, state)],
            [2],
        )

        state.candidates[0][0].add(2)
        self.assertNotIn(
            2,
            {
                rcc.digit
                for rcc in restricted_common_candidates(row_als, col_als, state)
            },
        )


class GeneralizedWingTests(unittest.TestCase):
    @staticmethod
    def _single_linked_state(size):
        values = {
            (0, 0): {1, 2},
            (1, 0): {1, 3},
            (1, 4): {2, 3},
            (1, 5): {2, 4},
            (0, 4): {2, 9},
        }
        previous = 4
        for column in range(6, size + 3):
            values[(1, column)] = {previous, previous + 1}
            previous += 1
        return _candidate_state(values)

    def test_wxyz_is_classified_by_the_als_xz_engine_and_keeps_parent(self):
        state = _candidate_state({
            (0, 0): {1, 2},
            (1, 0): {1, 3},
            (1, 4): {2, 3},
            (1, 5): {2, 4},
            (0, 4): {2, 9},
        })
        graph = ALSGraph(state, enumerate_als(state))
        deductions = find_als_xz(graph)
        wing = next(
            deduction
            for deduction in deductions
            if deduction.technique_id == "wing.wxyz"
            and (0, 4, 2) in deduction.eliminations
        )

        self.assertEqual(wing.parent_technique_id, "als.xz.single")
        self.assertEqual(wing.to_dict()["als_parent_technique_id"], "als.xz.single")

    def test_double_linked_wxyz_comes_from_the_same_detector(self):
        state = _candidate_state({
            (0, 0): {1, 2},
            (1, 0): {1, 3},
            (1, 1): {2, 3},
            (1, 2): {1, 4},
            (2, 0): {3, 9},
        })
        graph = ALSGraph(state, enumerate_als(state))
        deductions = find_als_xz(graph)

        wing = next(
            deduction
            for deduction in deductions
            if deduction.technique_id == "wing.wxyz.double"
        )
        self.assertEqual(wing.parent_technique_id, "als.xz.double")
        self.assertGreaterEqual(len(wing.rccs), 2)

    def test_every_single_linked_generalized_size_is_an_als_classification(self):
        expected = {
            3: "wing.wxyz",
            4: "wing.vwxyz",
            5: "wing.uvwxyz",
            6: "wing.tuvwxyz",
        }
        for size, technique_id in expected.items():
            with self.subTest(size=size, technique_id=technique_id):
                state = self._single_linked_state(size)
                deductions = find_als_xz(
                    ALSGraph(state, enumerate_als(state))
                )
                self.assertTrue(any(
                    item.technique_id == technique_id
                    and item.parent_technique_id == "als.xz.single"
                    for item in deductions
                ))


class ALSTechniqueRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = {
            case.base_code: case
            for case in load_hodoku_cases()
            if case.base_code in {"0901", "0902", "0903", "0904"}
        }
        cls.moves = {
            code: techniques.als(case.build_state())
            for code, case in cls.cases.items()
        }

    def test_external_gold_conclusions_keep_the_specific_modern_names(self):
        expected_ids = {
            "0901": "als.xz.single",
            "0902": "als.xy_wing",
            "0903": "als.chain",
            "0904": "als.death_blossom",
        }
        for code, technique_id in expected_ids.items():
            case = self.cases[code]
            self.assertTrue(any(
                move["technique_id"] == technique_id
                and set(move["eliminations"]) == set(case.expected_eliminations)
                and set(move["placements"]) == set(case.expected_placements)
                for move in self.moves[code]
            ), code)

    def test_chain_rccs_are_adjacent_compatible_and_proof_keeps_als_nodes(self):
        case = self.cases["0903"]
        move = next(
            move
            for move in self.moves["0903"]
            if move["technique_id"] == "als.chain"
            and set(move["eliminations"]) == set(case.expected_eliminations)
        )
        rcc_digits = [item["digit"] for item in move["als_pattern"]["rccs"]]
        self.assertTrue(all(
            left != right for left, right in zip(rcc_digits, rcc_digits[1:])
        ))
        self.assertTrue(any(
            node["payload"].get("node_type") == "als"
            for node in move["logic"]["proof_dag"]["nodes"].values()
        ))

    def test_external_patterns_never_eliminate_the_solution_value(self):
        for code, case in self.cases.items():
            with self.subTest(code=code):
                solution = backtracking_solve(case.build_state().grid)
                self.assertIsNotNone(solution)
                self.assertFalse(any(
                    int(solution[row, column]) == digit
                    for move in self.moves[code]
                    for row, column, digit in move["eliminations"]
                ))

    def test_specific_als_family_precedes_generic_net_shape(self):
        move = next(
            move for move in self.moves["0904"]
            if move["technique_id"] == "als.death_blossom"
        )
        dag = proof.ProofDAG.from_dict(move["logic"]["proof_dag"])

        self.assertEqual(proof.dependency_shape(dag), "net")
        self.assertEqual(proof.classify_proof_structure(dag), "als")
        self.assertEqual(
            proof.classify_proof_structure(dag, forcing_context=True),
            "net",
        )


if __name__ == "__main__":
    unittest.main()
