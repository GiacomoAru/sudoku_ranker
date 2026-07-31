from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core import solver


AnalysisMode = Literal["profile", "deep", "superficial"]


class SudokuSubmission(BaseModel):
    """Payload accettato dagli endpoint di analisi e archiviazione."""

    model_config = ConfigDict(str_strip_whitespace=True)

    grid: str = Field(
        description="Griglia di 81 cifre; 0 o punto indicano una cella vuota.",
    )
    name: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Campi legacy mantenuti per compatibilita con vecchi client e script.
    provenience: str = Field(default="web", min_length=1, max_length=100)
    tag: str = Field(default="nessun_riferimento", min_length=1, max_length=160)
    difficulty: str = Field(default="non_indicata", min_length=1, max_length=60)

    analysis_mode: AnalysisMode = "profile"
    profile_difficulty_window: float = Field(
        default=solver.DEFAULT_PROFILE_DIFFICULTY_WINDOW,
        ge=0.0,
        le=10.0,
    )
    force: bool = False
    photo_id: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{24}$",
        description=(
            "Identificatore opzionale della foto da collegare al Sudoku "
            "confermato."
        ),
    )

    @field_validator("grid")
    @classmethod
    def validate_grid_text(cls, value):
        normalised = "".join(value.split()).replace(".", "0")

        if len(normalised) != 81:
            raise ValueError(
                "La griglia deve contenere esattamente 81 celle."
            )

        if any(character not in "0123456789" for character in normalised):
            raise ValueError(
                "La griglia puo contenere soltanto cifre, punti e spazi."
            )

        return normalised

    @field_validator("provenience", "tag", "difficulty")
    @classmethod
    def validate_nomenclature_field(cls, value):
        value = " ".join(value.split())

        if not value:
            raise ValueError("Il campo non puo essere vuoto.")

        if any(character in value for character in "\r\n\t"):
            raise ValueError("Il campo contiene caratteri non validi.")

        return value

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value):
        """Valida i campi noti senza impedire metadati futuri."""
        metadata = dict(value or {})
        text_limits = {
            "title": 100,
            "source": 100,
            "source_reference": 160,
            "stated_difficulty": 60,
            "author_or_publisher": 100,
            "published_at": 32,
            "notes": 1000,
            "entry_channel": 40,
            "input_method": 20,
            "photo_id": 64,
        }

        for key, limit in text_limits.items():
            if key not in metadata or metadata[key] is None:
                continue

            if not isinstance(metadata[key], str):
                raise ValueError(
                    f"Il metadato {key!r} deve essere testuale."
                )

            cleaned = metadata[key].strip()
            if len(cleaned) > limit:
                raise ValueError(
                    f"Il metadato {key!r} supera {limit} caratteri."
                )
            metadata[key] = cleaned

        return metadata


class PlotLinks(BaseModel):
    difficulty_chain: str
    technique_heatmap: str


class AnalysisEnvelope(BaseModel):
    puzzle_id: str
    canonical_id: str
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    archive_profile: str
    is_isomorphic_duplicate: bool
    isomorphic_variant_count: int
    analysis: dict[str, Any]
    plots: PlotLinks | None


class HealthResponse(BaseModel):
    status: Literal["ok"]
    archive_profile: str
    exposure_mode: Literal["local", "lan", "internet"]
    authentication_enabled: bool
    default_analysis_mode: str
    default_profile_difficulty_window: float
    analysis_worker_count: int
    job_queue_capacity: int
    photo_recognition_version: str
    max_photo_size_mb: int


class JobAccepted(BaseModel):
    job_id: str
    status: Literal["queued", "running"]
    status_url: str


class JobStatus(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    created_at: str
    started_at: str | None
    completed_at: str | None
    result: AnalysisEnvelope | None
    error: str | None


class PhotoRecognitionResponse(BaseModel):
    photo_id: str
    algorithm_version: str
    grid: str
    detected_digit_count: int
    mean_confidence: float
    grid_detection_confidence: float
    grid_detection_method: str
    low_confidence_indices: list[int]
    cells: list[dict[str, Any]]
    warnings: list[str]
    source_size: dict[str, int]
    grid_corners: list[list[float]]
    original_url: str
    rectified_url: str
