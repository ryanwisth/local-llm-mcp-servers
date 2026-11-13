# twelvedata: market prices and indicators

An MCP server over the [Twelve Data](https://twelvedata.com) REST API. Seven tools: `td_search_symbol`, `td_price`, `td_quote`, `td_time_series`, `td_indicator`, `td_compare`, `td_api_usage`.

## Run

```bash
export TWELVEDATA_API_KEY=your-key   # free key at https://twelvedata.com/pricing
uv run twelvedata/server.py
```

Without a key, every tool returns a setup message.

## Design notes

- **REST, not their hosted MCP.** Twelve Data's hosted MCP advertises only the `authorization_code` and `refresh_token` OAuth grants, so it needs an interactive login and rotating tokens. The REST API takes a plain `apikey` parameter that survives restarts.
- **Free-tier shaped.** `price`, `quote`, `time_series` and the indicators work on the free plan; `symbol_search` works without any key; `/profile`, `/statistics`, `/earnings` and `/dividends` return 403 on free and are deliberately not exposed (probed 2026-09-18). The `../yfinance` server covers that data.
- **Errors arrive two ways.** Twelve Data reports failures inside a 200 body (`{"status": "error", "code": ...}`) as often as by HTTP status. Both become the same `ERROR <code>: <message>` string; a 429 adds a note about the per-minute credit limit.
- **`_fetch` returns parsed data, `_get` renders it.** `td_compare` needs to do arithmetic on the response; parsing a string that had already been truncated mid-JSON was a real bug caught before first run.
- **`td_compare`** sends one comma-separated request for all symbols, computes percent change, period high and low, and ranks the results. A bad symbol is reported under `problems` without failing the whole call.
- **Indicator allow-list.** 27 common indicators (SMA, EMA, RSI, MACD, Bollinger Bands, ATR, ADX and so on) out of roughly 100, so the model picks well.
- Output sizes are capped at 500 bars and 12,000 characters.
