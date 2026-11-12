"""Numerical analytics tests with tiny known datasets; no LLM/API."""
import json
from datetime import date, datetime, timezone

import pytest

from src.datasets import DatasetStore, PriceDataset
from src.analytics_artifacts import AnalysisStore
from src.analytics_tools import analyze_price_performance, compare_with_benchmark


def dataset(store, closes, symbol="600519", asset_type="stock", dates=None, adjustment="qfq"):
    return store.put(PriceDataset(kind="price_history", symbol=symbol, market="CN", currency="CNY",
        provider="test", retrieved_at=datetime.now(timezone.utc), data_mode="real", asset_type=asset_type,
        frequency="daily", adjustment=adjustment, price_unit="points" if asset_type == "index" else "CNY/share",
        volume_unit="not_available", rows=[{"date": d, "close": float(p)} for d, p in zip(
            dates or [date(2025, 1, n + 1) for n in range(len(closes))], closes)]))


def context():
    datasets, analyses = DatasetStore(), AnalysisStore()
    return datasets, analyses, {"configurable": {"dataset_store": datasets, "analysis_store": analyses}}


def test_performance_returns_drawdown_volatility_and_chart_artifact():
    datasets, analyses, config = context()
    ref = dataset(datasets, [100, 110, 88, 100])
    result = json.loads(analyze_price_performance.invoke({"dataset_id": ref.dataset_id}, config=config))
    assert result["status"] == "available"
    summary = result["analysis_ref"]
    assert summary["metrics"]["period_return"] == pytest.approx(0)
    assert summary["metrics"]["max_drawdown"] == pytest.approx(-.2)
    returns = [.1, -.2, 100 / 88 - 1]
    import numpy as np
    assert summary["metrics"]["annualized_volatility"] == pytest.approx(np.std(returns, ddof=1) * np.sqrt(252))
    artifact = analyses.get(summary["analysis_id"])
    assert artifact.series["cumulative_return"][1].value == pytest.approx(.1)
    assert artifact.series["drawdown"][2].value == pytest.approx(-.2)
    assert "series" not in summary
    assert summary["metric_units"]["period_return"] == "fraction"


def test_short_history_explains_undefined_volatility():
    datasets, _, config = context()
    ref = dataset(datasets, [100, 110])
    result = json.loads(analyze_price_performance.invoke({"dataset_id": ref.dataset_id}, config=config))
    assert result["analysis_ref"]["metrics"]["annualized_volatility"] is None
    assert result["analysis_ref"]["limitations"]


def test_benchmark_beta_and_correlation_with_identical_returns():
    datasets, analyses, config = context()
    stock = dataset(datasets, [100, 110, 99, 108.9])
    bench = dataset(datasets, [200, 220, 198, 217.8], "000300", "index", adjustment="none")
    result = json.loads(compare_with_benchmark.invoke({"dataset_id": stock.dataset_id,
        "benchmark_dataset_id": bench.dataset_id}, config=config))
    metrics = result["analysis_ref"]["metrics"]
    assert metrics["beta"] == pytest.approx(1)
    assert metrics["correlation"] == pytest.approx(1)
    assert metrics["tracking_error"] == pytest.approx(0, abs=1e-12)
    assert metrics["excess_period_return"] == pytest.approx(0, abs=1e-12)
    assert analyses.get(result["analysis_ref"]["analysis_id"]).assumptions["alignment"] == "common_dates_no_fill"


def test_alignment_is_explicit_and_does_not_forward_fill():
    datasets, _, config = context()
    stock = dataset(datasets, [100, 105, 110, 120])
    bench = dataset(datasets, [200, 220, 230], "000300", "index", dates=[date(2025, 1, i) for i in [1, 3, 4]], adjustment="none")
    result = json.loads(compare_with_benchmark.invoke({"dataset_id": stock.dataset_id,
        "benchmark_dataset_id": bench.dataset_id}, config=config))
    assert result["analysis_ref"]["sample_size"] == 2
    assert result["analysis_ref"]["limitations"]


def test_zero_variance_benchmark_does_not_return_nan():
    datasets, _, config = context()
    stock = dataset(datasets, [100, 110, 105])
    bench = dataset(datasets, [100, 100, 100], "000300", "index", adjustment="none")
    result = json.loads(compare_with_benchmark.invoke({"dataset_id": stock.dataset_id,
        "benchmark_dataset_id": bench.dataset_id}, config=config))
    assert result["analysis_ref"]["metrics"]["beta"] is None
    assert result["analysis_ref"]["metrics"]["correlation"] is None
    assert "NaN" not in json.dumps(result)


def test_bad_references_context_and_sample_return_structured_errors():
    datasets, _, config = context()
    one = dataset(datasets, [100])
    for args in ({"dataset_id": "missing"}, {"dataset_id": one.dataset_id},
                 {"dataset_id": one.dataset_id, "periods_per_year": 0}):
        result = json.loads(analyze_price_performance.invoke(args, config=config))
        assert result["status"] == "unavailable"
    assert json.loads(analyze_price_performance.invoke({"dataset_id": "x"}))["status"] == "unavailable"


def test_artifacts_are_request_local_and_copied():
    datasets, analyses, config = context()
    ref = dataset(datasets, [100, 110, 105])
    result = json.loads(analyze_price_performance.invoke({"dataset_id": ref.dataset_id}, config=config))
    ident = result["analysis_ref"]["analysis_id"]
    artifact = analyses.get(ident)
    artifact.metrics["period_return"] = 999
    assert analyses.get(ident).metrics["period_return"] != 999
    with pytest.raises(KeyError):
        AnalysisStore().get(ident)


def test_currency_and_total_return_mismatches_are_rejected():
    datasets, _, config = context()
    a = dataset(datasets, [100, 110, 105])
    b = dataset(datasets, [200, 220, 210], "other", adjustment="total_return")
    result = json.loads(compare_with_benchmark.invoke({"dataset_id": a.dataset_id,
        "benchmark_dataset_id": b.dataset_id}, config=config))
    assert result["status"] == "unavailable"
    altered = datasets.get(b.dataset_id).model_dump()
    altered.update(currency="USD", adjustment="qfq")
    b = datasets.put(altered)
    result = json.loads(compare_with_benchmark.invoke({"dataset_id": a.dataset_id,
        "benchmark_dataset_id": b.dataset_id}, config=config))
    assert result["status"] == "unavailable"


def test_mock_labels_propagate_to_analysis_and_no_raw_series_in_tool_response():
    datasets, _, config = context()
    original = dataset(datasets, [100, 110, 105])
    raw = datasets.get(original.dataset_id).model_dump()
    raw["data_mode"] = "mock"
    ref = datasets.put(raw)
    result = json.loads(analyze_price_performance.invoke({"dataset_id": ref.dataset_id}, config=config))
    summary = result["analysis_ref"]
    assert any("模拟" in text for text in summary["limitations"])
    assert summary["dataset_refs"][0]["data_mode"] == "mock"
    assert "series" not in summary
    assert summary["chart_refs"]


def test_flat_asset_undefined_correlation_but_defined_zero_beta():
    datasets, _, config = context()
    asset = dataset(datasets, [100, 100, 100])
    benchmark = dataset(datasets, [100, 110, 100], "000300", "index", adjustment="none")
    result = json.loads(compare_with_benchmark.invoke({"dataset_id": asset.dataset_id,
        "benchmark_dataset_id": benchmark.dataset_id}, config=config))
    assert result["analysis_ref"]["metrics"]["beta"] == pytest.approx(0)
    assert result["analysis_ref"]["metrics"]["correlation"] is None
