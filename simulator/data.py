from __future__ import annotations

from pathlib import Path

import pandas as pd

try:
    import yfinance as yf
except ImportError:  # pragma: no cover - exercised only before dependencies are installed
    yf = None

if yf is not None:
    try:
        cache_dir = Path("outputs") / "yfinance_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        yf.cache.set_cache_location(str(cache_dir))
    except Exception:
        # Data loading still works without an explicit cache; this only avoids
        # host-level cache permission issues in restricted environments.
        pass


def load_prices(ticker: str, years: int = 10) -> pd.DataFrame:
    """Load adjusted daily close prices from Yahoo Finance.

    Returns a DataFrame with columns: date, close.
    """
    if yf is None:
        raise RuntimeError("yfinance is required. Install dependencies with: pip install -r requirements.txt")

    df = yf.download(
        ticker,
        period=f"{years}y",
        interval="1d",
        auto_adjust=True,
        progress=False,
    )
    if df.empty:
        raise ValueError(f"No data: {ticker}")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()
    df.columns = [str(c).lower() for c in df.columns]
    return df[["date", "close"]].sort_values("date").reset_index(drop=True)


def load_ohlc(ticker: str, years: int = 10, warmup_days: int = 0) -> pd.DataFrame:
    """Load adjusted daily OHLC prices from Yahoo Finance.

    ``warmup_days`` fetches extra history before the displayed range so rolling
    indicators can be calculated without changing shape when the visible range
    changes.
    """
    if yf is None:
        raise RuntimeError("yfinance is required. Install dependencies with: pip install -r requirements.txt")

    kwargs = {
        "tickers": ticker,
        "interval": "1d",
        "auto_adjust": True,
        "progress": False,
    }
    if warmup_days > 0:
        end = pd.Timestamp.today().normalize() + pd.Timedelta(days=1)
        start = end - pd.DateOffset(years=years) - pd.Timedelta(days=int(warmup_days))
        kwargs["start"] = start.date()
        kwargs["end"] = end.date()
    else:
        kwargs["period"] = f"{years}y"

    df = yf.download(**kwargs)
    if df.empty:
        raise ValueError(f"No data: {ticker}")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()
    df.columns = [str(c).lower() for c in df.columns]
    required = ["date", "open", "high", "low", "close"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Missing OHLC columns: {missing}")

    return df[required].sort_values("date").reset_index(drop=True)
