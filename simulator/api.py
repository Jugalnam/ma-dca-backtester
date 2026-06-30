from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from simulator.data import load_ohlc
from simulator.swing import add_moving_averages, calculate_swing_dca_multi


TRADING_DAYS_PER_YEAR = 252
DEFAULT_MA_PERIODS = (50, 200, 400)

app = FastAPI(title="MA DCA Backtester API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SwingRequest(BaseModel):
    ticker: str = Field(min_length=1)
    years: int = Field(default=5, ge=1, le=20)
    ma_periods: list[int] = Field(default_factory=lambda: list(DEFAULT_MA_PERIODS))
    buy_start: str
    buy_end: str
    sell_dates: list[str] = Field(min_length=1, max_length=3)
    buy_mode: Literal["shares", "dollars"] = "dollars"
    buy_amount: float = Field(default=100.0, gt=0)
    price_basis: Literal["open", "close", "mid"] = "mid"
    fee_rate: float = Field(default=0.0, ge=0)
    slippage_rate: float = Field(default=0.0, ge=0)


def ma_warmup_days(ma_periods: tuple[int, ...]) -> int:
    max_period = max(ma_periods) if ma_periods else 0
    return int((max_period / TRADING_DAYS_PER_YEAR) * 365) + 45 if max_period else 0


def visible_price_window(prices: pd.DataFrame, years: int) -> pd.DataFrame:
    latest = pd.to_datetime(prices["date"]).max()
    display_start = latest - pd.DateOffset(years=years)
    return prices[pd.to_datetime(prices["date"]) >= display_start].reset_index(drop=True).copy()


def clean_periods(ma_periods: list[int] | tuple[int, ...]) -> tuple[int, ...]:
    periods = sorted({int(period) for period in ma_periods if int(period) > 0})
    return tuple(periods or DEFAULT_MA_PERIODS)


@lru_cache(maxsize=32)
def cached_ohlc(ticker: str, years: int, ma_periods: tuple[int, ...]) -> pd.DataFrame:
    warmup_days = ma_warmup_days(ma_periods)
    return load_ohlc(ticker, years=years, warmup_days=warmup_days)


def load_visible_prices(ticker: str, years: int, ma_periods: tuple[int, ...]) -> pd.DataFrame:
    raw = cached_ohlc(ticker.upper(), years, ma_periods).copy()
    raw["date"] = pd.to_datetime(raw["date"])
    with_ma = add_moving_averages(raw, list(ma_periods))
    return visible_price_window(with_ma, years)


def row_date(row: pd.Series) -> str:
    return pd.to_datetime(row["date"]).strftime("%Y-%m-%d")


def to_float(value: object) -> float:
    return float(value) if pd.notna(value) else 0.0


def format_summary(summary) -> dict[str, object]:
    return {
        "buy_start": summary.buy_start.strftime("%Y-%m-%d"),
        "buy_end": summary.buy_end.strftime("%Y-%m-%d"),
        "sell_date": summary.sell_date.strftime("%Y-%m-%d"),
        "buy_days": summary.buy_days,
        "total_units": summary.total_units,
        "total_cost": summary.total_cost,
        "average_cost": summary.average_cost,
        "sell_value": summary.sell_value,
        "net_profit": summary.net_profit,
        "return_pct": summary.return_pct,
        "annualized_return": summary.annualized_return,
        "holding_days": summary.holding_days,
        "avg_sell_price": summary.avg_sell_price,
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "MA DCA Backtester API is running.",
        "frontend_url": "http://127.0.0.1:5173",
        "docs_url": "http://127.0.0.1:8000/docs",
    }


@app.get("/api/prices")
def prices(
    ticker: str = Query(default="TSLA", min_length=1),
    years: int = Query(default=5, ge=1, le=20),
    ma_periods: list[int] = Query(default=list(DEFAULT_MA_PERIODS)),
) -> dict[str, object]:
    periods = clean_periods(ma_periods)
    try:
        df = load_visible_prices(ticker, years, periods)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"데이터를 조회할 수 없습니다: {exc}") from exc

    candles = [
        {
            "time": row_date(row),
            "open": to_float(row["open"]),
            "high": to_float(row["high"]),
            "low": to_float(row["low"]),
            "close": to_float(row["close"]),
        }
        for _, row in df.iterrows()
    ]
    moving_averages = {
        str(period): [
            {"time": row_date(row), "value": to_float(row[f"ma_{period}"])}
            for _, row in df.dropna(subset=[f"ma_{period}"]).iterrows()
        ]
        for period in periods
    }
    return {
        "ticker": ticker.upper(),
        "years": years,
        "ma_periods": list(periods),
        "min_date": row_date(df.iloc[0]),
        "max_date": row_date(df.iloc[-1]),
        "candles": candles,
        "moving_averages": moving_averages,
    }


@app.post("/api/swing")
def swing(request: SwingRequest) -> dict[str, object]:
    periods = clean_periods(request.ma_periods)
    try:
        prices = load_visible_prices(request.ticker, request.years, periods)
        trades, sells, summary = calculate_swing_dca_multi(
            prices,
            buy_start=pd.Timestamp(request.buy_start),
            buy_end=pd.Timestamp(request.buy_end),
            sell_dates=[pd.Timestamp(date) for date in request.sell_dates],
            buy_mode=request.buy_mode,
            buy_amount=request.buy_amount,
            price_basis=request.price_basis,
            fee_rate=request.fee_rate,
            slippage_rate=request.slippage_rate,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"계산할 수 없습니다: {exc}") from exc

    return {
        "summary": format_summary(summary),
        "trades": [
            {
                "date": row_date(row),
                "buy_price": to_float(row["buy_price"]),
                "units": to_float(row["units"]),
                "gross_cost": to_float(row["gross_cost"]),
                "fee": to_float(row["fee"]),
                "total_cost": to_float(row["total_cost"]),
            }
            for _, row in trades.iterrows()
        ],
        "sells": [
            {
                "date": row_date(row),
                "weight": to_float(row["weight"]),
                "units": to_float(row["units"]),
                "sell_price": to_float(row["sell_price"]),
                "gross": to_float(row["gross"]),
                "fee": to_float(row["fee"]),
                "value": to_float(row["value"]),
            }
            for _, row in sells.iterrows()
        ],
    }


@app.post("/api/swing/save")
def save_swing(request: SwingRequest) -> dict[str, object]:
    result = swing(request)
    summary = result["summary"]
    ticker = request.ticker.upper()
    sell_tag = "-".join(request.sell_dates)
    safe_name = f"{ticker}_{summary['buy_start']}_{summary['buy_end']}_{sell_tag}"
    out_dir = Path("outputs")
    out_dir.mkdir(exist_ok=True)

    trades_path = out_dir / f"{safe_name}_web_trades.csv"
    sells_path = out_dir / f"{safe_name}_web_sells.csv"
    summary_path = out_dir / f"{safe_name}_web_summary.csv"
    pd.DataFrame(result["trades"]).to_csv(trades_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(result["sells"]).to_csv(sells_path, index=False, encoding="utf-8-sig")
    pd.DataFrame([summary]).to_csv(summary_path, index=False, encoding="utf-8-sig")

    return {
        "paths": {
            "trades": str(trades_path),
            "sells": str(sells_path),
            "summary": str(summary_path),
        }
    }
