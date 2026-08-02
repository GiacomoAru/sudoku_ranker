"""Regressioni P13 per GroupNode, grafo grouped e nomenclatura moderna."""

from copy import deepcopy
import unittest

import numpy as np

from sudoku_app.core.data_structure import SudokuState
from sudoku_app.core.group_nodes import GroupNode
from sudoku_app.core.logic_engine import StaticImplicationGraph
from sudoku_app.core import move_presentation
from sudoku_app.core import proof
from sudoku_app.core import proof_schema
from sudoku_app.core import technique_classification
from sudoku_app.core import techniques
from tests.solver_corpus import load_hodoku_cases


def _segment_group(digit=1):
    return GroupNode(
        digit=digit,
        cells=frozenset({(0, 0), (0, 1)}),
        house_ids=(0, 18),
        role="row-segment",
    )


class GroupNodeGraphTests(unittest.TestCase):
    def test_group_node_is_a_validated_or_proposition(self):
        group = _segment_group(4)

        self.assertEqual(
            group.candidates,
            ((0, 0, 4), (0, 1, 4)),
        )
        self.assertEqual(GroupNode.from_dict(group.to_dict()), group)
        with self.assertRaises(ValueError):
            GroupNode(4, frozenset({(0, 0)}), (0, 18), "row-segment")
        with self.assertRaises(ValueError):
            GroupNode(
                4,
                frozenset({(0, 0), (0, 1)}),
                (0,),
                "row-segment",
            )

    def test_group_visibility_requires_every_member_to_see_the_target(self):
        graph = StaticImplicationGraph({
            (0, 0): {1},
            (0, 1): {1},
            (0, 4): {1},  # vede l'intero gruppo attraverso la riga
            (3, 0): {1},  # vede soltanto R1C1 attraverso la colonna
        })
        group = _segment_group()

        self.assertIsNotNone(graph.grouped_edge(
            (group, True),
            (0, 4, 1, False),
            "group-weak",
        ))
        self.assertIsNone(graph.grouped_edge(
            (group, True),
            (3, 0, 1, False),
            "group-weak",
        ))

    def test_group_strong_link_is_an_exact_house_partition(self):
        graph = StaticImplicationGraph({
            (0, 0): {1},
            (0, 1): {1},
            (0, 4): {1},
        })
        group = _segment_group()
        edge = graph.grouped_edge(
            (group, False),
            (0, 4, 1, True),
            "group-strong",
        )

        self.assertIsNotNone(edge)
        self.assertEqual(
            set(edge.support_candidates),
            {(0, 0, 1), (0, 1, 1), (0, 4, 1)},
        )
        self.assertEqual(edge.support_house_ids, (0,))


class GroupedProofTests(unittest.TestCase):
    def test_group_literals_round_trip_and_remain_distinct_in_evidence(self):
        graph = StaticImplicationGraph({
            (0, 0): {1},
            (0, 1): {1},
            (0, 4): {1},
        })
        group = _segment_group()
        chain = ((group, False), (0, 4, 1, True))
        reasons = ("group-strong",)
        supports = graph.grouped_chain_supports(chain, reasons)
        dag = proof.ProofDAG.from_chains(
            assumptions=(chain[0],),
            chains=(chain,),
            chain_reasons=(reasons,),
            chain_supports=(supports,),
            proof_kind="grouped-forcing-chain",
        )
        restored = proof.ProofDAG.from_dict(dag.to_dict())

        self.assertEqual(restored.derived_chains(), [list(chain)])
        metrics = restored.metrics()
        self.assertEqual(metrics["group_node_count"], 1)
        self.assertEqual(metrics["max_group_size"], 2)
        self.assertEqual(metrics["als_node_count"], 0)
        self.assertTrue(any(
            node.kind == "grouped-implication"
            for node in restored.nodes.values()
        ))
        links = restored.derived_chain_links()
        self.assertEqual(links[0][0]["source"]["node_type"], "group")

        logic = {
            "proof_dag": restored.to_dict(),
            "chain_links": links,
        }
        evidence = move_presentation.build_visual_evidence(
            primary=(),
            placements=(),
            eliminations=(),
            logic=logic,
        )
        self.assertEqual(len(evidence["groups"]), 1)
        self.assertEqual(
            {tuple(item) for item in evidence["groups"][0]["cells"]},
            {(0, 0), (0, 1)},
        )
        member_candidates = {
            (item["row"], item["column"], item["value"])
            for item in evidence["candidates"]
            if "group" in item["roles"]
        }
        self.assertEqual(member_candidates, set(group.candidates))

    def test_candidate_only_chain_is_never_classified_as_grouped(self):
        state = SudokuState(np.zeros((9, 9), dtype=int))
        state.candidates = [[set() for _ in range(9)] for _ in range(9)]
        state.candidates[0][0] = {1, 2}
        state.candidates[0][1] = {1, 2}
        graph = StaticImplicationGraph({
            (0, 0): {1, 2},
            (0, 1): {1, 2},
        })
        chain = (
            (0, 0, 1, True),
            (0, 0, 2, False),
            (0, 1, 2, True),
            (0, 1, 1, False),
        )
        reasons = ("y", "x", "y")
        dag = proof.ProofDAG.from_chains(
            assumptions=(chain[0],),
            chains=(chain,),
            chain_reasons=(reasons,),
            chain_supports=(graph.chain_supports(chain, reasons),),
            proof_kind="grouped-forcing-chain",
            eliminations=((0, 0, 1),),
        )
        logic = proof_schema.normalize_proof({
            "kind": "grouped-forcing-chain",
            "proof_dag": dag.to_dict(),
        }, eliminations=((0, 0, 1),))
        deduction = {
            "placements": [],
            "eliminations": [(0, 0, 1)],
            "logic": logic,
        }

        self.assertIsNone(technique_classification.classify_logic_technique(
            state,
            "Grouped Chain",
            deepcopy(deduction),
        ))


class GroupedTechniqueRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cases = {
            case.base_code: case
            for case in load_hodoku_cases()
            if case.base_code in {"0709", "0710", "0711"}
        }
        cls.cases = cases
        cls.moves = {
            code: techniques.grouped_chain(case.build_state())
            for code, case in cases.items()
        }

    def test_all_four_modern_grouped_names_are_structurally_reachable(self):
        names = {
            move["technique"]
            for moves in self.moves.values()
            for move in moves
        }
        self.assertTrue({
            "Grouped X-Chain",
            "Grouped AIC",
            "Grouped Nice Loop",
            "Grouped Continuous Nice Loop",
        } <= names)

    def test_external_cnl_and_dnl_gold_conclusions_are_exact(self):
        expected_ids = {
            "0709": "loop.grouped.cnl",
            "0710": "loop.grouped.dnl",
        }
        for code, technique_id in expected_ids.items():
            case = self.cases[code]
            self.assertTrue(any(
                move["technique_id"] == technique_id
                and set(move["placements"]) == set(case.expected_placements)
                and set(move["eliminations"]) == set(
                    case.expected_eliminations
                )
                for move in self.moves[code]
            ), code)


if __name__ == "__main__":
    unittest.main()
