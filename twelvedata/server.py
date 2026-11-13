# /// script
# dependencies = ["fastmcp"]
# ///
"""MCP over the Twelve Data REST API — stock/ETF/forex/crypto prices and indicators.

Wraps api.twelvedata.com directly instead of their hosted MCP (mcp.twelvedata.com), because
that endpoint is OAuth authorization_code only: it needs an interactive browser login and
refreshes tokens, and an MCP-to-HTTP bridge such as mcpo can only forward a static
header. The REST API takes a plain ?apikey= that never expires, so it survives restarts unattended.

Free-tier shaped on purpose. /profile, /statistics, /earnings and /dividends all return 403
on the free plan, so they are not exposed — a tool that can only fail is noise in the tool
list a small local model has to read. Add them here if the plan is ever upgraded.

Budget: the free "Basic" plan is credit-metered per minute; td_api_usage reports the real
remaining quota and should be trusted over any number written here. Multi-symbol calls are one
comma-separated request (N credits, 1 request) rather than a loop, and outputs are capped
so a chat turn cannot swallow the daily quota or the model's context.

Key: $TWELVEDATA_API_KEY. Get a free one at
https://twelvedata.com/pricing — no key, and every tool returns a clear setup message.
"""
import json
import os
import urllib.parse
import urllib.request

from fastmcp import FastMCP

BASE = "https://api.twelvedata.com"
MAX_CHARS = 12000

# Indicator endpoints worth exposing. Twelve Data serves ~100; this is the subset that
# actually gets asked for in price analysis, kept short so the model picks well.
INDICATORS = {
    "sma", "ema", "wma", "dema", "tema", "vwap",
    "rsi", "macd", "stoch", "stochrsi", "cci", "mom", "roc", "willr",
    "bbands", "atr", "natr", "adx", "aroon", "psar", "obv", "ad", "mfi",
    "supertrend", "ichimoku", "keltner", "percent_b",
}

mcp = FastMCP("twelvedata")


def _key() -> str | None:
    return os.environ.get("TWELVEDATA_API_KEY", "").strip() or None


def _fetch(path: str, params: dict):
    """One GET against the REST API. Returns parsed JSON, or an 'ERROR...' str on failure.

    Twelve Data reports failures as {"code": 4xx, "message": ...} inside a 200 body as often
    as via HTTP status, so both paths are unwrapped to the same message for the model."""
    key = _key()
    if not key:
        return (
            "ERROR: no Twelve Data API key. Get a free one at https://twelvedata.com/pricing "
            "then set it in the TWELVEDATA_API_KEY environment variable."
        )
    q = {k: v for k, v in params.items() if v not in (None, "")}
    q["apikey"] = key
    url = f"{BASE}/{path}?{urllib.parse.urlencode(q)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception as e:
        return f"ERROR: Twelve Data unreachable ({path}): {e}"
    try:
        data = json.loads(body)
    except Exception:
        return f"ERROR: Twelve Data returned non-JSON from /{path}: {body[:400]}"
    if isinstance(data, dict) and data.get("status") == "error":
        code = data.get("code", "?")
        msg = data.get("message", "unknown error")
        if code == 429:
            msg += " (free tier is credit-metered per minute — wait a minute, or call td_api_usage)"
        return f"ERROR {code}: {msg}"
    return data


def _get(path: str, params: dict) -> str:
    """_fetch rendered for a tool reply: compact JSON, capped so one call cannot flood the
    model's context. Truncation is announced, because silently short data reads as real."""
    data = _fetch(path, params)
    if isinstance(data, str):
        return data
    out = json.dumps(data, indent=1)
    if len(out) > MAX_CHARS:
        return out[:MAX_CHARS] + "\n... [truncated: ask for fewer bars via outputsize]"
    return out


@mcp.tool()
def td_search_symbol(query: str) -> str:
    """Find the ticker for a company name. Use this first whenever the user names a company
    rather than a symbol — 'Apple' -> AAPL — and check the exchange before pricing it,
    since the same name can list on several."""
    return _get("symbol_search", {"symbol": query, "outputsize": 10})


@mcp.tool()
def td_price(symbols: str) -> str:
    """Latest price only, for one symbol or a comma-separated list (e.g. 'AAPL,MSFT,NVDA').
    The cheapest call available — use it when the question is just 'what is X trading at'."""
    return _get("price", {"symbol": symbols})


@mcp.tool()
def td_quote(symbols: str) -> str:
    """Full quote: open/high/low/close, volume, change and percent change, previous close,
    52-week range, and average volume. One symbol or a comma-separated list. This is the
    right tool for 'how is X doing today'."""
    return _get("quote", {"symbol": symbols})


@mcp.tool()
def td_time_series(
    symbol: str,
    interval: str = "1day",
    outputsize: int = 30,
    start_date: str = "",
    end_date: str = "",
) -> str:
    """Historical OHLCV bars for one symbol — the tool for trends, ranges and drawdowns.

    interval: 1min 5min 15min 30min 45min 1h 2h 4h 1day 1week 1month.
    outputsize: number of bars back from now, capped at 500 so a reply stays readable.
    start_date/end_date: optional 'YYYY-MM-DD' to pin a window instead."""
    return _get("time_series", {
        "symbol": symbol,
        "interval": interval,
        "outputsize": max(1, min(int(outputsize), 500)),
        "start_date": start_date,
        "end_date": end_date,
    })


@mcp.tool()
def td_indicator(
    symbol: str,
    indicator: str,
    interval: str = "1day",
    outputsize: int = 30,
    time_period: int = 0,
    series_type: str = "close",
) -> str:
    """A technical indicator series for one symbol.

    indicator: sma ema wma dema tema vwap rsi macd stoch stochrsi cci mom roc willr bbands
    atr natr adx aroon psar obv ad mfi supertrend ichimoku keltner percent_b.
    time_period: the lookback the indicator uses (e.g. 14 for rsi, 20 for bbands); leave 0
    for Twelve Data's default. macd and ichimoku ignore it — they carry their own periods."""
    ind = indicator.strip().lower()
    if ind not in INDICATORS:
        return (
            f"ERROR: unsupported indicator '{indicator}'. "
            f"Supported: {', '.join(sorted(INDICATORS))}."
        )
    return _get(ind, {
        "symbol": symbol,
        "interval": interval,
        "outputsize": max(1, min(int(outputsize), 500)),
        "time_period": time_period or None,
        "series_type": series_type,
    })


@mcp.tool()
def td_compare(symbols: str, interval: str = "1day", outputsize: int = 30) -> str:
    """Percent performance of several symbols over the same window, ranked best to worst.

    Pass a comma-separated list ('AAPL,MSFT,NVDA'). Sent as a single request so it costs one
    rate-limit slot, and the percentages are computed here rather than left as raw bars for
    the model to divide — arithmetic on long price series is where small models go wrong."""
    data = _fetch("time_series", {
        "symbol": symbols,
        "interval": interval,
        "outputsize": max(2, min(int(outputsize), 500)),
    })
    if isinstance(data, str):
        return data
    # One symbol comes back flat; several come back keyed by symbol.
    series = {data.get("meta", {}).get("symbol", symbols): data} if "values" in data else data

    rows, problems = [], []
    for sym, payload in series.items():
        if not isinstance(payload, dict) or payload.get("status") == "error":
            problems.append(f"{sym}: {payload.get('message', 'no data') if isinstance(payload, dict) else 'no data'}")
            continue
        vals = payload.get("values") or []
        if len(vals) < 2:
            problems.append(f"{sym}: fewer than 2 bars returned")
            continue
        newest, oldest = float(vals[0]["close"]), float(vals[-1]["close"])
        highs = [float(v["high"]) for v in vals]
        lows = [float(v["low"]) for v in vals]
        rows.append({
            "symbol": sym,
            "pct_change": round((newest - oldest) / oldest * 100, 2),
            "first_close": oldest,
            "last_close": newest,
            "period_high": max(highs),
            "period_low": min(lows),
            "from": vals[-1]["datetime"],
            "to": vals[0]["datetime"],
        })

    rows.sort(key=lambda r: r["pct_change"], reverse=True)
    out = {"interval": interval, "bars": outputsize, "ranked": rows}
    if problems:
        out["problems"] = problems
    return json.dumps(out, indent=1)[:MAX_CHARS]


@mcp.tool()
def td_api_usage() -> str:
    """How much of today's Twelve Data quota is already spent. Check this when calls start
    failing with 429, before assuming a symbol or endpoint is broken."""
    return _get("api_usage", {})


if __name__ == "__main__":
    mcp.run()
