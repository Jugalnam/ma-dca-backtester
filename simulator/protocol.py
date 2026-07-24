"""Rule-based sell protocol simulator for the MA-deviation DCA strategy.

Implements the 3-layer sell protocol (2026-07-24 spec):

  Layer A (accumulate gate): buy a fixed amount every trading day while the
      daily close is below the moving average. Buying stops naturally above it.
  Layer B (profit taking, judged on WEEKLY closes, executed next trading day):
      tranche 1: deviation above MA >= x1  -> sell 1/3 of units
      tranche 2: deviation above MA >= x2  -> sell 1/2 of remaining units
      tranche 3: trailing on remainder     -> exit all when the deviation gives
                 back `giveback` of its post-tranche-1 peak
  Layer C (circuit breakers, judged on DAILY closes, executed next trading day):
      depth: close <= MA * (1 - depth_z)          -> liquidate, cycle void
      time:  below-MA stay exceeds `time_months`  -> liquidate, cycle void
      (the below-MA stay clock only resets when a WEEKLY close prints above MA)

After a circuit fires the strategy is disarmed until a weekly close prints
above the MA again (a fresh regime), then a new cycle may start below the MA.

All judgments use closes only; executions happen at the NEXT trading day's
close (no look-ahead: the MA itself is shifted one day, matching engine.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ProtocolParams:
    ma_period: int = 400
    daily_amount: float = 10.0
    # Optional tiered accumulation: ((dev_floor, amount), ...) sorted shallow
    # to deep. The amount of the deepest zone whose floor is above `dev` wins,
    # e.g. ((-0.10, 10), (-0.20, 20), (-1.0, 30)) buys 10 while the deviation
    # is above -10%, 20 down to -20%, then 30. None = flat daily_amount.
    amount_ladder: tuple[tuple[float, float], ...] | None = None
    # True: the zone is judged on the last WEEKLY close and holds for the next
    # week (matches real ops where the app's daily amount is set weekly).
    ladder_weekly: bool = False

    def amount_for(self, dev: float) -> float:
        if self.amount_ladder is None:
            return self.daily_amount
        for floor, amount in self.amount_ladder:
            if dev > floor:
                return amount
        return self.amount_ladder[-1][1]
    x1: float = 0.10          # tranche-1 deviation above MA
    x2: float = 0.20          # tranche-2 deviation above MA
    giveback: float = 0.5     # trailing: fraction of peak deviation given back
    depth_z: float = 0.25     # depth circuit: close <= MA * (1 - depth_z)
    time_months: float = 6.0  # time circuit: continuous below-MA stay
    fee_rate: float = 0.0
    slippage_rate: float = 0.0


@dataclass
class Cycle:
    cycle_id: int
    start: pd.Timestamp
    end: pd.Timestamp | None = None
    contributed: float = 0.0
    proceeds: float = 0.0
    units: float = 0.0
    tranches_sold: int = 0
    max_dev: float = 0.0          # peak weekly deviation, tracked after tranche 1
    below_streak_start: pd.Timestamp | None = None
    exit_type: str | None = None  # trailing / depth / time / open
    n_buys: int = 0

    def return_pct(self, mark_price: float | None = None) -> float:
        value = self.proceeds + (self.units * mark_price if mark_price else 0.0)
        return value / self.contributed - 1.0 if self.contributed > 0 else 0.0


def _mark_weekly_close(dates: pd.Series) -> pd.Series:
    """True on the last trading day of each ISO week."""
    iso = dates.dt.isocalendar()
    week_key = iso["year"].astype(str) + "-" + iso["week"].astype(str)
    return week_key != week_key.shift(-1)


def run_protocol(
    prices: pd.DataFrame,
    params: ProtocolParams,
) -> tuple[pd.DataFrame, list[Cycle]]:
    """Run the sell protocol over daily close prices.

    Returns (daily records DataFrame, list of cycles including any open one).
    """
    df = prices.sort_values("date").reset_index(drop=True).copy()
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = df["close"].astype(float)
    # Look-ahead guard: today's judgment uses the MA through yesterday.
    df["ma"] = df["close"].rolling(params.ma_period).mean().shift(1)
    df["is_weekly_close"] = _mark_weekly_close(df["date"])

    cycles: list[Cycle] = []
    cur: Cycle | None = None
    armed = True                       # disarmed after a circuit until re-arm
    pending: dict[str, Any] | None = None  # executes at today's close
    time_limit = pd.Timedelta(days=params.time_months * 30.4375)
    weekly_dev: float | None = None    # last weekly-close deviation (ladder)

    records: list[dict[str, Any]] = []

    for row in df.itertuples(index=False):
        date, price, ma, weekly = row.date, row.close, row.ma, row.is_weekly_close
        sold_today = 0.0
        bought_today = 0.0

        # 1) Execute the action scheduled on the previous judgment day.
        if pending is not None and cur is not None and cur.units > 0:
            exec_price = price * (1.0 - params.slippage_rate)
            if pending["kind"] == "fraction":
                units = cur.units * pending["fraction"]
            else:  # liquidate
                units = cur.units
            gross = units * exec_price
            net = gross * (1.0 - params.fee_rate)
            cur.units -= units
            cur.proceeds += net
            sold_today = net
            if pending["kind"] == "fraction":
                cur.tranches_sold += 1
            if cur.units <= 1e-12:
                cur.units = 0.0
                cur.end = date
                cur.exit_type = pending["exit_type"]
                cycles.append(cur)
                if pending["exit_type"] in ("depth", "time"):
                    armed = False
                cur = None
        pending = None

        if pd.isna(ma):
            records.append({"date": date, "price": price, "ma": None,
                            "bought": 0.0, "sold": 0.0})
            continue
        ma = float(ma)
        dev = price / ma - 1.0

        # 2) Re-arm after a circuit: a weekly close above the MA = new regime.
        if not armed and weekly and price >= ma:
            armed = True

        # 3) Layer A — daily accumulation below the MA (optionally tiered).
        if armed and price < ma:
            if cur is None:
                cur = Cycle(cycle_id=len(cycles) + 1, start=date,
                            below_streak_start=date)
            ladder_dev = (weekly_dev if params.ladder_weekly
                          and weekly_dev is not None else dev)
            amount = params.amount_for(ladder_dev)
            exec_price = price * (1.0 + params.slippage_rate)
            cur.contributed += amount
            cur.units += (amount * (1.0 - params.fee_rate)) / exec_price
            cur.n_buys += 1
            bought_today = amount

        if cur is not None and cur.units > 0:
            # 4) Below-MA stay clock (resets only on a weekly close above MA).
            if cur.below_streak_start is None and price < ma:
                cur.below_streak_start = date
            if weekly and price >= ma:
                cur.below_streak_start = None

            # 5) Layer C — daily circuit judgments.
            if price <= ma * (1.0 - params.depth_z):
                pending = {"kind": "liquidate", "exit_type": "depth"}
            elif (cur.below_streak_start is not None
                    and date - cur.below_streak_start > time_limit):
                pending = {"kind": "liquidate", "exit_type": "time"}

            # 6) Layer B — weekly profit-taking judgments.
            elif weekly:
                if cur.tranches_sold >= 1:
                    cur.max_dev = max(cur.max_dev, dev)
                if cur.tranches_sold == 0 and dev >= params.x1:
                    pending = {"kind": "fraction", "fraction": 1.0 / 3.0,
                               "exit_type": "tranche1"}
                    cur.max_dev = max(cur.max_dev, dev)
                elif cur.tranches_sold == 1 and dev >= params.x2:
                    pending = {"kind": "fraction", "fraction": 0.5,
                               "exit_type": "tranche2"}
                elif (cur.tranches_sold >= 1 and cur.max_dev > 0
                        and dev <= cur.max_dev * (1.0 - params.giveback)):
                    pending = {"kind": "liquidate", "exit_type": "trailing"}

        if weekly:
            weekly_dev = dev

        records.append({"date": date, "price": price, "ma": ma,
                        "bought": bought_today, "sold": sold_today})

    if cur is not None:
        cur.exit_type = "open"
        cur.end = df["date"].iloc[-1]
        cycles.append(cur)

    return pd.DataFrame(records), cycles


def summarize(cycles: list[Cycle], last_price: float) -> dict[str, Any]:
    """Aggregate cycle results into sweep-comparable metrics."""
    closed = [c for c in cycles if c.exit_type != "open"]
    open_cycles = [c for c in cycles if c.exit_type == "open"]
    contributed = sum(c.contributed for c in cycles)
    realized = sum(c.proceeds for c in cycles)
    unrealized = sum(c.units * last_price for c in open_cycles)
    total_value = realized + unrealized

    closed_returns = [c.return_pct() for c in closed]
    return {
        "n_cycles": len(cycles),
        "n_closed": len(closed),
        "n_depth": sum(1 for c in closed if c.exit_type == "depth"),
        "n_time": sum(1 for c in closed if c.exit_type == "time"),
        "n_trailing": sum(1 for c in closed if c.exit_type == "trailing"),
        "contributed": round(contributed, 2),
        "final_value": round(total_value, 2),
        "multiple": round(total_value / contributed, 4) if contributed else 0.0,
        "worst_cycle_pct": round(min(closed_returns) * 100, 2) if closed_returns else None,
        "best_cycle_pct": round(max(closed_returns) * 100, 2) if closed_returns else None,
        "open_unrealized_pct": (
            round((unrealized / sum(c.contributed for c in open_cycles) - 1) * 100, 2)
            if open_cycles and sum(c.contributed for c in open_cycles) > 0 else None
        ),
    }


def cycles_table(cycles: list[Cycle], last_price: float) -> pd.DataFrame:
    rows = []
    for c in cycles:
        mark = last_price if c.exit_type == "open" else None
        rows.append({
            "cycle": c.cycle_id,
            "start": c.start.date(),
            "end": c.end.date() if c.end is not None else None,
            "days": (c.end - c.start).days if c.end is not None else None,
            "buys": c.n_buys,
            "contributed": round(c.contributed, 2),
            "proceeds": round(c.proceeds, 2),
            "return_pct": round(c.return_pct(mark) * 100, 2),
            "exit": c.exit_type,
        })
    return pd.DataFrame(rows)
