"""Pure portfolio risk calculations shared by Strategy/Risk tools.

Returns are a constant-weight replay of current weights over historical asset
returns (daily rebalanced, cash return 0). Losses are positive fractions.
"""
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

Z = {95: -1.6448536269514722, 99: -2.3263478740408408}  # Standard normal quantiles at 5% / 1%.
MIN_OBSERVATIONS = {"annualized_volatility": 20, "max_drawdown": 20,
                    "historical_var_95": 100, "historical_cvar_95": 100,
                    "historical_var_99": 250, "historical_cvar_99": 250,
                    "parametric_var_95": 20, "parametric_cvar_95": 20,
                    "parametric_var_99": 20, "parametric_cvar_99": 20}


def portfolio_returns(returns: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    missing = set(weights) - set(returns.columns)
    if missing:
        raise ValueError(f"收益矩阵缺少持仓：{', '.join(sorted(missing))}")
    return sum(returns[symbol] * weight for symbol, weight in weights.items())


def nav(port: pd.Series) -> pd.Series:
    return (1 + port).cumprod()


def max_drawdown(values: pd.Series) -> float:
    """Largest peak-to-trough loss, with the initial value 1.0 as the first peak."""
    peaks = np.maximum.accumulate(np.concatenate([[1.0], values.to_numpy()]))[1:]
    return float(max(0.0, (1 - values / peaks).max()))


def risk_metrics(port: pd.Series, periods_per_year: int) -> tuple[dict, dict]:
    """Return (metrics, reasons); metrics below their sample threshold are None."""
    n, metrics, reasons = len(port), {}, {}
    mu, sigma = float(port.mean()), float(port.std(ddof=1)) if len(port) > 1 else math.nan
    for level, z in Z.items():
        alpha = 1 - level / 100
        q = float(np.quantile(port, alpha, method="linear")) if n else math.nan
        tail = port[port <= q]
        metrics[f"historical_var_{level}"] = -q
        metrics[f"historical_cvar_{level}"] = -float(tail.mean()) if len(tail) else None
        metrics[f"parametric_var_{level}"] = -(mu + z * sigma)
        metrics[f"parametric_cvar_{level}"] = sigma * math.exp(-z * z / 2) / math.sqrt(2 * math.pi) / alpha - mu
    metrics["annualized_volatility"] = sigma * math.sqrt(periods_per_year)
    metrics["max_drawdown"] = max_drawdown(nav(port)) if n else None
    for name, required in MIN_OBSERVATIONS.items():
        if n < required:
            metrics[name] = None
            reasons[name] = f"收益观察数{n}少于{required}个，不计算该指标"
        elif metrics[name] is not None and not math.isfinite(metrics[name]):
            metrics[name] = None
            reasons[name] = "数值无定义（零方差或样本异常）"
    return metrics, reasons


def compatible_matrix(request, analysis_store, requested_id=None):
    """Pick an authorized build_return_matrix covering every holding, not after the portfolio date.

    Returns (analysis_ref, returns_frame) or (None, reason).
    """
    portfolio = request.portfolio
    if portfolio is None or not portfolio.positions:
        return None, "缺少非现金持仓"
    symbols = {p.symbol for p in portfolio.positions}
    candidates = [ref for ref in request.analysis_refs
                  if ref.get("tool_name") == "build_return_matrix"
                  and symbols <= set(ref.get("assumptions", {}).get("symbols", []))
                  and ref["end_date"] <= portfolio.as_of_date.isoformat()
                  and all(d.get("currency") == portfolio.currency for d in ref.get("dataset_refs", []))]
    if requested_id is not None:
        candidates = [ref for ref in candidates if ref["analysis_id"] == requested_id]
    if not candidates:
        return None, "缺少覆盖全部持仓、日期不晚于持仓日且币种一致的收益矩阵产物"
    ref = max(candidates, key=lambda r: (r["end_date"], r["sample_size"]))
    series = analysis_store.get(ref["analysis_id"]).series
    frame = pd.DataFrame({s: pd.Series({p.date: p.value for p in series[s]}) for s in sorted(symbols)})
    return ref, frame


# Code-owned windows: SSE Composite closing-price peak -> trough (verified 2026-11-14); models only choose a key.
HISTORICAL_SCENARIOS = {
    "2008_gfc": ("2008 全球金融危机", date(2007, 10, 16), date(2008, 11, 4)),
    "2015_crash": ("2015 股灾", date(2015, 6, 12), date(2015, 8, 26)),
    "2020_covid": ("2020 新冠冲击", date(2020, 1, 13), date(2020, 3, 23)),
}
COVERAGE_TOLERANCE_DAYS = 7  # Holidays/suspensions at the window edges, not late listings.


def window_prices(dataset, start: date, end: date) -> tuple[pd.Series | None, str | None]:
    """Closes inside [start, end] if the dataset covers both window edges; else (None, reason)."""
    if dataset.asset_type != "index" and dataset.adjustment == "none":
        return None, "个股未复权，区间收益可能被拆股或分红扭曲"
    rows = [row for row in dataset.rows if start <= row.date <= end]
    tolerance = timedelta(days=COVERAGE_TOLERANCE_DAYS)
    if not rows or rows[0].date > start + tolerance or rows[-1].date < end - tolerance:
        return None, "数据未覆盖情景区间（可能尚未上市、停牌或采集区间不足）"
    return pd.Series([row.close for row in rows], index=[row.date.isoformat() for row in rows]), None
