from __future__ import annotations

import pandas as pd

from simulator.engine import DCABelowMA, Engine
from simulator.report import buy_and_hold, dca_summary


def test_accumulate_below_uses_shifted_sma_and_contributions() -> None:
    prices = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "close": [10.0, 10.0, 10.0, 9.0, 8.0],
        }
    )
    strategy = DCABelowMA(
        {
            "ma_period": 3,
            "entry_mode": "accumulate_below",
            "daily_amount": 30.0,
        }
    )
    result = Engine().run(prices, strategy, ma_periods=(3,))

    assert result["contributed_today"].tolist() == [0.0, 0.0, 0.0, 30.0, 30.0]
    assert result["contributed"].iloc[-1] == 60.0
    assert result["units"].iloc[-1] == (30.0 / 9.0) + (30.0 / 8.0)


def test_breakout_buys_on_first_cross_back_above_ma() -> None:
    prices = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=7, freq="D"),
            "close": [10.0, 10.0, 10.0, 9.0, 8.0, 11.0, 12.0],
        }
    )
    strategy = DCABelowMA(
        {
            "ma_period": 3,
            "entry_mode": "breakout",
            "daily_amount": 30.0,
        }
    )
    result = Engine().run(prices, strategy, ma_periods=(3,))

    assert result["contributed_today"].tolist() == [0.0, 0.0, 0.0, 0.0, 0.0, 30.0, 0.0]


def test_sell_above_ma_exits_existing_position() -> None:
    prices = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "close": [10.0, 10.0, 10.0, 9.0, 11.0],
        }
    )
    strategy = DCABelowMA(
        {
            "ma_period": 3,
            "entry_mode": "accumulate_below",
            "sell_mode": "sell_above_ma",
            "daily_amount": 30.0,
        }
    )
    result = Engine().run(prices, strategy, ma_periods=(3,))

    assert result["contributed_today"].tolist() == [0.0, 0.0, 0.0, 30.0, 0.0]
    assert result["sold_today"].iloc[-1] > 0
    assert result["units"].iloc[-1] == 0.0
    assert result["cash"].iloc[-1] > 30.0


def test_take_profit_exits_existing_position() -> None:
    prices = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "close": [10.0, 10.0, 10.0, 9.0, 12.0],
        }
    )
    strategy = DCABelowMA(
        {
            "ma_period": 3,
            "entry_mode": "accumulate_below",
            "sell_mode": "take_profit",
            "daily_amount": 30.0,
            "take_profit_pct": 0.2,
        }
    )
    result = Engine().run(prices, strategy, ma_periods=(3,))

    assert result["sold_today"].iloc[-1] > 0
    assert result["units"].iloc[-1] == 0.0


def test_dca_summary_and_buy_and_hold() -> None:
    prices = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=3, freq="D"),
            "close": [10.0, 20.0, 30.0],
        }
    )
    df = pd.DataFrame(
        {
            "date": prices["date"],
            "value": [10.0, 20.0, 35.0],
            "contributed": [10.0, 20.0, 20.0],
            "contributed_today": [10.0, 10.0, 0.0],
        }
    )

    summary = dca_summary(df)
    benchmark = buy_and_hold(prices, summary["contributed"])

    assert summary["final_value"] == 35.0
    assert summary["contributed"] == 20.0
    assert summary["multiple"] == 1.75
    assert benchmark["value"].iloc[-1] == 60.0


def test_irr_handles_long_daily_cashflow_series() -> None:
    dates = pd.date_range("2014-01-01", periods=3000, freq="D")
    df = pd.DataFrame(
        {
            "date": dates,
            "value": [float(i + 1) for i in range(3000)],
            "contributed": [float(i + 1) for i in range(3000)],
            "contributed_today": [1.0 for _ in range(3000)],
        }
    )

    summary = dca_summary(df)

    assert summary["final_value"] == 3000.0
    assert summary["contributed"] == 3000.0
    assert summary["multiple"] == 1.0
