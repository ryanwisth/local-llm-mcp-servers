# yfinance: company fundamentals

An MCP server over the [yfinance](https://github.com/ranaroussi/yfinance) library. Eight tools: `yf_profile`, `yf_statistics`, `yf_dividends`, `yf_earnings`, `yf_financials`, `yf_history`, `yf_analysts`, `yf_news`. No API key and no quota.

## Run

```bash
uv run yfinance/server.py
```

## Design notes

- **The library, not raw HTTP.** A direct request to Yahoo's `quoteSummary` endpoint returns `Invalid Crumb`; Yahoo requires a cookie and crumb pair, and yfinance does that handshake.
- **Version pin `yfinance>=1.7,<2`.** yfinance uses Yahoo's private endpoints, so Yahoo breaks it from time to time and the fix ships as a patch release. A floating minor picks up those fixes; `<2` blocks an unattended major change. If every tool fails at once, suspect Yahoo and try `uv run --upgrade` first. Verified against 1.7.0 on 2026-09-18.
- **Curated fields.** `.info` has 187 keys; each tool returns a hand-picked subset.
- **A bad ticker does not raise** in yfinance; `.info` comes back nearly empty and `.history()` returns an empty frame. `_load()` checks and returns a plain error.
- **NaN and NaT become `null`**, never the string `"nan"`. Prices are rounded to 4 decimal places. Large values are unscaled, and docstrings say so. `dividend_yield_pct` is already a percent, and its docstring says so too.
- **Statement line items null in every period are dropped** and counted in `line_items_omitted_as_empty`. `yf_financials` defaults to 4 periods, because the annual balance sheet (about 69 line items) overflowed the cap at 5.
- **`yf_history` returns CSV and resamples instead of truncating.** As JSON objects, the 12,000-character cap cut a daily series after about 81 bars. As CSV a bar costs about 48 characters. Past `max_bars` (default 400, ceiling 1000) the series rolls up daily to weekly to monthly to quarterly with proper OHLCV aggregation; summary stats are computed on the full series first, and `resampled_to` and `note` report the roll-up.
- **Resampled bars carry the last real trading date** in each bucket, not pandas' period-end label (which can be a Sunday or a future date).
