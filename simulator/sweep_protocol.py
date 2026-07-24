"""Parameter sweep for the rule-based sell protocol (simulator/protocol.py).

Usage:
    python -m simulator.sweep_protocol --ticker TSLA --years 12
    python -m simulator.sweep_protocol --ticker TSLA --years 12 \
        --detail 0.10 0.20 0.25 6

Writes outputs/protocol_sweep_{ticker}.csv (full grid) and prints the top
combinations plus a no-sell DCA baseline for the same period.
"""

from __future__ import annotations

import argparse
import itertools
from pathlib import Path

import pandas as pd

from .data import load_prices
from .protocol import ProtocolParams, cycles_table, run_protocol, summarize

X1_GRID = [0.05, 0.10, 0.15]
X2_GRID = [0.20, 0.25, 0.30]
GIVEBACK_GRID = [0.4, 0.5]
DEPTH_GRID = [0.20, 0.25, 0.30]
TIME_GRID = [4.0, 6.0, 9.0]


def no_sell_baseline(prices: pd.DataFrame, ma_period: int, daily_amount: float) -> dict:
    """DCA below the MA, never sell — final multiple on contributed."""
    df = prices.copy()
    df["ma"] = df["close"].rolling(ma_period).mean().shift(1)
    below = df[df["close"] < df["ma"]].dropna(subset=["ma"])
    contributed = daily_amount * len(below)
    units = (daily_amount / below["close"]).sum()
    final_value = units * float(df["close"].iloc[-1])
    return {
        "contributed": round(contributed, 2),
        "final_value": round(final_value, 2),
        "multiple": round(final_value / contributed, 4) if contributed else 0.0,
        "n_buys": len(below),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", default="TSLA")
    parser.add_argument("--years", type=int, default=12)
    parser.add_argument("--ma-period", type=int, default=400)
    parser.add_argument("--daily-amount", type=float, default=10.0)
    parser.add_argument(
        "--detail", nargs=4, type=float, metavar=("X1", "X2", "DEPTH", "MONTHS"),
        help="print the per-cycle table for one parameter set (giveback=0.5)",
    )
    args = parser.parse_args()

    prices = load_prices(args.ticker, years=args.years)
    last_price = float(prices["close"].iloc[-1])
    print(f"{args.ticker}: {len(prices)} rows "
          f"({prices['date'].iloc[0].date()} ~ {prices['date'].iloc[-1].date()}), "
          f"last close {last_price:.2f}")

    baseline = no_sell_baseline(prices, args.ma_period, args.daily_amount)
    print(f"[baseline: DCA below MA{args.ma_period}, never sell] "
          f"multiple x{baseline['multiple']} "
          f"(contributed {baseline['contributed']}, buys {baseline['n_buys']})")

    if args.detail:
        x1, x2, depth_z, months = args.detail
        params = ProtocolParams(
            ma_period=args.ma_period, daily_amount=args.daily_amount,
            x1=x1, x2=x2, giveback=0.5, depth_z=depth_z, time_months=months,
        )
        _, cycles = run_protocol(prices, params)
        print(cycles_table(cycles, last_price).to_string(index=False))
        print(summarize(cycles, last_price))
        return

    rows = []
    for x1, x2, gb, z, months in itertools.product(
            X1_GRID, X2_GRID, GIVEBACK_GRID, DEPTH_GRID, TIME_GRID):
        if x2 <= x1:
            continue
        params = ProtocolParams(
            ma_period=args.ma_period, daily_amount=args.daily_amount,
            x1=x1, x2=x2, giveback=gb, depth_z=z, time_months=months,
        )
        _, cycles = run_protocol(prices, params)
        row = {"x1": x1, "x2": x2, "giveback": gb,
               "depth_z": z, "time_months": months}
        row.update(summarize(cycles, last_price))
        rows.append(row)

    out = pd.DataFrame(rows).sort_values("multiple", ascending=False)
    out_dir = Path("outputs")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"protocol_sweep_{args.ticker}.csv"
    out.to_csv(out_path, index=False)
    print(f"\nwrote {out_path} ({len(out)} combinations)\n")
    print("top 12 by final multiple:")
    print(out.head(12).to_string(index=False))
    print("\nbottom 5:")
    print(out.tail(5).to_string(index=False))


if __name__ == "__main__":
    main()
