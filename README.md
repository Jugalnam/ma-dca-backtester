# 투자전략 시뮬레이터 프로토타입

이 프로토타입은 설계서에 맞춰 `이동평균선 아래 DCA 적립` 전략을 백테스트합니다.

## 실행

```powershell
pip install -r requirements.txt
python -m simulator.main --tickers TSLA MSFT INTC --years 10 --daily-amount 10
```

결과는 `outputs/` 폴더에 저장됩니다.

- `comparison.csv`: 전략별 비교표
- `{ticker}_prices.csv`: 다운로드한 가격 데이터
- `{ticker}_ma{period}_{mode}.csv`: 전략별 일별 결과

quantstats HTML 리포트까지 만들려면 `--html`을 추가합니다.

```powershell
python -m simulator.main --tickers TSLA MSFT INTC --years 10 --daily-amount 10 --html
```

## 설계 포인트

- 수정주가를 사용합니다. (`auto_adjust=True`)
- 이동평균은 전일까지의 값만 사용합니다. (`rolling(...).mean().shift(1)`)
- DCA는 외부 현금 유입으로 처리합니다.
- DCA 성과는 단순 일별 수익률이 아니라 최종배수와 IRR로 봅니다.
- 실주문이나 키 입력 코드는 포함하지 않습니다.

## 간단 UI

```powershell
streamlit run simulator/app.py
```
