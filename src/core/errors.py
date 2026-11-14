"""Structured task error shared by orchestration and specialist boundaries."""
from pydantic import BaseModel, ConfigDict, Field


class TaskError(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    type: str = Field(min_length=1)
    message: str = Field(min_length=1)
