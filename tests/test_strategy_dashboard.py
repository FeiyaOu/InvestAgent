"""Strategy dashboard: risk cards, NAV chart and replay rows render from validated payloads."""
from app.strategy_dashboard import build_strategy_figures, render_strategy_task


def record(**result):
    base = {"summary": "组合风险评估", "risk_results": [], "scenario_results": []}
    return {"task_id": "s", "question": "评估组合风险", "status": "partial", "error": None, "result": {**base, **result}}


def test_nav_and_replay_series_become_figures():
    series = {"strategy_1": {"portfolio_nav": [{"date": "2025-01-01", "value": 1.0}, {"date": "2025-01-02", "value": .98}]},
              "strategy_2": {"portfolio_value": [{"date": "2015-06-12", "value": 1.0}, {"date": "2015-08-26", "value": .7}]}}
    figures = build_strategy_figures(series)
    assert [kind for kind, _ in figures] == ["strategy_1_portfolio_nav", "strategy_2_portfolio_value"]
    assert list(figures[0][1].data[0].y) == [1.0, .98]


def test_incomplete_replay_and_null_metrics_render_without_formatting_none():
    scenario = {"scenario_id": "2015_crash", "name": "2015 股灾", "origin": "historical_replay",
                "start_date": "2015-06-12", "end_date": "2015-08-26", "as_of_date": "2026-11-13", "currency": "CNY",
                "portfolio_return": None, "max_drawdown": None, "coverage_weight": .6, "contributions": []}
    risk = {"return_matrix_analysis_id": "analysis_1", "observations": 120, "start_date": "2025-01-01",
            "end_date": "2025-06-30", "metrics": {"historical_var_99": None, "historical_var_95": .02},
            "reasons": {"historical_var_99": "收益观察数120少于250个"}, "units": {}, "method": {}}
    render_strategy_task("s", record(scenario_results=[scenario], risk_results=[risk]), series={})
