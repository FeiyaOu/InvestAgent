"""RSI / MACD / Bollinger / turnover factors: verified against independent calculations."""
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from src.core.datasets import DatasetStore, PriceDataset
from src.specialists.analytics import factors
from src.specialists.analytics.artifacts import AnalysisStore
from src.specialists.analytics.tools import compute_factors

CLOSES = [100, 102, 101, 105, 107, 106, 110, 108, 111, 115, 113, 116, 118, 117, 120,
          119, 122, 125, 123, 126, 128, 127, 130, 129, 133, 135, 134, 137, 136, 140,
          142, 141, 144, 146, 145, 148, 150, 149, 152, 155]


def context():
    ds, artifacts = DatasetStore(), AnalysisStore()
    return ds, {"configurable": {"dataset_store": ds, "analysis_store": artifacts}}


def put_prices(ds, closes, turnovers=None):
    start = date(2025, 1, 1)
    return ds.put(PriceDataset(kind="price_history", symbol="600519", market="SSE", currency="CNY",
        provider="test", retrieved_at=datetime.now(timezone.utc), data_mode="real", asset_type="stock",
        frequency="daily", adjustment="qfq", price_unit="CNY/share", volume_unit="not_available",
        turnover_unit="fraction" if turnovers else "not_available",
        rows=[{"date": start + timedelta(days=i), "close": float(v),
               "turnover": turnovers[i] if turnovers else None} for i, v in enumerate(closes)]))


def run(ds, config, ref, **args):
    return json.loads(compute_factors.invoke({"dataset_id": ref.dataset_id, **args}, config=config))


def wilder_rsi(closes, window):
    """Independent loop implementation of Wilder's RSI for cross-checking."""
    changes = np.diff(closes)
    gain, loss = np.clip(changes, 0, None), np.clip(-changes, 0, None)
    avg_gain, avg_loss = gain[:window].mean(), loss[:window].mean()
    for up, down in zip(gain[window:], loss[window:]):
        avg_gain = (avg_gain * (window - 1) + up) / window
        avg_loss = (avg_loss * (window - 1) + down) / window
    return 100 - 100 / (1 + avg_gain / avg_loss)


def test_rsi_matches_independent_wilder_implementation():
    series = pd.Series(CLOSES, dtype=float)
    result = factors.rsi(series, 14)
    assert result.iloc[-1] == pytest.approx(wilder_rsi(np.array(CLOSES, dtype=float), 14))
    assert result.iloc[:14].isna().all() and not np.isnan(result.iloc[14])  # Needs window + 1 prices.


def test_rsi_is_100_without_losses_and_undefined_without_changes():
    assert factors.rsi(pd.Series(range(1, 20), dtype=float), 5).iloc[-1] == 100
    assert np.isnan(factors.rsi(pd.Series([10.] * 20), 5).iloc[-1])


def test_macd_histogram_is_normalized_by_price_after_warmup():
    series = pd.Series(CLOSES, dtype=float)
    out = factors.macd(series, 12, 26, 9)
    fast = series.ewm(span=12, adjust=False).mean()
    slow = series.ewm(span=26, adjust=False).mean()
    line = fast - slow
    hist = line - line.ewm(span=9, adjust=False).mean()
    assert out["macd_hist_pct"].iloc[-1] == pytest.approx(hist.iloc[-1] / CLOSES[-1])
    assert out["macd_hist"].iloc[-1] == pytest.approx(hist.iloc[-1])
    assert out["macd_hist_pct"].iloc[:34].isna().all() and not np.isnan(out["macd_hist_pct"].iloc[34])


def test_bollinger_pct_b_uses_sample_std_and_handles_flat_band():
    series = pd.Series(CLOSES, dtype=float)
    window = series.iloc[-20:]
    mid, sd = window.mean(), window.std(ddof=1)
    expected = (CLOSES[-1] - (mid - 2 * sd)) / (4 * sd)
    assert factors.bollinger_pct_b(series, 20, 2.).iloc[-1] == pytest.approx(expected)
    assert np.isnan(factors.bollinger_pct_b(pd.Series([10.] * 25), 20, 2.).iloc[-1])


def test_compute_factors_reports_new_factors_with_units_and_parameters():
    ds, config = context()
    turnovers = [0.01 + i * 0.001 for i in range(len(CLOSES))]
    ref = put_prices(ds, CLOSES, turnovers)
    result = run(ds, config, ref, factors=["rsi", "macd_hist_pct", "bollinger_pct_b", "turnover"], window=20)
    art = result["analysis_ref"]
    assert art["metric_units"] == {"rsi": "index_0_100", "macd_hist_pct": "fraction",
                                   "bollinger_pct_b": "dimensionless", "turnover": "fraction"}
    assert art["metrics"]["turnover"] == pytest.approx(np.mean(turnovers[-20:]))
    assert art["assumptions"]["rsi_window"] == 14 and art["assumptions"]["bollinger_k"] == 2.
    assert art["assumptions"]["macd_spans"] == [12, 26, 9]
    keys = {chart["series_key"] for chart in art["chart_refs"]}
    assert {"macd", "macd_signal", "macd_hist"} <= keys


def test_short_history_and_missing_turnover_return_null_with_reasons():
    ds, config = context()
    ref = put_prices(ds, CLOSES[:20])
    art = run(ds, config, ref, factors=["macd_hist_pct", "turnover"])["analysis_ref"]
    assert art["metrics"] == {"macd_hist_pct": None, "turnover": None}
    text = " ".join(art["limitations"])
    assert "macd_hist_pct" in text and "turnover" in text


@pytest.mark.parametrize("args", [{"rsi_window": 1}, {"rsi_window": 101}, {"bollinger_k": 0}, {"bollinger_k": 5}])
def test_invalid_new_parameters_are_rejected(args):
    ds, config = context()
    ref = put_prices(ds, CLOSES)
    assert run(ds, config, ref, factors=["rsi", "bollinger_pct_b"], **args)["status"] == "unavailable"


def test_non_integer_rsi_window_is_rejected_by_tool_schema():
    from pydantic import ValidationError
    ds, config = context()
    ref = put_prices(ds, CLOSES)
    with pytest.raises(ValidationError):  # ToolNode turns this into a visible tool error.
        run(ds, config, ref, factors=["rsi"], rsi_window=14.5)


def test_new_factors_have_no_lookahead():
    ds, config = context()
    names = ["rsi", "macd_hist_pct", "bollinger_pct_b"]
    short = run(ds, config, put_prices(ds, CLOSES[:-3]), factors=names)["analysis_ref"]
    series = factors.compute_all(pd.Series(CLOSES, dtype=float), None, names, window=20, rsi_window=14,
                                 bollinger_k=2., periods_per_year=252)
    for name in names:
        assert series[name].iloc[-4] == pytest.approx(short["metrics"][name])
