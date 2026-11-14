"""Pure trailing factor functions shared by compute_factors and rank_peers.

Every value at t uses observations up to t only. Warm-up periods stay NaN;
nothing is forward-filled or zero-filled.
"""
import numpy as np
import pandas as pd

MACD_SPANS = (12, 26, 9)
CATALOGUE = {"momentum", "sma_gap", "realized_volatility", "volume_ratio",
             "rsi", "macd_hist_pct", "bollinger_pct_b", "turnover"}
UNITS = {"momentum": "fraction", "sma_gap": "fraction", "realized_volatility": "fraction",
         "volume_ratio": "dimensionless", "rsi": "index_0_100", "macd_hist_pct": "fraction",
         "bollinger_pct_b": "dimensionless", "turnover": "fraction"}


def rsi(prices: pd.Series, window: int) -> pd.Series:
    """Wilder RSI: seed with the simple mean of the first `window` changes, then smooth."""
    changes = prices.diff().to_numpy()
    out = np.full(len(prices), np.nan)
    if len(prices) <= window:
        return pd.Series(out, index=prices.index)
    gain, loss = np.clip(changes, 0, None), np.clip(-changes, 0, None)
    avg_gain, avg_loss = gain[1:window + 1].mean(), loss[1:window + 1].mean()
    for i in range(window, len(prices)):
        if i > window:
            avg_gain = (avg_gain * (window - 1) + gain[i]) / window
            avg_loss = (avg_loss * (window - 1) + loss[i]) / window
        if avg_loss > 0:
            out[i] = 100 - 100 / (1 + avg_gain / avg_loss)
        elif avg_gain > 0:
            out[i] = 100.
    return pd.Series(out, index=prices.index)


def macd(prices: pd.Series, fast: int, slow: int, signal: int) -> dict[str, pd.Series]:
    """EMA(adjust=False) MACD; values before slow + signal prices are masked as warm-up."""
    line = prices.ewm(span=fast, adjust=False).mean() - prices.ewm(span=slow, adjust=False).mean()
    signal_line = line.ewm(span=signal, adjust=False).mean()
    hist = line - signal_line
    warm = np.arange(len(prices)) < slow + signal - 1
    masked = {"macd": line, "macd_signal": signal_line, "macd_hist": hist}
    masked = {key: value.mask(warm) for key, value in masked.items()}
    masked["macd_hist_pct"] = masked["macd_hist"] / prices
    return masked


def bollinger_pct_b(prices: pd.Series, window: int, k: float) -> pd.Series:
    mid = prices.rolling(window, min_periods=window).mean()
    width = 2 * k * prices.rolling(window, min_periods=window).std(ddof=1)
    return (prices - (mid - width / 2)) / width.where(width > 0)


def compute_all(prices: pd.Series, inputs: dict | None, names: list[str], *, window: int,
                rsi_window: int, bollinger_k: float, periods_per_year: int) -> dict[str, pd.Series]:
    """Return trailing series for the requested factors; inputs may carry volume/turnover."""
    inputs = inputs or {}
    empty = pd.Series(np.nan, index=prices.index)
    out = {}
    for name in names:
        if name == "momentum":
            out[name] = prices / prices.shift(window) - 1
        elif name == "sma_gap":
            out[name] = prices / prices.rolling(window, min_periods=window).mean() - 1
        elif name == "realized_volatility":
            out[name] = prices.pct_change(fill_method=None).rolling(
                window, min_periods=window).std(ddof=1) * np.sqrt(periods_per_year)
        elif name == "volume_ratio":
            volumes = inputs.get("volume", empty)
            mean = volumes.rolling(window, min_periods=window).mean()
            out[name] = volumes / mean.where(mean > 0)
        elif name == "rsi":
            out[name] = rsi(prices, rsi_window)
        elif name == "macd_hist_pct":
            out[name] = macd(prices, *MACD_SPANS)["macd_hist_pct"]
        elif name == "bollinger_pct_b":
            out[name] = bollinger_pct_b(prices, window, bollinger_k)
        elif name == "turnover":
            out[name] = inputs.get("turnover", empty).rolling(window, min_periods=window).mean()
        else:
            raise ValueError(f"未知因子：{name}")
        out[name] = out[name].replace([np.inf, -np.inf], np.nan)
    return out
