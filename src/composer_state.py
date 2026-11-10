"""Composition output and shared execution state."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.supervisor_state import SupervisorState


class ComposedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    answer: str = Field(min_length=1)


class ResponseState(SupervisorState, total=False):
    user_query: str
    final_response: str
    composition_status: Literal["completed", "fallback", "needs_clarification", "failed"]
    composition_error: dict | None
