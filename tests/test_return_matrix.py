"""build_return_matrix: common-date alignment, sample thresholds, covariance cross-checks."""
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from src.core.datasets import DatasetStore, PriceDataset, ValuationDataset
from src.specialists.analytics.artifacts import AnalysisStore
from src.specialists.analytics.tools import build_return_matrix

START = date(2024, 1, 1)


def context():
    ds, artifacts = DatasetStore(), AnalysisStore()
    return ds, artifacts, {"configurable": {"dataset_store": ds, "analysis_store": artifacts}}


def closes(seed, n=120):
    rng = np.random.default_rng(seed)
    return list(100 * np.cumprod(1 + rng.normal(0.0005, 0.02, n)))


def put(ds, symbol, values, days=None, adjustment="qfq", asset_type="stock", data_mode="real"):
    days = days or [START + timedelta(days=i) for i in range(len(values))]
    return ds.put(PriceDataset(kind="price_history", symbol=symbol, market="SSE", currency="CNY",
        provider="test", retrieved_at=datetime.now(timezone.utc), data_mode=data_mode, asset_type=asset_type,
        frequency="daily", adjustment=adjustment, price_unit="CNY/share" if asset_type == "stock" else "points",
        volume_unit="not_available", rows=[{"date": d, "close": float(v)} for d, v in zip(days, values)]))


def build(config, refs, **args):
    return json.loads(build_return_matrix.invoke({"dataset_ids": [r.dataset_id for r in refs], **args}, config=config))


def test_covariance_matches_pandas_on_common_dates():
    ds, store, config = context()
    a, b, c = closes(1), closes(2), closes(3)
    refs = [put(ds, "600519", a), put(ds, "000858", b), put(ds, "600036", c)]
    result = build(config, refs)
    assert result["status"] == "available"
    ref = result["analysis_ref"]
    returns = pd.DataFrame({"600519": a, "000858": b, "600036": c}).pct_change().iloc[1:]
    cov, corr = returns.cov(ddof=1), returns.corr()
    rows = {(r["symbol_a"], r["symbol_b"]): r for r in ref["table"]}
    assert len(rows) == 6  # Upper triangle including the diagonal.
    pair = rows[("600519", "000858")]
    assert pair["daily_covariance"] == pytest.approx(cov.loc["600519", "000858"])
    assert pair["annualized_covariance"] == pytest.approx(cov.loc["600519", "000858"] * 252)
    assert pair["correlation"] == pytest.approx(corr.loc["600519", "000858"])
    assert ref["metrics"]["600519.annualized_volatility"] == pytest.approx(returns["600519"].std(ddof=1) * np.sqrt(252))
    assert ref["metric_units"]["600519.annualized_volatility"] == "fraction"
    assert ref["sample_size"] == 119
    assert ref["assumptions"]["symbols"] == ["600519", "000858", "600036"]
    assert ref["assumptions"]["shrinkage"] == "none"


def test_alignment_uses_common_dates_without_filling_and_records_drops():
    ds, store, config = context()
    days = [START + timedelta(days=i) for i in range(120)]
    a, b = closes(1), closes(2)
    gap = [d for i, d in enumerate(days) if i not in (10, 50)]  # Two suspension days for 000858.
    refs = [put(ds, "600519", a, days), put(ds, "000858", [v for i, v in enumerate(b) if i not in (10, 50)], gap)]
    ref = build(config, refs)["analysis_ref"]
    assert ref["sample_size"] == 117  # 118 common dates -> 117 return intervals.
    assert ref["assumptions"]["observations_before_alignment"] == {"600519": 120, "000858": 118}
    assert ref["assumptions"]["dropped_dates"] == {"600519": 2, "000858": 0}
    series = store.get(ref["analysis_id"]).series["600519"]
    assert days[10].isoformat() not in {point.date for point in series}
    assert any("对齐" in item for item in ref["limitations"])


def test_series_are_stored_but_not_returned_in_reference():
    ds, store, config = context()
    ref = build(config, [put(ds, "600519", closes(1)), put(ds, "000858", closes(2))])["analysis_ref"]
    assert "series" not in ref
    assert set(store.get(ref["analysis_id"]).series) == {"600519", "000858"}


def test_single_asset_is_allowed_for_one_stock_portfolios():
    ds, _, config = context()
    ref = build(config, [put(ds, "600519", closes(1))])["analysis_ref"]
    assert len(ref["table"]) == 1 and ref["table"][0]["symbol_a"] == ref["table"][0]["symbol_b"]


@pytest.mark.parametrize("n,min_obs,ok", [(61, 60, True), (60, 60, False), (21, 20, True), (20, 20, False)])
def test_minimum_observation_threshold(n, min_obs, ok):
    ds, _, config = context()
    refs = [put(ds, "600519", closes(1, n)), put(ds, "000858", closes(2, n))]
    assert (build(config, refs, min_observations=min_obs)["status"] == "available") is ok


def test_observations_must_exceed_twice_the_asset_count():
    ds, _, config = context()
    refs = [put(ds, f"60000{i}", closes(i, 30)) for i in range(1, 7)]  # 29 returns >= 20 but 2N rule is 12.
    assert build(config, refs, min_observations=20)["status"] == "available"
    refs = [put(ds, f"6000{10 + i}", closes(i, 22)) for i in range(11)]  # 21 returns < 2 x 11.
    assert build(config, refs, min_observations=20)["status"] == "unavailable"


def test_rejects_unadjusted_or_mixed_adjustment_stocks_duplicates_and_wrong_types():
    ds, _, config = context()
    good = put(ds, "600519", closes(1))
    cases = [
        [good, put(ds, "000858", closes(2), adjustment="none")],
        [good, put(ds, "000858", closes(2), adjustment="hfq")],
        [good, put(ds, "600519", closes(2))],
    ]
    for refs in cases:
        assert build(config, refs)["status"] == "unavailable"
    valuation = ds.put(ValuationDataset(kind="valuation_snapshot", symbol="000858", market="SZSE", currency="CNY",
        provider="test", retrieved_at=datetime.now(timezone.utc), data_mode="real", as_of_date=START,
        metrics={"pb": {"value": 2., "unit": "multiple", "basis": "PB_MRQ"}}))
    assert build(config, [good, valuation])["status"] == "unavailable"


def test_unadjusted_index_may_join_adjusted_stocks():
    ds, _, config = context()
    refs = [put(ds, "600519", closes(1)), put(ds, "000300", closes(2), adjustment="none", asset_type="index")]
    assert build(config, refs)["status"] == "available"


def test_zero_variance_asset_has_null_correlation_with_reason_and_mock_is_flagged():
    ds, _, config = context()
    refs = [put(ds, "600519", closes(1), data_mode="mock"), put(ds, "000858", [50.] * 120)]
    ref = build(config, refs)["analysis_ref"]
    pair = next(r for r in ref["table"] if {r["symbol_a"], r["symbol_b"]} == {"600519", "000858"})
    assert pair["correlation"] is None and pair["missing_reason"]
    assert any("模拟" in item for item in ref["limitations"])
