from io import BytesIO
from threading import RLock

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from ..archive import repository as archive
from ..core import data_structure
from ..core import solver
from ..core import visualization

from .schemas import SudokuSubmission
from .serialization import to_jsonable


def _validate_given_digits(grid):
    """Rifiuta duplicati già presenti in righe, colonne o box."""
    for unit in data_structure.UNITS:
        values = [
            int(grid[row, column])
            for row, column in unit
            if int(grid[row, column]) != 0
        ]

        if len(values) != len(set(values)):
            raise ValueError(
                "La griglia iniziale contiene cifre duplicate in una "
                "riga, colonna o box."
            )


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

    def analyse(self, submission: SudokuSubmission):
        grid = archive.normalise_sudoku_grid(submission.grid)
        _validate_given_digits(grid)

        with self._lock:
            puzzle = archive.save_with_standard_nomenclature(
                grid,
                provenience=submission.provenience,
                tag=submission.tag,
                difficulty=submission.difficulty,
                metadata={"source": "web"},
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

    def health(self, worker_count=1, queue_capacity=16):
        return {
            "status": "ok",
            "archive_profile": self.archive_configuration["profile"],
            "default_analysis_mode": solver.DEFAULT_ANALYSIS_MODE,
            "default_profile_difficulty_window": (
                solver.DEFAULT_PROFILE_DIFFICULTY_WINDOW
            ),
            "analysis_worker_count": worker_count,
            "job_queue_capacity": queue_capacity,
        }

    @staticmethod
    def json_analysis(analysis):
        return to_jsonable(analysis)
