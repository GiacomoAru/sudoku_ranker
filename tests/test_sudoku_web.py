import json
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from sudoku_app.archive import repository as archive
from sudoku_app.web.app import create_app


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
            "profile",
        )
        self.assertEqual(
            response.json()["default_profile_difficulty_window"],
            3.0,
        )
        self.assertEqual(
            response.json()["photo_recognition_version"],
            "opencv-hog-synthetic-v2",
        )
        self.assertEqual(response.json()["max_photo_size_mb"], 12)
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
        self.assertIn("Sudoku Logic Lab", response.text)
        self.assertIn("HoDoKu stimato", response.text)
        self.assertIn("<dt>Perceived</dt>", response.text)
        self.assertNotIn("Perceived 1–10", response.text)
        self.assertIn('inputmode="numeric"', response.text)
        self.assertIn('class="metric-help"', response.text)
        self.assertIn("Riconosci da una foto", response.text)
        self.assertIn("/static/app.js", response.text)

        javascript = self.client.get("/static/app.js")
        self.assertEqual(javascript.status_code, 200)
        self.assertIn('"Chiudi"', javascript.text)
        self.assertIn(
            'addEventListener("toggle", updateJsonSummaryAction)',
            javascript.text,
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
        self.assertEqual(payload["name"], "rivista_sfida_0")
        self.assertEqual(analysis["analysis_mode"], "profile")
        self.assertEqual(analysis["profile_difficulty_window"], 3.0)
        self.assertIn(analysis["status"], {"solved", "stuck"})
        self.assertIn("grading", analysis)
        self.assertIn("chain", analysis)
        self.assertIn("hodoku_score", analysis["grading"])
        self.assertIn("hodoku_level", analysis["grading"])
        self.assertEqual(
            analysis["grading"]["perceived_scale"],
            "1-10",
        )
        self.assertTrue(
            1.0
            <= analysis["grading"]["perceived_difficulty"]
            <= 10.0
        )
        self.assertIn("hodoku_score", analysis["chain"][0])
        self.assertIn("hodoku_level", analysis["chain"][0])
        self.assertTrue(
            (self.online_root / "puzzles" / f"{payload['puzzle_id']}.json")
            .exists()
        )
        self.assertTrue(
            (
                self.online_root
                / "analyses"
                / payload["puzzle_id"]
                / "analysis_profile_3.json"
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
                "source": "web",
                "provenience": "rivista",
                "tag": "luglio_2026",
                "difficulty": "sfida",
                "index": 0,
            },
        )

        analysis_path = (
            self.online_root
            / "analyses"
            / payload["puzzle_id"]
            / "analysis_profile_3.json"
        )
        stored_analysis = json.loads(
            analysis_path.read_text(encoding="utf-8")
        )
        stored_move = stored_analysis["analysis"]["chain"][0]
        self.assertEqual(stored_analysis["schema_version"], 3)
        self.assertIsInstance(
            stored_analysis["analysis"]["original"],
            str,
        )
        self.assertNotIn("applicable_by_technique", stored_move)
        self.assertIn(
            "applicable_by_technique",
            archive.load_analysis(payload["puzzle_id"])["chain"][0],
        )

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
