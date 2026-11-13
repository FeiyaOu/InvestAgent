"""Deterministic analytics over registered price datasets; no data-provider calls."""
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.analytics_artifacts import AnalysisStore
from src.datasets import DatasetStore, PriceDataset


def _context(config, periods_per_year):
    if isinstance(periods_per_year, bool) or not isinstance(periods_per_year, int) or not 1 <= periods_per_year <= 366:
        raise ValueError("periods_per_year 必须为1到366的整数")
    runtime = config.get("configurable") or {}
    datasets, analyses = runtime.get("dataset_store"), runtime.get("analysis_store")
    if not isinstance(datasets, DatasetStore) or not isinstance(analyses, AnalysisStore):
        raise ValueError("请求内 dataset_store / analysis_store 未配置")
    return datasets, analyses


def _prices(store, ident):
    data = store.get(ident)
    if not isinstance(data, PriceDataset):
        raise ValueError("输入必须是日频价格数据集")
    if len(data.rows) < 2:
        raise ValueError("至少需要两个价格观察值")
    series = pd.Series([row.close for row in data.rows], index=[row.date.isoformat() for row in data.rows], dtype=float)
    return data, series


def _points(series):
    return [{"date": str(day), "value": float(value)} for day, value in series.items()]


def _limitations(datasets):
    limitations = ["历史表现不代表未来收益；年化按相邻记录为连续交易日的假设计算。",
                   "价格收益按所提供复权口径计算，不能自动视为含分红的总回报。"]
    if any(data.data_mode == "mock" for data in datasets):
        limitations.append("包含模拟数据，不能作为真实市场表现。")
    if any(data.adjustment == "none" and data.asset_type != "index" for data in datasets):
        limitations.append("个股未复权，拆股或分红等公司行为可能使收益失真。")
    return limitations


def _register(store, datasets, ids, name, prices, returns, metrics, units, assumptions, limitations, series):
    return store.put(tool_name=name, dataset_refs=[datasets.get_ref(ident).model_dump(mode="json") for ident in ids],
        created_at=datetime.now(timezone.utc), start_date=str(prices.index[0]), end_date=str(prices.index[-1]),
        sample_size=len(returns), metrics=metrics, metric_units=units, assumptions=assumptions,
        limitations=limitations, series=series)


def _unavailable(exc):
    message = "数据集引用不存在或已过期" if isinstance(exc, KeyError) else str(exc)
    return json.dumps({"status": "unavailable", "error": {"type": "invalid_analytics_input", "message": message}}, ensure_ascii=False)


@tool
def analyze_price_performance(dataset_id: str, config: RunnableConfig, periods_per_year: int = 252) -> str:
    """Calculate historical price return, sample annualized volatility and maximum drawdown.

    Read an existing daily price dataset. Returns validated metrics and chart references;
    full chart series remain in the request AnalysisStore. No API fetching or investment advice.
    """
    try:
        datasets, analyses = _context(config, periods_per_year)
        data, prices = _prices(datasets, dataset_id)
        returns = prices.pct_change(fill_method=None).iloc[1:]
        cumulative = prices / prices.iloc[0] - 1
        drawdown = prices / prices.cummax() - 1
        limits = _limitations([data])
        volatility = float(returns.std(ddof=1) * np.sqrt(periods_per_year)) if len(returns) >= 2 else None
        if volatility is None:
            limits.append("少于两个收益观察值，无法估计样本波动率。")
        metrics = {"period_return": float(cumulative.iloc[-1]), "max_drawdown": float(drawdown.min()),
                   "annualized_volatility": volatility}
        ref = _register(analyses, datasets, [dataset_id], "analyze_price_performance", prices, returns,
            metrics, {key: "fraction" for key in metrics},
            {"periods_per_year": periods_per_year, "volatility_ddof": 1, "missing_data": "no_fill",
             "adjustment": data.adjustment, "drawdown_sign": "nonpositive"}, limits,
            {"cumulative_return": _points(cumulative), "drawdown": _points(drawdown)})
        return json.dumps({"status": "available", "analysis_ref": ref}, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, KeyError) as exc:
        return _unavailable(exc)


@tool
def compare_with_benchmark(dataset_id: str, benchmark_dataset_id: str, config: RunnableConfig,
                           periods_per_year: int = 252) -> str:
    """Compare aligned historical returns: excess return, beta, correlation and tracking error.

    Inner-align common price dates without filling. Undefined metrics return null with limitations.
    Does not infer a benchmark or fetch data. Different currencies and return bases are rejected.
    """
    try:
        datasets, analyses = _context(config, periods_per_year)
        stock, prices = _prices(datasets, dataset_id)
        benchmark, benchmark_prices = _prices(datasets, benchmark_dataset_id)
        if dataset_id == benchmark_dataset_id:
            raise ValueError("标的和基准必须为不同数据集")
        if stock.currency != benchmark.currency:
            raise ValueError("币种不同，须先明确汇率转换口径")
        if (stock.adjustment == "total_return") != (benchmark.adjustment == "total_return"):
            raise ValueError("价格收益与总回报口径不能直接比较")
        aligned = pd.concat([prices.rename("asset"), benchmark_prices.rename("benchmark")], axis=1, join="inner")
        if len(aligned) < 3:
            raise ValueError("至少需要三个共同价格日期以估计相关性和beta")
        returns = aligned.pct_change(fill_method=None).iloc[1:]
        asset_returns, benchmark_returns = returns["asset"], returns["benchmark"]
        variance = float(benchmark_returns.var(ddof=1))
        asset_variance = float(asset_returns.var(ddof=1))
        limits = _limitations([stock, benchmark])
        beta = float(asset_returns.cov(benchmark_returns) / variance) if variance > 1e-18 else None
        correlation = float(asset_returns.corr(benchmark_returns)) if variance > 1e-18 and asset_variance > 1e-18 else None
        if beta is None or correlation is None:
            limits.append("标的或基准收益方差为零或接近零，部分统计指标不可定义。")
        dropped_dates = len(aligned) != len(prices) or len(aligned) != len(benchmark_prices)
        tracking = float((asset_returns - benchmark_returns).std(ddof=1) * np.sqrt(periods_per_year))
        if dropped_dates:
            tracking = None
            limits.append("对齐移除了日期；共同日期收益可能跨多个交易日，不年化tracking error。")
        normalized = aligned / aligned.iloc[0] - 1
        metrics = {"asset_period_return": float(normalized["asset"].iloc[-1]),
                   "benchmark_period_return": float(normalized["benchmark"].iloc[-1]),
                   "excess_period_return": float(normalized["asset"].iloc[-1] - normalized["benchmark"].iloc[-1]),
                   "beta": beta, "correlation": correlation, "tracking_error": tracking}
        units = {key: "dimensionless" if key in {"beta", "correlation"} else "fraction" for key in metrics}
        ref = _register(analyses, datasets, [dataset_id, benchmark_dataset_id], "compare_with_benchmark",
            aligned, returns, metrics, units,
            {"periods_per_year": periods_per_year, "sample_ddof": 1, "alignment": "common_dates_no_fill",
             "asset_adjustment": stock.adjustment, "benchmark_adjustment": benchmark.adjustment,
             "excess_return_method": "difference_of_cumulative_returns"}, limits,
            {"asset_cumulative_return": _points(normalized["asset"]),
             "benchmark_cumulative_return": _points(normalized["benchmark"])})
        return json.dumps({"status": "available", "analysis_ref": ref}, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, KeyError) as exc:
        return _unavailable(exc)


@tool
def compute_factors(dataset_id: str, config: RunnableConfig, window: int = 20,
                    factors: list[str] | None = None, periods_per_year: int = 252) -> str:
    """Compute a small trailing price-factor catalogue without look-ahead or warm-up fills.

    momentum=P/P.shift(window)-1; sma_gap=P/trailing_mean(window)-1;
    realized_volatility=trailing sample return std*sqrt(periods_per_year);
    volume_ratio=current_volume/trailing_mean_volume(window).
    Returns latest values and chart references, not a strategy recommendation.
    """
    try:
        datasets, analyses = _context(config, periods_per_year)
        if isinstance(window, bool) or not isinstance(window, int) or not 2 <= window <= 252:
            raise ValueError("window 必须为2到252的整数观察数")
        selected = ["momentum", "sma_gap", "realized_volatility"] if factors is None else factors
        catalogue = {"momentum", "sma_gap", "realized_volatility", "volume_ratio"}
        if not selected or len(selected) != len(set(selected)) or not set(selected) <= catalogue:
            raise ValueError("请选择不重复的 momentum / sma_gap / realized_volatility / volume_ratio")
        data, prices = _prices(datasets, dataset_id)
        returns = prices.pct_change(fill_method=None).iloc[1:]
        limits = _limitations([data])
        outputs = {}
        if "momentum" in selected:
            outputs["momentum"] = prices / prices.shift(window) - 1
        if "sma_gap" in selected:
            outputs["sma_gap"] = prices / prices.rolling(window, min_periods=window).mean() - 1
        if "realized_volatility" in selected:
            outputs["realized_volatility"] = prices.pct_change(fill_method=None).rolling(
                window, min_periods=window).std(ddof=1) * np.sqrt(periods_per_year)
        if "volume_ratio" in selected:
            volumes = pd.Series([row.volume for row in data.rows], index=prices.index, dtype=float)
            mean = volumes.rolling(window, min_periods=window).mean()
            outputs["volume_ratio"] = volumes / mean.where(mean > 0)
        metrics, chart_series = {}, {}
        for name in selected:
            series = outputs[name].replace([np.inf, -np.inf], np.nan)
            metrics[name] = None if pd.isna(series.iloc[-1]) else float(series.iloc[-1])
            if metrics[name] is None:
                limits.append(f"{name} 最新值不可用：窗口样本不足、成交量缺失或分母为零。")
            valid = series.dropna()
            if not valid.empty:
                chart_series[name] = _points(valid)
        ref = _register(analyses, datasets, [dataset_id], "compute_factors", prices, returns, metrics,
            {name: "dimensionless" if name == "volume_ratio" else "fraction" for name in selected},
            {"window": window, "periods_per_year": periods_per_year, "missing_data": "no_fill_no_warmup_zeros",
             "factor_catalogue": selected, "volatility_ddof": 1, "sample_size_unit": "return_intervals",
             "volume_ratio_includes_current": True, "momentum_skip_recent": False}, limits, chart_series)
        return json.dumps({"status": "available", "analysis_ref": ref}, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, KeyError) as exc:
        return _unavailable(exc)


@tool
def compare_valuations(dataset_ids: list[str], config: RunnableConfig,
                       metrics: list[str] | None = None) -> str:
    """Compare 2–20 distinct-company valuation snapshots on exactly the same date/currency.

    Keep missing/nonpositive PE/PB out of relative comparisons. Only aggregate known,
    matching metric bases. Returns an explicit table, medians/spreads and limitations;
    does not infer investment value, rank stocks or give buy/sell recommendations.
    """
    from src.datasets import ValuationDataset
    try:
        datasets, analyses = _context(config, 252)
        if not 2 <= len(dataset_ids) <= 20 or len(dataset_ids) != len(set(dataset_ids)):
            raise ValueError("需要2到20个不重复估值数据集")
        selected = ["pe_ttm", "pb"] if metrics is None else metrics
        allowed = {"pe_ttm", "pb", "dividend_yield", "revenue_growth", "earnings_growth", "roe", "eps"}
        if not selected or len(selected) != len(set(selected)) or not set(selected) <= allowed:
            raise ValueError("估值指标为空、重复或不在目录中")
        snapshots = [datasets.get(ident) for ident in dataset_ids]
        if not all(isinstance(item, ValuationDataset) for item in snapshots):
            raise ValueError("仅接受 ValuationDataset")
        if len({(item.market, item.symbol) for item in snapshots}) != len(snapshots):
            raise ValueError("公司重复，不进行伪同业比较")
        if len({item.as_of_date for item in snapshots}) != 1 or len({item.currency for item in snapshots}) != 1:
            raise ValueError("观察日期或币种不一致，须先获取相同口径快照")
        limits = ["相对估值差异不等于投资价值，不构成买卖建议；行业、增长和财务质量需另行研究。",
                  "本工具不证明历史 point-in-time 可用性；未提供公告日期时不能用于无前视偏差回测。"]
        if any(item.data_mode == "mock" for item in snapshots):
            limits.append("包含模拟估值数据。")
        table, calculated, units = [], {}, {}
        for name in selected:
            values, bases = [], set()
            for ident, item in zip(dataset_ids, snapshots):
                metric = item.metrics.get(name)
                raw = metric.value if metric else None
                value, reason = raw, metric.missing_reason if metric else "数据集中未提供此指标"
                if name in {"pe_ttm", "pb"} and value is not None and value <= 0:
                    value, reason = None, "非正PE/PB不适用于相对估值比较"
                basis = metric.basis if metric else None
                if value is not None:
                    values.append(value)
                    bases.add(basis)
                table.append({"dataset_id": ident, "symbol": item.symbol, "market": item.market,
                    "as_of_date": item.as_of_date.isoformat(), "metric": name, "raw_value": raw,
                    "value": value, "unit": metric.unit if metric else None, "basis": basis,
                    "missing_reason": reason})
            known_bases = {"pe_ttm": {"PE_TTM"}, "pb": {"PB_MRQ", "PB_LYR"},
                "dividend_yield": {"DIVIDEND_YIELD_TTM"}, "revenue_growth": {"REVENUE_YOY"},
                "earnings_growth": {"EARNINGS_YOY"}, "roe": {"ROE_TTM", "ROE_FY"},
                "eps": {"EPS_TTM", "EPS_FY"}}
            comparable = len(values) == len(snapshots) and len(bases) == 1 and bases <= known_bases[name]
            if name in {"revenue_growth", "earnings_growth", "roe", "eps"}:
                comparable = comparable and len({item.report_period for item in snapshots}) == 1 \
                    and all(item.report_period and item.available_at for item in snapshots)
            unit = next((item.metrics[name].unit for item in snapshots if name in item.metrics), "unavailable")
            calculated[f"{name}.median"] = float(np.median(values)) if comparable else None
            calculated[f"{name}.spread"] = float(max(values) - min(values)) if comparable else None
            units[f"{name}.median"] = units[f"{name}.spread"] = unit
            if not comparable:
                limits.append(f"{name} 不做汇总比较：存在缺失/不适用数值或指标定义/报告期不一致。")
        ref = analyses.put(tool_name="compare_valuations",
            dataset_refs=[datasets.get_ref(ident).model_dump(mode="json") for ident in dataset_ids],
            created_at=datetime.now(timezone.utc), start_date=snapshots[0].as_of_date.isoformat(),
            end_date=snapshots[0].as_of_date.isoformat(), sample_size=len(snapshots),
            metrics=calculated, metric_units=units, assumptions={"sample_size_unit": "companies",
                "aggregation": "all_companies_must_have_valid_matching_basis", "metrics": selected},
            limitations=limits, table=table, series={})
        return json.dumps({"status": "available", "analysis_ref": ref}, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, KeyError) as exc:
        return _unavailable(exc)
