from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd


BuyMode = Literal["shares", "dollars"]
PriceBasis = Literal["open", "close", "mid"]


@dataclass(frozen=True)
class SwingSummary:
    buy_start: pd.Timestamp
    buy_end: pd.Timestamp
    sell_date: pd.Timestamp
    buy_days: int
    total_units: float
    total_cost: float
    average_cost: float
    sell_price: float
    sell_value: float
    net_profit: float
    return_pct: float
    annualized_return: float
    holding_days: int


def add_moving_averages(df: pd.DataFrame, periods: list[int]) -> pd.DataFrame:
    out = df.copy()
    for period in periods:
        out[f"ma_{period}"] = out["close"].rolling(period).mean()
    return out


def execution_price(row: pd.Series, basis: PriceBasis) -> float:
    if basis == "open":
        return float(row["open"])
    if basis == "close":
        return float(row["close"])
    if basis == "mid":
        return (float(row["open"]) + float(row["close"])) / 2.0
    raise ValueError(f"Unknown price basis: {basis}")


def calculate_swing_dca(
    ohlc: pd.DataFrame,
    buy_start: pd.Timestamp,
    buy_end: pd.Timestamp,
    sell_date: pd.Timestamp,
    buy_mode: BuyMode,
    buy_amount: float,
    price_basis: PriceBasis,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
) -> tuple[pd.DataFrame, SwingSummary]:
    """Backtest a manually selected DCA swing window.

    Buys happen on available trading days inside the buy window.
    The final exit always happens at the selected sell day's close.
    """
    if buy_amount <= 0:
        raise ValueError("buy_amount must be positive")

    prices = ohlc.sort_values("date").reset_index(drop=True).copy()
    prices["date"] = pd.to_datetime(prices["date"])
    buy_start = pd.to_datetime(buy_start)
    buy_end = pd.to_datetime(buy_end)
    sell_date = pd.to_datetime(sell_date)

    if buy_end < buy_start:
        raise ValueError("buy_end must be on or after buy_start")
    if sell_date < buy_start:
        raise ValueError("sell_date must be on or after buy_start")

    buy_rows = prices[
        (prices["date"] >= buy_start)
        & (prices["date"] <= buy_end)
        & (prices["date"] <= sell_date)
    ].copy()
    if buy_rows.empty:
        raise ValueError("No trading days in the selected buy window")

    sell_candidates = prices[prices["date"] <= sell_date]
    if sell_candidates.empty:
        raise ValueError("No trading day exists on or before sell_date")
    sell_row = sell_candidates.iloc[-1]
    actual_sell_date = pd.to_datetime(sell_row["date"])
    sell_price = float(sell_row["close"]) * (1.0 - slippage_rate)

    trade_rows: list[dict[str, float | pd.Timestamp]] = []
    total_units = 0.0
    total_cost = 0.0

    for _, row in buy_rows.iterrows():
        base_price = execution_price(row, price_basis)
        buy_price = base_price * (1.0 + slippage_rate)
        if buy_mode == "shares":
            units = float(buy_amount)
            gross_cost = units * buy_price
        elif buy_mode == "dollars":
            gross_cost = float(buy_amount)
            units = gross_cost / buy_price
        else:
            raise ValueError(f"Unknown buy mode: {buy_mode}")

        fee = gross_cost * fee_rate
        total_units += units
        total_cost += gross_cost + fee
        trade_rows.append(
            {
                "date": pd.to_datetime(row["date"]),
                "buy_price": buy_price,
                "units": units,
                "gross_cost": gross_cost,
                "fee": fee,
                "total_cost": gross_cost + fee,
            }
        )

    trades = pd.DataFrame(trade_rows)
    sell_gross = total_units * sell_price
    sell_fee = sell_gross * fee_rate
    sell_value = sell_gross - sell_fee
    net_profit = sell_value - total_cost
    return_pct = net_profit / total_cost if total_cost else 0.0
    average_cost = total_cost / total_units if total_units else 0.0
    holding_days = max(1, (actual_sell_date - pd.to_datetime(trades["date"].iloc[0])).days)
    annualized_return = (1.0 + return_pct) ** (365.0 / holding_days) - 1.0 if return_pct > -1 else -1.0

    summary = SwingSummary(
        buy_start=pd.to_datetime(trades["date"].iloc[0]),
        buy_end=pd.to_datetime(trades["date"].iloc[-1]),
        sell_date=actual_sell_date,
        buy_days=len(trades),
        total_units=total_units,
        total_cost=total_cost,
        average_cost=average_cost,
        sell_price=sell_price,
        sell_value=sell_value,
        net_profit=net_profit,
        return_pct=return_pct,
        annualized_return=annualized_return,
        holding_days=holding_days,
    )
    return trades, summary


@dataclass(frozen=True)
class SwingSellLeg:
    date: pd.Timestamp
    weight: float       # intended fraction of total holdings
    units: float        # units actually sold at this leg
    price: float        # net sell price after slippage
    gross: float        # units * price
    fee: float
    value: float        # gross - fee


@dataclass(frozen=True)
class SwingMultiSummary:
    buy_start: pd.Timestamp
    buy_end: pd.Timestamp
    buy_days: int
    total_units: float
    total_cost: float
    average_cost: float
    sells: tuple[SwingSellLeg, ...]
    sell_value: float
    net_profit: float
    return_pct: float
    annualized_return: float
    holding_days: int

    @property
    def sell_date(self) -> pd.Timestamp:
        """Final exit date (the last sell leg)."""
        return self.sells[-1].date

    @property
    def avg_sell_price(self) -> float:
        """Units-weighted average sell price across all legs."""
        sold = sum(leg.units for leg in self.sells)
        if sold <= 0:
            return 0.0
        return sum(leg.units * leg.price for leg in self.sells) / sold


def _snap_on_or_before(prices: pd.DataFrame, when: pd.Timestamp) -> pd.Series | None:
    rows = prices[prices["date"] <= when]
    if rows.empty:
        return None
    return rows.iloc[-1]


def calculate_swing_dca_multi(
    ohlc: pd.DataFrame,
    buy_start: pd.Timestamp,
    buy_end: pd.Timestamp,
    sell_dates: list[pd.Timestamp],
    buy_mode: BuyMode,
    buy_amount: float,
    price_basis: PriceBasis,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
) -> tuple[pd.DataFrame, pd.DataFrame, SwingMultiSummary]:
    """Backtest a manually chosen DCA window with up to N split sell points.

    Buys happen every trading day inside ``[buy_start, buy_end]``. The
    accumulated position is then sold in equal tranches at each date in
    ``sell_dates`` (the last leg clears any rounding remainder so the
    position is always fully closed).
    """
    if buy_amount <= 0:
        raise ValueError("buy_amount must be positive")
    if not sell_dates:
        raise ValueError("최소 한 개의 매도일이 필요합니다")

    prices = ohlc.sort_values("date").reset_index(drop=True).copy()
    prices["date"] = pd.to_datetime(prices["date"])
    buy_start = pd.to_datetime(buy_start)
    buy_end = pd.to_datetime(buy_end)

    if buy_end < buy_start:
        raise ValueError("매수 종료일은 시작일과 같거나 이후여야 합니다")

    buy_rows = prices[(prices["date"] >= buy_start) & (prices["date"] <= buy_end)].copy()
    if buy_rows.empty:
        raise ValueError("선택한 매수 구간에 거래일이 없습니다")

    last_buy_date = pd.to_datetime(buy_rows["date"].iloc[-1])

    # Snap each sell date to the latest trading day on or before it, keep them
    # unique and ordered, and require every sell to land after the buy window.
    snapped: list[pd.Timestamp] = []
    for raw in sorted(pd.to_datetime(d) for d in sell_dates):
        row = _snap_on_or_before(prices, raw)
        if row is None:
            raise ValueError("매도일 이전에 거래일이 존재하지 않습니다")
        sell_day = pd.to_datetime(row["date"])
        if sell_day < last_buy_date:
            raise ValueError("매도일은 매수 종료일 이후여야 합니다")
        if sell_day not in snapped:
            snapped.append(sell_day)
    if not snapped:
        raise ValueError("유효한 매도일이 없습니다")

    # --- accumulate the position across the buy window ---
    trade_rows: list[dict[str, float | pd.Timestamp]] = []
    total_units = 0.0
    total_cost = 0.0
    for _, row in buy_rows.iterrows():
        base_price = execution_price(row, price_basis)
        buy_price = base_price * (1.0 + slippage_rate)
        if buy_mode == "shares":
            units = float(buy_amount)
            gross_cost = units * buy_price
        elif buy_mode == "dollars":
            gross_cost = float(buy_amount)
            units = gross_cost / buy_price
        else:
            raise ValueError(f"Unknown buy mode: {buy_mode}")

        fee = gross_cost * fee_rate
        total_units += units
        total_cost += gross_cost + fee
        trade_rows.append(
            {
                "date": pd.to_datetime(row["date"]),
                "buy_price": buy_price,
                "units": units,
                "gross_cost": gross_cost,
                "fee": fee,
                "total_cost": gross_cost + fee,
            }
        )

    trades = pd.DataFrame(trade_rows)

    # --- split-sell the position in equal tranches ---
    n = len(snapped)
    weight = 1.0 / n
    remaining = total_units
    legs: list[SwingSellLeg] = []
    sell_value = 0.0
    for index, sell_day in enumerate(snapped):
        sell_row = prices[prices["date"] == sell_day].iloc[0]
        leg_price = float(sell_row["close"]) * (1.0 - slippage_rate)
        if index == n - 1:
            leg_units = remaining            # final leg fully closes the position
        else:
            leg_units = total_units * weight
        remaining -= leg_units
        gross = leg_units * leg_price
        fee = gross * fee_rate
        value = gross - fee
        sell_value += value
        legs.append(
            SwingSellLeg(
                date=sell_day,
                weight=weight,
                units=leg_units,
                price=leg_price,
                gross=gross,
                fee=fee,
                value=value,
            )
        )

    sells_df = pd.DataFrame(
        [
            {
                "date": leg.date,
                "weight": leg.weight,
                "units": leg.units,
                "sell_price": leg.price,
                "gross": leg.gross,
                "fee": leg.fee,
                "value": leg.value,
            }
            for leg in legs
        ]
    )

    net_profit = sell_value - total_cost
    return_pct = net_profit / total_cost if total_cost else 0.0
    average_cost = total_cost / total_units if total_units else 0.0
    first_buy_date = pd.to_datetime(trades["date"].iloc[0])
    holding_days = max(1, (snapped[-1] - first_buy_date).days)
    annualized_return = (
        (1.0 + return_pct) ** (365.0 / holding_days) - 1.0 if return_pct > -1 else -1.0
    )

    summary = SwingMultiSummary(
        buy_start=first_buy_date,
        buy_end=last_buy_date,
        buy_days=len(trades),
        total_units=total_units,
        total_cost=total_cost,
        average_cost=average_cost,
        sells=tuple(legs),
        sell_value=sell_value,
        net_profit=net_profit,
        return_pct=return_pct,
        annualized_return=annualized_return,
        holding_days=holding_days,
    )
    return trades, sells_df, summary

