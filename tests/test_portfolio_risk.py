"""Portfolio risk: constant-weight replay, VaR/CVaR methods, constraint checks, series isolation."""
import json
import math
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest
from langchain_core.messages import AIMessage

from src.core.datasets import DatasetStore, PriceDataset
from src.specialists.analytics.artifacts import AnalysisStore
from src.specialists.analytics.tools import build_return_matrix
from src.specialists.strategy import portfolio_risk
from src.specialists.strategy.agent import create_strategy_agent
from src.specialists.strategy.artifacts import StrategyStore
from src.specialists.strategy.handoff import canonical_request
from src.specialists.strategy.state import StrategyInput
from src.specialists.strategy.tools import assess_portfolio_risk, evaluate_risk_constraints

START = date(2024, 1, 1)


def put_prices(ds, symbol, seed, n=300):
    rng = np.random.default_rng(seed)
    values = 100 * np.cumprod(1 + rng.normal(0.0003, 0.015, n))
    return ds.put(PriceDataset(kind="price_history", symbol=symbol, market="SSE", currency="CNY",
        provider="test", retrieved_at=datetime.now(timezone.utc), data_mode="real", asset_type="stock",
        frequency="daily", adjustment="qfq", price_unit="CNY/share", volume_unit="not_available",
        rows=[{"date": START + timedelta(days=i), "close": float(v)} for i, v in enumerate(values)]))


def setup(symbols=("600519", "000858"), weights=(.5, .3), n=300, as_of="2026-11-13", constraints=None):
    ds, analyses, store = DatasetStore(), AnalysisStore(), StrategyStore()
    refs = [put_prices(ds, s, i, n) for i, s in enumerate(symbols)]
    matrix = json.loads(build_return_matrix.invoke({"dataset_ids": [r.dataset_id for r in refs]},
        config={"configurable": {"dataset_store": ds, "analysis_store": analyses}}))["analysis_ref"]
    raw = {"task": "评估组合风险", "dataset_refs": [r.model_dump(mode="json") for r in refs],
           "analysis_refs": [matrix], "risk_constraints": constraints or {},
           "portfolio": {"as_of_date": as_of, "currency": "CNY", "cash_weight": round(1 - sum(weights), 10),
                         "positions": [{"symbol": s, "weight": w} for s, w in zip(symbols, weights)]}}
    runtime = {"dataset_store": ds, "analysis_store": analyses, "strategy_store": store}
    request = canonical_request(raw, {"configurable": runtime})
    config = {"configurable": {**runtime, "strategy_input": request.model_dump(mode="json"), "strategy_scope": "s"}}
    returns = pd.DataFrame({s: [p.value for p in analyses.get(matrix["analysis_id"]).series[s]] for s in symbols})
    return config, store, matrix, returns


def invoke(tool, config, **args):
    return json.loads(tool.invoke(args, config=config))


# ---- pure functions ----

def test_constant_weight_portfolio_returns_treat_cash_as_zero():
    returns = pd.DataFrame({"a": [.01, -.02], "b": [.03, .01]})
    assert list(portfolio_risk.portfolio_returns(returns, {"a": .5, "b": .3})) == pytest.approx([.014, -.007])
    with pytest.raises(ValueError):
        portfolio_risk.portfolio_returns(returns, {"a": .5, "c": .3})


def test_historical_and_parametric_var_cvar_match_definitions():
    rng = np.random.default_rng(7)
    r = pd.Series(rng.normal(0.0005, 0.01, 300))
    metrics, reasons = portfolio_risk.risk_metrics(r, 252)
    q95 = np.quantile(r, .05, method="linear")
    assert metrics["historical_var_95"] == pytest.approx(-q95)
    assert metrics["historical_cvar_95"] == pytest.approx(-r[r <= q95].mean())
    mu, sigma = r.mean(), r.std(ddof=1)
    assert metrics["parametric_var_99"] == pytest.approx(-(mu - 2.3263478740408408 * sigma))
    phi = math.exp(-2.3263478740408408 ** 2 / 2) / math.sqrt(2 * math.pi)
    assert metrics["parametric_cvar_99"] == pytest.approx(sigma * phi / .01 - mu)
    assert metrics["annualized_volatility"] == pytest.approx(sigma * math.sqrt(252))
    assert not reasons


def test_sample_thresholds_null_out_unreliable_metrics():
    r = pd.Series(np.random.default_rng(1).normal(0, .01, 120))
    metrics, reasons = portfolio_risk.risk_metrics(r, 252)
    assert metrics["historical_var_95"] is not None
    assert metrics["historical_var_99"] is None and "250" in reasons["historical_var_99"]
    short, why = portfolio_risk.risk_metrics(r.iloc[:10], 252)
    assert all(value is None for value in short.values()) and why


def test_max_drawdown_is_a_positive_loss_from_the_starting_value():
    values = portfolio_risk.nav(pd.Series([.1, -.5, .2]))
    assert list(values) == pytest.approx([1.1, .55, .66])
    assert portfolio_risk.max_drawdown(values) == pytest.approx(.5)
    assert portfolio_risk.max_drawdown(portfolio_risk.nav(pd.Series([-.1, .05]))) == pytest.approx(.1)


# ---- assess_portfolio_risk ----

def test_tool_uses_authorized_matrix_and_keeps_series_out_of_artifact():
    config, store, matrix, returns = setup()
    result = invoke(assess_portfolio_risk, config, return_matrix_analysis_id=matrix["analysis_id"])
    assert result["status"] == "available"
    art = result["artifact"]
    row = art["risk_results"][0]
    expected = returns["600519"] * .5 + returns["000858"] * .3
    assert row["metrics"]["historical_var_95"] == pytest.approx(-np.quantile(expected, .05, method="linear"))
    assert row["return_matrix_analysis_id"] == matrix["analysis_id"]
    assert row["observations"] == len(expected)
    assert row["method"]["weighting"] == "constant_weight_daily_rebalanced"
    assert "series" not in art and "series" not in store.for_scope("s")[0]
    assert store.get_series(art["artifact_id"], "s")["portfolio_nav"]
    assert any("不是该组合的真实历史业绩" in item for item in art["limitations"])


def test_tool_rejects_matrix_missing_a_holding_or_after_portfolio_date_or_unauthorized():
    config, _, matrix, _ = setup()
    raw = config["configurable"]["strategy_input"]
    uncovered = {**raw, "portfolio": {**raw["portfolio"], "cash_weight": .1,
        "positions": [*raw["portfolio"]["positions"], {"symbol": "600036", "weight": .1}]}}
    for request in (uncovered, {**raw, "portfolio": {**raw["portfolio"], "as_of_date": "2024-02-01"}}):
        cfg = {"configurable": {**config["configurable"], "strategy_input": StrategyInput.model_validate_json(
            json.dumps(request)).model_dump(mode="json")}}
        assert invoke(assess_portfolio_risk, cfg, return_matrix_analysis_id=matrix["analysis_id"])["status"] == "unavailable"
    assert invoke(assess_portfolio_risk, config, return_matrix_analysis_id="analysis_unknown")["status"] == "unavailable"


# ---- portfolio constraints ----

def test_portfolio_constraints_are_checked_with_the_return_matrix():
    config, _, _, returns = setup(constraints={"max_portfolio_volatility": .05, "max_portfolio_drawdown": .99})
    checks = {c["constraint"]: c for c in invoke(evaluate_risk_constraints, config)["artifact"]["constraint_checks"]}
    vol = (returns["600519"] * .5 + returns["000858"] * .3).std(ddof=1) * math.sqrt(252)
    assert checks["max_portfolio_volatility"]["observed"] == pytest.approx(vol)
    assert checks["max_portfolio_volatility"]["status"] == ("violated" if vol > .05 else "satisfied")
    assert checks["max_portfolio_drawdown"]["status"] == "satisfied"
    assert checks["max_portfolio_volatility"]["analysis_id"]


def test_portfolio_constraints_stay_unknown_without_a_compatible_matrix():
    config, _, _, _ = setup(constraints={"max_portfolio_volatility": .2})
    raw = {**config["configurable"]["strategy_input"], "analysis_refs": []}
    cfg = {"configurable": {**config["configurable"], "strategy_input": raw}}
    check = invoke(evaluate_risk_constraints, cfg)["artifact"]["constraint_checks"][0]
    assert check["status"] == "unknown" and check["reason"]


# ---- agent forcing and result contract ----

def run_agent(config):
    def respond(messages):
        manifest = json.loads(messages[-1].content.split("\n", 1)[1])
        refs = manifest["available_references"]
        ids = refs["strategy_artifact_ids"] or refs["dataset_ids"]
        return AIMessage(content=json.dumps({"summary": "组合风险已评估", "risks": [
            {"text": "组合存在尾部损失风险", "evidence_ids": ids[:1]}]}, ensure_ascii=False))
    llm = Mock()
    llm.invoke.side_effect = respond
    with patch("src.specialists.strategy.nodes.create_llm", return_value=llm):
        return create_strategy_agent().invoke(config["configurable"]["strategy_input"], config=config)


def test_agent_forces_risk_assessment_when_portfolio_and_matrix_exist():
    config, _, matrix, _ = setup()
    result = run_agent(config)
    assert result["status"] == "completed"
    risk = result["result"]["risk_results"][0]
    assert risk["return_matrix_analysis_id"] == matrix["analysis_id"]
    assert all("series" not in artifact for artifact in result["strategy_artifacts"])
    assert result["strategy_artifacts"][0]["series_keys"] == ["portfolio_nav"]


def test_agent_does_not_force_risk_assessment_without_matrix():
    config, _, _, _ = setup()
    raw = {**config["configurable"]["strategy_input"], "analysis_refs": []}
    cfg = {"configurable": {**config["configurable"], "strategy_input": raw}}
    result = run_agent(cfg)
    assert result["result"]["risk_results"] == []
