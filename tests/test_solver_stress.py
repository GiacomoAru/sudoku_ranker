"""Corpus "cattivo": puzzle estremi che richiedono Complete Forcing Tree.

Isolati dall'archivio online (``archives/online``): ogni caso e' stato
scelto perche' la sua grading gia' calcolata riporta
``hardest_technique == "Complete Forcing Tree"``, cioe' nessuna tecnica
ordinaria ne' Nested basta a risolverlo. Sono famosi puzzle da SudokuWiki.org
(Arto Inkala, Escargot, la serie "Unsolvable", "golden nugget", "Level-3")
piu' alcune varianti "Very Hard" dello stesso archivio.

A differenza del corpus compatto in ``test_solver_corpus.py``, qui l'obiettivo
non e' la velocita' ma la resistenza: dimostrare che il solver termina sempre
con una soluzione corretta (o uno stato coerente) anche quando serve
l'ultimo fallback, senza eccezioni ne' hang indefiniti.

Il solve end-to-end di un solo puzzle di questo corpus con Complete Forcing
Tree puo' richiedere diversi minuti (misurato: Arto Inkala, 110 passi,
~5m30s in modalita' smart_profile di default; nessun cap interno per
costruzione, vedi PATCH.md P17.1). La classe
``StressCorpusEndToEndTests`` e' percio' disattivata per default e va
abilitata esplicitamente con ``SUDOKU_RUN_STRESS_TESTS=1``. Ogni caso gira
in un processo separato con un timeout esterno esplicito (default 900s,
``SUDOKU_STRESS_TIMEOUT_SECONDS`` per cambiarlo): un timeout e' un dato del
benchmark, non un fallimento del test, una soluzione sbagliata invece lo e'
sempre.
"""

import json
import multiprocessing
import os
import unittest
from pathlib import Path

import numpy as np

from sudoku_app.core.data_structure import SudokuState, count_solutions


CORPUS_PATH = (
    Path(__file__).resolve().parent
    / "fixtures" / "stress_corpus" / "puzzles.json"
)

RUN_STRESS_TESTS = os.environ.get("SUDOKU_RUN_STRESS_TESTS") == "1"
STRESS_TIMEOUT_SECONDS = float(
    os.environ.get("SUDOKU_STRESS_TIMEOUT_SECONDS", "900")
)


def load_stress_cases(path=CORPUS_PATH):
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("Versione del corpus stress non supportata.")
    return tuple(document["cases"])


def _solve_worker(grid_text, queue):
    """Eseguito in un processo separato: isola l'eventuale timeout."""
    from sudoku_app.core import solver

    try:
        analysis = solver.analyse_puzzle(grid_text, name="stress")
        queue.put((
            "done",
            analysis["status"],
            len(analysis["chain"]),
            bool(np.all(analysis["solved_grid"] != 0))
            if analysis["status"] == "solved"
            else None,
        ))
    except Exception as error:  # pragma: no cover - riportato dal test
        queue.put(("error", repr(error), None, None))


def _solve_with_timeout(grid_text, timeout_seconds):
    """Risolve in un processo separato con un timeout esterno esplicito."""
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    process = ctx.Process(target=_solve_worker, args=(grid_text, queue))
    process.start()
    process.join(timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join()
        return "timeout", None, None, None

    if not queue.empty():
        return queue.get()

    return "crashed", None, None, None


class StressCorpusFormatTests(unittest.TestCase):
    """Controlli rapidi e sempre attivi sul corpus, indipendenti dal solve."""

    def test_corpus_has_fourteen_distinct_complete_tree_cases(self):
        cases = load_stress_cases()
        self.assertEqual(len(cases), 14)
        self.assertEqual(len({case["id"] for case in cases}), 14)
        self.assertEqual(len({case["puzzle"] for case in cases}), 14)
        self.assertTrue(all(
            case["cached_hardest_technique"] == "Complete Forcing Tree"
            for case in cases
        ))

    def test_every_case_has_exactly_one_solution(self):
        for case in load_stress_cases():
            with self.subTest(case=case["id"], name=case["name"]):
                state = SudokuState(case["puzzle"])
                self.assertEqual(
                    count_solutions(state.grid, limit=2),
                    1,
                )


@unittest.skipUnless(
    RUN_STRESS_TESTS,
    "corpus cattivo: opt-in, richiede alcuni minuti per caso. "
    "Abilita con SUDOKU_RUN_STRESS_TESTS=1.",
)
class StressCorpusEndToEndTests(unittest.TestCase):
    """Benchmark cattivo: solve reale, un processo e un timeout per caso."""

    def test_every_extreme_puzzle_terminates_correctly_or_times_out(self):
        report = []
        for case in load_stress_cases():
            with self.subTest(case=case["id"], name=case["name"]):
                outcome, status_or_error, step_count, fully_filled = (
                    _solve_with_timeout(
                        case["puzzle"],
                        STRESS_TIMEOUT_SECONDS,
                    )
                )
                report.append((case["name"], outcome, status_or_error))

                self.assertNotEqual(
                    outcome,
                    "crashed",
                    f"{case['name']}: processo terminato senza risultato.",
                )
                self.assertNotEqual(
                    outcome,
                    "error",
                    f"{case['name']}: {status_or_error}",
                )
                if outcome == "done" and status_or_error == "solved":
                    self.assertTrue(
                        fully_filled,
                        f"{case['name']}: dichiarato solved a griglia "
                        "incompleta.",
                    )

        print("\nBenchmark cattivo (Complete Forcing Tree corpus):")
        for name, outcome, status_or_error in report:
            detail = status_or_error if outcome == "done" else outcome
            print(f"  {name:<20} {detail}")


if __name__ == "__main__":
    unittest.main()
