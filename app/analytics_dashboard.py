"""Streamlit/Plotly presentation over immutable, task-scoped analysis snapshots."""
import json
import math

import plotly.graph_objects as go
import streamlit as st

from src.specialists.analytics.artifacts import AnalysisArtifact

_LABELS = {"period_return": "区间收益", "annualized_volatility": "年化波动率", "max_drawdown": "最大回撤",
    "asset_period_return": "标的收益", "benchmark_period_return": "基准收益", "excess_period_return": "超额区间收益",
    "beta": "Beta", "correlation": "相关系数", "tracking_error": "年化跟踪误差",
    "momentum": "动量", "sma_gap": "均线偏离", "realized_volatility": "滚动年化波动率", "volume_ratio": "量比",
    "rsi": "RSI", "macd_hist_pct": "MACD柱/收盘价", "bollinger_pct_b": "布林带位置 %B", "turnover": "平均换手率"}
_SERIES = {"cumulative_return": "累计价格收益", "drawdown": "历史回撤",
           "asset_cumulative_return": "标的", "benchmark_cumulative_return": "基准"}


def format_metric(value, unit):
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return "不可用"
    if unit == "fraction":
        return f"{value:.2%}"
    if unit == "percent":
        return f"{value:.2f}%"
    if unit == "multiple":
        return f"{value:.2f} 倍"
    return f"{value:.4g}"


def resolve_artifact(ident, snapshots, allowed_dataset_ids):
    try:
        data = AnalysisArtifact.model_validate_json(json.dumps(snapshots[ident], ensure_ascii=False, allow_nan=False))
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("图表产物缺失或无效") from exc
    if data.analysis_id != ident or not {ref["dataset_id"] for ref in data.dataset_refs} <= allowed_dataset_ids:
        raise ValueError("图表产物身份或数据范围不匹配")
    return data


def _layout(figure, title, unit="fraction"):
    figure.update_layout(title=title, template="plotly_white", height=340, margin=dict(l=20, r=20, t=50, b=20),
                         hovermode="x unified", legend=dict(orientation="h", y=1.12))
    figure.update_xaxes(title=None)
    figure.update_yaxes(title={"fraction": "收益率 / 比例", "percent": "百分比", "multiple": "倍", "dimensionless": "比值"}.get(unit, unit), tickformat=".1%" if unit == "fraction" else None,
                       ticksuffix="%" if unit == "percent" else None)
    return figure


def build_peer_tables(table):
    """{dimension: rows} with one column per factor; cells show in-sample position only."""
    grouped = {}
    for row in table:
        rows = grouped.setdefault(row["dimension"], {})
        cell = "不可比" if row.get("excluded_reason") else "不可用" if row.get("percentile") is None else (
            f"z={row['z_score']:.2f} · {row['percentile']:.0%}" if row.get("z_score") is not None
            else f"z=不可用 · {row['percentile']:.0%}")
        label = " ".join(filter(None, (row["symbol"], row.get("security_name"))))
        rows.setdefault(row["symbol"], {"标的": label})[row["factor"]] = cell
    return {dimension: list(rows.values()) for dimension, rows in grouped.items()}


def _correlation_figure(table):
    symbols = list(dict.fromkeys([row["symbol_a"] for row in table] + [row["symbol_b"] for row in table]))
    index = {symbol: i for i, symbol in enumerate(symbols)}
    z = [[None] * len(symbols) for _ in symbols]
    for row in table:
        i, j = index[row["symbol_a"]], index[row["symbol_b"]]
        z[i][j] = z[j][i] = row.get("correlation")
    figure = go.Figure(go.Heatmap(x=symbols, y=symbols, z=z, zmin=-1, zmax=1, colorscale="RdBu", reversescale=True))
    figure.update_layout(title="收益相关系数（历史样本）", template="plotly_white", height=360,
                         margin=dict(l=20, r=20, t=50, b=20))
    return figure


def build_analysis_figures(artifact: AnalysisArtifact):
    """Plot numeric series without inferring values from LLM prose."""
    figures, consumed = [], set()
    if artifact.tool_name == "build_return_matrix" and artifact.table:
        return [("correlation", _correlation_figure(artifact.table))]
    benchmark_keys = ("asset_cumulative_return", "benchmark_cumulative_return")
    if any(artifact.series.get(key) for key in benchmark_keys):
        figure = go.Figure()
        for key in benchmark_keys:
            points = artifact.series.get(key, [])
            if points:
                figure.add_trace(go.Scatter(x=[p.date for p in points], y=[p.value for p in points],
                    name=_SERIES[key], mode="lines", connectgaps=False))
            consumed.add(key)
        figures.append(("benchmark", _layout(figure, "标的与基准 · 累计价格收益")))
    for key, points in artifact.series.items():
        if key in consumed or not points:
            continue
        unit = artifact.metric_units.get(key, "fraction")
        figure = go.Figure(go.Scatter(x=[p.date for p in points], y=[p.value for p in points],
            name=_SERIES.get(key, _LABELS.get(key, key)), mode="lines", connectgaps=False,
            fill="tozeroy" if key == "drawdown" else None))
        figures.append((key, _layout(figure, _SERIES.get(key, _LABELS.get(key, key)), unit)))
    names = list(dict.fromkeys(row.get("metric") for row in artifact.table if row.get("metric")))
    for metric in names:
        rows = [row for row in artifact.table if row.get("metric") == metric
                and row.get("value") is not None and isinstance(row.get("value"), (float, int))
                and math.isfinite(row["value"])]
        if not rows:
            continue
        units = {row.get("unit") for row in rows}
        bases = {row.get("basis") for row in rows}
        if len(units) != 1 or len(bases) != 1 or None in bases:
            continue  # Do not visually compare incompatible definitions.
        figure = go.Figure(go.Bar(x=[row.get("symbol", "未知") for row in rows], y=[row["value"] for row in rows],
                                 name=metric))
        figure.update_xaxes(type="category")
        figures.append((f"valuation_{metric}", _layout(figure, f"{metric} · {next(iter(bases))}", next(iter(units)))))
    return figures


def render_analytics_task(task_id, record, snapshots, render_id="final"):
    st.subheader(f"分析任务 {task_id}")
    st.caption(f"{record['question']} · 状态：{record['status']}")
    if record.get("error"):
        st.error(record["error"]["message"])
    result = record.get("result") or {}
    if result.get("summary"):
        st.markdown(result["summary"])
    for missing in result.get("missing_information", []):
        st.warning(missing)
    for request in result.get("missing_data_requests", []):
        st.info(f"待补数据：{request['kind']} · {', '.join(request['subjects'])} · {request['time_range']}；{request['reason']}")
    allowed = {ref["dataset_id"] for ref in result.get("dataset_refs", [])}
    refs = result.get("analysis_refs", [])
    if not refs:
        st.info("暂无可展示的计算产物。")
    for ref in refs:
        ident = ref["analysis_id"]
        try:
            artifact = resolve_artifact(ident, snapshots.get(task_id, {}), allowed)
            summary = artifact.model_dump(mode="json", exclude={"series"})
        except ValueError:
            artifact, summary = None, ref
            st.warning("本会话没有可解析的图表快照，仍展示已有指标；不会重新查询或计算。")
        st.markdown(f"**{summary.get('tool_name', ident)}**")
        st.caption(f"{summary.get('start_date', '未知')} → {summary.get('end_date', '未知')} · "
                   f"样本数 {summary.get('sample_size', '未知')}（单位见计算假设）")
        entries = list(summary.get("metrics", {}).items())
        for start in range(0, len(entries), 4):
            batch = entries[start:start+4]
            for column, (name, value) in zip(st.columns(len(batch)), batch):
                column.metric(_LABELS.get(name, name), format_metric(value, summary.get("metric_units", {}).get(name)))
        if summary.get("table") and summary.get("tool_name") == "rank_peers":
            st.caption("样本内相对位置（z-score · 百分位），不是评分或推荐；高低不代表好坏。")
            for dimension, rows in build_peer_tables(summary["table"]).items():
                st.markdown({"technical": "技术面", "valuation": "估值"}.get(dimension, dimension))
                st.dataframe(rows, hide_index=True, width="stretch")
        elif summary.get("table"):
            st.dataframe(summary["table"], hide_index=True, width="stretch")
        if artifact is not None:
            for kind, figure in build_analysis_figures(artifact):
                st.plotly_chart(figure, width="stretch", key=f"analytics_{render_id}_{task_id}_{ident}_{kind}")
        for source in summary.get("dataset_refs", []):
            mode = source.get("data_mode", "未知")
            if mode == "mock":
                st.warning("模拟数据：图表与指标仅用于演示。")
            st.caption(f"{source.get('symbol', '未知')} · {source.get('provider', '未知')} · {mode} · "
                       f"复权 {source.get('adjustment') or '不适用/未提供'} · "
                       f"{source.get('start_date', '未知')} → {source.get('end_date', '未知')}")
        with st.expander(f"假设与限制 · {task_id} · {ident}"):
            st.json(summary.get("assumptions", {}))
            for limitation in summary.get("limitations", []):
                st.write(limitation)
