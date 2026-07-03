from __future__ import annotations

from test_engine import (
    test_accumulate_below_uses_shifted_sma_and_contributions,
    test_breakout_buys_on_first_cross_back_above_ma,
    test_dca_summary_and_buy_and_hold,
    test_irr_handles_long_daily_cashflow_series,
    test_sell_above_ma_exits_existing_position,
    test_take_profit_exits_existing_position,
    test_trailing_stop_exits_after_peak_drawdown,
)


def main() -> None:
    test_accumulate_below_uses_shifted_sma_and_contributions()
    test_breakout_buys_on_first_cross_back_above_ma()
    test_sell_above_ma_exits_existing_position()
    test_take_profit_exits_existing_position()
    test_trailing_stop_exits_after_peak_drawdown()
    test_dca_summary_and_buy_and_hold()
    test_irr_handles_long_daily_cashflow_series()
    print("All tests passed.")


if __name__ == "__main__":
    main()
