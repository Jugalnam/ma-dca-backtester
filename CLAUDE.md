# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A backtesting prototype for **DCA (dollar-cost-averaging) strategies built around moving averages**. Two entry points share the same data and reporting layer but answer different questions:

- **`simulator/main.py`** — headless CLI sweep. Runs every combination of ticker × MA period × entry mode × sell mode and writes per-strategy CSVs plus a `comparison.csv` table (optionally quantstats HTML reports).
- **`simulator/app.py`** — Streamlit UI for **manually selected swing windows**: pick a buy start/end and a sell date on a candlestick chart, see the resulting DCA return. This path uses `simulator/swing.py`, NOT the `Engine`.

All explanations to the user must be in **Korean** (see global CLAUDE.md).

## Commands

```powershell
pip install -r requirements.txt

# CLI sweep (writes to outputs/)
python -m simulator.main --tickers TSLA MSFT INTC --years 10 --daily-amount 10
python -m simulator.main --tickers TSLA --ma-periods 50 200 --sell-modes hold take_profit --html

# Streamlit UI
streamlit run simulator/app.py

# Tests — run_tests.py uses bare `from test_engine import ...`, so it must run from inside tests/
cd tests; python run_tests.py
# or with pytest from the repo root
pytest tests/
```

There is no lint/format toolchain configured.

## Architecture

Two independent backtesting paths — do not confuse them:

### 1. Event-driven engine (CLI path)
`simulator/engine.py` defines a small framework:
- **`Engine.run(prices, strategy, ma_periods)`** iterates day by day, building a `Context` (price, SMAs, portfolio) and calling `strategy.next(ctx)`, which returns a list of action dicts (`buy`/`sell`/`sell_all`). `Engine._exec` applies fees/slippage and mutates the shared `Portfolio`.
- **`Strategy` / `DCABelowMA`** — strategy logic. `DCABelowMA` supports `entry_mode` (`accumulate_below`, `breakout`) and `sell_mode` (`hold`, `sell_above_ma`, `take_profit`, `stop_loss`, `take_profit_or_stop_loss`).
- To add a strategy: subclass `Strategy`, implement `next()` returning action dicts, and wire it into `run_sweep` in `main.py`.

### 2. Swing calculator (UI path)
`simulator/swing.py` `calculate_swing_dca(...)` is a self-contained, non-iterative computation for a user-chosen date window — it buys every trading day in the window and exits on the sell date. It has its own fee/slippage handling and returns a `(trades_df, SwingSummary)` tuple. It does **not** go through `Engine`.

### Shared layers
- **`simulator/data.py`** — `load_prices` (date/close) and `load_ohlc` (full OHLC) pull adjusted prices from Yahoo Finance via `yfinance` (`auto_adjust=True`). Both flatten the MultiIndex columns yfinance returns.
- **`simulator/report.py`** — performance metrics and quantstats output: `dca_summary`, `buy_and_hold` benchmark, and IRR solvers (`solve_xirr` dated, `solve_irr` periodic) implemented by hand via bisection (no scipy).

## Critical conventions

These reflect deliberate design decisions in the spec — preserve them:

- **No look-ahead.** Moving averages use only data through *yesterday*: `prices["close"].rolling(period).mean().shift(1)` in `Engine.run`. Any new MA logic must keep the `.shift(1)`.
- **DCA performance is measured by final multiple and money-weighted IRR, not naive daily returns.** Contributions are treated as external cash inflows (`contributed_today`), and IRR is computed from the dated cash-flow series. Do not switch summary stats to simple `pct_change` returns.
- **quantstats reports use self-financed returns** (`report_selffinanced` strips the contribution flows by taking `pct_change` of the value series) so the contribution inflows don't distort the return series.
- No live order or keypress/trading code — this is backtest-only by design.
- CSVs are written with `encoding="utf-8-sig"` (Excel-friendly Korean). Keep this when adding outputs.

## Outputs

Everything lands in `outputs/`: `{ticker}_prices.csv`, per-strategy `{ticker}_ma{period}_{entry}_{sell}.csv`, `comparison.csv`, optional `*_quantstats.html`, and swing exports `{ticker}_{start}_{end}_{sell}_swing_*.csv`. This directory is regenerated output, not source.
