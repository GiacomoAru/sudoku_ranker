import json
from pathlib import Path
import tempfile
import unittest

import cv2
from fastapi.testclient import TestClient
import numpy as np

from sudoku_app.archive import repository as archive
from sudoku_app.web.app import create_app
from sudoku_app.web.photo_recognition import SudokuPhotoRecognizer
from sudoku_app.web.photo_recognition import (
    _load_image,
    _periodic_projection_bounds,
)


PUZZLE = (
    "020704050805030402040508010307040105060307040"
    "000000000000000000681493527239175864"
)


def synthetic_sudoku_photo():
    board = np.full((900, 900, 3), 255, dtype=np.uint8)

    for index in range(10):
        thickness = 7 if index % 3 == 0 else 2
        position = index * 100
        cv2.line(
            board,
            (position, 0),
            (position, 899),
            (10, 10, 10),
            thickness,
        )
        cv2.line(
            board,
            (0, position),
            (899, position),
            (10, 10, 10),
            thickness,
        )

    for index, digit in enumerate(PUZZLE):
        if digit == "0":
            continue

        row, column = divmod(index, 9)
        font = cv2.FONT_HERSHEY_DUPLEX
        scale = 2.0
        thickness = 3
        (width, height), _ = cv2.getTextSize(
            digit,
            font,
            scale,
            thickness,
        )
        origin = (
            column * 100 + (100 - width) // 2,
            row * 100 + (100 + height) // 2,
        )
        cv2.putText(
            board,
            digit,
            origin,
            font,
            scale,
            (5, 5, 5),
            thickness,
            cv2.LINE_AA,
        )

    photo = np.full((1100, 1400, 3), 225, dtype=np.uint8)
    source = np.float32([
        [0, 0],
        [899, 0],
        [899, 899],
        [0, 899],
    ])
    destination = np.float32([
        [245, 120],
        [1190, 190],
        [1110, 1020],
        [170, 920],
    ])
    transform = cv2.getPerspectiveTransform(source, destination)
    warped = cv2.warpPerspective(
        board,
        transform,
        (1400, 1100),
        borderValue=(225, 225, 225),
    )
    mask = cv2.warpPerspective(
        np.full((900, 900), 255, dtype=np.uint8),
        transform,
        (1400, 1100),
    )
    photo[mask > 0] = warped[mask > 0]
    # Simula anche il bordo di una pagina: il rilevatore deve preferire
    # la struttura periodica 9x9, non il quadrilatero più grande.
    cv2.rectangle(photo, (35, 35), (1365, 1065), (30, 30, 30), 8)
    success, encoded = cv2.imencode(
        ".jpg",
        photo,
        [cv2.IMWRITE_JPEG_QUALITY, 90],
    )
    assert success
    return encoded.tobytes()


class SudokuPhotoRecognitionTests(unittest.TestCase):
    def test_perspective_photo_is_rectified_and_recognised(self):
        result = SudokuPhotoRecognizer().recognise(
            synthetic_sudoku_photo()
        )

        self.assertEqual(result["grid"], PUZZLE)
        self.assertEqual(result["detected_digit_count"], 40)
        self.assertGreater(result["mean_confidence"], 0.9)
        self.assertEqual(result["low_confidence_indices"], [])
        self.assertTrue(result["rectified_png"].startswith(b"\x89PNG"))

    def test_periodic_projection_finds_grid_inside_page_margins(self):
        projection = np.full(900, 12, dtype=np.float32)
        expected = [47 + 94 * index for index in range(10)]

        for position in expected:
            projection[position - 2:position + 3] = 220

        projection[15:20] = 250
        projection[870:875] = 245
        bounds = _periodic_projection_bounds(projection)

        self.assertIsNotNone(bounds)
        self.assertLessEqual(abs(bounds["start"] - expected[0]), 2)
        self.assertLessEqual(abs(bounds["end"] - expected[-1]), 2)

    def test_large_photo_is_downscaled_instead_of_rejected(self):
        image = np.full((120, 8000, 3), 255, dtype=np.uint8)
        success, encoded = cv2.imencode(".jpg", image)
        self.assertTrue(success)

        decoded, source_size = _load_image(encoded.tobytes())

        self.assertEqual(source_size, {"width": 8000, "height": 120})
        self.assertEqual(decoded.shape[1], 4000)


class SudokuPhotoApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary_directory.name) / "online"
        self.old_profile = archive.ACTIVE_ARCHIVE_PROFILE
        self.old_data_dir = archive.SUDOKU_DATA_DIR
        self.app = create_app(data_dir=self.data_dir)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        archive.configure_archive(
            self.old_profile,
            data_dir=self.old_data_dir,
        )
        self.temporary_directory.cleanup()

    def test_upload_review_and_analysis_create_training_record(self):
        response = self.client.post(
            "/api/v1/photos/recognise",
            files={
                "photo": (
                    "sudoku.jpg",
                    synthetic_sudoku_photo(),
                    "image/jpeg",
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        recognition = response.json()
        self.assertEqual(recognition["grid"], PUZZLE)
        photo_id = recognition["photo_id"]
        photo_directory = self.data_dir / "photos" / photo_id
        self.assertTrue((photo_directory / "original.jpg").exists())
        self.assertTrue((photo_directory / "rectified.png").exists())
        original_response = self.client.get(
            recognition["original_url"],
        )
        rectified_response = self.client.get(
            recognition["rectified_url"],
        )
        self.assertEqual(original_response.status_code, 200)
        self.assertEqual(rectified_response.status_code, 200)
        self.assertEqual(
            rectified_response.headers["content-type"],
            "image/png",
        )

        analysis_response = self.client.post(
            "/api/v1/analyses",
            json={
                "grid": PUZZLE,
                "provenience": "foto",
                "tag": "test",
                "difficulty": "ignota",
                "photo_id": photo_id,
            },
        )

        self.assertEqual(analysis_response.status_code, 200)
        puzzle_id = analysis_response.json()["puzzle_id"]
        metadata = json.loads(
            (photo_directory / "metadata.json").read_text(
                encoding="utf-8",
            )
        )
        self.assertEqual(metadata["status"], "confirmed")
        self.assertEqual(metadata["review"]["grid"], PUZZLE)
        self.assertEqual(metadata["review"]["puzzle_id"], puzzle_id)
        self.assertEqual(len(metadata["attempts"]), 1)
        self.assertEqual(
            metadata["attempts"][0]["algorithm_version"],
            "opencv-hog-synthetic-v2",
        )
        puzzle = archive.load_sudoku(puzzle_id)
        self.assertEqual(puzzle["metadata"]["source"], "web-photo")
        self.assertEqual(puzzle["metadata"]["photo_id"], photo_id)

    def test_failed_recognition_keeps_the_original_photo(self):
        blank = np.full((600, 800, 3), 255, dtype=np.uint8)
        success, encoded = cv2.imencode(".jpg", blank)
        self.assertTrue(success)
        response = self.client.post(
            "/api/v1/photos/recognise",
            files={
                "photo": (
                    "vuota.jpg",
                    encoded.tobytes(),
                    "image/jpeg",
                ),
            },
        )

        self.assertEqual(response.status_code, 422)
        photo_id = response.json()["detail"]["photo_id"]
        photo_directory = self.data_dir / "photos" / photo_id
        metadata = json.loads(
            (photo_directory / "metadata.json").read_text(
                encoding="utf-8",
            )
        )
        self.assertEqual(metadata["status"], "failed")
        self.assertEqual(len(metadata["attempts"]), 1)
        self.assertEqual(metadata["attempts"][0]["status"], "failed")
        self.assertTrue((photo_directory / "original.jpg").exists())


if __name__ == "__main__":
    unittest.main()
