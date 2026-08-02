"""Regressioni strutturali P15 per net, Templates e Kraken Fish."""

import unittest

import numpy as np

from sudoku_app.archive import repository as archive
from sudoku_app.core import kraken
from sudoku_app.core import logic_engine
from sudoku_app.core import proof
from sudoku_app.core import technique_catalog
from sudoku_app.core import technique_classification
from sudoku_app.core import techniques
from sudoku_app.core import templates
from sudoku_app.core.data_structure import SudokuState


def _candidate_state(values):
    state = SudokuState(np.zeros((9, 9), dtype=int))
    state.candidates = [[set() for _ in range(9)] for _ in range(9)]
    for cell, candidates in values.items():
        state.candidates[cell[0]][cell[1]] = set(candidates)
    return state


def _node(
    node_id,
    conclusion,
    parents=(),
    *,
    kind="static-implication",
    depth=None,
):
    return proof.ProofNode(
        id=node_id,
        kind=kind,
        conclusion=conclusion,
        parents=parents,
        reason="synthetic",
        depth=(0 if not parents else 1) if depth is None else depth,
        payload={"presentation": True},
    )


class DependencyShapeTests(unittest.TestCase):
    def test_a_fork_without_reconvergence_is_not_a_net(self):
        dag = proof.ProofDAG(
            nodes={
                0: _node(0, (0, 0, 1, True), kind="assumption"),
                1: _node(1, (0, 1, 1, False), (0,)),
                2: _node(2, (1, 0, 1, False), (0,)),
            },
            roots=(0,),
            conclusions=(1, 2),
        )

        self.assertFalse(proof.proof_has_fork_and_merge(dag))
        self.assertEqual(proof.dependency_shape(dag), "chain")

    def test_a_multi_parent_conclusion_is_a_net(self):
        dag = proof.ProofDAG(
            nodes={
                0: _node(0, (0, 0, 1, True), kind="assumption"),
                1: _node(1, (0, 1, 1, False), (0,)),
                2: _node(2, (1, 0, 1, False), (0,)),
                3: _node(
                    3,
                    (1, 1, 1, False),
                    (1, 2),
                    kind="common-conclusion",
                    depth=2,
                ),
            },
            roots=(0,),
            conclusions=(3,),
        )

        self.assertTrue(proof.proof_has_fork_and_merge(dag))
        self.assertEqual(proof.dependency_shape(dag), "net")
        self.assertEqual(dag.metrics()["merge_node_count"], 1)
        self.assertEqual(dag.metrics()["max_parent_count"], 2)


class TemplateTests(unittest.TestCase):
    @staticmethod
    def _single_digit_state():
        grid = np.array([
            [5, 3, 4, 6, 7, 8, 9, 1, 2],
            [6, 7, 2, 1, 9, 5, 3, 4, 8],
            [1, 9, 8, 3, 4, 2, 5, 6, 7],
            [8, 5, 9, 7, 6, 1, 4, 2, 3],
            [4, 2, 6, 8, 5, 3, 7, 9, 1],
            [7, 1, 3, 9, 2, 4, 8, 5, 6],
            [9, 6, 1, 5, 3, 7, 2, 8, 4],
            [2, 8, 7, 4, 1, 9, 6, 3, 5],
            [3, 4, 5, 2, 8, 6, 1, 7, 9],
        ], dtype=int)
        truth = (
            (0, 7), (1, 3), (2, 0),
            (3, 5), (4, 8), (5, 1),
            (6, 2), (7, 4), (8, 6),
        )
        for row, column in (*truth, (0, 3)):
            grid[row, column] = 0
        state = SudokuState(grid)
        state.candidates = [[set() for _ in range(9)] for _ in range(9)]
        for row, column in truth:
            state.candidates[row][column] = {1}
        state.candidates[0][3] = {1, 6}
        return state, truth

    def test_templates_enumerate_one_digit_not_complete_solutions(self):
        state, truth = self._single_digit_state()
        enumeration = templates.enumerate_digit_templates(state, 1)

        self.assertEqual(enumeration.template_count, 1)
        self.assertFalse(enumeration.truncated)
        self.assertEqual(
            enumeration.placements,
            frozenset((*cell, 1) for cell in truth),
        )
        self.assertEqual(enumeration.eliminations, {(0, 3, 1)})

        deduction = templates.find_templates(state)[0]
        payload = deduction.proof_payload()
        self.assertEqual(payload["kind"], "single-digit-templates")
        self.assertEqual(payload["metrics"]["template_count"], 1)
        self.assertEqual(payload["template_pattern"]["digit"], 1)
        self.assertNotIn("solution", payload["template_pattern"])

        move = techniques.templates(state)[0]
        self.assertEqual(move["technique_id"], "template.single_digit")
        self.assertEqual(move["template_digit"], 1)

    def test_a_truncated_template_search_produces_no_conclusion(self):
        state = _candidate_state({
            (row, column): {1}
            for row in range(9)
            for column in range(9)
        })

        enumeration = templates.enumerate_digit_templates(
            state,
            1,
            max_templates=1,
        )

        self.assertTrue(enumeration.truncated)
        self.assertEqual(enumeration.placements, frozenset())
        self.assertEqual(enumeration.eliminations, frozenset())


class ForcingNetTests(unittest.TestCase):
    @staticmethod
    def _cell_net_state():
        # Ogni alternativa in R1C1 spegne la stessa cifra in R2C2; la
        # bivalue residua rende quindi falso il 4 nel target.
        return _candidate_state({
            (0, 0): {1, 2, 3},
            (1, 1): {1, 2, 3, 4},
        })

    def test_cell_forcing_net_is_never_returned_as_a_chain(self):
        state = self._cell_net_state()
        deductions = logic_engine.find_logic_deductions(
            state,
            "Forcing Net",
            max_results=8,
        )

        self.assertEqual(len(deductions), 1)
        deduction = deductions[0]
        self.assertEqual(deduction["eliminations"], [(1, 1, 4)])
        self.assertEqual(
            technique_classification.classify_logic_technique(
                state,
                "Forcing Net",
                deduction,
            ),
            "Cell Forcing Net",
        )
        self.assertEqual(
            proof.dependency_shape(deduction["logic"]["proof_dag"]),
            "net",
        )
        self.assertEqual(
            deduction["logic"]["metrics"]["max_parent_count"],
            3,
        )

        self.assertEqual(techniques.cell_forcing_chain(state), [])
        moves = techniques.forcing_net(state)
        self.assertEqual([move["technique_id"] for move in moves], [
            "forcing.net.cell",
        ])

    def test_all_four_net_names_require_a_candidate_only_net(self):
        def classify(kind, assumptions, *, contradiction=False):
            nodes = {
                index: _node(
                    index,
                    literal,
                    kind="assumption",
                )
                for index, literal in enumerate(assumptions)
            }
            terminal_ids = []
            for index, assumption in enumerate(assumptions):
                node_id = len(nodes)
                nodes[node_id] = _node(
                    node_id,
                    (index + 3, index + 3, 9, False),
                    (index,),
                )
                terminal_ids.append(node_id)
            if contradiction:
                second_terminal = len(nodes)
                nodes[second_terminal] = _node(
                    second_terminal,
                    (4, 5, 8, False),
                    (0,),
                )
                terminal_ids.append(second_terminal)
                branch_id = len(nodes)
                nodes[branch_id] = _node(
                    branch_id,
                    None,
                    tuple(terminal_ids),
                    kind="contradiction",
                    depth=2,
                )
                terminal_ids = [branch_id]
            conclusion_id = len(nodes)
            nodes[conclusion_id] = _node(
                conclusion_id,
                (8, 8, 9, False),
                tuple(terminal_ids),
                kind="common-conclusion",
                depth=3 if contradiction else 2,
            )
            dag = proof.ProofDAG(
                nodes=nodes,
                roots=tuple(range(len(assumptions))),
                conclusions=(conclusion_id,),
            )
            return technique_classification.classify_forcing_net(
                proof.logic_payload(dag, kind=kind)
            )

        self.assertEqual(
            classify(
                "dynamic-contradiction",
                ((0, 0, 1, True),),
                contradiction=True,
            ),
            "forcing.net.contradiction",
        )
        self.assertEqual(
            classify(
                "dynamic-reduction",
                ((0, 0, 1, True), (0, 0, 1, False)),
            ),
            "forcing.net.double",
        )
        self.assertEqual(
            classify(
                "forcing-net-cell",
                (
                    (0, 0, 1, True),
                    (0, 0, 2, True),
                    (0, 0, 3, True),
                ),
            ),
            "forcing.net.cell",
        )
        self.assertEqual(
            classify(
                "forcing-net-region",
                (
                    (0, 0, 1, True),
                    (0, 3, 1, True),
                    (0, 6, 1, True),
                ),
            ),
            "forcing.net.region",
        )


class KrakenFishTests(unittest.TestCase):
    @staticmethod
    def _kraken_state():
        return _candidate_state({
            (0, 0): {1},
            (0, 3): {1},
            (0, 4): {1, 2},
            (0, 5): {2},
            (3, 0): {1},
            (3, 3): {1},
            (6, 5): {2},
            (6, 3): {1, 2},
        })

    def test_type1_keeps_the_fish_and_proves_every_fin(self):
        state = self._kraken_state()
        deductions = kraken.find_kraken(state, max_results=32)
        deduction = next(
            item for item in deductions
            if item.technique_id == "kraken.fish.type1"
            and item.target == (6, 3, 1)
            and item.possibilities == ((0, 4, 1),)
        )

        graph = logic_engine.static_implication_graph(state)
        for possibility, path, reasons, supports in zip(
            deduction.possibilities,
            deduction.paths,
            deduction.path_reasons,
            deduction.path_supports,
        ):
            self.assertEqual(path[0], (*possibility, True))
            self.assertEqual(path[-1], (*deduction.target, False))
            self.assertEqual(graph.chain_supports(path, reasons), supports)

        payload = deduction.proof_payload()
        self.assertEqual(proof.dependency_shape(payload["proof_dag"]), "net")
        self.assertEqual(payload["metrics"]["kraken_branch_count"], 2)
        self.assertEqual(
            payload["kraken_pattern"]["fish"],
            deduction.fish.to_dict(),
        )
        self.assertFalse(payload["proof_dag"]["nested_proofs"])

    def test_type2_proves_every_relevant_cover_possibility(self):
        state = self._kraken_state()
        deduction = next(
            item for item in kraken.find_kraken(state, max_results=32)
            if item.technique_id == "kraken.fish.type2"
        )

        cover_cells = {
            tuple(cell)
            for cell in logic_engine.UNITS[deduction.cover_set]
        }
        expected_cover = {
            candidate
            for candidate in logic_engine.static_implication_graph(
                state
            ).all_candidates
            if candidate[2] == deduction.fish.pattern.digit
            and candidate[:2] in cover_cells
        }
        self.assertNotIn(deduction.target, expected_cover)
        self.assertTrue(expected_cover <= set(deduction.possibilities))
        self.assertEqual(len(deduction.paths), len(deduction.possibilities))

    def test_type1_near_miss_without_one_aic_link_is_rejected(self):
        state = self._kraken_state()
        state.candidates[6][5] = set()

        deductions = kraken.find_kraken(state, max_results=32)

        self.assertFalse(any(
            item.technique_id == "kraken.fish.type1"
            and item.target == (6, 3, 1)
            and item.possibilities == ((0, 4, 1),)
            for item in deductions
        ))

    def test_kraken_search_is_bounded_and_catalogued_separately(self):
        state = self._kraken_state()
        deductions = kraken.find_kraken(
            state,
            max_results=32,
            max_path_attempts=1,
        )

        self.assertLessEqual(len(deductions), 1)
        for deduction in deductions:
            self.assertTrue(deduction.search_truncated)
            self.assertLessEqual(deduction.path_attempt_count, 1)
        self.assertEqual(
            technique_catalog.technique_definition(
                "kraken.fish.type1"
            ).detector_id,
            "kraken",
        )
        self.assertEqual(
            technique_catalog.technique_definition(
                "kraken.fish.type2"
            ).detector_id,
            "kraken",
        )

    def test_archive_keeps_template_and_kraken_structures(self):
        template_state, _ = TemplateTests._single_digit_state()
        template_move = techniques.templates(template_state)[0]
        kraken_move = techniques.kraken(self._kraken_state())[0]
        solved = (
            "534678912672195348198342567859761423426853791"
            "713924856961537284287419635345286179"
        )
        compact = archive._compact_analysis_for_storage({
            "name": "p15-payloads",
            "original": "0" + solved[1:],
            "solved_grid": solved,
            "unique_solution": True,
            "uniqueness_status": "verified_unique",
            "chain": [template_move, kraken_move],
            "status": "solved",
            "analysis_mode": "deep",
        })
        restored = archive._restore_analysis(compact)["chain"]

        self.assertEqual(
            restored[0]["template_pattern"],
            template_move["template_pattern"],
        )
        self.assertEqual(
            restored[1]["kraken_pattern"],
            kraken_move["kraken_pattern"],
        )
        self.assertEqual(
            restored[1]["logic"]["proof_dag"],
            kraken_move["logic"]["proof_dag"],
        )


if __name__ == "__main__":
    unittest.main()
