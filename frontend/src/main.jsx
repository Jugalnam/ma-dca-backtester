import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { createChart, CrosshairMode } from "lightweight-charts";
import {
  BarChart3,
  Calculator,
  Download,
  Filter,
  RefreshCw,
  Search,
  Target,
  X,
} from "lucide-react";
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

const DEFAULT_SCREEN_TICKERS =
  "MSFT,AAPL,AMZN,GOOGL,META,NVDA,AVGO,ORCL,CRM,ADBE,NOW,INTU,AMD,QCOM,TXN,ASML,TSM,COST,HD,MCD,V,MA,LLY,UNH,ISRG,NKE,SBUX,DIS,PYPL,QQQ,SPY,XLK,SMH";

const SELL_MODE_LABELS = {
  hold: "끝까지 보유",
  sell_above_ma: "이동평균 재돌파 매도",
  take_profit: "익절",
  stop_loss: "손절",
  take_profit_or_stop_loss: "익절 또는 손절",
  trailing_stop: "트레일링 스탑",
};

function money(value) {
  return `$${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function money2(value) {
  return `$${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${(Number(value) * 100).toFixed(2)}%`;
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

function modeLabel(mode) {
  if (mode === "buy_start") return "매수 시작";
  if (mode === "buy_end") return "매수 종료";
  return "매도 추가";
}

function ChartPanel({ priceData, maPeriods, trades, sells, events, mode, onPickDate }) {
  const containerRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current || !priceData?.candles?.length) return undefined;

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

    maPeriods.forEach((period) => {
      const series = chart.addLineSeries({
        color: MA_COLORS[period] || "#d7dee8",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      series.setData(priceData.moving_averages[String(period)] || []);
    });

    const manualMarkers = [
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
    const ruleMarkers = (events || []).flatMap((event) => {
      const markers = [];
      if (Number(event.bought) > 0) {
        markers.push({
          time: event.date,
          position: "belowBar",
          color: "#f2c94c",
          shape: "arrowUp",
          text: "규칙 매수",
        });
      }
      if (Number(event.sold) > 0) {
        markers.push({
          time: event.date,
          position: "aboveBar",
          color: "#6fcf97",
          shape: "arrowDown",
          text: "규칙 매도",
        });
      }
      return markers;
    });
    candleSeries.setMarkers([...manualMarkers, ...ruleMarkers]);

    chart.timeScale().fitContent();
    chart.subscribeClick((param) => {
      if (param?.time) onPickDate(String(param.time));
    });

    const resize = () => {
      chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener("resize", resize);
    resize();

    return () => {
      window.removeEventListener("resize", resize);
      chart.remove();
    };
  }, [priceData, maPeriods, trades, sells, events, onPickDate]);

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

function App() {
  const [activeMode, setActiveMode] = useState("manual");
  const [ticker, setTicker] = useState("MSFT");
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
  const [ruleResult, setRuleResult] = useState(null);
  const [screenerResult, setScreenerResult] = useState(null);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [ruleMaPeriod, setRuleMaPeriod] = useState(400);
  const [entryMode, setEntryMode] = useState("accumulate_below");
  const [sellMode, setSellMode] = useState("sell_above_ma");
  const [takeProfitPct, setTakeProfitPct] = useState(20);
  const [stopLossPct, setStopLossPct] = useState(20);
  const [trailingStopPct, setTrailingStopPct] = useState(10);
  const [screenerTickers, setScreenerTickers] = useState(DEFAULT_SCREEN_TICKERS);
  const [screenerYears, setScreenerYears] = useState(6);
  const [screenerMaPeriod, setScreenerMaPeriod] = useState(400);

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

  const fetchPrices = async (nextTicker = requestBase.ticker) => {
    setLoading(true);
    setStatus("데이터 조회 중...");
    setResult(null);
    setRuleResult(null);
    try {
      const response = await fetch(buildPriceUrl({ ticker: nextTicker, years, maPeriods }));
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
      setRuleResult(null);
      setStatus("수동 구간 계산이 완료되었습니다.");
    } catch (error) {
      setStatus(error.message);
    } finally {
      setLoading(false);
    }
  };

  const runRuleBacktest = async () => {
    setLoading(true);
    setStatus("규칙 백테스트 계산 중...");
    try {
      const response = await fetch("/api/rule-backtest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: requestBase.ticker,
          years: Number(years),
          ma_period: Number(ruleMaPeriod),
          entry_mode: entryMode,
          sell_mode: sellMode,
          daily_amount: Number(buyAmount),
          fee_rate: Number(feeRate),
          slippage_rate: Number(slippageRate),
          take_profit_pct: Number(takeProfitPct) / 100,
          stop_loss_pct: Number(stopLossPct) / 100,
          trailing_stop_pct: Number(trailingStopPct) / 100,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "규칙 백테스트 실패");
      setRuleResult(data);
      setResult(null);
      setStatus("규칙 백테스트가 완료되었습니다.");
    } catch (error) {
      setStatus(error.message);
    } finally {
      setLoading(false);
    }
  };

  const runScreener = async () => {
    setLoading(true);
    setStatus("후보 종목 스캔 중...");
    try {
      const params = new URLSearchParams();
      params.set("tickers", screenerTickers);
      params.set("years", screenerYears);
      params.set("ma_period", screenerMaPeriod);
      const response = await fetch(`/api/screener?${params.toString()}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "스크리너 실패");
      setScreenerResult(data);
      setStatus(`스크리너 완료: ${data.rows.length}개 종목 확인`);
    } catch (error) {
      setStatus(error.message);
    } finally {
      setLoading(false);
    }
  };

  const saveResult = async () => {
    if (!result) {
      setStatus("저장할 수동 계산 결과가 없습니다.");
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

  const handlePickDate = useCallback(
    (date) => {
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
    },
    [addSellDate],
  );

  const toggleMa = (period) => {
    setMaPeriods((current) => {
      const hasPeriod = current.includes(period);
      const next = hasPeriod ? current.filter((value) => value !== period) : [...current, period];
      return next.length ? next.sort((a, b) => a - b) : current;
    });
  };

  const loadCandidate = async (candidateTicker) => {
    setTicker(candidateTicker);
    setActiveMode("manual");
    await fetchPrices(candidateTicker);
  };

  const summary = result?.summary;
  const ruleSummary = ruleResult?.summary;

  return (
    <main className="app">
      <aside className="sidebar">
        <div className="brand">
          <BarChart3 size={22} />
          <div>
            <h1>MA DCA Backtester</h1>
            <p>수동 구간 + 규칙 검증</p>
          </div>
        </div>

        <section className="control-group">
          <h2>종목 / 차트</h2>
          <label>
            종목
            <input value={ticker} onChange={(event) => setTicker(event.target.value.toUpperCase())} />
          </label>
          <label>
            조회 기간(년)
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
          <button className="primary" onClick={() => fetchPrices()} disabled={loading} type="button">
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
            <input
              type="number"
              min="0"
              step="0.0001"
              value={feeRate}
              onChange={(event) => setFeeRate(event.target.value)}
            />
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
        <div className="app-tabs">
          {[
            ["manual", "수동 구간"],
            ["rule", "규칙 백테스트"],
            ["screener", "후보 스크리너"],
          ].map(([mode, label]) => (
            <button
              key={mode}
              className={activeMode === mode ? "active" : ""}
              onClick={() => setActiveMode(mode)}
              type="button"
            >
              {label}
            </button>
          ))}
        </div>

        {activeMode !== "screener" && (
          <ChartPanel
            priceData={priceData}
            maPeriods={maPeriods}
            trades={activeMode === "manual" ? result?.trades : null}
            sells={activeMode === "manual" ? result?.sells : null}
            events={activeMode === "rule" ? ruleResult?.events : null}
            mode={pickMode}
            onPickDate={handlePickDate}
          />
        )}

        {activeMode === "manual" && (
          <ManualPanel
            buyStart={buyStart}
            buyEnd={buyEnd}
            sellDates={sellDates}
            setBuyStart={setBuyStart}
            setBuyEnd={setBuyEnd}
            addSellDate={addSellDate}
            setSellDates={setSellDates}
            setPickMode={setPickMode}
            pickMode={pickMode}
            calculate={calculate}
            saveResult={saveResult}
            loading={loading}
            priceData={priceData}
            status={status}
            summary={summary}
            result={result}
          />
        )}

        {activeMode === "rule" && (
          <RulePanel
            ruleMaPeriod={ruleMaPeriod}
            setRuleMaPeriod={setRuleMaPeriod}
            entryMode={entryMode}
            setEntryMode={setEntryMode}
            sellMode={sellMode}
            setSellMode={setSellMode}
            takeProfitPct={takeProfitPct}
            setTakeProfitPct={setTakeProfitPct}
            stopLossPct={stopLossPct}
            setStopLossPct={setStopLossPct}
            trailingStopPct={trailingStopPct}
            setTrailingStopPct={setTrailingStopPct}
            runRuleBacktest={runRuleBacktest}
            loading={loading}
            priceData={priceData}
            status={status}
            ruleResult={ruleResult}
            ruleSummary={ruleSummary}
          />
        )}

        {activeMode === "screener" && (
          <ScreenerPanel
            screenerTickers={screenerTickers}
            setScreenerTickers={setScreenerTickers}
            screenerYears={screenerYears}
            setScreenerYears={setScreenerYears}
            screenerMaPeriod={screenerMaPeriod}
            setScreenerMaPeriod={setScreenerMaPeriod}
            runScreener={runScreener}
            loading={loading}
            status={status}
            screenerResult={screenerResult}
            loadCandidate={loadCandidate}
          />
        )}
      </section>
    </main>
  );
}

function ManualPanel({
  buyStart,
  buyEnd,
  sellDates,
  setBuyStart,
  setBuyEnd,
  addSellDate,
  setSellDates,
  setPickMode,
  pickMode,
  calculate,
  saveResult,
  loading,
  priceData,
  status,
  summary,
  result,
}) {
  return (
    <>
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
        <button onClick={() => setSellDates([])} type="button">
          <RefreshCw size={16} />
          매도일 초기화
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
            <Metric label="평균단가" value={money2(summary.average_cost)} />
            <Metric label="보유수량" value={number(summary.total_units)} />
          </section>
          <section className="notice">
            수동 구간 결과는 사후 선택 편향이 생길 수 있습니다. 투자 판단에는 규칙 백테스트 탭의 자동 청산 결과를 함께 보세요.
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
    </>
  );
}

function RulePanel({
  ruleMaPeriod,
  setRuleMaPeriod,
  entryMode,
  setEntryMode,
  sellMode,
  setSellMode,
  takeProfitPct,
  setTakeProfitPct,
  stopLossPct,
  setStopLossPct,
  trailingStopPct,
  setTrailingStopPct,
  runRuleBacktest,
  loading,
  priceData,
  status,
  ruleResult,
  ruleSummary,
}) {
  return (
    <>
      <section className="rule-controls">
        <label>
          기준 이동평균
          <input
            type="number"
            min="20"
            max="1000"
            value={ruleMaPeriod}
            onChange={(event) => setRuleMaPeriod(event.target.value)}
          />
        </label>
        <label>
          진입 규칙
          <select value={entryMode} onChange={(event) => setEntryMode(event.target.value)}>
            <option value="accumulate_below">이평선 아래 매일 매수</option>
            <option value="breakout">아래에서 위로 돌파 시 매수</option>
          </select>
        </label>
        <label>
          청산 규칙
          <select value={sellMode} onChange={(event) => setSellMode(event.target.value)}>
            {Object.entries(SELL_MODE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          익절(%)
          <input type="number" min="0" value={takeProfitPct} onChange={(event) => setTakeProfitPct(event.target.value)} />
        </label>
        <label>
          손절(%)
          <input type="number" min="0" value={stopLossPct} onChange={(event) => setStopLossPct(event.target.value)} />
        </label>
        <label>
          트레일링(%)
          <input
            type="number"
            min="0"
            value={trailingStopPct}
            onChange={(event) => setTrailingStopPct(event.target.value)}
          />
        </label>
      </section>

      <div className="actions">
        <button className="primary" onClick={runRuleBacktest} disabled={loading || !priceData} type="button">
          <Target size={16} />
          규칙 백테스트
        </button>
        <p>{status}</p>
      </div>

      {ruleSummary && (
        <>
          <section className="metrics rule-metrics">
            <Metric label="최종 가치" value={money(ruleSummary.final_value)} />
            <Metric label="투입금" value={money(ruleSummary.contributed)} />
            <Metric label="최종 배수" value={`${Number(ruleSummary.multiple || 0).toFixed(2)}x`} />
            <Metric label="연환산 IRR" value={pct(ruleSummary.annualized_irr)} />
            <Metric label="존버 배수" value={`${Number(ruleSummary.benchmark_multiple || 0).toFixed(2)}x`} />
            <Metric label="매수 횟수" value={String(ruleSummary.buy_count)} />
            <Metric label="매도 횟수" value={String(ruleSummary.sell_count)} />
          </section>
          <section className="notice">
            최근 가격은 기준 이동평균 대비 {pct(ruleSummary.latest_ma_gap_pct)}입니다. 이 값이 음수면 현재가가 기준선 아래에 있습니다.
          </section>
          <DataTable
            title="규칙 이벤트"
            rows={ruleResult.events.slice(-80)}
            columns={[
              ["date", "일자"],
              ["price", "가격"],
              ["bought", "매수금"],
              ["sold", "매도금"],
              ["value", "포트가치"],
            ]}
          />
        </>
      )}
    </>
  );
}

function ScreenerPanel({
  screenerTickers,
  setScreenerTickers,
  screenerYears,
  setScreenerYears,
  screenerMaPeriod,
  setScreenerMaPeriod,
  runScreener,
  loading,
  status,
  screenerResult,
  loadCandidate,
}) {
  return (
    <>
      <section className="screener-controls">
        <label>
          스캔 종목
          <textarea value={screenerTickers} onChange={(event) => setScreenerTickers(event.target.value)} />
        </label>
        <div className="screener-grid">
          <label>
            조회 기간(년)
            <input
              type="number"
              min="2"
              max="30"
              value={screenerYears}
              onChange={(event) => setScreenerYears(event.target.value)}
            />
          </label>
          <label>
            기준 이동평균
            <input
              type="number"
              min="20"
              max="1000"
              value={screenerMaPeriod}
              onChange={(event) => setScreenerMaPeriod(event.target.value)}
            />
          </label>
          <button className="primary" onClick={runScreener} disabled={loading} type="button">
            <Filter size={16} />
            후보 스캔
          </button>
        </div>
        <p className="helper">
          기준: 장기 CAGR 8% 이상, 현재가가 기준선 근처 또는 아래, 기준선 기울기 훼손이 크지 않은 종목을 먼저 올립니다.
        </p>
      </section>

      <div className="actions">
        <p>{status}</p>
      </div>

      {screenerResult && (
        <section className="table-wrap">
          <h2>후보 종목</h2>
          <div className="table-scroll screener-table">
            <table>
              <thead>
                <tr>
                  <th>종목</th>
                  <th>상태</th>
                  <th>현재가</th>
                  <th>이평선</th>
                  <th>이평 대비</th>
                  <th>52주 고점 대비</th>
                  <th>CAGR</th>
                  <th>1년 이탈일</th>
                  <th>3개월 기울기</th>
                  <th>동작</th>
                </tr>
              </thead>
              <tbody>
                {screenerResult.rows.map((row) => (
                  <tr key={row.ticker}>
                    <td>{row.ticker}</td>
                    <td>
                      <span className={`status-pill ${row.status}`}>{row.status_label}</span>
                    </td>
                    <td>{money2(row.latest)}</td>
                    <td>{money2(row.ma)}</td>
                    <td className={Number(row.ma_gap_pct) < 0 ? "negative" : "positive"}>{pct(row.ma_gap_pct)}</td>
                    <td>{pct(row.drawdown_52w)}</td>
                    <td>{pct(row.cagr)}</td>
                    <td>{row.days_below_1y}</td>
                    <td>{pct(row.ma_slope_3m)}</td>
                    <td>
                      <button onClick={() => loadCandidate(row.ticker)} type="button">
                        차트
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {screenerResult.errors?.length > 0 && (
            <p className="helper">{screenerResult.errors.length}개 종목은 데이터를 불러오지 못했습니다.</p>
          )}
        </section>
      )}
    </>
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
            {(rows || []).map((row, index) => (
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
  if (key === "bought" || key === "sold") return Number(value) > 0 ? money(value) : "-";
  if (key === "price" || key === "value") return money2(value);
  return `$${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

createRoot(document.getElementById("root")).render(<App />);
