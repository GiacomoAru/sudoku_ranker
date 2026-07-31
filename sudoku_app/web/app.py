import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .jobs import AnalysisJobManager, JobQueueFullError
from .schemas import (
    AnalysisEnvelope,
    HealthResponse,
    JobAccepted,
    JobStatus,
    PhotoRecognitionResponse,
    SudokuSubmission,
)
from .service import SudokuWebService
from .photo_recognition import MAX_IMAGE_BYTES, PhotoRecognitionError
from .security import install_security_middleware


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
        "metadata": dict(puzzle.get("metadata", {})),
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


def create_app(
    data_dir=None,
    job_queue_capacity=16,
    exposure_mode=None,
    access_username=None,
    access_password=None,
):
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
    configured_exposure_mode = (
        exposure_mode
        if exposure_mode is not None
        else os.environ.get("SUDOKU_WEB_EXPOSURE", "lan")
    ).casefold()
    configured_username = (
        access_username
        if access_username is not None
        else os.environ.get("SUDOKU_WEB_ACCESS_USERNAME", "sudoku")
    )
    configured_password = (
        access_password
        if access_password is not None
        else os.environ.get("SUDOKU_WEB_ACCESS_PASSWORD")
    )

    if configured_exposure_mode not in {"local", "lan", "internet"}:
        raise ValueError(
            "SUDOKU_WEB_EXPOSURE deve essere local, lan o internet."
        )
    if not configured_username:
        raise ValueError("Il nome utente web non può essere vuoto.")
    if ":" in configured_username:
        raise ValueError("Il nome utente web non può contenere ':'.")
    if configured_exposure_mode == "internet" and not configured_password:
        raise ValueError(
            "La modalità internet richiede SUDOKU_WEB_ACCESS_PASSWORD."
        )
    if (
        configured_exposure_mode == "internet"
        and len(configured_password) < 12
    ):
        raise ValueError(
            "In modalità internet la password deve avere almeno "
            "12 caratteri."
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
        version="0.2.0",
        description=(
            "API web per riconoscere Sudoku da foto, salvarli e ricevere "
            "analisi logiche in locale, LAN o tramite tunnel HTTPS."
        ),
        lifespan=lifespan,
    )
    app.state.sudoku_service = service
    app.state.analysis_jobs = job_manager
    authentication_enabled = install_security_middleware(
        app,
        username=configured_username,
        password=configured_password,
    )
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
            exposure_mode=configured_exposure_mode,
            authentication_enabled=authentication_enabled,
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
        "/api/v1/photos/recognise",
        response_model=PhotoRecognitionResponse,
    )
    def recognise_photo(photo: UploadFile = File(...)):
        content_type = (photo.content_type or "").casefold()

        if content_type not in {
            "image/jpeg",
            "image/png",
            "image/webp",
        }:
            raise HTTPException(
                status_code=415,
                detail="Formato non supportato: usa JPEG, PNG o WebP.",
            )

        image_bytes = photo.file.read(MAX_IMAGE_BYTES + 1)

        try:
            return service.recognise_photo(
                image_bytes,
                filename=photo.filename,
                content_type=content_type,
            )
        except PhotoRecognitionError as error:
            detail = {
                "message": str(error),
                "photo_id": getattr(error, "photo_id", None),
            }
            raise HTTPException(
                status_code=422,
                detail=detail,
            ) from error

    @app.get(
        "/api/v1/photos/{photo_id}/{kind}",
        response_class=FileResponse,
    )
    def photo_media(photo_id: str, kind: str):
        try:
            path, payload = service.photo_archive.media_path(
                photo_id,
                kind,
            )
        except (KeyError, FileNotFoundError) as error:
            raise HTTPException(
                status_code=404,
                detail="Foto o anteprima non trovata.",
            ) from error

        media_type = (
            "image/png"
            if kind == "rectified"
            else payload.get("content_type", "application/octet-stream")
        )
        return FileResponse(
            path,
            media_type=media_type,
            headers={"Cache-Control": "no-store"},
        )

    @app.post(
        "/api/v1/jobs",
        response_model=JobAccepted,
        status_code=202,
    )
    def submit_job(submission: SudokuSubmission):
        # Il job viene eseguito in un thread separato. La copia profonda
        # conserva in modo esplicito anche il dizionario metadata.
        queued_submission = submission.model_copy(deep=True)

        try:
            job = job_manager.submit(
                lambda: _analysis_envelope(service, queued_submission)
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
