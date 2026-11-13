"""Dataset contracts/storage: deterministic and request-scoped, no APIs."""
from datetime import date, datetime, timezone
import pytest
from pydantic import ValidationError

from src.datasets import DatasetStore, PriceDataset, ValuationDataset


def prices(**updates):
    return {"kind": "price_history", "symbol": "600519", "market": "SSE", "asset_type": "stock",
            "currency": "CNY", "frequency": "daily", "adjustment": "qfq", "price_unit": "CNY/share",
            "volume_unit": "shares", "provider": "test", "source_url": None,
            "retrieved_at": datetime(2026, 11, 12, tzinfo=timezone.utc), "data_mode": "mock",
            "rows": [{"date": date(2026, 11, 9), "close": 100.0},
                     {"date": date(2026, 11, 10), "close": 110.0}], **updates}


def test_valid_price_dataset_preserves_provenance_and_optional_ohlcv():
    dataset = PriceDataset.model_validate(prices())
    assert dataset.rows[0].volume is None
    assert dataset.data_mode == "mock"
    assert dataset.adjustment == "qfq"


@pytest.mark.parametrize("rows", [
    [], [{"date": date(2026, 11, 10), "close": float("nan")}],
    [{"date": date(2026, 11, 10), "close": float("inf")}],
    [{"date": date(2026, 11, 10), "close": 0.0}],
    [{"date": date(2026, 11, 10), "close": 1.0, "volume": -1.0}],
    [{"date": date(2026, 11, 10), "close": 1.0}] * 2,
    [{"date": date(2026, 11, 10), "close": 1.0}, {"date": date(2026, 11, 9), "close": 2.0}],
    [{"date": date(2026, 11, 10), "close": 10.0, "high": 9.0, "low": 8.0}],
])
def test_rejects_invalid_price_rows(rows):
    with pytest.raises(ValidationError):
        PriceDataset.model_validate(prices(rows=rows))


def test_metadata_rejects_naive_time_unknown_adjustment_and_missing_units():
    for updates in ({"retrieved_at": datetime(2026, 11, 12)}, {"adjustment": "adjusted"},
                    {"price_unit": ""}, {"volume_unit": "lots"}):
        with pytest.raises(ValidationError):
            PriceDataset.model_validate(prices(**updates))


def test_valuation_distinguishes_observation_date_report_period_and_availability():
    data = ValuationDataset.model_validate({"kind": "valuation_snapshot", "symbol": "600519", "market": "SSE",
        "currency": "CNY", "provider": "test", "retrieved_at": datetime.now(timezone.utc), "data_mode": "real",
        "as_of_date": date(2026, 11, 10), "report_period": date(2026, 9, 30),
        "available_at": date(2026, 10, 29), "metrics": {
            "pe_ttm": {"value": None, "unit": "multiple", "missing_reason": "亏损，PE不适用"},
            "dividend_yield": {"value": 2.0, "unit": "percent"}}})
    assert data.metrics["pe_ttm"].value is None
    assert data.available_at <= data.as_of_date


def test_store_generates_reference_and_isolates_mutation_and_requests():
    first, second = DatasetStore(), DatasetStore()
    dataset = PriceDataset.model_validate(prices())
    ref = first.put(dataset)
    dataset.rows[0].close = 999
    loaded = first.get(ref.dataset_id)
    assert loaded.rows[0].close == 100.0
    loaded.rows[0].close = 888
    assert first.get(ref.dataset_id).rows[0].close == 100.0
    assert ref.row_count == 2
    assert ref.start_date == date(2026, 11, 9)
    assert "rows" not in ref.model_dump()
    assert first.get_ref(ref.dataset_id) == ref
    with pytest.raises(KeyError):
        second.get(ref.dataset_id)
    first.clear()
    with pytest.raises(KeyError):
        first.get(ref.dataset_id)


def test_store_revalidates_model_instances_before_registration():
    dataset = PriceDataset.model_validate(prices())
    dataset.rows[0].close = -10
    with pytest.raises(ValidationError):
        DatasetStore().put(dataset)


@pytest.mark.parametrize("updates", [
    {"available_at": date(2026, 11, 11)},
    {"report_period": date(2026, 12, 31)},
    {"metrics": {"pe_ttm": {"value": 20.0, "unit": "percent"}}},
    {"metrics": {"pe_ttm": {"value": None, "unit": "multiple"}}},
    {"metrics": {"pe_ttm": {"value": float("inf"), "unit": "multiple"}}},
])
def test_rejects_valuation_lookahead_units_and_unexplained_missing(updates):
    base = {"kind": "valuation_snapshot", "symbol": "600519", "market": "SSE", "currency": "CNY",
            "provider": "test", "retrieved_at": datetime.now(timezone.utc), "data_mode": "real",
            "as_of_date": date(2026, 11, 10), "metrics": {"pe_ttm": {"value": 20.0, "unit": "multiple"}}}
    with pytest.raises(ValidationError):
        ValuationDataset.model_validate({**base, **updates})


def test_json_reference_roundtrip_and_unadjusted_benchmark():
    from src.datasets import DatasetRef
    store = DatasetStore()
    ref = store.put(prices(symbol="000300", asset_type="index", adjustment="none", volume_unit="not_available"))
    assert DatasetRef.model_validate_json(ref.model_dump_json()) == ref
    assert store.get(ref.dataset_id).asset_type == "index"
