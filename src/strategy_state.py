"""Independent Strategy/Risk contracts; no orchestration or market acquisition."""
from datetime import date
from typing import Annotated, Literal
from math import isclose
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False, str_strip_whitespace=True)


class Position(StrictModel):
    symbol: str = Field(pattern=r'^[036][0-9]{5}$')
    weight: float = Field(ge=0, le=1)


class Portfolio(StrictModel):
    as_of_date: date
    currency: Literal['CNY']
    cash_weight: float = Field(default=0, ge=0, le=1)
    positions: list[Position] = Field(max_length=50)

    @field_validator('as_of_date', mode='before')
    @classmethod
    def parse_iso_date(cls, value):
        return date.fromisoformat(value) if isinstance(value, str) else value

    @model_validator(mode='after')
    def valid_weights(self):
        ids = [p.symbol for p in self.positions]
        if len(ids) != len(set(ids)) or not isclose(sum(p.weight for p in self.positions) + self.cash_weight, 1, abs_tol=1e-8, rel_tol=0):
            raise ValueError('持仓不得重复，持仓与现金权重之和须为1；不自动归一化')
        return self


class RiskConstraints(StrictModel):
    max_single_asset_weight: float | None = Field(default=None, ge=0, le=1)
    max_asset_annualized_volatility: float | None = Field(default=None, ge=0)
    max_asset_drawdown: float | None = Field(default=None, ge=0, le=1)
    max_portfolio_volatility: float | None = Field(default=None, ge=0)
    max_portfolio_drawdown: float | None = Field(default=None, ge=0, le=1)


class PriceScenario(StrictModel):
    scenario_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1)
    origin: Literal['user', 'agent_proposed']
    price_shocks: dict[str, float]

    @model_validator(mode='after')
    def valid_shocks(self):
        if any(v < -1 for v in self.price_shocks.values()):
            raise ValueError('冲击不可低于-100%')
        return self


class StrategyParameters(StrictModel):
    subjects: list[str] = Field(default_factory=list)
    time_range: str = ''
    portfolio: Portfolio | None = None
    risk_constraints: RiskConstraints = Field(default_factory=RiskConstraints)
    scenario_assumptions: list[PriceScenario] = Field(default_factory=list, max_length=10)

    @field_validator('risk_constraints', mode='before')
    @classmethod
    def default_limits(cls, value):
        return {} if value is None else value

    @field_validator('scenario_assumptions', mode='before')
    @classmethod
    def default_scenarios(cls, value):
        return [] if value is None else value

    @model_validator(mode='after')
    def unique_scenarios(self):
        ids = [s.scenario_id for s in self.scenario_assumptions]
        if len(ids) != len(set(ids)):
            raise ValueError('情景ID重复')
        return self


class StrategyInput(StrategyParameters):
    task: str = Field(min_length=1)
    dataset_refs: list[dict] = Field(default_factory=list)
    analysis_refs: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)


class StrategyClaim(StrictModel):
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class StrategyDataRequest(StrictModel):
    kind: Literal['portfolio', 'risk_constraints', 'scenario_assumptions', 'price_history', 'analysis', 'evidence', 'earnings', 'valuation_snapshot', 'unspecified']
    subjects: list[str] = Field(default_factory=list)
    time_range: str = ''
    reason: str = Field(min_length=1)


class StrategyAnswer(StrictModel):
    summary: str = Field(min_length=1)
    opportunities: list[StrategyClaim] = Field(default_factory=list)
    risks: list[StrategyClaim] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    missing_data_requests: list[StrategyDataRequest] = Field(default_factory=list)


class StrategyResult(StrictModel):
    summary: str
    opportunities: list[StrategyClaim] = Field(default_factory=list)
    risks: list[StrategyClaim] = Field(default_factory=list)
    artifact_refs: list[dict] = Field(default_factory=list)
    scenario_results: list[dict] = Field(default_factory=list)
    constraint_checks: list[dict] = Field(default_factory=list)
    dataset_refs: list[dict] = Field(default_factory=list)
    analysis_refs: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    assumptions: dict = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    missing_data_requests: list[StrategyDataRequest] = Field(default_factory=list)


class StrategyState(TypedDict, total=False):
    task: str
    subjects: list[str]
    time_range: str
    portfolio: dict | None
    risk_constraints: dict
    scenario_assumptions: list[dict]
    dataset_refs: list[dict]
    analysis_refs: list[dict]
    evidence: list[dict]
    scope_id: str
    messages: Annotated[list[BaseMessage], add_messages]
    tool_rounds: int
    tool_calls_used: int
    output_retries: int
    strategy_artifacts: list[dict]
    tool_errors: list[dict]
    result: dict | None
    status: Literal['running', 'completed', 'partial', 'failed']
    error: dict | None


def strategy_answer_schema() -> dict:
    """Narrative-only model projection; executed Strategy artifacts are selected by code."""
    schema = StrategyAnswer.model_json_schema()
    schema['properties'].pop('artifact_ids')
    return schema
