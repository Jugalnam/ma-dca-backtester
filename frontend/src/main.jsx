import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { createChart, CrosshairMode } from "lightweight-charts";
import { BarChart3, Calculator, Download, RefreshCw, Search, X } from "lucide-react";
import "./styles.css";

const MA_OPTIONS = [20, 50, 100, 150, 200, 300, 400];
const MA_COLORS = {
  20: "#f2c94c",
  50: "#56ccf2",
  100: "#bb6bd9",
  150: "#6fcf97",
  200: "#eb5757",
  300: "#9b9bff",
  400: "#f2994a",
};

function money(value) {
  return `$${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function pct(value) {
  return `${(Number(value || 0) * 100).toFixed(2)}%`;
}

function number(value, digits = 4) {
  return Number(value || 0).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function addMonths(dateText, months) {
  const date = new Date(`${dateText}T00:00:00`);
  date.setMonth(date.getMonth() + months);
  return date.toISOString().slice(0, 10);
}

function buildPriceUrl({ ticker, years, maPeriods }) {
  const params = new URLSearchParams();
  params.set("ticker", ticker);
  params.set("years", years);
  maPeriods.forEach((period) => params.append("ma_periods", period));
  return `/api/prices?${params.toString()}`;
}

function ChartPanel({ priceData, maPeriods, trades, sells, mode, onPickDate }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const candleRef = useRef(null);
  const maRefs = useRef([]);

  useEffect(() => {
    if (!containerRef.current || !priceData?.candles?.length) {
      return;
    }

    containerRef.current.innerHTML = "";
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: "#0f1419" },
        textColor: "#aab6c4",
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      },
      grid: {
        vertLines: { color: "#1d2530" },
        horzLines: { color: "#1d2530" },
      },
      rightPriceScale: { borderColor: "#33404d" },
      timeScale: {
        borderColor: "#33404d",
        timeVisible: false,
        secondsVisible: false,
      },
      crosshair: { mode: CrosshairMode.Normal },
      localization: { priceFormatter: (price) => `$${price.toFixed(2)}` },
      handleScroll: true,
      handleScale: true,
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#e15241",
      downColor: "#2f80ed",
      borderUpColor: "#e15241",
      borderDownColor: "#2f80ed",
      wickUpColor: "#e15241",
      wickDownColor: "#2f80ed",
    });
    candleSeries.setData(priceData.candles);

    maRefs.current = maPeriods.map((period) => {
      const series = chart.addLineSeries({
        color: MA_COLORS[period] || "#d7dee8",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      series.setData(priceData.moving_averages[String(period)] || []);
      return series;
    });

    const markers = [
      ...(trades || []).map((trade) => ({
        time: trade.date,
        position: "belowBar",
        color: "#f2c94c",
        shape: "arrowUp",
        text: "매수",
      })),
      ...(sells || []).map((sell, index) => ({
        time: sell.date,
        position: "aboveBar",
        color: ["#6fcf97", "#56ccf2", "#bb6bd9"][index % 3],
        shape: "arrowDown",
        text: `매도${index + 1}`,
      })),
    ];
    candleSeries.setMarkers(markers);

    chart.timeScale().fitContent();
    chart.subscribeClick((param) => {
      if (param?.time) {
        onPickDate(String(param.time));
      }
    });

    const resize = () => {
      chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener("resize", resize);
    resize();

    chartRef.current = chart;
    candleRef.current = candleSeries;
    return () => {
      window.removeEventListener("resize", resize);
      chart.remove();
    };
  }, [priceData, maPeriods, trades, sells, onPickDate]);

  return (
    <section className="chart-shell">
      <div className="chart-topbar">
        <div>
          <h2>{priceData?.ticker || "차트"}</h2>
          <span>{priceData ? `${priceData.min_date} - ${priceData.max_date}` : "종목을 조회하세요"}</span>
        </div>
        <div className="chart-mode">클릭 모드: {modeLabel(mode)}</div>
      </div>
      <div ref={containerRef} className="chart-canvas" />
    </section>
  );
}

function modeLabel(mode) {
  if (mode === "buy_start") return "매수 시작";
  if (mode === "buy_end") return "매수 종료";
  return "매도 추가";
}

function App() {
  const [ticker, setTicker] = useState("TSLA");
  const [years, setYears] = useState(5);
  const [maPeriods, setMaPeriods] = useState([50, 200, 400]);
  const [buyMode, setBuyMode] = useState("dollars");
  const [buyAmount, setBuyAmount] = useState(100);
  const [priceBasis, setPriceBasis] = useState("mid");
  const [feeRate, setFeeRate] = useState(0);
  const [slippageRate, setSlippageRate] = useState(0);
  const [pickMode, setPickMode] = useState("buy_start");
  const [buyStart, setBuyStart] = useState("");
  const [buyEnd, setBuyEnd] = useState("");
  const [sellDates, setSellDates] = useState([]);
  const [priceData, setPriceData] = useState(null);
  const [result, setResult] = useState(null);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const pickModeRef = useRef(pickMode);
  const buyEndRef = useRef(buyEnd);

  useEffect(() => {
    pickModeRef.current = pickMode;
    buyEndRef.current = buyEnd;
  }, [pickMode, buyEnd]);

  const requestBase = useMemo(
    () => ({
      ticker: ticker.trim().toUpperCase(),
      years: Number(years),
      ma_periods: maPeriods,
      buy_mode: buyMode,
      buy_amount: Number(buyAmount),
      price_basis: priceBasis,
      fee_rate: Number(feeRate),
      slippage_rate: Number(slippageRate),
    }),
    [ticker, years, maPeriods, buyMode, buyAmount, priceBasis, feeRate, slippageRate],
  );

  const fetchPrices = async () => {
    setLoading(true);
    setStatus("데이터 조회 중...");
    setResult(null);
    try {
      const response = await fetch(buildPriceUrl({ ticker: requestBase.ticker, years, maPeriods }));
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "데이터 조회 실패");
      setPriceData(data);
      const defaultEnd = data.max_date;
      const defaultStart = addMonths(defaultEnd, -3);
      setBuyStart(defaultStart < data.min_date ? data.min_date : defaultStart);
      setBuyEnd(defaultEnd);
      setSellDates([defaultEnd]);
      setStatus(`${data.ticker} ${data.years}년 데이터를 불러왔습니다.`);
    } catch (error) {
      setStatus(error.message);
    } finally {
      setLoading(false);
    }
  };

  const calculate = async () => {
    if (!buyStart || !buyEnd || sellDates.length === 0) {
      setStatus("매수 시작, 매수 종료, 매도일을 모두 선택하세요.");
      return;
    }
    setLoading(true);
    setStatus("계산 중...");
    try {
      const response = await fetch("/api/swing", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...requestBase,
          buy_start: buyStart,
          buy_end: buyEnd,
          sell_dates: sellDates,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "계산 실패");
      setResult(data);
      setStatus("계산이 완료되었습니다.");
    } catch (error) {
      setStatus(error.message);
    } finally {
      setLoading(false);
    }
  };

  const saveResult = async () => {
    if (!result) {
      setStatus("저장할 계산 결과가 없습니다.");
      return;
    }
    setLoading(true);
    setStatus("저장 중...");
    try {
      const response = await fetch("/api/swing/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...requestBase,
          buy_start: buyStart,
          buy_end: buyEnd,
          sell_dates: sellDates,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "저장 실패");
      setStatus(`저장 완료: ${data.paths.summary}`);
    } catch (error) {
      setStatus(error.message);
    } finally {
      setLoading(false);
    }
  };

  const addSellDate = useCallback((date) => {
    setSellDates((current) => {
      const next = Array.from(new Set([...current, date])).sort();
      return next.slice(0, 3);
    });
  }, []);

  const handlePickDate = useCallback((date) => {
    const mode = pickModeRef.current;
    if (mode === "buy_start") {
      setBuyStart(date);
      if (!buyEndRef.current || date > buyEndRef.current) setBuyEnd(date);
      setPickMode("buy_end");
      return;
    }
    if (mode === "buy_end") {
      setBuyEnd(date);
      setPickMode("sell");
      return;
    }
    addSellDate(date);
  }, [addSellDate]);

  const toggleMa = (period) => {
    setMaPeriods((current) => {
      const hasPeriod = current.includes(period);
      const next = hasPeriod ? current.filter((value) => value !== period) : [...current, period];
      return next.length ? next.sort((a, b) => a - b) : current;
    });
  };

  const summary = result?.summary;

  return (
    <main className="app">
      <aside className="sidebar">
        <div className="brand">
          <BarChart3 size={22} />
          <div>
            <h1>MA DCA Backtester</h1>
            <p>스윙 구간 직접 선택</p>
          </div>
        </div>

        <section className="control-group">
          <h2>종목 / 차트</h2>
          <label>
            종목
            <input value={ticker} onChange={(event) => setTicker(event.target.value.toUpperCase())} />
          </label>
          <label>
            조회 기간(연)
            <input
              type="number"
              min="1"
              max="20"
              value={years}
              onChange={(event) => setYears(event.target.value)}
            />
          </label>
          <div className="ma-grid">
            {MA_OPTIONS.map((period) => (
              <button
                key={period}
                className={maPeriods.includes(period) ? "active" : ""}
                onClick={() => toggleMa(period)}
                type="button"
              >
                {period}
              </button>
            ))}
          </div>
          <button className="primary" onClick={fetchPrices} disabled={loading} type="button">
            <Search size={16} />
            차트 조회
          </button>
        </section>

        <section className="control-group">
          <h2>매수 조건</h2>
          <label>
            매수 단위
            <select value={buyMode} onChange={(event) => setBuyMode(event.target.value)}>
              <option value="dollars">매일 N달러</option>
              <option value="shares">매일 N주</option>
            </select>
          </label>
          <label>
            매일 매수량
            <input
              type="number"
              min="0.0001"
              step="1"
              value={buyAmount}
              onChange={(event) => setBuyAmount(event.target.value)}
            />
          </label>
          <label>
            매수가 기준
            <select value={priceBasis} onChange={(event) => setPriceBasis(event.target.value)}>
              <option value="mid">시가-종가 중간값</option>
              <option value="open">시가</option>
              <option value="close">종가</option>
            </select>
          </label>
        </section>

        <section className="control-group">
          <h2>체결 비용</h2>
          <label>
            수수료율
            <input type="number" min="0" step="0.0001" value={feeRate} onChange={(event) => setFeeRate(event.target.value)} />
          </label>
          <label>
            슬리피지
            <input
              type="number"
              min="0"
              step="0.0001"
              value={slippageRate}
              onChange={(event) => setSlippageRate(event.target.value)}
            />
          </label>
        </section>
      </aside>

      <section className="workspace">
        <div className="selection-bar">
          <div className="date-fields">
            <label>
              매수 시작
              <input type="date" value={buyStart} onChange={(event) => setBuyStart(event.target.value)} max={todayIso()} />
            </label>
            <label>
              매수 종료
              <input type="date" value={buyEnd} onChange={(event) => setBuyEnd(event.target.value)} max={todayIso()} />
            </label>
            <label>
              매도일 추가
              <input
                type="date"
                max={todayIso()}
                onChange={(event) => {
                  if (event.target.value) {
                    addSellDate(event.target.value);
                    event.target.value = "";
                  }
                }}
              />
            </label>
          </div>
          <div className="mode-buttons">
            {["buy_start", "buy_end", "sell"].map((mode) => (
              <button
                key={mode}
                className={pickMode === mode ? "active" : ""}
                onClick={() => setPickMode(mode)}
                type="button"
              >
                {modeLabel(mode)}
              </button>
            ))}
          </div>
        </div>

        <ChartPanel
          priceData={priceData}
          maPeriods={maPeriods}
          trades={result?.trades}
          sells={result?.sells}
          mode={pickMode}
          onPickDate={handlePickDate}
        />

        <div className="sell-list">
          {sellDates.map((date) => (
            <span key={date}>
              {date}
              <button onClick={() => setSellDates((current) => current.filter((item) => item !== date))} type="button">
                <X size={12} />
              </button>
            </span>
          ))}
        </div>

        <div className="actions">
          <button className="primary" onClick={calculate} disabled={loading || !priceData} type="button">
            <Calculator size={16} />
            계산하기
          </button>
          <button onClick={saveResult} disabled={loading || !result} type="button">
            <Download size={16} />
            결과 저장
          </button>
          <button onClick={() => setResult(null)} type="button">
            <RefreshCw size={16} />
            결과 초기화
          </button>
          <p>{status}</p>
        </div>

        {summary && (
          <>
            <section className="metrics">
              <Metric label="총 수익률" value={pct(summary.return_pct)} tone={summary.net_profit >= 0 ? "good" : "bad"} />
              <Metric label="연환산 수익률" value={pct(summary.annualized_return)} />
              <Metric label="순손익" value={money(summary.net_profit)} tone={summary.net_profit >= 0 ? "good" : "bad"} />
              <Metric label="총 투입금" value={money(summary.total_cost)} />
              <Metric label="총 매도금액" value={money(summary.sell_value)} />
              <Metric label="평균단가" value={`$${Number(summary.average_cost).toFixed(2)}`} />
              <Metric label="보유수량" value={number(summary.total_units)} />
            </section>

            <section className="tables">
              <DataTable
                title="매수 내역"
                rows={result.trades}
                columns={[
                  ["date", "매수일"],
                  ["buy_price", "매수가"],
                  ["units", "수량"],
                  ["gross_cost", "매수금"],
                  ["fee", "수수료"],
                  ["total_cost", "총 비용"],
                ]}
              />
              <DataTable
                title="매도 내역"
                rows={result.sells}
                columns={[
                  ["date", "매도일"],
                  ["weight", "비중"],
                  ["units", "수량"],
                  ["sell_price", "매도가"],
                  ["gross", "매도금"],
                  ["fee", "수수료"],
                  ["value", "실수령액"],
                ]}
              />
            </section>
          </>
        )}
      </section>
    </main>
  );
}

function Metric({ label, value, tone }) {
  return (
    <div className={`metric ${tone || ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DataTable({ title, rows, columns }) {
  return (
    <section className="table-wrap">
      <h2>{title}</h2>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {columns.map(([, label]) => (
                <th key={label}>{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${title}-${index}`}>
                {columns.map(([key]) => (
                  <td key={key}>{formatCell(key, row[key])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function formatCell(key, value) {
  if (key === "date") return value;
  if (key === "weight") return `${(Number(value) * 100).toFixed(1)}%`;
  if (key.includes("units")) return number(value);
  return `$${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

createRoot(document.getElementById("root")).render(<App />);
