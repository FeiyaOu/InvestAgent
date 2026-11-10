"""Validated task plans for the future parent graph."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import TypedDict

TaskCategory = Literal["market_data", "analytics", "investment_strategy", "report"]


class PlanTask(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    task_id: str = Field(min_length=1, max_length=80)
    category: TaskCategory
    question: str = Field(min_length=1)
    depends_on: list[str]


class TaskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    status: Literal["ready", "needs_clarification"]
    tasks: list[PlanTask] = Field(max_length=12)
    clarification_questions: list[str]

    @model_validator(mode="after")
    def validate_plan(self) -> "TaskPlan":
        if self.status == "needs_clarification":
            if self.tasks or not self.clarification_questions or any(
                not question.strip() for question in self.clarification_questions
            ):
                raise ValueError("澄清计划必须无任务且包含非空澄清问题")
            return self
        if not self.tasks or self.clarification_questions:
            raise ValueError("ready 计划必须包含任务且不得包含澄清问题")
        ids = [task.task_id for task in self.tasks]
        if len(set(ids)) != len(ids):
            raise ValueError("task_id 不得重复")
        remaining = {}
        for task in self.tasks:
            dependencies = set(task.depends_on)
            if len(dependencies) != len(task.depends_on):
                raise ValueError(f"{task.task_id}: 依赖不得重复")
            if task.task_id in dependencies:
                raise ValueError(f"{task.task_id}: 不得依赖自身")
            unknown = dependencies - set(ids)
            if unknown:
                raise ValueError(f"{task.task_id}: 未知依赖 {sorted(unknown)}")
            remaining[task.task_id] = dependencies
        resolved = set()
        while remaining:
            ready = {ident for ident, deps in remaining.items() if deps <= resolved}
            if not ready:
                raise ValueError("任务依赖存在有向环")
            resolved.update(ready)
            remaining = {ident: deps for ident, deps in remaining.items() if ident not in ready}
        return self


class PlannerState(TypedDict, total=False):
    user_query: str
    conversation_context: str
    plan: dict | None
    planning_status: Literal["ready", "needs_clarification", "failed"]
    planning_error: dict | None
    planning_attempts: int
