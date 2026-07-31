from io import BytesIO
from threading import RLock

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from ..archive import repository as archive
from ..core import solver
from ..core import visualization

from .schemas import SudokuSubmission
from .photo_archive import PhotoArchive
from .photo_recognition import (
    MAX_IMAGE_BYTES,
    RECOGNITION_VERSION,
    SudokuPhotoRecognizer,
)
from .serialization import to_jsonable


class SudokuWebService:
    """
    Adattatore sottile fra FastAPI e l'archivio/solver esistenti.

    L'archivio usa configurazione di processo; il lock impedisce che richieste
    contemporanee intersechino scrittura dei JSON e rendering Matplotlib.
    """

    def __init__(self, data_dir=None):
        self._lock = RLock()
        self.archive_configuration = archive.configure_archive(
            "online",
            data_dir=data_dir,
        )
        self.photo_archive = PhotoArchive(
            self.archive_configuration["data_dir"],
        )
        self.photo_recognizer = SudokuPhotoRecognizer()

    def _submission_metadata(self, submission: SudokuSubmission):
        """Costruisce i metadati da salvare senza perdere quelli del client."""
        metadata = dict(submission.metadata or {})

        # Questi sono dati tecnici dell'endpoint web, non la fonte editoriale.
        metadata["entry_channel"] = "web"

        # input_method e photo_id sono determinati dal campo top-level validato.
        # Non ci fidiamo di eventuali valori omonimi dentro metadata.
        metadata.pop("photo_id", None)
        metadata["input_method"] = "manual"

        if submission.photo_id:
            try:
                self.photo_archive.load(submission.photo_id)
            except KeyError as error:
                raise ValueError(
                    "La foto collegata non esiste nell'archivio web."
                ) from error

            metadata["input_method"] = "photo"
            metadata["photo_id"] = submission.photo_id

        return metadata

    def analyse(self, submission: SudokuSubmission):
        grid = archive.validate_unique_sudoku(submission.grid)
        metadata = self._submission_metadata(submission)

        with self._lock:
            puzzle = archive.save_with_standard_nomenclature(
                grid,
                provenience=submission.provenience,
                tag=submission.tag,
                difficulty=submission.difficulty,
                metadata=metadata,
                name=submission.name,
            )

            if submission.photo_id:
                self.photo_archive.confirm(
                    submission.photo_id,
                    submission.grid,
                    puzzle_id=puzzle["id"],
                )

            analysis = archive.analyse_puzzle_cached(
                puzzle["id"],
                force=submission.force,
                analysis_mode=submission.analysis_mode,
                profile_difficulty_window=(
                    submission.profile_difficulty_window
                ),
            )
            puzzle = archive.load_sudoku(puzzle["id"])

        return puzzle, analysis

    def recognise_photo(self, image_bytes, filename, content_type):
        upload = self.photo_archive.save_upload(
            image_bytes,
            filename=filename,
            content_type=content_type,
        )
        photo_id = upload["photo_id"]

        try:
            recognition = self.photo_recognizer.recognise(image_bytes)
        except Exception as error:
            self.photo_archive.save_failure(
                photo_id,
                str(error),
                algorithm_version=RECOGNITION_VERSION,
            )
            setattr(error, "photo_id", photo_id)
            raise

        rectified_png = recognition.pop("rectified_png")
        self.photo_archive.save_recognition(
            photo_id,
            recognition,
            rectified_png,
        )

        return {
            "photo_id": photo_id,
            **recognition,
            "original_url": (
                f"/api/v1/photos/{photo_id}/original"
            ),
            "rectified_url": (
                f"/api/v1/photos/{photo_id}/rectified"
            ),
        }

    def render_plot(
        self,
        puzzle_id,
        plot_name,
        analysis_mode,
        profile_difficulty_window,
    ):
        with self._lock:
            analysis = archive.load_analysis(
                puzzle_id,
                analysis_mode=analysis_mode,
                profile_difficulty_window=profile_difficulty_window,
            )

            if not analysis.get("chain"):
                raise ValueError(
                    "L'analisi non contiene una catena visualizzabile."
                )

            if plot_name == "difficulty-chain":
                result = visualization.plot_difficulty_chain(
                    analysis,
                    show=False,
                )
            elif plot_name == "technique-heatmap":
                result = visualization.plot_technique_activity(
                    analysis,
                    show=False,
                )
            else:
                raise KeyError(plot_name)

            figure = result[0]

            try:
                stream = BytesIO()
                figure.savefig(
                    stream,
                    format="png",
                    dpi=135,
                    bbox_inches="tight",
                    facecolor="white",
                )
                return stream.getvalue()
            finally:
                plt.close(figure)

    def health(
        self,
        worker_count=1,
        queue_capacity=16,
        exposure_mode="lan",
        authentication_enabled=False,
    ):
        return {
            "status": "ok",
            "archive_profile": self.archive_configuration["profile"],
            "exposure_mode": exposure_mode,
            "authentication_enabled": authentication_enabled,
            "default_analysis_mode": solver.DEFAULT_ANALYSIS_MODE,
            "default_profile_difficulty_window": (
                solver.DEFAULT_PROFILE_DIFFICULTY_WINDOW
            ),
            "analysis_worker_count": worker_count,
            "job_queue_capacity": queue_capacity,
            "photo_recognition_version": RECOGNITION_VERSION,
            "max_photo_size_mb": MAX_IMAGE_BYTES // (1024 * 1024),
        }

    @staticmethod
    def json_analysis(analysis):
        return to_jsonable(analysis)
