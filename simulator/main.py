from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from simulator.data import load_prices
from simulator.engine import DCABelowMA, Engine
from simulator.report import buy_and_hold, dca_summary, report_selffinanced, write_comparison_csv


def run_sweep(
    tickers: list[str],
    years: int,
    daily_amount: float,
    ma_periods: list[int],
    entry_modes: list[str],
    sell_modes: list[str],
    out_dir: Path,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
    take_profit_pct: float = 0.2,
    stop_loss_pct: float = 0.2,
    trailing_stop_pct: float = 0.1,
    make_html: bool = True,
) -> pd.DataFrame:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    engine = Engine(fee_rate=fee_rate, slippage_rate=slippage_rate)

    for ticker in tickers:
        prices = load_prices(ticker, years=years)
        prices_path = out_dir / f"{ticker}_prices.csv"
        prices.to_csv(prices_path, index=False, encoding="utf-8-sig")

        for ma_period in ma_periods:
            for entry_mode in entry_modes:
                for sell_mode in sell_modes:
                    cfg = {
                        "ma_period": ma_period,
                        "entry_mode": entry_mode,
                        "sell_mode": sell_mode,
                        "daily_amount": daily_amount,
                        "take_profit_pct": take_profit_pct,
                        "stop_loss_pct": stop_loss_pct,
                        "trailing_stop_pct": trailing_stop_pct,
                    }
                    strategy = DCABelowMA(cfg)
                    result = engine.run(prices, strategy, ma_periods=tuple(sorted(set(ma_periods))))
                    summary = dca_summary(result)

                    strategy_name = f"{ticker}_ma{ma_period}_{entry_mode}_{sell_mode}"
                    result_path = out_dir / f"{strategy_name}.csv"
                    result.to_csv(result_path, index=False, encoding="utf-8-sig")

                    benchmark = buy_and_hold(prices, summary["contributed"])
                    benchmark_final = float(benchmark["value"].iloc[-1]) if not benchmark.empty else 0.0
                    benchmark_multiple = (
                        benchmark_final / summary["contributed"] if summary["contributed"] else 0.0
                    )

                    if make_html and summary["contributed"] > 0:
                        html_path = out_dir / f"{strategy_name}_quantstats.html"
                        try:
                            strategy_value = result.set_index(pd.to_datetime(result["date"]))["value"]
                            benchmark_value = benchmark.set_index(pd.to_datetime(benchmark["date"]))["value"]
                            report_selffinanced(
                                strategy_value,
                                benchmark_value,
                                str(html_path),
                            )
                        except Exception as exc:
                            print(f"[WARN] quantstats report failed for {strategy_name}: {exc}")

                    rows.append(
                        {
                            "ticker": ticker,
                            "ma_period": ma_period,
                            "entry_mode": entry_mode,
                            "sell_mode": sell_mode,
                            "daily_amount": daily_amount,
                            "fee_rate": fee_rate,
                            "slippage_rate": slippage_rate,
                            "take_profit_pct": take_profit_pct,
                            "stop_loss_pct": stop_loss_pct,
                            "trailing_stop_pct": trailing_stop_pct,
                            "final_value": summary["final_value"],
                            "contributed": summary["contributed"],
                            "multiple": summary["multiple"],
                            "annualized_irr": summary["annualized_irr"],
                            "benchmark_final_value": benchmark_final,
                            "benchmark_multiple": benchmark_multiple,
                            "sell_count": int((result["sold_today"] > 0).sum()),
                            "result_csv": str(result_path),
                        }
                    )

    return write_comparison_csv(rows, out_dir / "comparison.csv")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DCA below moving-average backtester")
    parser.add_argument("--tickers", nargs="+", default=["TSLA", "MSFT", "INTC"])
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--daily-amount", type=float, default=10.0)
    parser.add_argument("--ma-periods", nargs="+", type=int, default=[200, 400])
    parser.add_argument(
        "--entry-modes",
        nargs="+",
        choices=["accumulate_below", "breakout"],
        default=["accumulate_below", "breakout"],
    )
    parser.add_argument(
        "--sell-modes",
        nargs="+",
        choices=[
            "hold",
            "sell_above_ma",
            "take_profit",
            "stop_loss",
            "take_profit_or_stop_loss",
            "trailing_stop",
        ],
        default=["hold"],
    )
    parser.add_argument("--out-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--fee-rate", type=float, default=0.0)
    parser.add_argument("--slippage-rate", type=float, default=0.0)
    parser.add_argument("--take-profit-pct", type=float, default=0.2)
    parser.add_argument("--stop-loss-pct", type=float, default=0.2)
    parser.add_argument("--trailing-stop-pct", type=float, default=0.1)
    parser.add_argument("--html", action="store_true", help="Generate quantstats HTML reports")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    comparison = run_sweep(
        tickers=args.tickers,
        years=args.years,
        daily_amount=args.daily_amount,
        ma_periods=args.ma_periods,
        entry_modes=args.entry_modes,
        sell_modes=args.sell_modes,
        out_dir=args.out_dir,
        fee_rate=args.fee_rate,
        slippage_rate=args.slippage_rate,
        take_profit_pct=args.take_profit_pct,
        stop_loss_pct=args.stop_loss_pct,
        trailing_stop_pct=args.trailing_stop_pct,
        make_html=args.html,
    )
    print(comparison.to_string(index=False))
    print(f"\nSaved outputs to: {args.out_dir.resolve()}")


if __name__ == "__main__":
    main()
