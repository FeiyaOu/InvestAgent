"""Uniform terminal task envelope; specialist payloads keep their own schemas."""
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.planner_schemas import PlanTask

TaskStatus = Literal["completed", "partial", "failed", "blocked", "unsupported"]


class TaskError(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    type: str = Field(min_length=1)
    message: str = Field(min_length=1)


class TaskResult(PlanTask):
    status: TaskStatus
    result: dict | None
    error: TaskError | None

    @model_validator(mode="after")
    def consistent_outcome(self) -> "TaskResult":
        if self.status in {"completed", "partial"}:
            if self.result is None or self.error is not None:
                raise ValueError("可用任务结果必须有 result 且无执行错误")
        else:
            if self.error is None:
                raise ValueError("失败、阻断或未接入任务必须有结构化 error")
            if self.status in {"blocked", "unsupported"} and self.result is not None:
                raise ValueError("未执行任务不得有 result")
        return self


    def to_state(self) -> dict:
        output = self.model_dump()
        if self.analytics_parameters is None:
            output.pop("analytics_parameters", None)
        else:
            output["analytics_parameters"] = self.analytics_parameters.model_dump(exclude_none=True)
        if self.strategy_parameters is None:
            output.pop("strategy_parameters", None)
        else:
            output["strategy_parameters"] = self.strategy_parameters.model_dump(mode="json", exclude_none=True)
        return output


def validate_task_results(records: dict[str, dict]) -> dict[str, dict]:
    """Validate map identity and detach nested payloads from caller-owned data."""
    if not isinstance(records, dict):
        raise ValueError("task_results 必须为字典")
    validated = {}
    for key, raw in records.items():
        result = TaskResult.model_validate(raw)
        if key != result.task_id:
            raise ValueError("结果字典 key 必须与 task_id 一致")
        validated[key] = deepcopy(result.to_state())
    return validated
