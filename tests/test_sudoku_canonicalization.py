import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np

from sudoku_app.archive import repository as archive
from sudoku_app.core import canonicalization as canonical
from sudoku_app.core import solver


PUZZLE = (
    "020704050805030402040508010307040105060307040"
    "000000000000000000681493527239175864"
)


class CanonicalizationTests(unittest.TestCase):
    def test_default_archive_paths_are_anchored_to_project_root(self):
        project_root = Path(archive.__file__).resolve().parents[2]

        self.assertEqual(
            archive.ARCHIVE_PROFILE_PATHS["offline"],
            project_root / "archives" / "offline",
        )
        self.assertEqual(
            archive.ARCHIVE_PROFILE_PATHS["online"],
            project_root / "archives" / "online",
        )
        self.assertTrue(
            archive.ARCHIVE_PROFILE_PATHS["offline"].is_absolute()
        )

    def test_all_random_isomorphs_have_the_same_exact_minlex_form(self):
        expected = canonical.canonical_string(PUZZLE)

        for seed in range(5):
            randomised, transform = canonical.randomize_sudoku(
                PUZZLE,
                rng=seed,
                return_transform=True,
            )

            self.assertEqual(
                canonical.canonical_string(randomised),
                expected,
            )
            self.assertTrue(canonical.are_isomorphic(PUZZLE, randomised))
            self.assertTrue(
                np.array_equal(
                    transform.inverse().apply(randomised),
                    canonical._normalise_grid(PUZZLE),
                )
            )

    def test_canonical_transform_reproduces_the_returned_grid(self):
        details = canonical.canonicalize_details(PUZZLE)

        self.assertEqual(
            canonical.grid_to_string(details.grid),
            details.canonical_string,
        )
        self.assertTrue(
            np.array_equal(
                details.transform.apply(PUZZLE),
                details.grid,
            )
        )
        self.assertTrue(
            np.array_equal(
                canonical.canonicalize_sudoku(details.grid),
                details.grid,
            )
        )

    def test_redundant_finalists_do_not_change_the_canonical_result(self):
        solved = np.fromfunction(
            lambda row, column: (
                (row * 3 + row // 3 + column) % 9
            ) + 1,
            (9, 9),
            dtype=int,
        )
        details = canonical.canonicalize_details(solved)

        self.assertGreater(details.equivalent_minimum_count, 1)
        self.assertEqual(details.geometric_candidates, 3_359_232)
        self.assertTrue(
            np.array_equal(
                details.transform.apply(solved),
                details.grid,
            )
        )

    def test_randomisation_preserves_a_resolution_chain(self):
        randomised = canonical.randomize_sudoku(PUZZLE, rng=44)
        original_frame = canonical.canonicalize_details(PUZZLE).transform
        random_frame = canonical.canonicalize_details(randomised).transform

        _, original_chain, original_status = solver.solve_and_log(
            PUZZLE,
            analysis_mode="superficial",
        )
        _, random_chain, random_status = solver.solve_and_log(
            randomised,
            analysis_mode="superficial",
        )

        self.assertEqual(original_status, random_status)

        def canonical_step(move, transform):
            return (
                move["technique"],
                move["technical_difficulty"],
                tuple(sorted(
                    transform.map_candidate(*placement)
                    for placement in move["placements"]
                )),
                tuple(sorted(
                    transform.map_candidate(*elimination)
                    for elimination in move["eliminations"]
                )),
            )

        self.assertEqual(
            [
                canonical_step(move, original_frame)
                for move in original_chain
            ],
            [
                canonical_step(move, random_frame)
                for move in random_chain
            ],
        )


class CanonicalArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.old_paths = (
            archive.SUDOKU_DATA_DIR,
            archive.SUDOKU_PUZZLES_DIR,
            archive.SUDOKU_ANALYSES_DIR,
            archive.SUDOKU_CANONICAL_DIR,
        )
        archive.SUDOKU_DATA_DIR = root
        archive.SUDOKU_PUZZLES_DIR = root / "puzzles"
        archive.SUDOKU_ANALYSES_DIR = root / "analyses"
        archive.SUDOKU_CANONICAL_DIR = root / "canonical"
        archive._ANALYSIS_MEMORY_CACHE.clear()

    def tearDown(self):
        (
            archive.SUDOKU_DATA_DIR,
            archive.SUDOKU_PUZZLES_DIR,
            archive.SUDOKU_ANALYSES_DIR,
            archive.SUDOKU_CANONICAL_DIR,
        ) = self.old_paths
        archive._ANALYSIS_MEMORY_CACHE.clear()
        self.temporary_directory.cleanup()

    def test_isomorphic_variants_remain_distinct_but_are_linked(self):
        randomised = canonical.randomize_sudoku(PUZZLE, rng=17)
        first = archive.save_sudoku(PUZZLE, name="original")
        second = archive.save_sudoku(randomised, name="randomised")
        reloaded_first = archive.load_sudoku(first["id"])

        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["canonical_id"], second["canonical_id"])
        self.assertTrue(second["is_isomorphic_duplicate"])
        self.assertEqual(second["isomorphic_variant_count"], 2)
        self.assertEqual(reloaded_first["isomorphic_variant_count"], 2)

        canonical_class = archive.load_canonical_class(
            first["canonical_id"]
        )
        self.assertEqual(canonical_class["variant_count"], 2)
        self.assertEqual(
            {item["name"] for item in canonical_class["variants"]},
            {"original", "randomised"},
        )

    def test_archive_rejects_non_unique_puzzles_before_writing(self):
        ambiguous = "1" + ("0" * 80)

        with self.assertRaisesRegex(ValueError, "soluzione unica"):
            archive.save_sudoku(ambiguous, name="ambiguo")

        self.assertEqual(
            list(archive.SUDOKU_PUZZLES_DIR.glob("*.json")),
            [],
        )
        self.assertEqual(
            list(archive.SUDOKU_CANONICAL_DIR.glob("*.json")),
            [],
        )

    def test_analysis_rejects_non_unique_puzzles_before_logic_search(self):
        ambiguous = "1" + ("0" * 80)

        with mock.patch.object(solver, "solve_and_log") as logical_solver:
            with self.assertRaisesRegex(ValueError, "soluzione unica"):
                solver.analyse_puzzle(ambiguous)

        logical_solver.assert_not_called()

    def test_migration_reports_legacy_non_unique_records(self):
        archive._ensure_sudoku_directories()
        ambiguous = "1" + ("0" * 80)
        puzzle_id = archive.sudoku_id(ambiguous)
        archive._puzzle_path(puzzle_id).write_text(
            json.dumps({
                "schema_version": 1,
                "id": puzzle_id,
                "name": "legacy_ambiguo",
                "grid": ambiguous,
            }),
            encoding="utf-8",
        )

        report = archive.migrate_canonical_archive(
            dry_run=True,
            workers=1,
        )

        self.assertEqual(report["puzzle_count"], 1)
        self.assertEqual(report["valid_puzzle_count"], 0)
        self.assertEqual(report["invalid_puzzle_count"], 1)
        self.assertEqual(
            report["invalid_puzzles"][0]["id"],
            puzzle_id,
        )

    def test_delete_sudoku_removes_record_analyses_cache_and_empty_class(self):
        stored = archive.save_sudoku(PUZZLE, name="da_eliminare")
        analysis_directory = archive._analysis_directory(stored["id"])
        analysis_directory.mkdir(parents=True)
        (analysis_directory / "analysis_profile_3.json").write_text(
            "{}",
            encoding="utf-8",
        )
        archive._ANALYSIS_MEMORY_CACHE[
            (stored["id"], "profile_3")
        ] = {"cached": True}

        report = archive.delete_sudoku("da_eliminare")

        self.assertTrue(report["deleted"])
        self.assertEqual(report["id"], stored["id"])
        self.assertEqual(report["deleted_analysis_file_count"], 1)
        self.assertEqual(report["cleared_memory_cache_entry_count"], 1)
        self.assertTrue(report["canonical_class_deleted"])
        self.assertEqual(report["remaining_isomorphic_variant_count"], 0)
        self.assertFalse(archive._puzzle_path(stored["id"]).exists())
        self.assertFalse(analysis_directory.exists())
        self.assertFalse(
            archive._canonical_path(stored["canonical_id"]).exists()
        )
        self.assertEqual(archive.list_sudokus(), [])

        with self.assertRaises(FileNotFoundError):
            archive.load_sudoku(stored["id"])

    def test_delete_sudoku_preserves_and_reindexes_isomorphic_variants(self):
        randomised = canonical.randomize_sudoku(PUZZLE, rng=17)
        first = archive.save_sudoku(PUZZLE, name="original")
        second = archive.save_sudoku(randomised, name="randomised")

        report = archive.delete_sudoku(first["id"])
        canonical_class = archive.load_canonical_class(
            second["canonical_id"]
        )
        remaining = archive.load_sudoku(second["id"])

        self.assertFalse(report["canonical_class_deleted"])
        self.assertEqual(
            report["remaining_isomorphic_variant_ids"],
            [second["id"]],
        )
        self.assertEqual(canonical_class["variant_count"], 1)
        self.assertEqual(canonical_class["variant_ids"], [second["id"]])
        self.assertEqual(
            canonical_class["primary_puzzle_id"],
            second["id"],
        )
        self.assertFalse(remaining["is_isomorphic_duplicate"])
        self.assertIsNone(remaining["duplicate_of"])

    def test_delete_sudoku_refuses_paths_outside_the_archive(self):
        external_path = (
            Path(self.temporary_directory.name)
            / "external_record.json"
        )
        external_path.write_text(
            json.dumps({
                "id": "external_record",
                "grid": PUZZLE,
            }),
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            archive.delete_sudoku(external_path)

        self.assertTrue(external_path.exists())

    def test_legacy_migration_is_non_destructive_and_reports_duplicates(self):
        archive._ensure_sudoku_directories()
        randomised = canonical.randomize_sudoku(PUZZLE, rng=17)
        grids = (PUZZLE, canonical.grid_to_string(randomised))
        timestamp = "2026-01-02T03:04:05+00:00"

        for index, grid in enumerate(grids):
            puzzle_id = archive.sudoku_id(grid)
            payload = {
                "schema_version": 1,
                "id": puzzle_id,
                "name": f"legacy_{index}",
                "grid": grid,
                "clues": 81 - grid.count("0"),
                "metadata": {"legacy": True},
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            archive._puzzle_path(puzzle_id).write_text(
                json.dumps(payload),
                encoding="utf-8",
            )

        dry_run = archive.migrate_canonical_archive(dry_run=True)
        untouched = json.loads(
            archive._puzzle_path(archive.sudoku_id(PUZZLE)).read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(untouched["schema_version"], 1)
        self.assertEqual(dry_run["puzzle_count"], 2)
        self.assertEqual(dry_run["canonical_class_count"], 1)
        self.assertEqual(dry_run["isomorphic_duplicate_count"], 1)

        applied = archive.migrate_canonical_archive(dry_run=False)
        migrated = json.loads(
            archive._puzzle_path(archive.sudoku_id(PUZZLE)).read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(applied["updated_puzzle_file_count"], 2)
        self.assertEqual(migrated["schema_version"], 3)
        self.assertTrue(migrated["unique_solution"])
        self.assertEqual(migrated["created_at"], timestamp)
        self.assertEqual(migrated["updated_at"], timestamp)
        self.assertIn("canonical_id", migrated)
        self.assertIn("canonical_transform", migrated)


if __name__ == "__main__":
    unittest.main()
