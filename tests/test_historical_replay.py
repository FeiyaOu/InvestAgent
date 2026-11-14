"""Historical scenario replay: fixed catalogue, buy-and-hold over the window, no proxies."""
import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from src.core.datasets import DatasetStore, PriceDataset
from src.specialists.analytics.artifacts import AnalysisStore
from src.specialists.strategy import portfolio_risk
from src.specialists.strategy.agent import create_strategy_agent
from src.specialists.strategy.artifacts import StrategyStore
from src.specialists.strategy.handoff import canonical_request
from src.specialists.strategy.state import StrategyParameters
from src.specialists.strategy.tools import replay_historical_scenario


def put(ds, symbol, start, end, step=0.002, crash=None, asset_type="stock", adjustment="qfq"):
    """Daily closes rising by `step`; optional (from, to, daily) crash segment inside the range."""
    rows, price, day = [], 100., start
    while day <= end:
        if crash and crash[0] <= day <= crash[1]:
            price *= 1 + crash[2]
        else:
            price *= 1 + step
        rows.append({"date": day, "close": round(price, 6)})
        day += timedelta(days=1)
    return ds.put(PriceDataset(kind="price_history", symbol=symbol, currency="CNY", provider="test",
        market="CN_INDEX" if asset_type == "index" else "SSE", retrieved_at=datetime.now(timezone.utc),
        data_mode="real", asset_type=asset_type, frequency="daily", adjustment=adjustment,
        price_unit="points" if asset_type == "index" else "CNY/share", volume_unit="not_available", rows=rows))


def setup(refs_fn, weights=(("600519", .6), ("000858", .3)), scenarios=("2015_crash",), portfolio=True):
    ds, store = DatasetStore(), StrategyStore()
    refs = refs_fn(ds)
    raw = {"task": "如果2015年股灾重演，我的组合会怎样", "dataset_refs": [r.model_dump(mode="json") for r in refs],
           "historical_scenarios": list(scenarios)}
    if portfolio:
        raw["portfolio"] = {"as_of_date": "2026-11-13", "currency": "CNY", "cash_weight": round(1 - sum(w for _, w in weights), 10),
                            "positions": [{"symbol": s, "weight": w} for s, w in weights]}
    runtime = {"dataset_store": ds, "analysis_store": AnalysisStore(), "strategy_store": store}
    request = canonical_request(raw, {"configurable": runtime})
    return {"configurable": {**runtime, "strategy_input": request.model_dump(mode="json"), "strategy_scope": "s"}}, ds, store


def replay(config, key="2015_crash"):
    return json.loads(replay_historical_scenario.invoke({"scenario_key": key}, config=config))


def window_return(ds, ref, start, end):
    rows = [r for r in ds.get(ref.dataset_id).rows if start <= r.date <= end]
    return rows[-1].close / rows[0].close - 1


def test_catalogue_is_fixed_and_dates_are_code_owned():
    assert set(portfolio_risk.HISTORICAL_SCENARIOS) == {"2008_gfc", "2015_crash", "2020_covid"}
    windows = {key: (start, end) for key, (_, start, end) in portfolio_risk.HISTORICAL_SCENARIOS.items()}
    assert windows == {"2008_gfc": (date(2007, 10, 16), date(2008, 11, 4)),  # Closing-price extremes,
                       "2015_crash": (date(2015, 6, 12), date(2015, 8, 26)),  # verified against SSE Composite
                       "2020_covid": (date(2020, 1, 13), date(2020, 3, 23))}  # in acceptance round 1.


def test_full_coverage_replays_buy_and_hold_with_cash_at_zero():
    refs = {}
    def make(ds):
        refs["a"] = put(ds, "600519", date(2015, 5, 1), date(2015, 9, 30), crash=(date(2015, 6, 15), date(2015, 7, 8), -.03))
        refs["b"] = put(ds, "000858", date(2015, 5, 1), date(2015, 9, 30), crash=(date(2015, 6, 20), date(2015, 7, 3), -.02))
        return list(refs.values())
    config, ds, store = setup(make)
    result = replay(config)
    row = result["artifact"]["scenario_results"][0]
    start, end = date(2015, 6, 12), date(2015, 8, 26)
    ra, rb = window_return(ds, refs["a"], start, end), window_return(ds, refs["b"], start, end)
    assert row["scenario_id"] == "2015_crash" and row["origin"] == "historical_replay"
    assert row["portfolio_return"] == pytest.approx(.6 * ra + .3 * rb)
    assert row["coverage_weight"] == pytest.approx(.9)
    assert row["max_drawdown"] > 0
    assert row["start_date"] == "2015-06-12" and row["end_date"] == "2015-08-26"
    assert store.get_series(result["artifact"]["artifact_id"], "s")["portfolio_value"]
    assert any("不代表未来" in item for item in result["artifact"]["limitations"])


def test_holding_listed_after_scenario_start_blocks_portfolio_number_without_proxy():
    def make(ds):
        return [put(ds, "600519", date(2015, 5, 1), date(2015, 9, 30)),
                put(ds, "000858", date(2015, 7, 20), date(2015, 9, 30))]
    config, _, _ = setup(make)
    row = replay(config)["artifact"]["scenario_results"][0]
    assert row["portfolio_return"] is None and row["max_drawdown"] is None
    assert row["coverage_weight"] == pytest.approx(.6)
    late = next(c for c in row["contributions"] if c["symbol"] == "000858")
    assert late["status"] == "not_covered" and late["reason"] and late["period_return"] is None


def test_recent_only_or_unadjusted_data_is_not_used():
    def make(ds):
        return [put(ds, "600519", date(2024, 1, 1), date(2024, 12, 31)),
                put(ds, "000858", date(2015, 5, 1), date(2015, 9, 30), adjustment="none")]
    config, _, _ = setup(make)
    rows = {c["symbol"]: c for c in replay(config)["artifact"]["scenario_results"][0]["contributions"]}
    assert rows["600519"]["status"] == "not_covered"
    assert rows["000858"]["status"] == "not_covered" and "复权" in rows["000858"]["reason"]


def test_benchmark_index_return_is_attached_for_context():
    def make(ds):
        return [put(ds, "600519", date(2015, 5, 1), date(2015, 9, 30)),
                put(ds, "000858", date(2015, 5, 1), date(2015, 9, 30)),
                put(ds, "000001", date(2015, 5, 1), date(2015, 9, 30), asset_type="index", adjustment="none")]
    config, _, _ = setup(make)
    row = replay(config)["artifact"]["scenario_results"][0]
    assert [b["symbol"] for b in row["benchmarks"]] == ["000001"]
    assert all(c["symbol"] != "000001" for c in row["contributions"])


def test_requires_portfolio_and_rejects_unknown_keys():
    config, _, _ = setup(lambda ds: [put(ds, "600519", date(2015, 5, 1), date(2015, 9, 30))], portfolio=False)
    assert replay(config)["status"] == "unavailable"
    with pytest.raises(ValidationError):
        replay(config, key="1929_crash")


def test_parameter_accepts_known_unique_keys_only():
    assert StrategyParameters.model_validate({"historical_scenarios": None}).historical_scenarios == []
    for bad in (["2015_crash", "2015_crash"], ["1987_crash"]):
        with pytest.raises(ValidationError):
            StrategyParameters.model_validate({"historical_scenarios": bad})


def test_agent_forces_requested_replays_and_reports_incomplete_coverage():
    def make(ds):
        return [put(ds, "600519", date(2015, 5, 1), date(2015, 9, 30)),
                put(ds, "000858", date(2015, 7, 20), date(2015, 9, 30))]
    config, _, _ = setup(make, scenarios=("2015_crash",))
    def respond(messages):
        refs = json.loads(messages[-1].content.split("\n", 1)[1])["available_references"]
        return AIMessage(content=json.dumps({"summary": "情景重演完成", "risks": [
            {"text": "股灾期间回撤明显", "evidence_ids": refs["strategy_artifact_ids"][:1]}]}, ensure_ascii=False))
    llm = Mock()
    llm.invoke.side_effect = respond
    with patch("src.specialists.strategy.nodes.create_llm", return_value=llm):
        result = create_strategy_agent().invoke(config["configurable"]["strategy_input"], config=config)
    scenario = result["result"]["scenario_results"][0]
    assert scenario["scenario_id"] == "2015_crash"
    assert result["status"] == "partial"
    assert any("2015_crash" in item for item in result["result"]["missing_information"])
