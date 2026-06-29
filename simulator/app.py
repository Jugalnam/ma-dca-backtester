from __future__ import annotations

from pathlib import Path
from html import escape

import pandas as pd
import streamlit as st

from simulator.data import load_ohlc
from simulator.swing import add_moving_averages, calculate_swing_dca_multi


BUY_MODE_LABELS = {
    "shares": "매일 N주",
    "dollars": "매일 N달러",
}

PRICE_BASIS_LABELS = {
    "mid": "시가-종가 중간값",
    "open": "시가",
    "close": "종가",
}

# Candlestick / accent palette (Korean convention: 상승=빨강, 하락=파랑).
UP_COLOR = "#e15241"
DOWN_COLOR = "#2f80ed"
BUY_BAND_COLOR = "#f2c94c"
SELL_COLORS = ["#6fcf97", "#56ccf2", "#bb6bd9"]
MA_COLORS = ["#f2c94c", "#56ccf2", "#bb6bd9", "#6fcf97", "#eb5757", "#9b9bff", "#f2994a"]


def money(value: float) -> str:
    return f"${value:,.0f}"


def qty(value: float) -> str:
    return f"{value:,.4f}주"


def pct(value: float) -> str:
    return f"{value:.2%}"


def write_swing_report_html(
    out_path: Path,
    *,
    ticker: str,
    summary_rows: list[list[object]],
    trades: pd.DataFrame,
) -> None:
    """Render a standalone dark-themed HTML report for a swing DCA run.

    No external dependencies — builds the markup by hand so the report opens
    in any browser without quantstats.
    """
    summary_html = "\n".join(
        "<tr><th>{label}</th><td>{value}</td></tr>".format(
            label=escape(str(label)), value=escape(str(value))
        )
        for label, value in summary_rows
    )

    trade_display = trades.copy()
    trade_display["date"] = pd.to_datetime(trade_display["date"]).dt.date
    header_cols = ["매수일", "매수가", "수량", "매수금", "수수료", "총 비용"]
    head_html = "".join(f"<th>{escape(col)}</th>" for col in header_cols)

    body_rows: list[str] = []
    for _, row in trade_display.iterrows():
        cells = [
            escape(str(row["date"])),
            f"${float(row['buy_price']):,.2f}",
            f"{float(row['units']):,.4f}",
            f"${float(row['gross_cost']):,.2f}",
            f"${float(row['fee']):,.2f}",
            f"${float(row['total_cost']):,.2f}",
        ]
        body_rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    trades_html = "\n".join(body_rows)

    generated_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    html = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(ticker)} 스윙 DCA 리포트</title>
<style>
  body {{ background:#101418; color:#d7dee8; font-family:-apple-system,'Segoe UI',sans-serif;
         margin:0; padding:32px; }}
  h1 {{ color:#eef3f8; font-size:1.6rem; margin:0 0 4px; }}
  .meta {{ color:#91a1b3; font-size:0.85rem; margin-bottom:28px; }}
  h2 {{ color:#eef3f8; font-size:1.1rem; margin:28px 0 12px; }}
  table {{ border-collapse:collapse; width:100%; max-width:880px; font-size:0.9rem; }}
  th, td {{ border:1px solid #2f3a45; padding:8px 12px; text-align:right; }}
  thead th {{ background:#161d24; color:#91a1b3; }}
  .summary th {{ background:#161d24; color:#91a1b3; text-align:left; width:180px; }}
  .summary td {{ color:#f2f6fb; text-align:left; }}
  tbody tr:nth-child(odd) {{ background:#13191f; }}
</style>
</head>
<body>
  <h1>{escape(ticker)} 스윙 DCA 리포트</h1>
  <div class="meta">생성 시각: {escape(generated_at)}</div>

  <h2>요약</h2>
  <table class="summary"><tbody>
  {summary_html}
  </tbody></table>

  <h2>매수 내역 ({len(trade_display)}건)</h2>
  <table><thead><tr>{head_html}</tr></thead>
  <tbody>
  {trades_html}
  </tbody></table>
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")


def records_for_vega(df: pd.DataFrame) -> list[dict[str, object]]:
    out = df.copy()
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return out.to_dict("records")


def coerce_date(value: object) -> pd.Timestamp | None:
    """Turn a Vega selection value into a Timestamp.

    Interval brushes come back as epoch-millisecond numbers; point clicks come
    back as the datum's "YYYY-MM-DD" string. Handle both shapes.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return pd.to_datetime(value, unit="ms")
    try:
        return pd.to_datetime(value)
    except (ValueError, TypeError):
        return None


def make_chart(
    prices: pd.DataFrame,
    ma_periods: list[int],
    trades: pd.DataFrame | None,
    buy_window: tuple[object, object] | None,
    sell_dates: list[object],
    interactive: bool = True,
):
    """Build a Vega-Lite candlestick spec with optional drag/click selections."""
    chart_prices = prices.copy()
    chart_prices["date"] = pd.to_datetime(chart_prices["date"])
    chart_prices["방향"] = chart_prices.apply(
        lambda row: "상승" if row["close"] >= row["open"] else "하락", axis=1
    )

    # Moving-average lines (long form for a single coloured legend).
    ma_frames = []
    for period in ma_periods:
        column = f"ma_{period}"
        if column in chart_prices.columns:
            frame = chart_prices[["date", column]].dropna().copy()
            frame["이평선"] = f"{period}일"
            frame = frame.rename(columns={column: "value"})
            ma_frames.append(frame)
    ma_data = pd.concat(ma_frames, ignore_index=True) if ma_frames else pd.DataFrame()
    ma_order = [f"{p}일" for p in ma_periods]

    color_condition = {
        "condition": {"test": "datum.close >= datum.open", "value": UP_COLOR},
        "value": DOWN_COLOR,
    }

    layers: list[dict] = []

    # 1) Buy window band.
    if buy_window is not None:
        start, end = buy_window
        layers.append(
            {
                "data": {
                    "values": [
                        {
                            "start": pd.to_datetime(start).strftime("%Y-%m-%d"),
                            "end": pd.to_datetime(end).strftime("%Y-%m-%d"),
                        }
                    ]
                },
                "mark": {"type": "rect", "opacity": 0.14, "color": BUY_BAND_COLOR},
                "encoding": {
                    "x": {"field": "start", "type": "temporal"},
                    "x2": {"field": "end"},
                },
            }
        )

    # 2) Candle wicks (high-low rule).
    layers.append(
        {
            "mark": {"type": "rule"},
            "encoding": {
                "x": {"field": "date", "type": "temporal"},
                "y": {"field": "low", "type": "quantitative", "scale": {"zero": False}},
                "y2": {"field": "high"},
                "color": color_condition,
            },
        }
    )

    # 3) Candle bodies (open-close bar). The selection params live here so they
    #    bind to a single unit spec (Vega-Lite forbids params on layered specs).
    body_layer: dict = {
        "mark": {"type": "bar", "size": 5},
        "encoding": {
            "x": {"field": "date", "type": "temporal"},
            "y": {"field": "open", "type": "quantitative", "scale": {"zero": False}},
            "y2": {"field": "close"},
            "color": color_condition,
            "tooltip": [
                {"field": "date", "type": "temporal", "title": "날짜", "format": "%Y-%m-%d"},
                {"field": "open", "type": "quantitative", "title": "시가", "format": ",.2f"},
                {"field": "high", "type": "quantitative", "title": "고가", "format": ",.2f"},
                {"field": "low", "type": "quantitative", "title": "저가", "format": ",.2f"},
                {"field": "close", "type": "quantitative", "title": "종가", "format": ",.2f"},
            ],
        },
    }
    if interactive:
        body_layer["params"] = [
            {"name": "buy_window", "select": {"type": "interval", "encodings": ["x"]}},
            {
                "name": "sell_pts",
                "select": {
                    "type": "point",
                    "encodings": ["x"],
                    "toggle": True,
                    "nearest": True,
                },
            },
        ]
    layers.append(body_layer)

    # 4) Moving averages.
    if not ma_data.empty:
        layers.append(
            {
                "data": {"values": records_for_vega(ma_data)},
                "mark": {"type": "line", "strokeWidth": 1.6, "opacity": 0.9},
                "encoding": {
                    "x": {"field": "date", "type": "temporal"},
                    "y": {"field": "value", "type": "quantitative", "scale": {"zero": False}},
                    "color": {
                        "field": "이평선",
                        "type": "nominal",
                        "scale": {"domain": ma_order, "range": MA_COLORS[: len(ma_order)]},
                        "legend": {"title": "이동평균"},
                    },
                },
            }
        )

    # 5) Buy markers.
    if trades is not None and not trades.empty:
        marker = trades[["date", "buy_price"]].copy()
        marker["date"] = pd.to_datetime(marker["date"]).dt.strftime("%Y-%m-%d")
        layers.append(
            {
                "data": {"values": marker.to_dict("records")},
                "mark": {
                    "type": "point",
                    "shape": "triangle-up",
                    "filled": True,
                    "size": 36,
                    "color": "#ffffff",
                    "stroke": "#101418",
                    "strokeWidth": 0.4,
                    "opacity": 0.85,
                },
                "encoding": {
                    "x": {"field": "date", "type": "temporal"},
                    "y": {"field": "buy_price", "type": "quantitative"},
                    "tooltip": [
                        {"field": "date", "type": "temporal", "title": "매수일"},
                        {"field": "buy_price", "type": "quantitative", "title": "매수가", "format": ",.2f"},
                    ],
                },
            }
        )

    # 6) Sell lines (one dashed vertical rule + label per leg).
    clean_sells = []
    for index, raw in enumerate(sell_dates):
        when = pd.to_datetime(raw)
        clean_sells.append(
            {
                "date": when.strftime("%Y-%m-%d"),
                "label": f"매도{index + 1}",
                "color": SELL_COLORS[index % len(SELL_COLORS)],
            }
        )
    if clean_sells:
        layers.append(
            {
                "data": {"values": clean_sells},
                "mark": {"type": "rule", "strokeDash": [6, 4], "size": 1.6},
                "encoding": {
                    "x": {"field": "date", "type": "temporal"},
                    "color": {"field": "color", "type": "nominal", "scale": None, "legend": None},
                },
            }
        )
        layers.append(
            {
                "data": {"values": clean_sells},
                "mark": {
                    "type": "text",
                    "align": "left",
                    "dx": 4,
                    "dy": -6,
                    "baseline": "top",
                    "fontSize": 11,
                    "fontWeight": "bold",
                },
                "encoding": {
                    "x": {"field": "date", "type": "temporal"},
                    "y": {"value": 6},
                    "text": {"field": "label"},
                    "color": {"field": "color", "type": "nominal", "scale": None, "legend": None},
                },
            }
        )

    return {
        "data": {"values": records_for_vega(chart_prices)},
        "layer": layers,
        "height": 560,
        "autosize": {"type": "fit", "contains": "padding"},
        "resolve": {"scale": {"y": "shared", "color": "independent"}},
        "encoding": {
            "x": {"axis": {"format": "%Y-%m", "labelAngle": 0, "title": None, "tickCount": 8}},
            "y": {"axis": {"format": "$,.0f", "title": "가격"}},
        },
        "config": {
            "background": "#0f1419",
            "font": "-apple-system, 'Segoe UI', sans-serif",
            "view": {"stroke": "transparent"},
            "axis": {
                "gridColor": "#1d2530",
                "domainColor": "#33404d",
                "tickColor": "#33404d",
                "labelColor": "#8a99ab",
                "titleColor": "#aab6c4",
                "labelFontSize": 11,
                "titleFontSize": 12,
            },
            "legend": {
                "labelColor": "#d7dee8",
                "titleColor": "#aab6c4",
                "orient": "top-left",
                "fillColor": "#141b22",
                "padding": 8,
                "cornerRadius": 4,
            },
        },
    }


def read_chart_selection(prices: pd.DataFrame) -> None:
    """Sync the latest chart drag/click into the date inputs (once per change).

    Reads the selection stored under the chart's widget key, and only writes
    back to session state when the selection actually changed, so it never
    clobbers a manual edit the user just made in the date boxes.
    """
    event = st.session_state.get("swing_chart")
    selection = getattr(event, "selection", None)
    if not selection:
        return

    signature = repr(selection)
    if st.session_state.get("_last_selection") == signature:
        return
    st.session_state["_last_selection"] = signature

    # Drag → buy window.
    window = selection.get("buy_window") or {}
    bounds = window.get("date")
    if bounds and len(bounds) == 2:
        lo, hi = sorted(d for d in (coerce_date(b) for b in bounds) if d is not None)
        in_range = prices[(prices["date"] >= lo) & (prices["date"] <= hi)]
        if not in_range.empty:
            st.session_state["sel_buy_start"] = in_range["date"].min().date()
            st.session_state["sel_buy_end"] = in_range["date"].max().date()

    # Clicks → up to 3 sell points.
    points = selection.get("sell_pts") or []
    picked: list = []
    for point in points:
        value = point.get("date") if isinstance(point, dict) else point
        parsed = coerce_date(value)
        if parsed is not None:
            picked.append(parsed.date())
    picked = sorted(dict.fromkeys(picked))[:3]
    if picked:
        st.session_state["sel_sells"] = picked


st.set_page_config(page_title="DCA 스윙 백테스터", layout="wide")
st.markdown(
    """
    <style>
    .stApp { background: #0f1419; color: #d7dee8; }
    [data-testid="stSidebar"] {
        background: #141b22;
        border-right: 1px solid #232f3b;
    }
    .block-container { padding-top: 1.1rem; padding-bottom: 2rem; }
    h1, h2, h3 { color: #eef3f8; letter-spacing: 0; }
    [data-testid="stMetric"] {
        background: #161d24;
        border: 1px solid #28333e;
        border-radius: 6px;
        padding: 12px 14px;
    }
    [data-testid="stMetricLabel"] { color: #8a99ab; }
    [data-testid="stMetricValue"] { color: #f2f6fb; font-size: 1.3rem; }
    div[data-testid="stDataFrame"] { border: 1px solid #28333e; border-radius: 6px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("DCA 스윙 백테스터")

with st.sidebar:
    st.subheader("종목 / 차트")
    ticker = st.text_input("종목", value="TSLA").upper().strip()
    years = st.slider("조회 기간", min_value=1, max_value=20, value=10)
    ma_periods = st.multiselect(
        "표시할 이평선",
        options=[20, 50, 100, 150, 200, 300, 400],
        default=[50, 200, 400],
    )

    st.subheader("매수 조건")
    buy_mode = st.selectbox(
        "매수 단위",
        options=list(BUY_MODE_LABELS),
        format_func=lambda key: BUY_MODE_LABELS[key],
    )
    default_amount = 1.0 if buy_mode == "shares" else 100.0
    buy_amount = st.number_input("매일 매수량", min_value=0.0001, value=default_amount, step=1.0)
    price_basis = st.selectbox(
        "매수가 기준",
        options=list(PRICE_BASIS_LABELS),
        format_func=lambda key: PRICE_BASIS_LABELS[key],
    )

    st.subheader("체결 비용")
    fee_rate = st.number_input("수수료율", min_value=0.0, value=0.0, step=0.0001, format="%.4f")
    slippage_rate = st.number_input("슬리피지", min_value=0.0, value=0.0, step=0.0001, format="%.4f")

    st.subheader("리포트")
    publish_report = st.checkbox("HTML 리포트 발행", value=False)

    load = st.button("차트 조회", type="primary", use_container_width=True)


if not load and "ohlc" not in st.session_state:
    st.info("좌측 조건을 확인한 뒤 차트 조회를 누르세요.")
    st.stop()

if (
    load
    or "ohlc" not in st.session_state
    or st.session_state.get("ticker") != ticker
    or st.session_state.get("years") != years
):
    with st.spinner("일봉 데이터를 조회하는 중"):
        st.session_state["ohlc"] = load_ohlc(ticker, years=years)
        st.session_state["ticker"] = ticker
        st.session_state["years"] = years

ohlc = st.session_state["ohlc"].copy()
ohlc["date"] = pd.to_datetime(ohlc["date"])
ma_periods = ma_periods or [400]
prices = add_moving_averages(ohlc, ma_periods)

min_date = prices["date"].min().date()
max_date = prices["date"].max().date()

# Empty by default (요구사항 1). Chart drag/click fills these via read_chart_selection.
st.session_state.setdefault("sel_buy_start", None)
st.session_state.setdefault("sel_buy_end", None)
st.session_state.setdefault("sel_sells", [])

read_chart_selection(prices)

st.subheader("구간 선택")
st.caption(
    "차트에서 **매수 구간을 드래그**하고 **매도 시점을 클릭**(최대 3개)하세요. "
    "아래 날짜를 직접 입력해도 됩니다. 매도는 지정한 지점마다 보유량을 균등 분할해 매도합니다."
)

cols = st.columns(5)
buy_start_input = cols[0].date_input(
    "매수 시작", value=st.session_state["sel_buy_start"], min_value=min_date, max_value=max_date
)
buy_end_input = cols[1].date_input(
    "매수 종료", value=st.session_state["sel_buy_end"], min_value=min_date, max_value=max_date
)
st.session_state["sel_buy_start"] = buy_start_input
st.session_state["sel_buy_end"] = buy_end_input

current_sells = st.session_state["sel_sells"]
sell_inputs: list = []
for i in range(3):
    default_value = current_sells[i] if i < len(current_sells) else None
    sell_inputs.append(
        cols[2 + i].date_input(
            f"매도 {i + 1}", value=default_value, min_value=min_date, max_value=max_date
        )
    )
sell_dates = sorted(dict.fromkeys(s for s in sell_inputs if s is not None))
st.session_state["sel_sells"] = sell_dates

reset = st.button("선택 초기화")
if reset:
    st.session_state["sel_buy_start"] = None
    st.session_state["sel_buy_end"] = None
    st.session_state["sel_sells"] = []
    st.session_state.pop("_last_selection", None)
    st.rerun()

inputs_ready = (
    buy_start_input is not None and buy_end_input is not None and len(sell_dates) >= 1
)

buy_window = (
    (buy_start_input, buy_end_input)
    if buy_start_input is not None and buy_end_input is not None
    else None
)

if not inputs_ready:
    st.info("매수 시작·종료일과 매도일(최소 1개)을 지정하면 결과가 계산됩니다.")
    st.vega_lite_chart(
        make_chart(prices, ma_periods, None, buy_window, sell_dates, interactive=True),
        use_container_width=True,
        on_select="rerun",
        key="swing_chart",
    )
    st.stop()

try:
    trades, sells_df, summary = calculate_swing_dca_multi(
        prices,
        buy_start=pd.Timestamp(buy_start_input),
        buy_end=pd.Timestamp(buy_end_input),
        sell_dates=[pd.Timestamp(d) for d in sell_dates],
        buy_mode=buy_mode,
        buy_amount=buy_amount,
        price_basis=price_basis,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
    )
except Exception as exc:
    st.error(f"계산할 수 없습니다: {exc}")
    st.vega_lite_chart(
        make_chart(prices, ma_periods, None, buy_window, sell_dates, interactive=True),
        use_container_width=True,
        on_select="rerun",
        key="swing_chart",
    )
    st.stop()

metric_cols = st.columns(7)
metric_cols[0].metric("총 수익률", pct(summary.return_pct))
metric_cols[1].metric("연환산 수익률", pct(summary.annualized_return))
metric_cols[2].metric("순손익", money(summary.net_profit))
metric_cols[3].metric("총 투입금", money(summary.total_cost))
metric_cols[4].metric("총 매도금액", money(summary.sell_value))
metric_cols[5].metric("평균단가", f"${summary.average_cost:,.2f}")
metric_cols[6].metric("보유수량", qty(summary.total_units))

sell_caption = " · ".join(
    f"매도{i + 1} {leg.date.date()} {leg.units:,.4f}주 @ ${leg.price:,.2f}"
    for i, leg in enumerate(summary.sells)
)
st.caption(
    f"실제 적용 구간: 매수 {summary.buy_start.date()} ~ {summary.buy_end.date()} "
    f"({summary.buy_days}거래일) · {sell_caption}"
)

actual_sell_dates = [leg.date for leg in summary.sells]
st.vega_lite_chart(
    make_chart(prices, ma_periods, trades, buy_window, actual_sell_dates, interactive=True),
    use_container_width=True,
    on_select="rerun",
    key="swing_chart",
)

left, right = st.columns([2, 1])
with left:
    st.subheader("매수 내역")
    trade_display = trades.copy()
    trade_display["date"] = pd.to_datetime(trade_display["date"]).dt.date
    trade_display = trade_display.rename(
        columns={
            "date": "매수일",
            "buy_price": "매수가",
            "units": "수량",
            "gross_cost": "매수금",
            "fee": "수수료",
            "total_cost": "총 비용",
        }
    )
    st.dataframe(trade_display, use_container_width=True, hide_index=True)

    st.subheader("매도 내역")
    sell_display = sells_df.copy()
    sell_display["date"] = pd.to_datetime(sell_display["date"]).dt.date
    sell_display["weight"] = (sell_display["weight"] * 100).round(1)
    sell_display = sell_display.rename(
        columns={
            "date": "매도일",
            "weight": "비중(%)",
            "units": "수량",
            "sell_price": "매도가",
            "gross": "매도금",
            "fee": "수수료",
            "value": "실수령액",
        }
    )
    st.dataframe(sell_display, use_container_width=True, hide_index=True)

with right:
    st.subheader("요약")
    summary_df = pd.DataFrame(
        [
            ["매수 방식", BUY_MODE_LABELS[buy_mode]],
            ["매수가 기준", PRICE_BASIS_LABELS[price_basis]],
            ["매수 거래일", f"{summary.buy_days}일"],
            ["보유 기간", f"{summary.holding_days}일"],
            ["분할 매도 횟수", f"{len(summary.sells)}회"],
            ["평균단가", f"${summary.average_cost:,.2f}"],
            ["평균 매도가", f"${summary.avg_sell_price:,.2f}"],
            ["총 수익률", pct(summary.return_pct)],
            ["연환산 수익률", pct(summary.annualized_return)],
        ],
        columns=["항목", "값"],
    )
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

out_dir = Path("outputs")
out_dir.mkdir(exist_ok=True)
sell_tag = "-".join(str(leg.date.date()) for leg in summary.sells)
safe_name = f"{ticker}_{summary.buy_start.date()}_{summary.buy_end.date()}_{sell_tag}"
trades_path = out_dir / f"{safe_name}_swing_trades.csv"
sells_path = out_dir / f"{safe_name}_swing_sells.csv"
summary_path = out_dir / f"{safe_name}_swing_summary.csv"
trades.to_csv(trades_path, index=False, encoding="utf-8-sig")
sells_df.to_csv(sells_path, index=False, encoding="utf-8-sig")
pd.DataFrame([{k: v for k, v in summary.__dict__.items() if k != "sells"}]).to_csv(
    summary_path, index=False, encoding="utf-8-sig"
)

if publish_report:
    html_path = out_dir / f"{safe_name}_swing_report.html"
    try:
        write_swing_report_html(
            html_path,
            ticker=ticker,
            summary_rows=summary_df.values.tolist(),
            trades=trades,
        )
        st.success(f"리포트 발행 완료: {html_path.resolve()}")
    except Exception as exc:
        st.warning(f"리포트 발행 실패: {exc}")

st.caption(
    f"저장: {trades_path.name} · {sells_path.name} · {summary_path.name} (outputs/)"
)
