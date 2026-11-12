"""Request-local, validated calculation artifacts; chart arrays stay out of graph state."""
from datetime import datetime
from threading import RLock
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class SeriesPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    date: str
    value: float


class AnalysisArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    analysis_id: str
    tool_name: str
    dataset_refs: list[dict]
    created_at: datetime
    start_date: str
    end_date: str
    sample_size: int = Field(ge=1)  # Unit is documented in assumptions.
    metrics: dict[str, float | None]
    metric_units: dict[str, str]
    assumptions: dict
    limitations: list[str]
    table: list[dict] = Field(default_factory=list)
    series: dict[str, list[SeriesPoint]]


class AnalysisStore:
    def __init__(self):
        self._items: dict[str, AnalysisArtifact] = {}
        self._lock = RLock()

    def put(self, **payload) -> dict:
        ident = "analysis_" + uuid4().hex
        artifact = AnalysisArtifact(analysis_id=ident, **payload)
        with self._lock:
            self._items[ident] = artifact.model_copy(deep=True)
        ref = artifact.model_dump(mode="json", exclude={"series"})
        ref["chart_refs"] = [{"analysis_id": ident, "series_key": key} for key in artifact.series]
        return ref

    def get(self, analysis_id: str) -> AnalysisArtifact:
        with self._lock:
            return self._items[analysis_id].model_copy(deep=True)

    def clear(self):
        with self._lock:
            self._items.clear()
