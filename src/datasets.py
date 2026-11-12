"""Validated financial datasets and an explicitly request-scoped memory store.

Provider adapters normalize units/dates before registration. No API access,
module-global registry, automatic persistence or dataframe in graph state.
"""
from datetime import date, datetime
from threading import RLock
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class DatasetModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True,
                              allow_inf_nan=False)


class Provenance(DatasetModel):
    symbol: str = Field(min_length=1)
    market: str = Field(min_length=1)
    currency: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    source_url: str | None = None
    retrieved_at: datetime
    data_mode: Literal["real", "mock"]

    @model_validator(mode="after")
    def timezone_required(self):
        if self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at 必须包含时区")
        return self


class PriceRow(DatasetModel):
    date: date
    close: float = Field(gt=0)
    open: float | None = Field(default=None, gt=0)
    high: float | None = Field(default=None, gt=0)
    low: float | None = Field(default=None, gt=0)
    volume: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def consistent_range(self):
        values = [value for value in (self.open, self.close, self.high, self.low) if value is not None]
        if self.high is not None and self.high < max(values):
            raise ValueError("high 小于其他价格")
        if self.low is not None and self.low > min(values):
            raise ValueError("low 大于其他价格")
        return self


class PriceDataset(Provenance):
    kind: Literal["price_history"]
    asset_type: Literal["stock", "index", "fund"]
    frequency: Literal["daily"]
    adjustment: Literal["none", "qfq", "hfq", "total_return"]
    price_unit: str = Field(min_length=1)
    volume_unit: Literal["shares", "not_available"]
    rows: list[PriceRow] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_observations(self):
        dates = [row.date for row in self.rows]
        if any(left >= right for left, right in zip(dates, dates[1:])):
            raise ValueError("价格日期必须唯一且严格递增")
        if self.volume_unit == "not_available" and any(row.volume is not None for row in self.rows):
            raise ValueError("成交量存在时必须提供已规范化的单位")
        return self


class ValuationMetric(DatasetModel):
    value: float | None
    unit: Literal["multiple", "percent", "currency_per_share"]
    missing_reason: str | None = None

    @model_validator(mode="after")
    def missing_value_explained(self):
        if self.value is None and not (self.missing_reason or "").strip():
            raise ValueError("缺失数值必须说明原因，不得以零替代")
        return self


MetricName = Literal["pe_ttm", "pb", "dividend_yield", "revenue_growth", "earnings_growth", "roe", "eps"]


class ValuationDataset(Provenance):
    kind: Literal["valuation_snapshot"]
    as_of_date: date
    report_period: date | None = None
    available_at: date | None = None
    metrics: dict[MetricName, ValuationMetric] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent_observation(self):
        if self.available_at and self.available_at > self.as_of_date:
            raise ValueError("财务数据在观察日期尚未公开")
        if self.report_period and self.report_period > self.as_of_date:
            raise ValueError("报告期晚于观察日期")
        for name, metric in self.metrics.items():
            unit = "multiple" if name in {"pe_ttm", "pb"} else "currency_per_share" if name == "eps" else "percent"
            if metric.unit != unit:
                raise ValueError(f"{name} 的单位必须为 {unit}")
        return self


Dataset = Annotated[PriceDataset | ValuationDataset, Field(discriminator="kind")]
_DATASET_ADAPTER = TypeAdapter(Dataset)


class DatasetRef(Provenance):
    dataset_id: str
    kind: Literal["price_history", "valuation_snapshot"]
    start_date: date
    end_date: date
    row_count: int = Field(gt=0)
    adjustment: Literal["none", "qfq", "hfq", "total_return"] | None = None
    frequency: Literal["daily"] | None = None
    price_unit: str | None = None
    volume_unit: Literal["shares", "not_available"] | None = None


class DatasetStore:
    """Create one instance per request; inject that instance into future tools.

    IDs resolve only in this instance. Copies prevent cross-tool mutation.
    Revalidate model_dump() so even mutated/constructed model objects are checked.
    """
    def __init__(self):
        self._datasets: dict[str, dict] = {}
        self._refs: dict[str, DatasetRef] = {}
        self._lock = RLock()

    def put(self, dataset: PriceDataset | ValuationDataset | dict) -> DatasetRef:
        data = _DATASET_ADAPTER.validate_python(dataset.model_dump() if isinstance(dataset, BaseModel) else dataset)
        ident = "dataset_" + uuid4().hex
        common = {name: getattr(data, name) for name in Provenance.model_fields}
        if isinstance(data, PriceDataset):
            ref = DatasetRef(**common, dataset_id=ident, kind=data.kind,
                start_date=data.rows[0].date, end_date=data.rows[-1].date, row_count=len(data.rows),
                adjustment=data.adjustment, frequency=data.frequency,
                price_unit=data.price_unit, volume_unit=data.volume_unit)
        else:
            ref = DatasetRef(**common, dataset_id=ident, kind=data.kind,
                start_date=data.as_of_date, end_date=data.as_of_date, row_count=1)
        with self._lock:
            self._datasets[ident] = data.model_dump()
            self._refs[ident] = ref.model_copy(deep=True)
        return ref

    def get(self, dataset_id: str) -> PriceDataset | ValuationDataset:
        with self._lock:
            return _DATASET_ADAPTER.validate_python(self._datasets[dataset_id])

    def get_ref(self, dataset_id: str) -> DatasetRef:
        with self._lock:
            return self._refs[dataset_id].model_copy(deep=True)

    def clear(self) -> None:
        with self._lock:
            self._datasets.clear()
            self._refs.clear()
