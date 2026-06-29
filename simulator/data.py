from __future__ import annotations

import pandas as pd

try:
    import yfinance as yf
except ImportError:  # pragma: no cover - exercised only before dependencies are installed
    yf = None


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


def load_ohlc(ticker: str, years: int = 10) -> pd.DataFrame:
    """Load adjusted daily OHLC prices from Yahoo Finance."""
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
    required = ["date", "open", "high", "low", "close"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Missing OHLC columns: {missing}")

    return df[required].sort_values("date").reset_index(drop=True)
