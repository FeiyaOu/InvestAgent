"""rank_peers: in-sample relative position only — no composite score or direction labels."""
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from src.core.datasets import DatasetStore, PriceDataset, ValuationDataset
from src.specialists.analytics import factors
from src.specialists.analytics.artifacts import AnalysisStore
from src.specialists.analytics.tools import rank_peers

SYMBOLS = ["600519", "000858", "000568", "600809", "002304", "603369"]
DAY = date(2025, 3, 31)


def context():
    ds, artifacts = DatasetStore(), AnalysisStore()
    return ds, {"configurable": {"dataset_store": ds, "analysis_store": artifacts}}


def valuation(ds, symbol, pe=20., pb=2., ps=5., day=DAY, data_mode="real", pe_basis="PE_TTM"):
    return ds.put(ValuationDataset(kind="valuation_snapshot", symbol=symbol, market="SSE", currency="CNY",
        provider="test", retrieved_at=datetime.now(timezone.utc), data_mode=data_mode, as_of_date=day,
        metrics={"pe_ttm": {"value": pe, "unit": "multiple", "basis": pe_basis},
                 "pb": {"value": pb, "unit": "multiple", "basis": "PB_MRQ"},
                 "ps_ttm": {"value": ps, "unit": "multiple", "basis": "PS_TTM"}}))


def prices(ds, symbol, seed, n=60, start=date(2025, 1, 1)):
    rng = np.random.default_rng(seed)
    values = 100 * np.cumprod(1 + rng.normal(0.001, 0.02, n))
    return ds.put(PriceDataset(kind="price_history", symbol=symbol, market="SSE", currency="CNY",
        provider="test", retrieved_at=datetime.now(timezone.utc), data_mode="real", asset_type="stock",
        frequency="daily", adjustment="qfq", price_unit="CNY/share", volume_unit="not_available",
        rows=[{"date": start + timedelta(days=i), "close": float(v)} for i, v in enumerate(values)]))


def rank(config, price_refs=(), valuation_refs=(), **args):
    return json.loads(rank_peers.invoke({"price_dataset_ids": [r.dataset_id for r in price_refs],
        "valuation_dataset_ids": [r.dataset_id for r in valuation_refs], **args}, config=config))


def rows_for(ref, factor):
    return {row["symbol"]: row for row in ref["table"] if row["factor"] == factor}


def test_valuation_z_scores_and_percentiles_match_manual_calculation():
    ds, config = context()
    pes = [30., 20., 25., 40., 15.]
    refs = [valuation(ds, s, pe=v) for s, v in zip(SYMBOLS, pes)]
    ref = rank(config, valuation_refs=refs, factors=["pe_ttm"])["analysis_ref"]
    values = pd.Series(pes, index=SYMBOLS[:5])
    z = (values - values.mean()) / values.std(ddof=1)
    rows = rows_for(ref, "pe_ttm")
    for symbol in SYMBOLS[:5]:
        assert rows[symbol]["z_score"] == pytest.approx(z[symbol])
        assert rows[symbol]["percentile"] == pytest.approx(values.rank(pct=True)[symbol])
        assert rows[symbol]["dimension"] == "valuation" and rows[symbol]["valid_count"] == 5


def test_fewer_than_five_valid_values_yield_null_with_reason():
    ds, config = context()
    refs = [valuation(ds, s) for s in SYMBOLS[:4]]
    ref = rank(config, valuation_refs=refs, factors=["pb"])["analysis_ref"]
    assert all(row["z_score"] is None and row["percentile"] is None for row in rows_for(ref, "pb").values())
    assert any("pb" in item and "5" in item for item in ref["limitations"])


def test_nonpositive_and_unknown_basis_values_are_excluded_not_ranked():
    ds, config = context()
    refs = [valuation(ds, s, pe=v) for s, v in zip(SYMBOLS, [30., 20., -5., 40., 15., 22.])]
    refs.append(valuation(ds, "600000", pe=18., pe_basis="PE_STATIC"))
    rows = rows_for(rank(config, valuation_refs=refs, factors=["pe_ttm"])["analysis_ref"], "pe_ttm")
    assert rows["000568"]["z_score"] is None and rows["000568"]["excluded_reason"]
    assert rows["600000"]["z_score"] is None and rows["600000"]["excluded_reason"]
    assert rows["600519"]["valid_count"] == 5


def test_technical_factors_use_the_common_last_trading_date():
    ds, config = context()
    refs = [prices(ds, s, i) for i, s in enumerate(SYMBOLS[:5])]
    refs[0] = prices(ds, "600519", 0, n=62)  # Two extra later days must not be used.
    ref = rank(config, price_refs=refs, factors=["momentum", "rsi"], window=20)["analysis_ref"]
    assert ref["end_date"] == (date(2025, 1, 1) + timedelta(days=59)).isoformat()
    first = ds.get(refs[0].dataset_id)
    series = pd.Series([r.close for r in first.rows], index=[r.date.isoformat() for r in first.rows])
    expected = factors.compute_all(series, None, ["momentum"], window=20, rsi_window=14,
                                   bollinger_k=2., periods_per_year=252)["momentum"].loc[ref["end_date"]]
    assert rows_for(ref, "momentum")["600519"]["raw_value"] == pytest.approx(expected)
    assert rows_for(ref, "rsi")["600519"]["dimension"] == "technical"


def test_output_has_no_composite_score_and_states_relative_meaning():
    ds, config = context()
    refs = [valuation(ds, s, pe=10. + i) for i, s in enumerate(SYMBOLS[:5])]
    ref = rank(config, valuation_refs=refs, factors=["pe_ttm", "pb"])["analysis_ref"]
    expected = {"symbol", "security_name", "dimension", "factor", "raw_value", "z_score", "percentile",
                "valid_count", "excluded_reason"}
    assert all(set(row) == expected for row in ref["table"])
    assert not any("score" in key for key in ref["metrics"])
    assert ref["assumptions"]["composite_score"] == "not_computed"
    assert any("不代表预测" in item for item in ref["limitations"])
    assert ref["assumptions"]["percentile_method"] and ref["assumptions"]["z_score_ddof"] == 1


def test_rejects_invalid_requests():
    ds, config = context()
    good = [valuation(ds, s) for s in SYMBOLS[:5]]
    late = valuation(ds, "600000", day=DAY + timedelta(days=1))
    too_many = [valuation(ds, f"{600100 + i}") for i in range(21)]
    for kwargs in ({"valuation_refs": good + [late], "factors": ["pb"]},
                   {"valuation_refs": too_many, "factors": ["pb"]},
                   {"valuation_refs": good, "factors": ["momentum"]},
                   {"valuation_refs": good, "factors": ["magic"]},
                   {"valuation_refs": good, "factors": []},
                   {"valuation_refs": good + [valuation(ds, SYMBOLS[0])], "factors": ["pb"]}):
        assert rank(config, **kwargs)["status"] == "unavailable"


def test_mock_data_is_flagged():
    ds, config = context()
    refs = [valuation(ds, s, data_mode="mock") for s in SYMBOLS[:5]]
    ref = rank(config, valuation_refs=refs, factors=["pb"])["analysis_ref"]
    assert any("模拟" in item for item in ref["limitations"])


def test_rows_carry_the_verified_security_name():
    ds, config = context()
    refs = [ds.put(ds.get(valuation(ds, s).dataset_id).model_copy(update={"security_name": f"公司{s}"})) for s in SYMBOLS[:5]]
    rows = rows_for(rank(config, valuation_refs=refs, factors=["pb"])["analysis_ref"], "pb")
    assert rows["600519"]["security_name"] == "公司600519"
