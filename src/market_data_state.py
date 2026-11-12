"""Local contracts for the independent market-data subgraph."""
from typing import Annotated, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict
from src.datasets import DatasetRef


class MarketDataAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str = Field(min_length=1)
    evidence_ids: list[str]
    missing_information: list[str]


class MarketEvidence(BaseModel):
    tool_call_id: str
    tool_name: str
    content: str
    retrieved_at: str
    status: Literal["returned", "error"]
    data_mode: str
    # Existing text tools do not supply reliable source/date metadata.
    source_url: str | None = None
    as_of_date: str | None = None


class MarketDataResult(MarketDataAnswer):
    evidence: list[MarketEvidence]
    dataset_refs: list[DatasetRef] = Field(default_factory=list)


class MarketDataState(TypedDict, total=False):
    task: str
    subject: str
    time_range: str
    existing_evidence: list[dict]
    messages: Annotated[list[BaseMessage], add_messages]
    tool_rounds: int
    tool_calls_used: int
    output_retries: int
    evidence: list[dict]
    dataset_refs: list[dict]
    result: dict | None
    status: Literal["running", "completed", "partial", "failed"]
    error: dict | None
