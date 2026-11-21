# MarketPulse AI — Gold-only XAUS research dashboard

## Run locally

Requires Python 3.10+ and internet access.

```bash
python -m pip install -r requirements.txt
uvicorn server:app --reload --host 127.0.0.1 --port 8000
```

Run from this folder, then visit http://127.0.0.1:8000 . **No API key is required.**

## How it works

- TradingView widget displays FX_IDC:XAUUSD independently.
- The backend fetches real (not simulated) XAU chart OHLC data from `https://xaus.com/api/v1/chart` using `symbol=xau`.
- Timeframes: 5m, 15m, 1h and 1d. EMA20, EMA50, RSI14, MACD and ATR14 use fetched candle data.
- Refreshes every 60 seconds; the backend caches each interval for 60 seconds. Provider data may update more slowly.
- Stale or unavailable data is explicitly labeled. Stale data disables illustrative scenarios. Errors do not generate synthetic prices.
- Illustrative scenarios are **not** trading recommendations or executable quotes.

## Limitations

- The chart's TradingView prices and XAUS reference prices may differ. The XAUS provider says its prices are indicative and not executable.
- The latest candle may be incomplete. The data freshness heuristic can flag closed markets as stale.
- XAUS's documented endpoint uses a third-party market data proxy; availability and interval coverage may vary. If fewer than 60 candles are returned, analysis is unavailable rather than fabricated.
- This package is not deployed and its provider connection has **not been end-to-end verified** in this environment. Start the app and verify `/api/analysis?interval=15min`.
- Check XAUS public commercial usage/redistribution terms and TradingView widget terms before public deployment. XAUS documents free reasonable use with caching and asks high-volume commercial users to contact them.

Documentation: https://xaus.com/api/
