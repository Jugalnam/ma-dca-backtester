from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

try:
    import quantstats as qs
except ImportError:  # pragma: no cover - exercised only before dependencies are installed
    qs = None


def buy_and_hold(prices: pd.DataFrame, invested_amount: float) -> pd.DataFrame:
    """Invest the same total amount on the first day and hold."""
    if prices.empty:
        raise ValueError("prices is empty")

    prices = prices.sort_values("date").reset_index(drop=True).copy()
    first_price = float(prices["close"].iloc[0])
    units = invested_amount / first_price if first_price > 0 else 0.0
    out = pd.DataFrame(
        {
            "date": prices["date"],
            "price": prices["close"].astype(float),
            "value": units * prices["close"].astype(float),
            "contributed": invested_amount,
        }
    )
    return out


def report_selffinanced(value: pd.Series, benchmark: pd.Series, out_html: str) -> None:
    """Create a quantstats HTML report for self-financed return series."""
    if qs is None:
        raise RuntimeError("quantstats is required. Install dependencies with: pip install -r requirements.txt")

    strategy_returns = value.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    benchmark_returns = benchmark.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    qs.reports.html(
        strategy_returns,
        benchmark=benchmark_returns,
        output=out_html,
        title="Strategy vs Buy & Hold",
    )


def dca_summary(df: pd.DataFrame) -> dict[str, float]:
    final_value = float(df["value"].iloc[-1]) if not df.empty else 0.0
    contributed = float(df["contributed"].iloc[-1]) if not df.empty else 0.0
    multiple = final_value / contributed if contributed else 0.0
    annual_irr = money_weighted_annual_irr(df)
    daily_irr = (1.0 + annual_irr) ** (1.0 / 365.0) - 1.0 if annual_irr > -1 else -1.0
    return {
        "final_value": final_value,
        "contributed": contributed,
        "multiple": multiple,
        "daily_irr": daily_irr,
        "annualized_irr": annual_irr,
    }


def money_weighted_annual_irr(df: pd.DataFrame) -> float:
    """Compute annualized money-weighted return using dated contributions."""
    if df.empty or "contributed_today" not in df.columns:
        return 0.0

    flows = [-float(v) for v in df["contributed_today"].fillna(0.0)]
    flows[-1] += float(df["value"].iloc[-1])
    dates = pd.to_datetime(df["date"]).tolist() if "date" in df.columns else None

    if not any(v < 0 for v in flows) or not any(v > 0 for v in flows):
        return 0.0

    if dates:
        return solve_xirr(flows, dates)

    daily_irr = solve_irr(flows)
    return annualize_daily_rate(daily_irr)


def money_weighted_daily_irr(df: pd.DataFrame) -> float:
    """Compute daily money-weighted return using contributions and final value."""
    annual_rate = money_weighted_annual_irr(df)
    return (1.0 + annual_rate) ** (1.0 / 365.0) - 1.0 if annual_rate > -1 else -1.0


def solve_xirr(
    flows: list[float],
    dates: list[pd.Timestamp],
    low: float = -0.999999,
    high: float = 10.0,
) -> float:
    """Solve annualized IRR for dated cash flows."""
    first_date = dates[0]

    def npv(rate: float) -> float:
        return sum(
            flow / ((1.0 + rate) ** ((date - first_date).days / 365.0))
            for flow, date in zip(flows, dates)
        )

    low_value = npv(low)
    high_value = npv(high)
    while low_value * high_value > 0 and high < 10000:
        high *= 2
        high_value = npv(high)

    if low_value * high_value > 0:
        return 0.0

    for _ in range(100):
        mid = (low + high) / 2
        mid_value = npv(mid)
        if abs(mid_value) < 1e-7:
            return mid
        if low_value * mid_value <= 0:
            high = mid
            high_value = mid_value
        else:
            low = mid
            low_value = mid_value

    return (low + high) / 2


def solve_irr(flows: list[float], low: float = -0.95, high: float = 1.0) -> float:
    """Solve periodic IRR by bisection without extra dependencies."""

    def npv(rate: float) -> float:
        total = 0.0
        base = 1.0 + rate
        for i, flow in enumerate(flows):
            try:
                discount = base**i
                total += flow / discount
            except (OverflowError, ZeroDivisionError):
                return float("inf") if flow > 0 else float("-inf")
        return total

    low_value = npv(low)
    high_value = npv(high)
    while low_value * high_value > 0 and high < 1000:
        high *= 2
        high_value = npv(high)

    if low_value * high_value > 0:
        return 0.0

    for _ in range(100):
        mid = (low + high) / 2
        mid_value = npv(mid)
        if abs(mid_value) < 1e-7:
            return mid
        if low_value * mid_value <= 0:
            high = mid
            high_value = mid_value
        else:
            low = mid
            low_value = mid_value

    return (low + high) / 2


def annualize_daily_rate(rate: float) -> float:
    if rate <= -1:
        return -1.0
    return (1.0 + rate) ** 252 - 1.0


def write_comparison_csv(rows: list[dict[str, object]], out_path: str | Path) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    return df
