import json
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from sudoku_app.archive import repository as archive
from sudoku_app.core import proof_schema
from sudoku_app.core import solver
from sudoku_app.web.app import create_app
from sudoku_app.web.photo_recognition import RECOGNITION_VERSION


PUZZLE = (
    "020704050805030402040508010307040105060307040"
    "000000000000000000681493527239175864"
)


class SudokuWebTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        temporary_root = Path(self.temporary_directory.name)
        self.offline_root = temporary_root / "offline"
        self.online_root = temporary_root / "online"
        self.old_profile = archive.ACTIVE_ARCHIVE_PROFILE
        self.old_data_dir = archive.SUDOKU_DATA_DIR

        archive.configure_archive(
            "offline",
            data_dir=self.offline_root,
        )
        self.offline_puzzle = archive.save_sudoku(
            PUZZLE,
            name="solo_offline",
        )

        self.app = create_app(data_dir=self.online_root)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        archive.configure_archive(
            self.old_profile,
            data_dir=self.old_data_dir,
        )
        self.temporary_directory.cleanup()

    def test_factory_selects_a_separate_online_archive(self):
        response = self.client.get("/api/v1/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["archive_profile"], "online")
        self.assertEqual(
            response.json()["default_analysis_mode"],
            "smart_profile",
        )
        self.assertEqual(
            response.json()["default_profile_difficulty_window"],
            solver.DEFAULT_PROFILE_DIFFICULTY_WINDOW,
        )
        self.assertEqual(
            response.json()["photo_recognition_version"],
            RECOGNITION_VERSION,
        )
        self.assertEqual(response.json()["max_photo_size_mb"], 12)
        openapi = self.app.openapi()
        self.assertEqual(openapi["info"]["title"], "Sudoku Ranker")
        self.assertEqual(
            openapi["components"]["schemas"]["SudokuSubmission"]
            ["properties"]["profile_difficulty_window"]["default"],
            solver.DEFAULT_PROFILE_DIFFICULTY_WINDOW,
        )
        plot_parameters = {
            parameter["name"]: parameter
            for parameter in openapi["paths"][
                "/api/v1/analyses/{puzzle_id}/plots/{plot_name}.png"
            ]["get"]["parameters"]
        }
        self.assertEqual(
            plot_parameters["profile_difficulty_window"]["schema"][
                "default"
            ],
            solver.DEFAULT_PROFILE_DIFFICULTY_WINDOW,
        )
        self.assertTrue(
            (
                self.offline_root
                / "puzzles"
                / f"{self.offline_puzzle['id']}.json"
            ).exists()
        )
        self.assertEqual(
            list((self.online_root / "puzzles").glob("*.json")),
            [],
        )

    def test_home_page_is_served(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Sudoku Ranker", response.text)
        self.assertIn("<dt>Carico risolutivo</dt>", response.text)
        self.assertIn("<dt>Difficoltà tecnica</dt>", response.text)
        self.assertNotIn("Perceived 1–10", response.text)
        self.assertIn('inputmode="numeric"', response.text)
        self.assertIn('class="metric-help ', response.text)
        self.assertIn("Importa il Sudoku da una foto", response.text)
        self.assertIn("/static/app.js", response.text)

        javascript = self.client.get("/static/app.js")
        self.assertEqual(javascript.status_code, 200)
        self.assertIn('"Chiudi"', javascript.text)
        self.assertIn(
            'addEventListener("toggle", updateJsonSummaryAction)',
            javascript.text,
        )
        self.assertIn(
            "profile_difficulty_window: 1.5",
            javascript.text,
        )
        self.assertIn("candidate-grid", javascript.text)
        self.assertIn("renderStepExplanation", javascript.text)
        self.assertIn("renderImplicationLinks", javascript.text)
        self.assertIn("implicationPath", javascript.text)
        self.assertIn("Celle che implicano la mossa", response.text)
        self.assertIn("Celle modificate", response.text)

    def test_internet_mode_requires_authentication(self):
        protected_app = create_app(
            data_dir=self.online_root,
            exposure_mode="internet",
            access_username="telefono",
            access_password="password-test-sicura",
        )

        with TestClient(protected_app) as protected_client:
            denied = protected_client.get("/api/v1/health")
            self.assertEqual(denied.status_code, 401)
            self.assertIn(
                "Basic",
                denied.headers["www-authenticate"],
            )
            self.assertEqual(
                denied.headers["x-sudoku-ranker"],
                "1",
            )

            accepted = protected_client.get(
                "/api/v1/health",
                auth=("telefono", "password-test-sicura"),
                headers={"X-Forwarded-Proto": "https"},
            )
            self.assertEqual(accepted.status_code, 200)
            self.assertEqual(
                accepted.json()["exposure_mode"],
                "internet",
            )
            self.assertTrue(
                accepted.json()["authentication_enabled"],
            )
            self.assertIn(
                "max-age",
                accepted.headers["strict-transport-security"],
            )

    def test_internet_mode_rejects_missing_or_short_password(self):
        with self.assertRaisesRegex(ValueError, "richiede"):
            create_app(
                data_dir=self.online_root,
                exposure_mode="internet",
            )

        with self.assertRaisesRegex(ValueError, "12 caratteri"):
            create_app(
                data_dir=self.online_root,
                exposure_mode="internet",
                access_password="corta",
            )

    def test_submit_returns_json_and_both_plot_urls(self):
        response = self.client.post(
            "/api/v1/analyses",
            json={
                "grid": PUZZLE,
                "provenience": "rivista",
                "tag": "luglio_2026",
                "difficulty": "sfida",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        analysis = payload["analysis"]

        self.assertEqual(payload["archive_profile"], "online")
        self.assertEqual(
            payload["name"],
            f"sudoku_{payload['puzzle_id'][:8]}",
        )
        self.assertEqual(analysis["analysis_mode"], "smart_profile")
        self.assertEqual(
            analysis["profile_difficulty_window"],
            solver.DEFAULT_PROFILE_DIFFICULTY_WINDOW,
        )
        self.assertIn(analysis["status"], {"solved", "stuck"})
        self.assertIn("grading", analysis)
        self.assertIn("chain", analysis)
        self.assertTrue(analysis["unique_solution"])
        self.assertIn("technical_difficulty", analysis["grading"])
        self.assertIn("resolution_load", analysis["grading"])
        self.assertIn("resolution_load_label", analysis["grading"])
        self.assertGreater(
            analysis["grading"]["move_discovery_difficulty"],
            0.0,
        )
        self.assertIn("technical_difficulty", analysis["chain"][0])
        self.assertIn("resolution_load", analysis["chain"][0])
        self.assertIn("technique_id", analysis["chain"][0])
        self.assertIn("difficulty_metrics", analysis["chain"][0])
        self.assertIn("explanation", analysis["chain"][0])
        self.assertIn("visual_evidence", analysis["chain"][0])
        self.assertIn("candidates_before", analysis["chain"][0])
        self.assertIn("candidates_after", analysis["chain"][0])
        self.assertEqual(
            analysis["chain"][0]["difficulty_metrics"][
                "metrics_version"
            ],
            proof_schema.PROOF_METRICS_VERSION,
        )
        self.assertTrue(
            (self.online_root / "puzzles" / f"{payload['puzzle_id']}.json")
            .exists()
        )
        self.assertTrue(
            (
                self.online_root
                / "analyses"
                / payload["puzzle_id"]
                / "analysis_smart_profile_1p5.json"
            ).exists()
        )
        puzzle_payload = json.loads(
            (
                self.online_root
                / "puzzles"
                / f"{payload['puzzle_id']}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            puzzle_payload["metadata"],
            {
                "entry_channel": "web",
                "input_method": "manual",
                "source": "rivista",
                "source_reference": "luglio_2026",
                "stated_difficulty": "sfida",
            },
        )

        analysis_path = (
            self.online_root
            / "analyses"
            / payload["puzzle_id"]
            / "analysis_smart_profile_1p5.json"
        )
        stored_analysis = json.loads(
            analysis_path.read_text(encoding="utf-8")
        )
        stored_move = stored_analysis["analysis"]["chain"][0]
        self.assertEqual(
            stored_analysis["schema_version"],
            archive.ANALYSIS_SCHEMA_VERSION,
        )
        self.assertEqual(
            stored_analysis["analysis_version"],
            archive.ANALYSIS_VERSION,
        )
        self.assertIsInstance(
            stored_analysis["analysis"]["original"],
            str,
        )
        self.assertIn("available_by_technique", stored_move)
        self.assertIn("technique_id", stored_move)
        self.assertIn("difficulty_metrics", stored_move)
        self.assertIn("explanation", stored_move)
        self.assertIn("visual_evidence", stored_move)
        self.assertIn("candidates_after", stored_move)
        self.assertNotIn("availability", stored_move)
        archive._ANALYSIS_MEMORY_CACHE.clear()
        reloaded_move = archive.load_analysis(
            payload["puzzle_id"]
        )["chain"][0]
        self.assertEqual(
            set(analysis["chain"][0]),
            set(reloaded_move),
        )
        self.assertEqual(
            analysis["chain"][0]["difficulty_metrics"],
            reloaded_move["difficulty_metrics"],
        )
        self.assertEqual(
            analysis["chain"][0].get("logic"),
            reloaded_move.get("logic"),
        )
        self.assertNotIn("applicable_by_technique", reloaded_move)

        for plot_url in payload["plots"].values():
            plot_response = self.client.get(plot_url)
            self.assertEqual(plot_response.status_code, 200)
            self.assertEqual(
                plot_response.headers["content-type"],
                "image/png",
            )
            self.assertTrue(plot_response.content.startswith(b"\x89PNG"))

    def test_submit_rejects_conflicting_given_digits(self):
        invalid = "110000000" + ("0" * 72)
        response = self.client.post(
            "/api/v1/analyses",
            json={
                "grid": invalid,
                "provenience": "web",
                "tag": "test",
                "difficulty": "ignota",
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("duplicate", response.json()["detail"])

    def test_job_endpoint_accepts_and_completes_analysis(self):
        response = self.client.post(
            "/api/v1/jobs",
            json={
                "grid": PUZZLE,
                "provenience": "job",
                "tag": "test",
                "difficulty": "media",
            },
        )

        self.assertEqual(response.status_code, 202)
        accepted = response.json()
        self.assertIn(accepted["status"], {"queued", "running"})

        deadline = time.monotonic() + 30
        job = None

        while time.monotonic() < deadline:
            job_response = self.client.get(accepted["status_url"])
            self.assertEqual(job_response.status_code, 200)
            job = job_response.json()

            if job["status"] in {"completed", "failed"}:
                break

            time.sleep(0.05)

        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["result"]["archive_profile"], "online")
        self.assertIn("analysis", job["result"])


if __name__ == "__main__":
    unittest.main()
