import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .jobs import AnalysisJobManager, JobQueueFullError
from .schemas import (
    AnalysisEnvelope,
    HealthResponse,
    JobAccepted,
    JobStatus,
    SudokuSubmission,
)
from .service import SudokuWebService


STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"


def _plot_links(puzzle_id, submission):
    query = urlencode({
        "analysis_mode": submission.analysis_mode,
        "profile_difficulty_window": (
            submission.profile_difficulty_window
        ),
    })
    base = f"/api/v1/analyses/{puzzle_id}/plots"
    return {
        "difficulty_chain": (
            f"{base}/difficulty-chain.png?{query}"
        ),
        "technique_heatmap": (
            f"{base}/technique-heatmap.png?{query}"
        ),
    }


def _analysis_envelope(service, submission):
    puzzle, analysis = service.analyse(submission)
    plots = (
        _plot_links(puzzle["id"], submission)
        if analysis.get("chain")
        else None
    )
    return {
        "puzzle_id": puzzle["id"],
        "canonical_id": puzzle["canonical_id"],
        "name": puzzle["name"],
        "archive_profile": service.archive_configuration["profile"],
        "is_isomorphic_duplicate": puzzle.get(
            "is_isomorphic_duplicate",
            False,
        ),
        "isomorphic_variant_count": puzzle.get(
            "isomorphic_variant_count",
            1,
        ),
        "analysis": service.json_analysis(analysis),
        "plots": plots,
    }


def create_app(data_dir=None, job_queue_capacity=16):
    """
    Crea l'app LAN e seleziona l'archivio online separato.

    ``data_dir`` è usato dai test; in esecuzione può essere impostato tramite
    ``SUDOKU_WEB_DATA_DIR``. Senza override usa ``archives/online``.
    """
    configured_data_dir = (
        data_dir
        if data_dir is not None
        else os.environ.get("SUDOKU_WEB_DATA_DIR")
    )
    service = SudokuWebService(data_dir=configured_data_dir)
    job_manager = AnalysisJobManager(
        worker_count=1,
        queue_capacity=job_queue_capacity,
    )

    @asynccontextmanager
    async def lifespan(_app):
        yield
        job_manager.shutdown(wait=True)

    app = FastAPI(
        title="Sudoku Logic Lab",
        version="0.1.0",
        description=(
            "API LAN minima per salvare Sudoku e ricevere analisi logiche."
        ),
        lifespan=lifespan,
    )
    app.state.sudoku_service = service
    app.state.analysis_jobs = job_manager
    app.mount(
        "/static",
        StaticFiles(directory=STATIC_DIRECTORY),
        name="static",
    )

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIRECTORY / "index.html")

    @app.get(
        "/api/v1/health",
        response_model=HealthResponse,
    )
    def health():
        return service.health(
            worker_count=job_manager.worker_count,
            queue_capacity=job_manager.queue_capacity,
        )

    @app.post(
        "/api/v1/analyses",
        response_model=AnalysisEnvelope,
    )
    def analyse(submission: SudokuSubmission):
        try:
            return _analysis_envelope(service, submission)
        except (AssertionError, ValueError) as error:
            raise HTTPException(
                status_code=422,
                detail=str(error),
            ) from error

    @app.post(
        "/api/v1/jobs",
        response_model=JobAccepted,
        status_code=202,
    )
    def submit_job(submission: SudokuSubmission):
        try:
            job = job_manager.submit(
                lambda: _analysis_envelope(service, submission)
            )
        except JobQueueFullError as error:
            raise HTTPException(
                status_code=429,
                detail=str(error),
            ) from error

        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "status_url": f"/api/v1/jobs/{job['job_id']}",
        }

    @app.get(
        "/api/v1/jobs/{job_id}",
        response_model=JobStatus,
    )
    def get_job(job_id: str):
        try:
            return job_manager.get(job_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail="Job non trovato.",
            ) from error

    @app.get(
        "/api/v1/analyses/{puzzle_id}/plots/{plot_name}.png",
        response_class=Response,
    )
    def analysis_plot(
        puzzle_id: str,
        plot_name: str,
        analysis_mode: str = Query(default="profile"),
        profile_difficulty_window: float = Query(
            default=3.0,
            ge=0.0,
            le=10.0,
        ),
    ):
        if analysis_mode not in {"profile", "deep", "superficial"}:
            raise HTTPException(
                status_code=422,
                detail="Modalità di analisi non valida.",
            )

        try:
            image = service.render_plot(
                puzzle_id,
                plot_name,
                analysis_mode,
                profile_difficulty_window,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail="Grafico non trovato.",
            ) from error
        except FileNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail=str(error),
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail=str(error),
            ) from error

        return Response(
            content=image,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    return app
