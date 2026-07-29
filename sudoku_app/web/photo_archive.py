"""Archivio locale delle foto ricevute e delle revisioni OCR."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from threading import RLock
from uuid import uuid4


PHOTO_SCHEMA_VERSION = 1
PHOTO_ID_PATTERN = re.compile(r"^[a-f0-9]{24}$")
CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(value):
    name = Path(value or "foto_sudoku").name
    cleaned = "".join(
        character
        for character in name
        if character.isalnum() or character in "._- "
    ).strip()
    return cleaned[:120] or "foto_sudoku"


class PhotoArchive:
    """Persistenza append-only delle immagini, separata per profilo web."""

    def __init__(self, data_dir):
        self.root = Path(data_dir) / "photos"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    @staticmethod
    def _validate_photo_id(photo_id):
        photo_id = str(photo_id)

        if not PHOTO_ID_PATTERN.fullmatch(photo_id):
            raise KeyError(photo_id)

        return photo_id

    def _directory(self, photo_id):
        return self.root / self._validate_photo_id(photo_id)

    @staticmethod
    def _write_json(path, payload):
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def _metadata_path(self, photo_id):
        return self._directory(photo_id) / "metadata.json"

    @staticmethod
    def _preserve_legacy_attempt(payload):
        attempts = payload.setdefault("attempts", [])

        if attempts or payload.get("status") == "uploaded":
            return attempts

        recognition = payload.get("recognition") or {}
        attempts.append({
            "attempted_at": payload.get("updated_at"),
            "algorithm_version": recognition.get(
                "algorithm_version",
                "legacy-unknown",
            ),
            "status": (
                "recognised"
                if recognition
                else payload.get("status", "failed")
            ),
            "grid": recognition.get("grid"),
            "detected_digit_count": recognition.get(
                "detected_digit_count",
            ),
            "mean_confidence": recognition.get("mean_confidence"),
            "error": payload.get("error"),
        })
        return attempts

    def load(self, photo_id):
        path = self._metadata_path(photo_id)

        if not path.exists():
            raise KeyError(photo_id)

        return json.loads(path.read_text(encoding="utf-8"))

    def save_upload(self, image_bytes, filename, content_type):
        photo_id = uuid4().hex[:24]
        extension = CONTENT_TYPE_EXTENSIONS.get(
            str(content_type).casefold(),
            ".img",
        )
        directory = self._directory(photo_id)

        with self._lock:
            directory.mkdir(parents=True, exist_ok=False)
            original_name = f"original{extension}"
            (directory / original_name).write_bytes(image_bytes)
            payload = {
                "schema_version": PHOTO_SCHEMA_VERSION,
                "photo_id": photo_id,
                "status": "uploaded",
                "created_at": _timestamp(),
                "updated_at": _timestamp(),
                "original_filename": _safe_filename(filename),
                "content_type": str(content_type or "application/octet-stream"),
                "size_bytes": len(image_bytes),
                "sha256": hashlib.sha256(image_bytes).hexdigest(),
                "original_file": original_name,
                "rectified_file": None,
                "recognition": None,
                "attempts": [],
                "review": None,
                "error": None,
            }
            self._write_json(self._metadata_path(photo_id), payload)

        return payload

    def save_recognition(self, photo_id, recognition, rectified_png):
        with self._lock:
            payload = self.load(photo_id)
            attempts = self._preserve_legacy_attempt(payload)
            directory = self._directory(photo_id)
            rectified_name = "rectified.png"
            (directory / rectified_name).write_bytes(rectified_png)
            attempts.append({
                "attempted_at": _timestamp(),
                "algorithm_version": recognition.get(
                    "algorithm_version",
                ),
                "status": "recognised",
                "grid": recognition.get("grid"),
                "detected_digit_count": recognition.get(
                    "detected_digit_count",
                ),
                "mean_confidence": recognition.get("mean_confidence"),
                "error": None,
            })
            payload.update({
                "status": (
                    "confirmed"
                    if payload.get("review")
                    else "recognised"
                ),
                "updated_at": _timestamp(),
                "rectified_file": rectified_name,
                "recognition": recognition,
                "error": None,
            })
            self._write_json(self._metadata_path(photo_id), payload)

        return payload

    def save_failure(
        self,
        photo_id,
        message,
        algorithm_version=None,
    ):
        with self._lock:
            payload = self.load(photo_id)
            attempts = self._preserve_legacy_attempt(payload)
            attempts.append({
                "attempted_at": _timestamp(),
                "algorithm_version": algorithm_version,
                "status": "failed",
                "grid": None,
                "detected_digit_count": None,
                "mean_confidence": None,
                "error": str(message),
            })
            payload.update({
                "status": "failed",
                "updated_at": _timestamp(),
                "error": str(message),
            })
            self._write_json(self._metadata_path(photo_id), payload)

    def confirm(self, photo_id, grid, puzzle_id=None):
        with self._lock:
            payload = self.load(photo_id)
            payload["status"] = "confirmed"
            payload["updated_at"] = _timestamp()
            payload["review"] = {
                "confirmed_at": _timestamp(),
                "grid": str(grid),
                "puzzle_id": puzzle_id,
                "changed_from_ocr": (
                    payload.get("recognition", {}).get("grid") != str(grid)
                ),
            }
            self._write_json(self._metadata_path(photo_id), payload)

        return payload

    def media_path(self, photo_id, kind):
        payload = self.load(photo_id)

        if kind == "original":
            filename = payload["original_file"]
        elif kind == "rectified":
            filename = payload.get("rectified_file")
        else:
            raise KeyError(kind)

        if not filename:
            raise FileNotFoundError(kind)

        path = self._directory(photo_id) / filename

        if not path.exists():
            raise FileNotFoundError(kind)

        return path, payload
