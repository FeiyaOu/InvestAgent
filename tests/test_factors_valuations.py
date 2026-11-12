"""V1 factor, valuation acquisition/comparison tests: no live providers."""
import json
import sys
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from src.analytics_artifacts import AnalysisStore
from src.analytics_tools import compute_factors, compare_valuations
from src.datasets import DatasetStore, PriceDataset, ValuationDataset
from src.tools import get_valuation_snapshot


def context():
    ds, artifacts = DatasetStore(), AnalysisStore()
    return ds, artifacts, {"configurable": {"dataset_store": ds, "analysis_store": artifacts}}


def price(ds, closes, volumes=None):
    return ds.put(PriceDataset(kind="price_history", symbol="600519", market="SSE", currency="CNY",
        provider="test", retrieved_at=datetime.now(timezone.utc), data_mode="real", asset_type="stock",
        frequency="daily", adjustment="qfq", price_unit="CNY/share", volume_unit="shares" if volumes else "not_available",
        rows=[{"date": date(2025, 1, i+1), "close": float(v), "volume": float(volumes[i]) if volumes else None}
              for i, v in enumerate(closes)]))


def valuation(ds, symbol, pe=20., pb=2., day=date(2025, 1, 3), **updates):
    return ds.put(ValuationDataset(kind="valuation_snapshot", symbol=symbol, market="SSE", currency="CNY",
        provider="test", retrieved_at=datetime.now(timezone.utc), data_mode="real", as_of_date=day,
        metrics={"pe_ttm": {"value": pe, "unit": "multiple", "basis": "PE_TTM"},
                 "pb": {"value": pb, "unit": "multiple", "basis": "PB_MRQ"}}, **updates))


def test_factor_values_and_chart_series_are_reproducible():
    ds, store, config = context()
    ref = price(ds, [100, 110, 121], [10, 20, 30])
    result = json.loads(compute_factors.invoke({"dataset_id": ref.dataset_id, "window": 2,
        "factors": ["momentum", "sma_gap", "realized_volatility", "volume_ratio"]}, config=config))
    summary = result["analysis_ref"]
    assert summary["metrics"]["momentum"] == pytest.approx(.21)
    assert summary["metrics"]["sma_gap"] == pytest.approx(121/115.5-1)
    assert summary["metrics"]["realized_volatility"] == pytest.approx(0, abs=1e-12)
    assert summary["metrics"]["volume_ratio"] == pytest.approx(1.2)
    artifact = store.get(summary["analysis_id"])
    assert len(artifact.series["momentum"]) == 1  # No warm-up zeros.


def test_insufficient_or_missing_factor_inputs_return_null_with_reasons():
    ds, _, config = context()
    ref = price(ds, [100, 110])
    result = json.loads(compute_factors.invoke({"dataset_id": ref.dataset_id, "window": 20,
        "factors": ["momentum", "volume_ratio"]}, config=config))
    assert result["analysis_ref"]["metrics"] == {"momentum": None, "volume_ratio": None}
    assert result["analysis_ref"]["limitations"]
    assert result["analysis_ref"]["chart_refs"] == []


@pytest.mark.parametrize("args", [{"window": 1}, {"window": 999}, {"factors": ["magic"]},
    {"factors": []}, {"factors": ["momentum", "momentum"]}])
def test_invalid_factor_parameters(args):
    ds, _, config = context()
    ref = price(ds, [100, 110, 120])
    result = json.loads(compute_factors.invoke({"dataset_id": ref.dataset_id, **args}, config=config))
    assert result["status"] == "unavailable"


def test_comparison_retains_rows_and_computes_spread_without_recommendation():
    ds, store, config = context()
    a, b = valuation(ds, "600519"), valuation(ds, "000858", pe=10., pb=1.)
    result = json.loads(compare_valuations.invoke({"dataset_ids": [a.dataset_id, b.dataset_id]}, config=config))
    ref = result["analysis_ref"]
    assert ref["metrics"]["pe_ttm.spread"] == 10.
    assert ref["metrics"]["pe_ttm.median"] == 15.
    assert len(store.get(ref["analysis_id"]).table) == 4
    assert ref["assumptions"]["sample_size_unit"] == "companies"
    assert ref["limitations"]


def test_negative_pe_is_not_ranked_and_missing_dividend_is_not_zero():
    ds, _, config = context()
    a, b = valuation(ds, "600519", pe=-10.), valuation(ds, "000858")
    result = json.loads(compare_valuations.invoke({"dataset_ids": [a.dataset_id, b.dataset_id],
        "metrics": ["pe_ttm", "dividend_yield"]}, config=config))
    ref = result["analysis_ref"]
    assert ref["metrics"]["pe_ttm.spread"] is None
    rows = ref["table"]
    pe = next(r for r in rows if r["symbol"] == "600519" and r["metric"] == "pe_ttm")
    assert pe["value"] is None and pe["raw_value"] == -10.
    assert all(r["value"] is None for r in rows if r["metric"] == "dividend_yield")


def test_mismatched_dates_and_duplicate_symbols_rejected():
    ds, _, config = context()
    a = valuation(ds, "600519")
    for b in (valuation(ds, "600519"), valuation(ds, "000858", day=date(2025, 1, 2))):
        result = json.loads(compare_valuations.invoke({"dataset_ids": [a.dataset_id, b.dataset_id]}, config=config))
        assert result["status"] == "unavailable"


def test_unknown_metric_basis_does_not_produce_comparable_spread():
    ds, _, config = context()
    a, b = valuation(ds, "600519"), valuation(ds, "000858")
    raw = ds.get(b.dataset_id).model_dump()
    raw["metrics"]["pb"]["basis"] = None
    b = ds.put(raw)
    ref = json.loads(compare_valuations.invoke({"dataset_ids": [a.dataset_id, b.dataset_id]}, config=config))["analysis_ref"]
    assert ref["metrics"]["pb.spread"] is None
    assert ref["metrics"]["pe_ttm.spread"] == 0.


def test_acquisition_uses_ttm_not_static_and_actual_observation_day(monkeypatch):
    monkeypatch.setenv("USE_REAL_DATA", "true")
    ds, _, config = context()
    provider = Mock(); provider.stock_value_em.return_value = pd.DataFrame({
        "数据日期": ["2025-01-02", "2025-01-03", "2025-01-06"],
        "PE(TTM)": [20., 21., 22.], "PE(静)": [999., 999., 999.], "市净率": [2., 2.1, 2.2]})
    with patch.dict(sys.modules, {"akshare": provider}):
        result = json.loads(get_valuation_snapshot.invoke({"query": "茅台", "as_of_date": "2025-01-05"}, config=config))
    assert result["status"] == "available"
    data = ds.get(result["dataset_ref"]["dataset_id"])
    assert data.as_of_date == date(2025, 1, 3)
    assert data.metrics["pe_ttm"].value == 21.
    assert data.metrics["pb"].basis == "PB_MRQ"
    assert data.metrics["dividend_yield"].value is None
    assert data.available_at is None


def test_acquisition_mock_and_provider_failure_are_explicit(monkeypatch):
    ds, _, config = context()
    monkeypatch.setenv("USE_REAL_DATA", "false")
    result = json.loads(get_valuation_snapshot.invoke({"query": "五粮液", "as_of_date": "2025-01-03"}, config=config))
    assert result["dataset_ref"]["data_mode"] == "mock"
    monkeypatch.setenv("USE_REAL_DATA", "true")
    provider = Mock(); provider.stock_value_em.side_effect = RuntimeError("secret")
    with patch.dict(sys.modules, {"akshare": provider}):
        result = json.loads(get_valuation_snapshot.invoke({"query": "茅台"}, config=config))
    assert result["status"] == "unavailable" and "dataset_ref" not in result
    assert "secret" not in str(result)


def test_trailing_factors_do_not_change_when_future_rows_are_added():
    ds, store, config = context()
    prefix = price(ds, [100, 110, 121])
    full = price(ds, [100, 110, 121, 40, 50])
    refs = [json.loads(compute_factors.invoke({"dataset_id": ref.dataset_id, "window": 2}, config=config))["analysis_ref"]
            for ref in (prefix, full)]
    a, b = (store.get(ref["analysis_id"]) for ref in refs)
    for key in a.series:
        assert a.series[key] == b.series[key][:len(a.series[key])]


def test_zero_volume_does_not_create_infinite_factor():
    ds, _, config = context()
    ref = price(ds, [100, 110, 120], [0, 0, 0])
    result = json.loads(compute_factors.invoke({"dataset_id": ref.dataset_id, "window": 2,
        "factors": ["volume_ratio"]}, config=config))
    assert result["analysis_ref"]["metrics"]["volume_ratio"] is None
    assert result["analysis_ref"]["chart_refs"] == []


def test_static_pe_is_never_substituted_and_duplicate_dates_fail(monkeypatch):
    monkeypatch.setenv("USE_REAL_DATA", "true")
    ds, _, config = context()
    provider = Mock()
    provider.stock_value_em.return_value = pd.DataFrame({"数据日期": ["2025-01-03"], "PE(静)": [9.], "市净率": [2.]})
    with patch.dict(sys.modules, {"akshare": provider}):
        result = json.loads(get_valuation_snapshot.invoke({"query": "茅台", "as_of_date": "2025-01-03"}, config=config))
        assert result["metrics"]["pe_ttm"]["value"] is None
        provider.stock_value_em.return_value = pd.concat([provider.stock_value_em.return_value] * 2)
        result = json.loads(get_valuation_snapshot.invoke({"query": "茅台", "as_of_date": "2025-01-03"}, config=config))
        assert result["status"] == "unavailable"


def test_wrong_dataset_type_and_missing_reference_are_rejected():
    ds, _, config = context()
    ref = price(ds, [100, 110, 120])
    other = valuation(ds, "000858")
    assert json.loads(compare_valuations.invoke({"dataset_ids": [ref.dataset_id, other.dataset_id]}, config=config))["status"] == "unavailable"
    assert json.loads(compute_factors.invoke({"dataset_id": other.dataset_id}, config=config))["status"] == "unavailable"
    assert json.loads(compare_valuations.invoke({"dataset_ids": ["missing", "other"]}, config=config))["status"] == "unavailable"


def test_matching_but_unknown_or_static_pe_basis_is_not_ttm_comparison():
    ds, _, config = context()
    refs = []
    for symbol in ("600519", "000858"):
        original = valuation(ds, symbol)
        raw = ds.get(original.dataset_id).model_dump()
        raw["metrics"]["pe_ttm"]["basis"] = "PE_STATIC"
        refs.append(ds.put(raw).dataset_id)
    result = json.loads(compare_valuations.invoke({"dataset_ids": refs}, config=config))
    assert result["analysis_ref"]["metrics"]["pe_ttm.spread"] is None
