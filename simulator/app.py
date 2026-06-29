from __future__ import annotations

from pathlib import Path
from html import escape

import pandas as pd
import streamlit as st

from simulator.data import load_ohlc
from simulator.swing import add_moving_averages, calculate_swing_dca


BUY_MODE_LABELS = {
    "shares": "매일 N주",
    "dollars": "매일 N달러",
}

PRICE_BASIS_LABELS = {
    "mid": "시가-종가 중간값",
    "open": "시가",
    "close": "종가",
}


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


def write_swing_report_html(
    path: Path,
    ticker: str,
    summary_rows: list[list[str]],
    trades: pd.DataFrame,
) -> None:
    trade_rows = []
    for _, row in trades.iterrows():
        trade_rows.append(
            "<tr>"
            f"<td>{escape(str(pd.to_datetime(row['date']).date()))}</td>"
            f"<td>{float(row['buy_price']):,.2f}</td>"
            f"<td>{float(row['units']):,.4f}</td>"
            f"<td>{float(row['gross_cost']):,.2f}</td>"
            f"<td>{float(row['fee']):,.2f}</td>"
            f"<td>{float(row['total_cost']):,.2f}</td>"
            "</tr>"
        )

    summary_html = "\n".join(
        f"<tr><th>{escape(label)}</th><td>{escape(value)}</td></tr>"
        for label, value in summary_rows
    )
    trades_html = "\n".join(trade_rows)

    html = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>{escape(ticker)} DCA 스윙 리포트</title>
  <style>
    body {{ margin: 32px; background: #101418; color: #d7dee8; font-family: Arial, sans-serif; }}
    h1, h2 {{ color: #eef3f8; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0 28px; }}
    th, td {{ border: 1px solid #2f3a45; padding: 8px 10px; text-align: right; }}
    th {{ background: #18212a; color: #91a1b3; text-align: left; }}
    td {{ background: #151b22; }}
  </style>
</head>
<body>
  <h1>{escape(ticker)} DCA 스윙 리포트</h1>
  <h2>요약</h2>
  <table>{summary_html}</table>
  <h2>매수 내역</h2>
  <table>
    <tr><th>매수일</th><th>매수가</th><th>수량</th><th>매수금</th><th>수수료</th><th>총 비용</th></tr>
    {trades_html}
  </table>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def make_chart(
    prices: pd.DataFrame,
    ma_periods: list[int],
    trades: pd.DataFrame | None,
    buy_start: pd.Timestamp,
    buy_end: pd.Timestamp,
    sell_date: pd.Timestamp,
):
    chart_prices = prices.copy()
    chart_prices["date"] = pd.to_datetime(chart_prices["date"])
    chart_prices["direction"] = chart_prices.apply(
        lambda row: "상승" if row["close"] >= row["open"] else "하락",
        axis=1,
    )

    ma_frames = []
    for period in ma_periods:
        column = f"ma_{period}"
        if column in chart_prices.columns:
            ma_frame = chart_prices[["date", column]].dropna().copy()
            ma_frame["period"] = f"{period}일선"
            ma_frame = ma_frame.rename(columns={column: "value"})
            ma_frames.append(ma_frame)
    ma_data = pd.concat(ma_frames, ignore_index=True) if ma_frames else pd.DataFrame()

    layers = [
        {
            "data": {
                "values": [
                    {
                        "start": pd.to_datetime(buy_start).strftime("%Y-%m-%d"),
                        "end": pd.to_datetime(buy_end).strftime("%Y-%m-%d"),
                    }
                ]
            },
            "mark": {"type": "rect", "opacity": 0.12, "color": "#f2c94c"},
            "encoding": {
                "x": {"field": "start", "type": "temporal"},
                "x2": {"field": "end"},
            },
        },
        {
            "mark": "rule",
            "encoding": {
                "x": {"field": "date", "type": "temporal"},
                "y": {"field": "low", "type": "quantitative", "scale": {"zero": False}},
                "y2": {"field": "high"},
                "color": {
                    "condition": {"test": "datum.close >= datum.open", "value": "#e15241"},
                    "value": "#2f80ed",
                },
            },
        },
        {
            "mark": {"type": "bar", "size": 4},
            "encoding": {
                "x": {"field": "date", "type": "temporal"},
                "y": {"field": "open", "type": "quantitative", "scale": {"zero": False}},
                "y2": {"field": "close"},
                "color": {
                    "condition": {"test": "datum.close >= datum.open", "value": "#e15241"},
                    "value": "#2f80ed",
                },
            },
        },
        {
            "data": {"values": [{"date": pd.to_datetime(sell_date).strftime("%Y-%m-%d")}]},
            "mark": {"type": "rule", "strokeDash": [6, 4], "color": "#27ae60", "size": 2},
            "encoding": {"x": {"field": "date", "type": "temporal"}},
        },
    ]

    if not ma_data.empty:
        layers.append(
            {
                "data": {"values": ma_data.to_dict("records")},
                "mark": {"type": "line", "strokeWidth": 1.6},
                "encoding": {
                    "x": {"field": "date", "type": "temporal"},
                    "y": {"field": "value", "type": "quantitative", "scale": {"zero": False}},
                    "color": {
                        "field": "period",
                        "type": "nominal",
                        "scale": {"range": ["#f2c94c", "#56ccf2", "#bb6bd9", "#6fcf97"]},
                    },
                },
            }
        )

    if trades is not None and not trades.empty:
        marker_data = trades[["date", "buy_price"]].copy()
        marker_data["date"] = pd.to_datetime(marker_data["date"]).dt.strftime("%Y-%m-%d")
        layers.append(
            {
                "data": {"values": records_for_vega(marker_data)},
                "mark": {"type": "point", "filled": True, "size": 32, "color": "#ffffff"},
                "encoding": {
                    "x": {"field": "date", "type": "temporal"},
                    "y": {"field": "buy_price", "type": "quantitative"},
                    "tooltip": [
                        {"field": "date", "type": "temporal", "title": "매수일"},
                        {"field": "buy_price", "type": "quantitative", "title": "매수가"},
                    ],
                },
            }
        )

    return {
        "data": {"values": records_for_vega(chart_prices)},
        "layer": layers,
        "height": 520,
        "resolve": {"scale": {"y": "shared"}},
        "config": {
            "background": "#101418",
            "view": {"stroke": "#2b3642"},
            "axis": {"gridColor": "#25303a", "domainColor": "#3a4652"},
            "legend": {"labelColor": "#d7dee8", "titleColor": "#d7dee8"},
        },
    }


st.set_page_config(page_title="DCA 스윙 백테스터", layout="wide")
st.markdown(
    """
    <style>
    .stApp { background: #101418; color: #d7dee8; }
    [data-testid="stSidebar"] {
        background: #151b22;
        border-right: 1px solid #2b3642;
    }
    .block-container { padding-top: 1.1rem; padding-bottom: 2rem; }
    h1, h2, h3 { color: #eef3f8; letter-spacing: 0; }
    [data-testid="stMetric"] {
        background: #161d24;
        border: 1px solid #2f3a45;
        border-radius: 4px;
        padding: 12px 14px;
    }
    [data-testid="stMetricLabel"] { color: #91a1b3; }
    [data-testid="stMetricValue"] { color: #f2f6fb; font-size: 1.35rem; }
    div[data-testid="stDataFrame"] { border: 1px solid #2f3a45; }
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

if not ticker:
    st.info("좌측에서 종목을 입력하세요.")
    st.stop()

if not load and "ohlc" not in st.session_state:
    st.info("좌측 조건을 확인한 뒤 차트 조회를 누르세요.")
    st.stop()

if load or "ohlc" not in st.session_state or st.session_state.get("ticker") != ticker or st.session_state.get("years") != years:
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
default_buy_start = max(min_date, pd.Timestamp("2022-04-05").date())
default_buy_end = min(max_date, pd.Timestamp("2023-05-05").date())

st.subheader("구간 선택")
range_cols = st.columns(3)
buy_start_input = range_cols[0].date_input("매수 시작일", value=default_buy_start, min_value=min_date, max_value=max_date)
buy_end_input = range_cols[1].date_input("매수 종료일", value=default_buy_end, min_value=min_date, max_value=max_date)
sell_date_input = range_cols[2].date_input("매도일", value=max(default_buy_end, max_date), min_value=min_date, max_value=max_date)

try:
    trades, summary = calculate_swing_dca(
        prices,
        buy_start=pd.Timestamp(buy_start_input),
        buy_end=pd.Timestamp(buy_end_input),
        sell_date=pd.Timestamp(sell_date_input),
        buy_mode=buy_mode,
        buy_amount=buy_amount,
        price_basis=price_basis,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
    )
except Exception as exc:
    st.error(f"계산할 수 없습니다: {exc}")
    st.stop()

metric_cols = st.columns(7)
metric_cols[0].metric("총 수익률", pct(summary.return_pct))
metric_cols[1].metric("연환산 수익률", pct(summary.annualized_return))
metric_cols[2].metric("순손익", money(summary.net_profit))
metric_cols[3].metric("총 투입금", money(summary.total_cost))
metric_cols[4].metric("매도금액", money(summary.sell_value))
metric_cols[5].metric("평균단가", f"${summary.average_cost:,.2f}")
metric_cols[6].metric("보유수량", qty(summary.total_units))

st.caption(
    f"실제 적용 구간: 매수 {summary.buy_start.date()} ~ {summary.buy_end.date()} "
    f"({summary.buy_days}거래일), 매도 {summary.sell_date.date()} 종가 ${summary.sell_price:,.2f}"
)

st.vega_lite_chart(
    make_chart(
        prices=prices,
        ma_periods=ma_periods,
        trades=trades,
        buy_start=summary.buy_start,
        buy_end=summary.buy_end,
        sell_date=summary.sell_date,
    ),
    use_container_width=True,
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

with right:
    st.subheader("요약")
    summary_df = pd.DataFrame(
        [
            ["매수 방식", BUY_MODE_LABELS[buy_mode]],
            ["매수가 기준", PRICE_BASIS_LABELS[price_basis]],
            ["매수 거래일", f"{summary.buy_days}일"],
            ["보유 기간", f"{summary.holding_days}일"],
            ["평균단가", f"${summary.average_cost:,.2f}"],
            ["매도가", f"${summary.sell_price:,.2f}"],
            ["총 수익률", pct(summary.return_pct)],
            ["연환산 수익률", pct(summary.annualized_return)],
        ],
        columns=["항목", "값"],
    )
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

out_dir = Path("outputs")
out_dir.mkdir(exist_ok=True)
safe_name = f"{ticker}_{summary.buy_start.date()}_{summary.buy_end.date()}_{summary.sell_date.date()}"
trades_path = out_dir / f"{safe_name}_swing_trades.csv"
summary_path = out_dir / f"{safe_name}_swing_summary.csv"
trades.to_csv(trades_path, index=False, encoding="utf-8-sig")
pd.DataFrame([summary.__dict__]).to_csv(summary_path, index=False, encoding="utf-8-sig")

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

st.caption(f"거래내역 저장: {trades_path.resolve()} / 요약 저장: {summary_path.resolve()}")
