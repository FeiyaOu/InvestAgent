"""Chart correctness and artifact identity, without model/API calls."""
from datetime import datetime, timezone

import pytest

from app.analytics_dashboard import build_analysis_figures, format_metric, resolve_artifact
from src.specialists.analytics.artifacts import AnalysisArtifact


def artifact(**updates):
    return AnalysisArtifact(analysis_id="a1", tool_name="analyze_price_performance",
        dataset_refs=[{"dataset_id": "d1", "symbol": "600519", "data_mode": "real"}],
        created_at=datetime.now(timezone.utc), start_date="2025-01-01", end_date="2025-01-03", sample_size=2,
        metrics={"period_return": -.01, "max_drawdown": -.1}, metric_units={"period_return": "fraction", "max_drawdown": "fraction"},
        assumptions={"periods_per_year": 252}, limitations=["历史不代表未来"],
        **({"series": {"cumulative_return": [{"date": "2025-01-01", "value": 0.}, {"date": "2025-01-03", "value": -.01}],
            "drawdown": [{"date": "2025-01-01", "value": 0.}, {"date": "2025-01-03", "value": -.1}]}} | updates))


def test_performance_figures_plot_actual_values_without_percentage_rescaling():
    figures = build_analysis_figures(artifact())
    assert len(figures) == 2
    cumulative, drawdown = [fig for _, fig in figures]
    assert list(cumulative.data[0].y) == [0., -.01]
    assert list(drawdown.data[0].y) == [0., -.1]
    assert cumulative.layout.yaxis.tickformat == ".1%"
    assert format_metric(.05, "fraction") == "5.00%"
    assert format_metric(2., "percent") == "2.00%"
    assert format_metric(None, "multiple") == "不可用"


def test_benchmark_series_share_one_comparison_figure():
    data = artifact(series={"asset_cumulative_return": [{"date": "2025-01-01", "value": .1}],
                            "benchmark_cumulative_return": [{"date": "2025-01-01", "value": .05}]})
    figures = build_analysis_figures(data)
    assert len(figures) == 1
    assert len(figures[0][1].data) == 2


def test_valuation_bars_skip_missing_values_but_preserve_artifact_table():
    data = artifact(series={}, table=[{"symbol": "600519", "metric": "pe_ttm", "value": 20., "unit": "multiple", "basis": "PE_TTM"},
        {"symbol": "000858", "metric": "pe_ttm", "value": None, "unit": "multiple", "basis": "PE_TTM", "missing_reason": "不适用"}])
    figures = build_analysis_figures(data)
    assert list(figures[0][1].data[0].y) == [20.]
    assert len(data.table) == 2


def test_snapshot_resolution_is_task_scoped_and_checks_identity():
    data = artifact().model_dump(mode="json")
    assert resolve_artifact("a1", {"a1": data}, {"d1"}).analysis_id == "a1"
    for ident, snapshots, allowed in (("a2", {"a1": data}, {"d1"}),
        ("a2", {"a2": data}, {"d1"}), ("a1", {"a1": data}, {"foreign"})):
        with pytest.raises(ValueError):
            resolve_artifact(ident, snapshots, allowed)


def test_empty_series_and_table_do_not_create_placeholder_charts():
    assert build_analysis_figures(artifact(series={})) == []


def test_peer_tables_group_by_dimension_and_show_position_only():
    from app.analytics_dashboard import build_peer_tables
    table = [{"symbol": "600519", "dimension": "valuation", "factor": "pe_ttm", "raw_value": 30., "z_score": 1.2,
              "percentile": .8, "valid_count": 5, "excluded_reason": None},
             {"symbol": "000858", "dimension": "valuation", "factor": "pe_ttm", "raw_value": -3., "z_score": None,
              "percentile": None, "valid_count": 5, "excluded_reason": "非正PE"},
             {"symbol": "600519", "dimension": "technical", "factor": "rsi", "raw_value": 55., "z_score": None,
              "percentile": None, "valid_count": 3, "excluded_reason": None}]
    tables = build_peer_tables(table)
    assert set(tables) == {"valuation", "technical"}
    rows = {row["标的"]: row for row in tables["valuation"]}
    assert rows["600519"]["pe_ttm"] == "z=1.20 · 80%"
    assert rows["000858"]["pe_ttm"] == "不可比"


def test_return_matrix_correlation_heatmap_uses_table_values():
    data = AnalysisArtifact(analysis_id="m1", tool_name="build_return_matrix", dataset_refs=[],
        created_at=datetime.now(timezone.utc), start_date="2025-01-01", end_date="2025-06-30", sample_size=120,
        series={}, metrics={}, metric_units={}, assumptions={}, limitations=[], table=[
        {"symbol_a": "600519", "symbol_b": "600519", "correlation": 1.0},
        {"symbol_a": "600519", "symbol_b": "000858", "correlation": .6},
        {"symbol_a": "000858", "symbol_b": "000858", "correlation": 1.0}])
    figures = dict(build_analysis_figures(data))
    heat = figures["correlation"].data[0]
    assert list(heat.x) == ["600519", "000858"] and heat.z[0][1] == .6 and heat.z[1][0] == .6


def test_peer_table_labels_include_security_name():
    from app.analytics_dashboard import build_peer_tables
    tables = build_peer_tables([{"symbol": "600809", "security_name": "山西汾酒", "dimension": "valuation",
        "factor": "pb", "raw_value": 7., "z_score": .5, "percentile": .6, "valid_count": 5, "excluded_reason": None}])
    assert tables["valuation"][0]["标的"] == "600809 山西汾酒"
