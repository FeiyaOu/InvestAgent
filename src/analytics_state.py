"""Local inputs and validated public output for the independent Analytics agent."""
from typing import Annotated, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict


class AnalyticsAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    periods_per_year: int | None = Field(default=None, ge=1, le=366)
    window: int | None = Field(default=None, ge=2, le=252)
    missing_data: Literal["no_fill"] = "no_fill"


class AnalyticsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    task: str = Field(min_length=1)
    subjects: list[str] = Field(default_factory=list)
    time_range: str = ""
    dataset_refs: list[dict] = Field(default_factory=list)
    existing_analysis_refs: list[dict] = Field(default_factory=list)
    assumptions: AnalyticsAssumptions = Field(default_factory=AnalyticsAssumptions)


class MissingDataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    kind: Literal["price_history", "benchmark_history", "valuation_snapshot", "unspecified"]
    subjects: list[str]
    time_range: str
    reason: str = Field(min_length=1)


class AnalyticsAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    summary: str = Field(min_length=1)
    analysis_ids: list[str]
    missing_information: list[str]
    missing_data_requests: list[MissingDataRequest]


class AnalyticsResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary: str
    findings: list[dict]
    analysis_refs: list[dict]
    chart_refs: list[dict]
    dataset_refs: list[dict]
    assumptions: dict
    limitations: list[str]
    missing_information: list[str]
    missing_data_requests: list[MissingDataRequest]


class AnalyticsState(TypedDict, total=False):
    task: str
    subjects: list[str]
    time_range: str
    dataset_refs: list[dict]
    existing_analysis_refs: list[dict]
    assumptions: dict
    messages: Annotated[list[BaseMessage], add_messages]
    tool_rounds: int
    tool_calls_used: int
    output_retries: int
    analysis_artifacts: list[dict]
    tool_errors: list[dict]
    result: dict | None
    status: Literal["running", "completed", "partial", "failed"]
    error: dict | None
