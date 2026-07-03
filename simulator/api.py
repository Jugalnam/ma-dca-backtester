from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from simulator.data import load_ohlc
from simulator.engine import DCABelowMA, Engine
from simulator.report import buy_and_hold, dca_summary
from simulator.swing import add_moving_averages, calculate_swing_dca_multi


TRADING_DAYS_PER_YEAR = 252
DEFAULT_MA_PERIODS = (50, 200, 400)
DEFAULT_SCREEN_TICKERS = (
    "MSFT",
    "AAPL",
    "AMZN",
    "GOOGL",
    "META",
    "NVDA",
    "AVGO",
    "ORCL",
    "CRM",
    "ADBE",
    "NOW",
    "INTU",
    "AMD",
    "QCOM",
    "TXN",
    "ASML",
    "TSM",
    "COST",
    "HD",
    "MCD",
    "V",
    "MA",
    "LLY",
    "UNH",
    "ISRG",
    "NKE",
    "SBUX",
    "DIS",
    "PYPL",
    "QQQ",
    "SPY",
    "XLK",
    "SMH",
)
SellMode = Literal[
    "hold",
    "sell_above_ma",
    "take_profit",
    "stop_loss",
    "take_profit_or_stop_loss",
    "trailing_stop",
]

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


class RuleBacktestRequest(BaseModel):
    ticker: str = Field(min_length=1)
    years: int = Field(default=10, ge=1, le=30)
    ma_period: int = Field(default=400, ge=2, le=1000)
    entry_mode: Literal["accumulate_below", "breakout"] = "accumulate_below"
    sell_mode: SellMode = "sell_above_ma"
    daily_amount: float = Field(default=100.0, gt=0)
    fee_rate: float = Field(default=0.0, ge=0)
    slippage_rate: float = Field(default=0.0, ge=0)
    take_profit_pct: float = Field(default=0.2, ge=0)
    stop_loss_pct: float = Field(default=0.2, ge=0)
    trailing_stop_pct: float = Field(default=0.1, ge=0)


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


def parse_ticker_list(raw: str | None) -> list[str]:
    if not raw:
        return list(DEFAULT_SCREEN_TICKERS)
    tickers = [part.strip().upper() for part in raw.replace("\n", ",").split(",")]
    return [ticker for ticker in dict.fromkeys(tickers) if ticker]


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


def format_rule_summary(result: pd.DataFrame, prices: pd.DataFrame, ma_period: int) -> dict[str, object]:
    summary = dca_summary(result)
    benchmark = buy_and_hold(prices, summary["contributed"]) if summary["contributed"] else pd.DataFrame()
    benchmark_final = float(benchmark["value"].iloc[-1]) if not benchmark.empty else 0.0
    benchmark_multiple = (
        benchmark_final / summary["contributed"] if summary["contributed"] else 0.0
    )
    shifted_ma = prices["close"].rolling(ma_period).mean().shift(1)
    latest_ma = None if pd.isna(shifted_ma.iloc[-1]) else float(shifted_ma.iloc[-1])
    latest_price = float(prices["close"].iloc[-1])
    return {
        **summary,
        "benchmark_final_value": benchmark_final,
        "benchmark_multiple": benchmark_multiple,
        "buy_count": int((result["bought_today"] > 0).sum()),
        "sell_count": int((result["sold_today"] > 0).sum()),
        "latest_price": latest_price,
        "latest_ma": latest_ma,
        "latest_ma_gap_pct": (
            latest_price / latest_ma - 1.0 if latest_ma and latest_ma > 0 else None
        ),
        "start_date": row_date(prices.iloc[0]),
        "end_date": row_date(prices.iloc[-1]),
    }


def screen_row(
    ticker: str,
    years: int,
    ma_period: int,
    min_cagr: float,
    max_ma_gap_pct: float,
    min_ma_slope_pct: float,
) -> dict[str, object]:
    prices = load_visible_prices(ticker, years, (ma_period,))
    close = prices["close"].astype(float)
    ma_column = f"ma_{ma_period}"
    ma = prices[ma_column].astype(float)
    latest = float(close.iloc[-1])
    latest_ma = float(ma.dropna().iloc[-1]) if not ma.dropna().empty else 0.0
    ma_gap_pct = latest / latest_ma - 1.0 if latest_ma > 0 else 0.0
    high_52w = float(close.tail(TRADING_DAYS_PER_YEAR).max())
    drawdown_52w = latest / high_52w - 1.0 if high_52w > 0 else 0.0
    first = float(close.iloc[0])
    elapsed_years = max(1e-9, (pd.to_datetime(prices["date"].iloc[-1]) - pd.to_datetime(prices["date"].iloc[0])).days / 365.25)
    cagr = (latest / first) ** (1.0 / elapsed_years) - 1.0 if first > 0 else 0.0
    days_below_1y = int((close.tail(TRADING_DAYS_PER_YEAR) < ma.tail(TRADING_DAYS_PER_YEAR)).sum())
    below_days = int((close < ma).sum())
    ma_60 = ma.dropna().iloc[-60] if len(ma.dropna()) >= 60 else latest_ma
    ma_slope_3m = latest_ma / float(ma_60) - 1.0 if ma_60 and ma_60 > 0 else 0.0

    if cagr >= min_cagr and ma_gap_pct <= max_ma_gap_pct and ma_slope_3m >= min_ma_slope_pct:
        status = "candidate"
        status_label = "후보"
    elif ma_gap_pct <= max_ma_gap_pct and cagr >= 0:
        status = "watch"
        status_label = "주의"
    else:
        status = "wait"
        status_label = "대기"

    return {
        "ticker": ticker.upper(),
        "latest": latest,
        "ma": latest_ma,
        "ma_gap_pct": ma_gap_pct,
        "drawdown_52w": drawdown_52w,
        "cagr": cagr,
        "days_below_1y": days_below_1y,
        "below_days": below_days,
        "ma_slope_3m": ma_slope_3m,
        "status": status,
        "status_label": status_label,
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


@app.post("/api/rule-backtest")
def rule_backtest(request: RuleBacktestRequest) -> dict[str, object]:
    try:
        raw = load_ohlc(request.ticker.upper(), years=request.years)
        prices = raw[["date", "close"]].sort_values("date").reset_index(drop=True)
        strategy = DCABelowMA(
            {
                "ma_period": request.ma_period,
                "entry_mode": request.entry_mode,
                "sell_mode": request.sell_mode,
                "daily_amount": request.daily_amount,
                "take_profit_pct": request.take_profit_pct,
                "stop_loss_pct": request.stop_loss_pct,
                "trailing_stop_pct": request.trailing_stop_pct,
            }
        )
        result = Engine(
            fee_rate=request.fee_rate,
            slippage_rate=request.slippage_rate,
        ).run(prices, strategy, ma_periods=(request.ma_period,))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"규칙 백테스트를 계산할 수 없습니다: {exc}") from exc

    events = result[(result["bought_today"] > 0) | (result["sold_today"] > 0)].copy()
    return {
        "ticker": request.ticker.upper(),
        "summary": format_rule_summary(result, prices, request.ma_period),
        "series": [
            {
                "date": row_date(row),
                "price": to_float(row["price"]),
                "value": to_float(row["value"]),
                "units": to_float(row["units"]),
                "contributed": to_float(row["contributed"]),
            }
            for _, row in result.iterrows()
        ],
        "events": [
            {
                "date": row_date(row),
                "price": to_float(row["price"]),
                "bought": to_float(row["bought_today"]),
                "sold": to_float(row["sold_today"]),
                "value": to_float(row["value"]),
            }
            for _, row in events.iterrows()
        ],
    }


@app.get("/api/screener")
def screener(
    tickers: str | None = Query(default=None),
    years: int = Query(default=6, ge=2, le=30),
    ma_period: int = Query(default=400, ge=20, le=1000),
    min_cagr: float = Query(default=0.08),
    max_ma_gap_pct: float = Query(default=0.02),
    min_ma_slope_pct: float = Query(default=-0.03),
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    for ticker in parse_ticker_list(tickers):
        try:
            rows.append(
                screen_row(
                    ticker=ticker,
                    years=years,
                    ma_period=ma_period,
                    min_cagr=min_cagr,
                    max_ma_gap_pct=max_ma_gap_pct,
                    min_ma_slope_pct=min_ma_slope_pct,
                )
            )
        except Exception as exc:
            errors.append({"ticker": ticker, "error": str(exc)})

    status_order = {"candidate": 0, "watch": 1, "wait": 2}
    rows.sort(
        key=lambda row: (
            status_order.get(str(row["status"]), 9),
            abs(float(row["ma_gap_pct"])),
        )
    )
    return {
        "years": years,
        "ma_period": ma_period,
        "criteria": {
            "min_cagr": min_cagr,
            "max_ma_gap_pct": max_ma_gap_pct,
            "min_ma_slope_pct": min_ma_slope_pct,
        },
        "rows": rows,
        "errors": errors,
    }
