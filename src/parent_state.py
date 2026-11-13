"""Request-local parent state. No graph, persistence, or child messages here."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

from src.supervisor_state import ReportParameters
from src.task_contracts import validate_task_results  # Public boundary helper.


class ParentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    user_query: str = Field(min_length=1)
    conversation_context: str = ""
    report_parameters: dict[str, ReportParameters] = Field(default_factory=dict)


class ParentState(TypedDict, total=False):
    user_query: str
    conversation_context: str
    report_parameters: dict[str, dict]
    plan: dict | None
    planning_status: Literal["ready", "needs_clarification", "failed"] | None
    planning_error: dict | None
    planning_attempts: int
    task_results: dict[str, dict]
    supervisor_status: Literal["running", "completed", "partial", "failed", "needs_clarification"] | None
    supervisor_error: dict | None
    final_response: str | None
    composition_status: Literal["completed", "fallback", "needs_clarification", "failed"] | None
    composition_error: dict | None


def create_parent_state(user_query: str, *, conversation_context: str = "",
                        report_parameters: dict | None = None) -> ParentState:
    """Validate request inputs and initialize fresh per-request outputs."""
    request = ParentRequest.model_validate({"user_query": user_query,
        "conversation_context": conversation_context,
        "report_parameters": {} if report_parameters is None else report_parameters})
    return {**request.model_dump(), "plan": None, "planning_status": None,
            "planning_error": None, "planning_attempts": 0, "task_results": {},
            "supervisor_status": None, "supervisor_error": None,
            "final_response": None, "composition_status": None, "composition_error": None}
