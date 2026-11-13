"""State contracts for sequential task dispatch."""
from typing import Literal

from pydantic import BaseModel, ConfigDict
from typing_extensions import TypedDict


class ReportParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    research_topic: str = ""
    industry_focus: str = ""
    time_horizon: str = ""


class SupervisorState(TypedDict, total=False):
    plan: dict | None
    report_parameters: dict[str, dict]
    task_results: dict[str, dict]
    supervisor_status: Literal["running", "completed", "partial", "failed", "needs_clarification"]
    supervisor_error: dict | None
    last_task_id: str | None
