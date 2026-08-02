import copy
import unittest

import numpy as np

from sudoku_app.core import logic_engine
from sudoku_app.core import technique_classification
from sudoku_app.core import techniques
from sudoku_app.core.data_structure import SudokuState


def synthetic_state(entries):
    state = SudokuState(np.zeros((9, 9), dtype=int))
    state.candidates = [[set() for _ in range(9)] for _ in range(9)]
    for (row, column), values in entries.items():
        state.candidates[row][column] = set(values)
    return state


class StructuralTechniqueClassificationTests(unittest.TestCase):
    def setUp(self):
        logic_engine.clear_logic_cache()

    def test_proof_preserves_ordered_link_reason_and_strength(self):
        state = synthetic_state({
            (0, 0): {1, 2},
            (3, 0): {2, 3},
            (3, 4): {3, 4},
            (1, 4): {1, 4},
            (1, 1): {1},
        })
        deduction = logic_engine.find_logic_deductions(state, "XY-Chain")[0]
        links = deduction["logic"]["chain_links"][0]

        self.assertEqual(
            [(link["reason"], link["strength"]) for link in links],
            [
                ("peer", "weak"),
                ("y", "strong"),
                ("peer", "weak"),
                ("y", "strong"),
                ("peer", "weak"),
                ("y", "strong"),
                ("peer", "weak"),
                ("y", "strong"),
                ("peer", "weak"),
            ],
        )
        dag_nodes = deduction["logic"]["proof_dag"]["nodes"]
        self.assertEqual(
            [dag_nodes[str(index)]["reason"] for index in range(1, 10)],
            [link["reason"] for link in links],
        )

    def test_remote_pair_requires_the_same_pair_in_every_cell(self):
        remote_state = synthetic_state({
            (0, 0): {1, 2},
            (3, 0): {1, 2},
            (3, 4): {1, 2},
            (1, 4): {1, 2},
            (1, 1): {1},
        })
        remote_move = next(
            move for move in techniques.xy_chain(remote_state)
            if move["eliminations"] == [(1, 1, 1)]
        )
        self.assertEqual(remote_move["technique"], "Remote Pair")
        self.assertEqual(remote_move["technique_id"], "chain.remote_pair")
        self.assertEqual(remote_move["parent_id"], "se.bidirectional_y_cycle")
        self.assertEqual(
            remote_move["se_equivalent_parent_id"],
            "se.bidirectional_y_cycle",
        )

        xy_state = synthetic_state({
            (0, 0): {1, 2},
            (3, 0): {2, 3},
            (3, 4): {3, 4},
            (1, 4): {1, 4},
            (1, 1): {1},
        })
        xy_move = next(
            move for move in techniques.xy_chain(xy_state)
            if move["eliminations"] == [(1, 1, 1)]
        )
        self.assertEqual(xy_move["technique"], "XY-Chain")
        self.assertNotEqual(xy_move["technique_id"], "chain.remote_pair")

    def test_x_chain_specificity_precedes_turbot(self):
        skyscraper_state = synthetic_state({
            (0, 8): {1},
            (0, 4): {1},
            (3, 4): {1},
            (3, 7): {1},
            (1, 7): {1},
        })
        deduction = next(
            item
            for item in logic_engine.find_logic_deductions(
                skyscraper_state, "Forcing X-Chain"
            )
            if item["eliminations"] == [(0, 8, 1)]
        )
        self.assertEqual(
            techniques._specific_logic_technique(
                skyscraper_state, "Forcing X-Chain", deduction
            ),
            "Skyscraper",
        )

        turbot_state = synthetic_state({
            cell: {1}
            for cell in ((5, 8), (8, 2), (3, 7), (8, 4), (3, 4), (3, 2))
        })
        turbot_move = next(
            move for move in techniques.forcing_x_chain(turbot_state)
            if move["technique"] == "Turbot Fish"
        )
        self.assertEqual(turbot_move["eliminations"], [(3, 7, 1)])
        self.assertEqual(turbot_move["technique_id"], "sdp.turbot_fish")
        self.assertEqual(turbot_move["parent_id"], "se.forcing_x_chain")

    def test_six_literals_and_generic_kind_do_not_classify_a_proof(self):
        state = synthetic_state({(0, 0): {1, 2}})
        fake_chain = [
            {
                "row": 0,
                "column": index % 2,
                "value": 1,
                "state": "on" if index % 2 == 0 else "off",
            }
            for index in range(6)
        ]
        self.assertIsNone(techniques._specific_logic_technique(
            state,
            "Forcing X-Chain",
            {"eliminations": [(0, 0, 1)], "logic": {
                "kind": "forcing-chain",
                "chains": [fake_chain],
            }},
        ))
        self.assertIsNone(techniques._specific_logic_technique(
            state,
            "Forcing Chain",
            {"logic": {"kind": "forcing-chain", "chains": []}},
        ))
        self.assertIsNone(techniques._specific_logic_technique(
            state,
            "Bidirectional Cycle",
            {"logic": {"kind": "bidirectional-cycle", "chains": []}},
        ))

    def test_discontinuous_loop_requires_valid_strong_weak_transitions(self):
        state = synthetic_state({
            (0, 0): {1},
            (0, 4): {1, 2},
            (3, 4): {2},
            (3, 7): {2},
            (0, 7): {1, 2},
            (0, 8): {2, 5, 6},
        })
        move = next(
            move for move in techniques.forcing_chain(state)
            if move["eliminations"] == [(0, 0, 1)]
        )
        self.assertEqual(move["technique"], "Discontinuous Nice Loop")
        self.assertEqual(move["technique_id"], "loop.dnl")
        self.assertEqual(move["parent_id"], "se.forcing_chain")

        deduction = logic_engine.find_logic_deductions(state, "Forcing Chain")[0]
        broken = copy.deepcopy(deduction)
        broken["logic"]["chain_links"][0][0]["strength"] = "strong"
        self.assertIsNone(technique_classification.classify_logic_technique(
            state, "Forcing Chain", broken
        ))

    def test_cnl_is_a_closed_continuous_loop(self):
        state = synthetic_state({
            (0, 0): {1, 2},
            (0, 3): {1, 2},
            (3, 3): {2},
            (3, 0): {2},
            (0, 6): {1},
        })
        move = techniques.bidirectional_cycle(state)[0]
        self.assertEqual(move["technique"], "Continuous Nice Loop")
        self.assertEqual(move["technique_id"], "loop.cnl")
        self.assertEqual(move["parent_id"], "se.bidirectional_cycle")
        chain = move["logic"]["chains"][0]
        self.assertEqual(chain[0], chain[-1])
        self.assertEqual(
            [link["strength"] for link in move["logic"]["chain_links"][0]],
            ["weak", "strong", "weak", "strong", "weak", "strong"],
        )

    def test_xy_cycle_and_x_cycle_validate_their_link_types(self):
        xy_state = synthetic_state({
            (0, 0): {1, 2},
            (0, 4): {2, 3},
            (0, 7): {1, 3},
            (0, 8): {1},
        })
        xy_deduction = logic_engine.find_logic_deductions(
            xy_state, "Bidirectional Y-Cycle"
        )[0]
        self.assertEqual(
            technique_classification.classify_logic_technique(
                xy_state, "Bidirectional Y-Cycle", xy_deduction
            ),
            "XY-Cycle",
        )

        x_state = synthetic_state({
            (0, 0): {1},
            (0, 3): {1},
            (3, 3): {1},
            (3, 0): {1},
            (0, 1): {1},
        })
        x_deduction = logic_engine.find_logic_deductions(
            x_state, "Bidirectional X-Cycle"
        )[0]
        self.assertEqual(
            technique_classification.classify_logic_technique(
                x_state, "Bidirectional X-Cycle", x_deduction
            ),
            "Bidirectional X-Cycle",
        )


if __name__ == "__main__":
    unittest.main()
