from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class Portfolio:
    cash: float = 0.0
    units: float = 0.0
    invested: float = 0.0
    total_contributed: float = 0.0


@dataclass
class Context:
    i: int
    date: Any
    price: float
    sma: dict[int, float | None]
    portfolio: Portfolio
    state: dict[str, Any] = field(default_factory=dict)


class Strategy:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.state: dict[str, Any] = {}

    def next(self, ctx: Context) -> list[dict[str, Any]]:
        raise NotImplementedError


class DCABelowMA(Strategy):
    """Buy a fixed dollar amount around a moving-average rule."""

    def next(self, ctx: Context) -> list[dict[str, Any]]:
        ma_period = int(self.cfg["ma_period"])
        ma = ctx.sma[ma_period]
        if ma is None:
            return []

        mode = self.cfg.get("entry_mode", "accumulate_below")
        sell_mode = self.cfg.get("sell_mode", "hold")
        amount = float(self.cfg["daily_amount"])
        actions: list[dict[str, Any]] = []

        if self._should_sell(ctx, ma, sell_mode):
            return [{"type": "sell_all"}]

        if mode == "accumulate_below":
            actions = [{"type": "buy", "amount": amount}] if ctx.price < ma else []

        elif mode == "breakout":
            was_below = bool(self.state.get("below", ctx.price < ma))
            is_below = ctx.price < ma
            crossed_up = was_below and ctx.price >= ma
            self.state["below"] = is_below
            actions = [{"type": "buy", "amount": amount}] if crossed_up else []

        else:
            raise ValueError(f"Unknown entry_mode: {mode}")

        return actions

    def _should_sell(self, ctx: Context, ma: float, sell_mode: str) -> bool:
        if sell_mode == "hold" or ctx.portfolio.units <= 0:
            return False

        avg_cost = ctx.portfolio.invested / ctx.portfolio.units if ctx.portfolio.units else 0.0
        take_profit_pct = float(self.cfg.get("take_profit_pct", 0.2))
        stop_loss_pct = float(self.cfg.get("stop_loss_pct", 0.2))

        if sell_mode == "sell_above_ma":
            return ctx.price >= ma
        if sell_mode == "take_profit":
            return avg_cost > 0 and ctx.price >= avg_cost * (1.0 + take_profit_pct)
        if sell_mode == "stop_loss":
            return avg_cost > 0 and ctx.price <= avg_cost * (1.0 - stop_loss_pct)
        if sell_mode == "take_profit_or_stop_loss":
            return avg_cost > 0 and (
                ctx.price >= avg_cost * (1.0 + take_profit_pct)
                or ctx.price <= avg_cost * (1.0 - stop_loss_pct)
            )

        raise ValueError(f"Unknown sell_mode: {sell_mode}")


class Engine:
    def __init__(self, fee_rate: float = 0.0, slippage_rate: float = 0.0):
        self.fee_rate = float(fee_rate)
        self.slippage_rate = float(slippage_rate)

    def run(
        self,
        prices: pd.DataFrame,
        strategy: Strategy,
        ma_periods: tuple[int, ...] = (200, 400),
    ) -> pd.DataFrame:
        if "date" not in prices.columns or "close" not in prices.columns:
            raise ValueError("prices must contain date and close columns")

        prices = prices.sort_values("date").reset_index(drop=True).copy()
        prices["close"] = prices["close"].astype(float)

        # Prevent look-ahead: today's decision uses moving averages through yesterday.
        sma_tbl = {
            period: prices["close"].rolling(period).mean().shift(1)
            for period in ma_periods
        }

        pf = Portfolio()
        records: list[dict[str, Any]] = []

        for i, row in prices.iterrows():
            price = float(row["close"])
            ctx = Context(
                i=i,
                date=row["date"],
                price=price,
                sma={
                    period: (
                        None
                        if pd.isna(sma_tbl[period].iloc[i])
                        else float(sma_tbl[period].iloc[i])
                    )
                    for period in ma_periods
                },
                portfolio=pf,
                state=strategy.state,
            )

            actions = strategy.next(ctx)
            contributed_today = 0.0
            bought_today = 0.0
            sold_today = 0.0
            for action in actions:
                result = self._exec(pf, action, price)
                contributed_today += result["contributed"]
                bought_today += result["bought"]
                sold_today += result["sold"]

            equity = pf.units * price
            records.append(
                {
                    "date": row["date"],
                    "price": price,
                    "equity": equity,
                    "cash": pf.cash,
                    "value": equity + pf.cash,
                    "units": pf.units,
                    "contributed": pf.total_contributed,
                    "contributed_today": contributed_today,
                    "bought_today": bought_today,
                    "sold_today": sold_today,
                }
            )

        return pd.DataFrame(records)

    def _exec(self, pf: Portfolio, action: dict[str, Any], price: float) -> dict[str, float]:
        action_type = action["type"]

        if action_type == "sell_all":
            if pf.units <= 0:
                return {"contributed": 0.0, "bought": 0.0, "sold": 0.0}
            execution_price = price * (1.0 - self.slippage_rate)
            gross = pf.units * execution_price
            fee = gross * self.fee_rate
            net = gross - fee
            pf.units = 0.0
            pf.invested = 0.0
            pf.cash += net
            return {"contributed": 0.0, "bought": 0.0, "sold": net}

        amount = float(action["amount"])
        if amount <= 0:
            return {"contributed": 0.0, "bought": 0.0, "sold": 0.0}

        if action_type == "buy":
            fee = amount * self.fee_rate
            tradable_amount = amount - fee
            execution_price = price * (1.0 + self.slippage_rate)
            pf.total_contributed += amount
            pf.units += tradable_amount / execution_price
            pf.invested += amount
            return {"contributed": amount, "bought": amount, "sold": 0.0}

        if action_type == "sell":
            execution_price = price * (1.0 - self.slippage_rate)
            units = min(amount / execution_price, pf.units)
            gross = units * execution_price
            fee = gross * self.fee_rate
            net = gross - fee
            if pf.units > 0:
                pf.invested *= max(0.0, 1.0 - (units / pf.units))
            pf.units -= units
            pf.cash += net
            return {"contributed": 0.0, "bought": 0.0, "sold": net}

        raise ValueError(f"Unknown action type: {action_type}")
