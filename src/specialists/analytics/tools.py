"""Deterministic analytics over registered price datasets; no data-provider calls."""
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.core.datasets import DatasetStore, PriceDataset
from src.specialists.analytics import factors as factor_lib
from src.specialists.analytics.artifacts import AnalysisStore


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
                    factors: list[str] | None = None, periods_per_year: int = 252,
                    rsi_window: int = 14, bollinger_k: float = 2.) -> str:
    """Compute a trailing price-factor catalogue without look-ahead or warm-up fills.

    momentum=P/P.shift(window)-1; sma_gap=P/trailing_mean(window)-1;
    realized_volatility=trailing sample return std*sqrt(periods_per_year);
    volume_ratio=current_volume/trailing_mean_volume(window);
    rsi=Wilder RSI(rsi_window), 0-100; macd_hist_pct=MACD(12,26,9) histogram / close;
    bollinger_pct_b=(P-lower)/(upper-lower), window-day band of bollinger_k sample std;
    turnover=trailing mean turnover fraction over window.
    Returns latest values and chart references, not a strategy recommendation.
    """
    try:
        datasets, analyses = _context(config, periods_per_year)
        if isinstance(window, bool) or not isinstance(window, int) or not 2 <= window <= 252:
            raise ValueError("window 必须为2到252的整数观察数")
        if isinstance(rsi_window, bool) or not isinstance(rsi_window, int) or not 2 <= rsi_window <= 100:
            raise ValueError("rsi_window 必须为2到100的整数观察数")
        if isinstance(bollinger_k, bool) or not isinstance(bollinger_k, (int, float)) or not 0.5 <= bollinger_k <= 4:
            raise ValueError("bollinger_k 必须在0.5到4之间")
        selected = ["momentum", "sma_gap", "realized_volatility"] if factors is None else factors
        if not selected or len(selected) != len(set(selected)) or not set(selected) <= factor_lib.CATALOGUE:
            raise ValueError("请选择不重复的因子：" + " / ".join(sorted(factor_lib.CATALOGUE)))
        data, prices = _prices(datasets, dataset_id)
        returns = prices.pct_change(fill_method=None).iloc[1:]
        limits = _limitations([data])
        inputs = {"volume": pd.Series([row.volume for row in data.rows], index=prices.index, dtype=float),
                  "turnover": pd.Series([row.turnover for row in data.rows], index=prices.index, dtype=float)}
        outputs = factor_lib.compute_all(prices, inputs, selected, window=window, rsi_window=rsi_window,
                                         bollinger_k=float(bollinger_k), periods_per_year=periods_per_year)
        metrics, chart_series = {}, {}
        for name in selected:
            series = outputs[name]
            metrics[name] = None if pd.isna(series.iloc[-1]) else float(series.iloc[-1])
            if metrics[name] is None:
                limits.append(f"{name} 最新值不可用：窗口样本不足、成交量/换手率缺失或分母为零。")
            valid = series.dropna()
            if not valid.empty:
                chart_series[name] = _points(valid)
        if "macd_hist_pct" in selected:
            # Raw MACD lines are in price units: chart-only, not cross-stock comparable metrics.
            for key, series in factor_lib.macd(prices, *factor_lib.MACD_SPANS).items():
                if key != "macd_hist_pct" and not series.dropna().empty:
                    chart_series[key] = _points(series.dropna())
        ref = _register(analyses, datasets, [dataset_id], "compute_factors", prices, returns, metrics,
            {name: factor_lib.UNITS[name] for name in selected},
            {"window": window, "periods_per_year": periods_per_year, "missing_data": "no_fill_no_warmup_zeros",
             "factor_catalogue": selected, "volatility_ddof": 1, "sample_size_unit": "return_intervals",
             "volume_ratio_includes_current": True, "momentum_skip_recent": False,
             "rsi_window": rsi_window, "rsi_smoothing": "wilder", "macd_spans": list(factor_lib.MACD_SPANS),
             "bollinger_k": float(bollinger_k), "bollinger_std_ddof": 1}, limits, chart_series)
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
    from src.core.datasets import ValuationDataset
    try:
        datasets, analyses = _context(config, 252)
        if not 2 <= len(dataset_ids) <= 20 or len(dataset_ids) != len(set(dataset_ids)):
            raise ValueError("需要2到20个不重复估值数据集")
        selected = ["pe_ttm", "pb"] if metrics is None else metrics
        allowed = {"pe_ttm", "pb", "ps_ttm", "dividend_yield", "revenue_growth", "earnings_growth", "roe", "eps"}
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
                if name in {"pe_ttm", "pb", "ps_ttm"} and value is not None and value <= 0:
                    value, reason = None, "非正PE/PB/PS不适用于相对估值比较"
                basis = metric.basis if metric else None
                if value is not None:
                    values.append(value)
                    bases.add(basis)
                table.append({"dataset_id": ident, "symbol": item.symbol, "market": item.market,
                    "as_of_date": item.as_of_date.isoformat(), "metric": name, "raw_value": raw,
                    "value": value, "unit": metric.unit if metric else None, "basis": basis,
                    "missing_reason": reason})
            known_bases = {"pe_ttm": {"PE_TTM"}, "pb": {"PB_MRQ", "PB_LYR"}, "ps_ttm": {"PS_TTM"},
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


@tool
def build_return_matrix(dataset_ids: list[str], config: RunnableConfig, min_observations: int = 60,
                        periods_per_year: int = 252) -> str:
    """Align 1-50 daily price datasets on common trading dates and estimate covariance.

    Returns are simple returns between adjacent common dates; nothing is filled.
    Sample covariance (ddof=1) without shrinkage, annualized by periods_per_year, plus
    correlations and per-asset annualized volatility. Aligned returns are stored for
    Strategy/Risk portfolio calculations. Requires max(min_observations, 2 x assets) returns.
    """
    try:
        datasets, analyses = _context(config, periods_per_year)
        if isinstance(min_observations, bool) or not isinstance(min_observations, int) or not 20 <= min_observations <= 2000:
            raise ValueError("min_observations 必须为20到2000的整数")
        if not 1 <= len(dataset_ids) <= 50 or len(dataset_ids) != len(set(dataset_ids)):
            raise ValueError("需要1到50个不重复价格数据集")
        loaded = [_prices(datasets, ident) for ident in dataset_ids]
        data = [item[0] for item in loaded]
        symbols = [item.symbol for item in data]
        if len(set(symbols)) != len(symbols):
            raise ValueError("标的重复，不构建重复资产的协方差")
        stock_adjustments = {item.adjustment for item in data if item.asset_type != "index"}
        if "none" in stock_adjustments or len(stock_adjustments) > 1:
            raise ValueError("股票须使用一致的复权口径（qfq/hfq/total_return），不接受未复权或混合口径")
        if len({item.currency for item in data}) != 1:
            raise ValueError("币种不一致，不构建协方差")
        frame = pd.concat({symbol: series for symbol, (_, series) in zip(symbols, loaded)}, axis=1, join="inner")
        returns = frame.pct_change(fill_method=None).iloc[1:]
        required = max(min_observations, 2 * len(symbols))
        if len(returns) < required:
            raise ValueError(f"共同交易日收益观察数{len(returns)}不足，至少需要{required}个")
        before = {symbol: len(series) for symbol, (_, series) in zip(symbols, loaded)}
        dropped = {symbol: count - len(frame) for symbol, count in before.items()}
        cov, corr = returns.cov(ddof=1), returns.corr()
        table = []
        for i, left in enumerate(symbols):
            for right in symbols[i:]:
                value = corr.loc[left, right]
                table.append({"symbol_a": left, "symbol_b": right,
                    "daily_covariance": float(cov.loc[left, right]),
                    "annualized_covariance": float(cov.loc[left, right] * periods_per_year),
                    "correlation": None if pd.isna(value) else float(value),
                    "missing_reason": "零方差标的的相关系数无定义" if pd.isna(value) else None})
        metrics = {f"{symbol}.annualized_volatility": float(returns[symbol].std(ddof=1) * np.sqrt(periods_per_year))
                   for symbol in symbols}
        limits = _limitations(data) + ["样本协方差未做收缩估计；标的较多或样本较短时估计误差较大，历史相关性可能在危机中改变。"]
        if any(dropped.values()):
            limits.append("对齐到共同交易日时剔除了非共同日期：" + "，".join(
                f"{symbol} {count}个" for symbol, count in dropped.items() if count))
        ref = analyses.put(tool_name="build_return_matrix",
            dataset_refs=[datasets.get_ref(ident).model_dump(mode="json") for ident in dataset_ids],
            created_at=datetime.now(timezone.utc), start_date=str(frame.index[0]), end_date=str(frame.index[-1]),
            sample_size=len(returns), metrics=metrics, metric_units={key: "fraction" for key in metrics},
            assumptions={"symbols": symbols, "alignment": "inner_join_common_dates", "return_type": "simple",
                "covariance_ddof": 1, "shrinkage": "none", "periods_per_year": periods_per_year,
                "min_observations": min_observations, "observations_before_alignment": before,
                "dropped_dates": dropped, "sample_size_unit": "return_intervals", "missing_data": "no_fill"},
            limitations=limits, table=table, series={symbol: _points(returns[symbol]) for symbol in symbols})
        return json.dumps({"status": "available", "analysis_ref": ref}, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, KeyError) as exc:
        return _unavailable(exc)


_PEER_TECHNICAL = ("momentum", "realized_volatility", "rsi", "macd_hist_pct", "bollinger_pct_b", "turnover")
_PEER_VALUATION = {"pe_ttm": "PE_TTM", "pb": "PB_MRQ", "ps_ttm": "PS_TTM"}
_PEER_MIN_VALID = 5


@tool
def rank_peers(factors: list[str], config: RunnableConfig, price_dataset_ids: list[str] | None = None,
               valuation_dataset_ids: list[str] | None = None, window: int = 20, rsi_window: int = 14,
               bollinger_k: float = 2., periods_per_year: int = 252) -> str:
    """Show each peer's in-sample z-score and percentile per factor, by dimension.

    Technical factors (momentum, realized_volatility, rsi, macd_hist_pct, bollinger_pct_b,
    turnover) use price datasets at their common last trading date; valuation factors
    (pe_ttm, pb, ps_ttm) need same-date snapshots. Up to 20 peers; a factor needs >=5 valid
    values. No composite score, no good/bad direction and no recommendation.
    """
    try:
        datasets, analyses = _context(config, periods_per_year)
        price_ids, valuation_ids = list(price_dataset_ids or []), list(valuation_dataset_ids or [])
        if not factors or len(factors) != len(set(factors)) or not set(factors) <= set(_PEER_TECHNICAL) | set(_PEER_VALUATION):
            raise ValueError("请选择不重复的因子：" + " / ".join([*_PEER_TECHNICAL, *_PEER_VALUATION]))
        technical = [name for name in factors if name in _PEER_TECHNICAL]
        valuation = [name for name in factors if name in _PEER_VALUATION]
        if technical and not price_ids or valuation and not valuation_ids:
            raise ValueError("技术面因子需要价格数据集，估值因子需要估值快照")
        if len(price_ids) != len(set(price_ids)) or len(valuation_ids) != len(set(valuation_ids)):
            raise ValueError("数据集引用重复")
        prices = [_prices(datasets, ident) for ident in price_ids] if technical else []
        snapshots = [datasets.get(ident) for ident in valuation_ids] if valuation else []
        from src.core.datasets import ValuationDataset
        if not all(isinstance(item, ValuationDataset) for item in snapshots):
            raise ValueError("估值因子仅接受 ValuationDataset")
        price_symbols = [item[0].symbol for item in prices]
        value_symbols = [item.symbol for item in snapshots]
        if len(set(price_symbols)) != len(price_symbols) or len(set(value_symbols)) != len(value_symbols):
            raise ValueError("同一维度内标的重复")
        if len(set(price_symbols) | set(value_symbols)) > 20:
            raise ValueError("同行样本最多20个标的")
        if snapshots and (len({item.as_of_date for item in snapshots}) != 1 or len({item.currency for item in snapshots}) != 1):
            raise ValueError("估值快照观察日期或币种不一致，须先获取相同口径快照")
        raw = {}  # factor -> {symbol: (value | None, reason | None)}
        dates = []
        if technical:
            common = set.intersection(*(set(series.index) for _, series in prices))
            if not common:
                raise ValueError("价格数据集没有共同交易日")
            as_of = max(common)
            dates.append(as_of)
            for data, series in prices:
                inputs = {"volume": pd.Series([row.volume for row in data.rows], index=series.index, dtype=float),
                          "turnover": pd.Series([row.turnover for row in data.rows], index=series.index, dtype=float)}
                trimmed = {key: value.loc[:as_of] for key, value in inputs.items()}
                computed = factor_lib.compute_all(series.loc[:as_of], trimmed, technical, window=window,
                    rsi_window=rsi_window, bollinger_k=float(bollinger_k), periods_per_year=periods_per_year)
                for name in technical:
                    value = computed[name].iloc[-1]
                    raw.setdefault(name, {})[data.symbol] = (None, "窗口样本不足或输入数据缺失") if pd.isna(value) else (float(value), None)
        if valuation:
            dates.append(snapshots[0].as_of_date.isoformat())
            for item in snapshots:
                for name in valuation:
                    metric = item.metrics.get(name)
                    if metric is None or metric.value is None:
                        entry = (None, metric.missing_reason if metric else "数据集中未提供此指标")
                    elif metric.basis != _PEER_VALUATION[name]:
                        entry = (None, "指标口径未知或不一致")
                    elif metric.value <= 0:
                        entry = (None, "非正PE/PB/PS不适用于相对比较")
                    else:
                        entry = (metric.value, None)
                    raw.setdefault(name, {})[item.symbol] = entry
        names = {item.symbol: item.security_name for item in [data for data, _ in prices] + snapshots if item.security_name}
        table, metrics, units = [], {}, {}
        limits = _limitations([item[0] for item in prices]) if prices else []
        if any(item.data_mode == "mock" for item in snapshots) and not any("模拟" in text for text in limits):
            limits.append("包含模拟数据，不能作为真实市场表现。")
        limits.append("这是给定样本内的相对位置，不代表预测能力或投资价值；样本小时 z-score 不稳定。")
        for name in factors:
            valid = pd.Series({symbol: value for symbol, (value, _) in raw[name].items() if value is not None}, dtype=float)
            std = valid.std(ddof=1) if len(valid) >= 2 else np.nan
            enough = len(valid) >= _PEER_MIN_VALID
            if not enough:
                limits.append(f"{name} 有效值{len(valid)}个，少于{_PEER_MIN_VALID}个，不计算相对位置。")
            elif not std > 0:
                limits.append(f"{name} 各标的数值相同，z-score 无定义。")
            pct = valid.rank(method="average", pct=True)
            for symbol, (value, reason) in raw[name].items():
                ranked = enough and value is not None
                table.append({"symbol": symbol, "security_name": names.get(symbol),
                    "dimension": "technical" if name in _PEER_TECHNICAL else "valuation",
                    "factor": name, "raw_value": value,
                    "z_score": float((value - valid.mean()) / std) if ranked and std > 0 else None,
                    "percentile": float(pct[symbol]) if ranked else None,
                    "valid_count": len(valid), "excluded_reason": reason})
            unit = factor_lib.UNITS.get(name, "multiple")
            metrics[f"{name}.cross_section_mean"] = float(valid.mean()) if enough else None
            metrics[f"{name}.cross_section_std"] = float(std) if enough and std > 0 else None
            units[f"{name}.cross_section_mean"] = units[f"{name}.cross_section_std"] = unit
        if len(set(dates)) > 1:
            limits.append(f"技术面截至{dates[0]}，估值截至{dates[1]}，两类维度观察日不同。")
        ref = analyses.put(tool_name="rank_peers",
            dataset_refs=[datasets.get_ref(ident).model_dump(mode="json") for ident in price_ids + valuation_ids],
            created_at=datetime.now(timezone.utc), start_date=min(dates), end_date=max(dates),
            sample_size=len(set(price_symbols) | set(value_symbols)), metrics=metrics, metric_units=units,
            assumptions={"factors": factors, "window": window, "rsi_window": rsi_window,
                "bollinger_k": float(bollinger_k), "periods_per_year": periods_per_year,
                "z_score_ddof": 1, "percentile_method": "average_rank_over_n", "min_valid_values": _PEER_MIN_VALID,
                "technical_as_of": "common_last_trading_date", "sample_size_unit": "companies",
                "composite_score": "not_computed"},
            limitations=limits, table=table, series={})
        return json.dumps({"status": "available", "analysis_ref": ref}, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, KeyError) as exc:
        return _unavailable(exc)
