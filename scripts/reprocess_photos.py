"""Riesegue il riconoscimento sulle foto già presenti nell'archivio web."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sudoku_app.web.photo_archive import PhotoArchive  # noqa: E402
from sudoku_app.web.photo_recognition import (  # noqa: E402
    RECOGNITION_VERSION,
    SudokuPhotoRecognizer,
)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description=(
            "Ricalcola OCR e rettifica delle foto archiviate. Senza --apply "
            "esegue soltanto una prova non distruttiva."
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "archives" / "online",
    )
    parser.add_argument(
        "--status",
        action="append",
        choices=("failed", "recognised", "confirmed"),
        default=None,
        help=(
            "Stato da includere; ripetibile. Il default considera soltanto "
            "i fallimenti."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aggiorna metadata e rectified.png conservando lo storico.",
    )
    return parser.parse_args()


def main():
    arguments = parse_arguments()
    statuses = set(arguments.status or ["failed"])
    archive = PhotoArchive(arguments.data_dir)
    recognizer = SudokuPhotoRecognizer()
    processed = 0
    recognised = 0
    failed = 0

    for directory in sorted(archive.root.iterdir()):
        if not directory.is_dir():
            continue

        photo_id = directory.name

        try:
            metadata = archive.load(photo_id)
        except (KeyError, ValueError):
            continue

        if metadata.get("status") not in statuses:
            continue

        original = directory / metadata["original_file"]
        processed += 1

        try:
            result = recognizer.recognise(original.read_bytes())
            rectified_png = result.pop("rectified_png")
            recognised += 1
            print(
                f"{photo_id}: OK "
                f"{result['grid_detection_method']}, "
                f"{result['detected_digit_count']} cifre, "
                f"confidenza {result['mean_confidence']:.3f}"
            )

            if arguments.apply:
                archive.save_recognition(
                    photo_id,
                    result,
                    rectified_png,
                )
        except Exception as error:
            failed += 1
            print(f"{photo_id}: ERRORE {error}")

            if arguments.apply:
                archive.save_failure(
                    photo_id,
                    str(error),
                    algorithm_version=RECOGNITION_VERSION,
                )

    mode = "APPLICATO" if arguments.apply else "DRY RUN"
    print(
        f"{mode}: {processed} foto, "
        f"{recognised} riconosciute, {failed} fallite, "
        f"algoritmo {RECOGNITION_VERSION}."
    )


if __name__ == "__main__":
    main()
