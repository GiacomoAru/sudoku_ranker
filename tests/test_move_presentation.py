import io
import unittest

import numpy as np

from sudoku_app.archive import repository as archive
from sudoku_app.core import move_presentation
from sudoku_app.core import proof_schema
from sudoku_app.core import solver
from sudoku_app.core import techniques
from sudoku_app.core.data_structure import SudokuState


class CandidateEvidenceTests(unittest.TestCase):
    def test_move_exposes_structured_explanation_and_candidate_roles(self):
        state = SudokuState(np.zeros((9, 9), dtype=int))
        state.candidates[0][0] = {2, 5}

        move = techniques._elim_move(
            "Naked Pair",
            "Subset",
            2.6,
            "I due candidati sono confinati nelle celle del pattern.",
            [(0, 0, 5)],
            [(0, 0), (0, 1)],
            state,
        )

        self.assertEqual(
            move["visual_evidence"]["schema_version"],
            move_presentation.VISUAL_EVIDENCE_SCHEMA_VERSION,
        )
        candidates = {
            (item["row"], item["column"], item["value"]): set(item["roles"])
            for item in move["visual_evidence"]["candidates"]
        }
        self.assertIn("support", candidates[(0, 0, 2)])
        self.assertEqual(
            {"support", "target", "elimination"},
            candidates[(0, 0, 5)],
        )
        self.assertEqual(
            ["pattern", "reasoning", "conclusion"],
            [section["kind"] for section in move["explanation"]["sections"]],
        )
        self.assertEqual(
            move["description"],
            move_presentation.render_explanation(move["explanation"]),
        )
        self.assertEqual(move["highlight"]["effect"], [(0, 0)])
        self.assertEqual(move["highlight"]["implication"], [(0, 1)])

    def test_proof_dag_candidates_and_links_are_derived(self):
        logic = proof_schema.normalize_proof({
            "kind": "synthetic-chain",
            "assumptions": [{
                "row": 0, "column": 0, "value": 1, "state": "on",
            }],
            "chains": [[
                {"row": 0, "column": 0, "value": 1, "state": "on"},
                {"row": 0, "column": 1, "value": 1, "state": "off"},
            ]],
        }, eliminations=[(0, 1, 1)])

        evidence = move_presentation.build_visual_evidence(
            [(0, 0), (0, 1)],
            (),
            [(0, 1, 1)],
            logic=logic,
        )

        records = {
            (item["row"], item["column"], item["value"]): item
            for item in evidence["candidates"]
        }
        self.assertIn("assumption", records[(0, 0, 1)]["roles"])
        self.assertIn("elimination", records[(0, 1, 1)]["roles"])
        self.assertEqual(len(evidence["links"]), 1)
        self.assertEqual(evidence["links"][0]["strength"], "weak")
        self.assertEqual(evidence["links"][0]["relation"], "implication")
        self.assertEqual(evidence["links"][0]["direction"], "forward")

    def test_equivalence_is_only_preserved_when_explicit(self):
        evidence = move_presentation.build_visual_evidence(
            (),
            (),
            [(0, 1, 1)],
            explicit={
                "links": [{
                    "source": {
                        "row": 0, "column": 0, "value": 1, "state": "on",
                    },
                    "target": {
                        "row": 0, "column": 1, "value": 1, "state": "off",
                    },
                    "relation": "equivalence",
                    "strength": "strong",
                    "reason": "prova in entrambi i versi",
                }],
            },
        )

        self.assertEqual(evidence["links"][0]["relation"], "equivalence")
        self.assertEqual(evidence["links"][0]["direction"], "bidirectional")


class CandidateGridTests(unittest.TestCase):
    def test_candidate_grid_renders_values_pencil_marks_and_evidence(self):
        grid = np.zeros((9, 9), dtype=int)
        grid[0, 0] = 5
        candidates = [[set() for _ in range(9)] for _ in range(9)]
        candidates[0][1] = {1, 5, 9}
        evidence = {
            "candidates": [{
                "row": 0,
                "column": 1,
                "value": 5,
                "roles": ["elimination", "target"],
            }],
        }

        rendered = move_presentation.format_candidate_grid(
            grid,
            candidates,
            visual_evidence=evidence,
        )

        self.assertIn(" 5 ", rendered)
        self.assertIn("R1C2#5: elimination, target", rendered)
        self.assertEqual(rendered.count("+-----------+-----------+-----------+"), 4)
        self.assertEqual(len(rendered.splitlines()), 33)

        output = io.StringIO()
        returned = move_presentation.print_candidate_grid(
            grid, candidates, visual_evidence=evidence, file=output
        )
        self.assertEqual(output.getvalue(), returned + "\n")


class CandidateSnapshotTests(unittest.TestCase):
    def test_solver_records_candidates_before_and_after_each_move(self):
        solved = (
            "534678912672195348198342567859761423426853791"
            "713924856961537284287419635345286179"
        )
        state, chain, status = solver.solve_and_log("0" + solved[1:])

        self.assertEqual(status, "solved")
        self.assertTrue(state.is_solved())
        self.assertEqual(chain[0]["candidates_before"][0][0], [5])
        self.assertEqual(chain[0]["candidates_after"][0][0], [])
        self.assertEqual(chain[0]["grid_before"][0, 0], 0)
        self.assertEqual(chain[0]["grid_after"][0, 0], 5)
        self.assertIn("explanation", chain[0])
        self.assertIn("visual_evidence", chain[0])

    def test_archive_contract_keeps_new_presentation_fields(self):
        for field in (
            "explanation",
            "visual_evidence",
            "grid_before",
            "candidates_before",
            "candidates_after",
        ):
            self.assertIn(field, archive._STORED_MOVE_FIELDS)
        self.assertEqual(archive.ANALYSIS_VERSION, 26)
        self.assertEqual(archive.ANALYSIS_SCHEMA_VERSION, 14)


if __name__ == "__main__":
    unittest.main()
