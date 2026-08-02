import copy
import unittest

import numpy as np

from sudoku_app.core import logic_engine
from sudoku_app.core import proof
from sudoku_app.core import technique_classification
from sudoku_app.core import techniques
from sudoku_app.core.data_structure import SudokuState


def synthetic_state(entries):
    state = SudokuState(np.zeros((9, 9), dtype=int))
    state.candidates = [[set() for _ in range(9)] for _ in range(9)]
    for (row, column), values in entries.items():
        state.candidates[row][column] = set(values)
    return state


class AICEngineTests(unittest.TestCase):
    def setUp(self):
        logic_engine.clear_logic_cache()

    def test_graph_consolidates_every_house_support(self):
        state = synthetic_state({
            (0, 0): {1},
            (0, 1): {1},
        })
        graph = logic_engine.static_implication_graph(state)
        edge = graph.edge(
            (0, 0, 1, False),
            (0, 1, 1, True),
            "x",
        )

        self.assertIsNotNone(edge)
        self.assertEqual(edge.support_candidates, ((0, 0, 1), (0, 1, 1)))
        self.assertEqual(edge.support_house_ids, (0, 18))

    def test_edge_support_is_authoritative_and_chain_links_are_derived(self):
        state = synthetic_state({
            (0, 8): {1},
            (0, 4): {1},
            (3, 4): {1},
            (3, 7): {1},
            (1, 7): {1},
        })
        deduction = logic_engine.find_logic_deductions(
            state, "Forcing X-Chain"
        )[0]
        dag = proof.ProofDAG.from_dict(deduction["logic"]["proof_dag"])

        self.assertTrue(dag.edge_supports)
        self.assertEqual(
            dag.derived_chain_links(),
            deduction["logic"]["chain_links"],
        )
        for link in dag.derived_chain_links()[0]:
            self.assertTrue(link["support_candidates"])
            self.assertTrue(link["support_house_ids"])

        restored = proof.ProofDAG.from_dict(dag.to_dict())
        self.assertEqual(restored.signature(), dag.signature())

    def test_x_chain_is_classified_from_one_digit_endpoints(self):
        state = synthetic_state({
            cell: {1}
            for cell in (
                (0, 0), (0, 4), (3, 4), (3, 7),
                (6, 7), (6, 2), (1, 2),
            )
        })
        moves = techniques.forcing_x_chain(state)

        self.assertTrue(any(move["technique"] == "X-Chain" for move in moves))
        self.assertTrue(all(
            len({
                literal["value"]
                for chain in move["logic"]["chains"]
                for literal in chain
            }) == 1
            for move in moves
        ))

    def test_aic_type_1_uses_same_digit_endpoints(self):
        state = synthetic_state({
            (0, 0): {1, 2},
            (0, 3): {2},
            (3, 3): {1, 2},
            (3, 7): {1},
            (0, 7): {1},
        })
        move = next(
            move for move in techniques.aic(state)
            if move["technique"] == "AIC Type 1"
            and move["eliminations"] == [(0, 7, 1)]
        )

        self.assertEqual(move["technique_id"], "chain.aic.type1")
        central = move["logic"]["chains"][0][1:-1]
        self.assertEqual(central[0]["value"], central[-1]["value"])
        self.assertGreater(len({item["value"] for item in central}), 1)

    def test_aic_type_2_uses_different_digit_endpoints(self):
        state = synthetic_state({
            (0, 0): {1},
            (0, 4): {1, 2},
            (3, 4): {2},
            (3, 7): {2},
            (0, 7): {1, 2},
            (0, 8): {2, 5, 6},
        })
        move = next(
            move for move in techniques.aic(state)
            if move["technique"] == "AIC Type 2"
        )

        self.assertEqual(move["technique_id"], "chain.aic.type2")
        self.assertEqual(len(move["logic"]["chains"]), 1)
        self.assertEqual(
            tuple(move["logic"]["chains"][0][0][field] for field in (
                "row", "column", "value",
            )),
            move["eliminations"][0],
        )
        central = move["logic"]["chains"][0][1:-1]
        self.assertNotEqual(central[0]["value"], central[-1]["value"])

        broken = copy.deepcopy(move)
        del broken["logic"]["chain_links"][0][0]["support_candidates"]
        self.assertIsNone(
            technique_classification.classify_logic_technique(
                state, "AIC", broken
            )
        )

    def test_discontinuous_and_continuous_loops_have_distinct_conclusions(self):
        discontinuous_state = synthetic_state({
            (0, 0): {1},
            (0, 4): {1, 2},
            (3, 4): {2},
            (3, 7): {2},
            (0, 7): {1, 2},
            (0, 8): {2, 5, 6},
        })
        dnl = next(
            move for move in techniques.forcing_chain(discontinuous_state)
            if move["eliminations"] == [(0, 0, 1)]
        )
        self.assertEqual(dnl["technique"], "Discontinuous Nice Loop")
        self.assertEqual(dnl["technique_id"], "loop.dnl")

        continuous_state = synthetic_state({
            (0, 0): {1, 2},
            (0, 3): {1, 2},
            (3, 3): {2},
            (3, 0): {2},
            (0, 6): {1},
        })
        cnl = techniques.bidirectional_cycle(continuous_state)[0]
        self.assertEqual(cnl["technique"], "Continuous Nice Loop")
        self.assertEqual(cnl["eliminations"], [(0, 6, 1)])
        weak_support_houses = {
            house_id
            for link in cnl["logic"]["chain_links"][0]
            if link["strength"] == "weak"
            for house_id in link["support_house_ids"]
        }
        self.assertIn(0, weak_support_houses)


if __name__ == "__main__":
    unittest.main()
