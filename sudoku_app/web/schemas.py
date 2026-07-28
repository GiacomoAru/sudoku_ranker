from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


AnalysisMode = Literal["profile", "deep", "superficial"]


class SudokuSubmission(BaseModel):
    """Payload minimo accettato dall'endpoint di analisi."""

    model_config = ConfigDict(str_strip_whitespace=True)

    grid: str = Field(
        description="Griglia di 81 cifre; 0 o punto indicano una cella vuota.",
    )
    provenience: str = Field(min_length=1, max_length=60)
    tag: str = Field(min_length=1, max_length=80)
    difficulty: str = Field(min_length=1, max_length=40)
    analysis_mode: AnalysisMode = "profile"
    profile_difficulty_window: float = Field(
        default=3.0,
        ge=0.0,
        le=10.0,
    )
    force: bool = False

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
                "La griglia può contenere soltanto cifre, punti e spazi."
            )

        return normalised

    @field_validator("provenience", "tag", "difficulty")
    @classmethod
    def validate_nomenclature_field(cls, value):
        value = " ".join(value.split())

        if not value:
            raise ValueError("Il campo non può essere vuoto.")

        if any(character in value for character in "\r\n\t"):
            raise ValueError("Il campo contiene caratteri non validi.")

        return value


class PlotLinks(BaseModel):
    difficulty_chain: str
    technique_heatmap: str


class AnalysisEnvelope(BaseModel):
    puzzle_id: str
    canonical_id: str
    name: str
    archive_profile: str
    is_isomorphic_duplicate: bool
    isomorphic_variant_count: int
    analysis: dict[str, Any]
    plots: PlotLinks | None


class HealthResponse(BaseModel):
    status: Literal["ok"]
    archive_profile: str
    default_analysis_mode: str
    default_profile_difficulty_window: float
    analysis_worker_count: int
    job_queue_capacity: int


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
