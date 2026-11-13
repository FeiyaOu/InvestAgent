"""Validated task plans for the future parent graph."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from typing_extensions import TypedDict
from src.analytics_state import AnalyticsAssumptions
from src.strategy_state import StrategyParameters

TaskCategory = Literal["market_data", "analytics", "investment_strategy", "report"]


class AnalyticsDependencyError(ValueError):
    """A structurally valid plan cannot supply analytics task data."""


class AnalyticsTaskParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    subjects: list[str] = Field(default_factory=list)
    time_range: str = ""
    assumptions: AnalyticsAssumptions = Field(default_factory=AnalyticsAssumptions)

    @field_validator("assumptions", mode="before")
    @classmethod
    def default_null_assumptions(cls, value):
        """Optional model-generated null is equivalent to omitting assumptions."""
        return {} if value is None else value


class PlanTask(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    task_id: str = Field(min_length=1, max_length=80)
    category: TaskCategory
    question: str = Field(min_length=1)
    depends_on: list[str]
    analytics_parameters: AnalyticsTaskParameters | None = None
    strategy_parameters: StrategyParameters | None = None

    @model_validator(mode="after")
    def parameters_match_category(self):
        if self.analytics_parameters is not None and self.category != "analytics":
            raise ValueError("analytics_parameters 仅用于 analytics 任务")
        if self.strategy_parameters is not None and self.category != "investment_strategy":
            raise ValueError("strategy_parameters仅用于investment_strategy任务")
        return self


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


    def validate_analytics_dependencies(self) -> None:
        """Planner rule: request-local analytics must get refs through direct dependencies.

        Kept separate from generic TaskPlan validation so standalone Supervisor can
        still return a structured missing-data result for a caller-supplied bare task.
        """
        categories = {task.task_id: task.category for task in self.tasks}
        for task in self.tasks:
            if task.category == "analytics" and not any(
                categories[ident] in {"market_data", "analytics"} for ident in task.depends_on
            ):
                raise AnalyticsDependencyError(f"analytics 任务 {task.task_id} 必须直接依赖提供结构化数据的 market_data 或 analytics 任务")

    def to_state(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)


class PlannerState(TypedDict, total=False):
    user_query: str
    conversation_context: str
    plan: dict | None
    planning_status: Literal["ready", "needs_clarification", "failed"]
    planning_error: dict | None
    planning_attempts: int


def planner_output_schema() -> dict:
    """Model-facing projection; fixed runtime policies are filled by TaskPlan validation.

    Keep a fresh schema each call so runtime contracts and other agents are unchanged.
    Explicit user parameters remain available; no_fill is never a model decision.
    """
    schema = TaskPlan.model_json_schema()
    assumptions = schema["$defs"]["AnalyticsAssumptions"]
    assumptions["properties"].pop("missing_data")
    assumptions["description"] = "Only explicit user-specified parameters. Omit unspecified values."
    return schema
