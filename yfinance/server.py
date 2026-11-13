# /// script
# dependencies = ["fastmcp", "yfinance>=1.7,<2"]
# ///
"""MCP over yfinance — the company fundamentals Twelve Data's free plan will not serve.

Companion to ../twelvedata, not a replacement. Split by what each source is good at:
  twelvedata  live/intraday prices + server-side technical indicators (RSI, MACD, ...)
  yfinance    profile, valuation stats, dividends, earnings, statements, analysts, news
Those six are 403 on Twelve Data's free plan. Here they cost nothing and need no API key.

Version pinned >=1.7,<2 on purpose. yfinance scrapes Yahoo's private endpoints rather than a
contracted API, so Yahoo breaks it periodically and the fix arrives as a patch release — the
floating minor is what keeps it working. The <2 blocks a major API break landing unattended.
Raw HTTP against these endpoints returns 'Invalid Crumb'; yfinance does the cookie/crumb dance,
which is the whole reason this wraps the library instead of curl.

No key, no quota. Yahoo does throttle a client that hammers it, so tools return curated fields
rather than dumps — .info alone carries 187 keys, and handing a small local model all of them buries the
handful that answer the question.
"""
import json
import math
from datetime import date, datetime

import pandas as pd
import yfinance as yf
from fastmcp import FastMCP

MAX_CHARS = 12000

# Price series are the one reply where volume IS the point, so they get their own budget and a
# compact encoding. Measured 2026-09-18: one bar as a JSON object at indent=1 costs ~149 chars,
# which meant a 12 000-char cap truncated anything past ~81 bars — i.e. 3 months of daily data.
# As a CSV line it costs ~48. Same budget, 3x the history, and no repeated keys for the model
# to wade through. Beyond MAX_BARS the series is resampled coarser rather than cut off, because
# 260 weekly bars answer "how did this do over 5 years" and the newest 81 daily bars do not.
MAX_BARS = 400
MAX_BARS_CEILING = 1000

mcp = FastMCP("yfinance")


def _clean(v):
    """pandas/numpy scalars -> JSON-safe. NaN and NaT become null rather than the string 'nan',
    which a model will happily read as a real value."""
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, (datetime, date)):
        return str(v)[:19]
    if hasattr(v, "item"):
        try:
            v = v.item()
        except Exception:
            return str(v)
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def _dump(obj) -> str:
    out = json.dumps(obj, indent=1, default=str)
    if len(out) > MAX_CHARS:
        return out[:MAX_CHARS] + "\n... [truncated: narrow the request]"
    return out


def _load(symbol: str):
    """Ticker + info, or an error string. A bad symbol does NOT raise in yfinance: .info comes
    back with a single key and every value None, so it is checked explicitly."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return "ERROR: no symbol given."
    try:
        t = yf.Ticker(sym)
        info = t.info or {}
    except Exception as e:
        return f"ERROR: Yahoo lookup failed for {sym}: {type(e).__name__}: {e}"
    if len(info) < 5 or info.get("symbol") is None:
        return f"ERROR: no data for '{sym}' — symbol not found or delisted. Check the ticker."
    return t, info


def _frame(df, limit: int) -> list:
    """Rows of a yfinance DataFrame as records, newest first, date-indexed."""
    if df is None or getattr(df, "empty", True):
        return []
    rows = []
    for idx, row in df.tail(limit).iloc[::-1].iterrows():
        rec = {"date": str(idx)[:19]}
        rec.update({str(k): _clean(v) for k, v in row.items()})
        rows.append(rec)
    return rows


@mcp.tool()
def yf_profile(symbol: str) -> str:
    """What the company actually does: sector, industry, headcount, country, website and the
    business summary. Use this before reasoning about a company you do not recognise."""
    r = _load(symbol)
    if isinstance(r, str):
        return r
    t, i = r
    return _dump({
        "symbol": i.get("symbol"),
        "name": i.get("longName") or i.get("shortName"),
        "sector": i.get("sector"),
        "industry": i.get("industry"),
        "employees": i.get("fullTimeEmployees"),
        "country": i.get("country"),
        "website": i.get("website"),
        "exchange": i.get("fullExchangeName") or i.get("exchange"),
        "currency": i.get("currency"),
        "summary": i.get("longBusinessSummary"),
    })


@mcp.tool()
def yf_statistics(symbol: str) -> str:
    """Valuation and quality metrics: PE (trailing and forward), PEG, price/book, market cap,
    enterprise value, margins, return on equity, debt/equity, beta, and the 52-week range.

    These are the numbers Twelve Data's free plan refuses. dividend_yield_pct is already a
    percent (0.32 means 0.32%), not a fraction — do not multiply it by 100 again."""
    r = _load(symbol)
    if isinstance(r, str):
        return r
    t, i = r
    return _dump({
        "symbol": i.get("symbol"),
        "currency": i.get("currency"),
        "current_price": i.get("currentPrice"),
        "market_cap": i.get("marketCap"),
        "enterprise_value": i.get("enterpriseValue"),
        "trailing_pe": i.get("trailingPE"),
        "forward_pe": i.get("forwardPE"),
        "peg_ratio": i.get("pegRatio"),
        "price_to_book": i.get("priceToBook"),
        "price_to_sales": i.get("priceToSalesTrailing12Months"),
        "profit_margin": i.get("profitMargins"),
        "operating_margin": i.get("operatingMargins"),
        "return_on_equity": i.get("returnOnEquity"),
        "return_on_assets": i.get("returnOnAssets"),
        "debt_to_equity": i.get("debtToEquity"),
        "current_ratio": i.get("currentRatio"),
        "total_revenue": i.get("totalRevenue"),
        "beta": i.get("beta"),
        "dividend_yield_pct": i.get("dividendYield"),
        "payout_ratio": i.get("payoutRatio"),
        "fifty_two_week_low": i.get("fiftyTwoWeekLow"),
        "fifty_two_week_high": i.get("fiftyTwoWeekHigh"),
    })


@mcp.tool()
def yf_dividends(symbol: str, limit: int = 12) -> str:
    """Dividend payment history, most recent first, plus the current yield and payout ratio.
    limit is how many payments back to return. Empty history means the company pays none."""
    r = _load(symbol)
    if isinstance(r, str):
        return r
    t, i = r
    try:
        d = t.dividends
    except Exception as e:
        return f"ERROR: dividend history unavailable: {type(e).__name__}: {e}"
    pays = [] if d is None or d.empty else [
        {"date": str(ix.date()), "amount": _clean(v)}
        for ix, v in list(d.items())[::-1][:max(1, min(int(limit), 200))]
    ]
    return _dump({
        "symbol": i.get("symbol"),
        "currency": i.get("currency"),
        "dividend_yield_pct": i.get("dividendYield"),
        "payout_ratio": i.get("payoutRatio"),
        "total_payments_on_record": 0 if d is None or d.empty else len(d),
        "payments": pays or "none — this company has never paid a dividend on record",
    })


@mcp.tool()
def yf_earnings(symbol: str, limit: int = 8) -> str:
    """Earnings dates with EPS estimate, reported EPS and the surprise percent. Includes
    upcoming dates, where reported EPS is null because the quarter has not been announced —
    a null there means 'not yet reported', never 'missed'."""
    r = _load(symbol)
    if isinstance(r, str):
        return r
    t, i = r
    try:
        e = t.get_earnings_dates(limit=max(1, min(int(limit), 50)))
    except Exception as ex:
        return f"ERROR: earnings dates unavailable: {type(ex).__name__}: {ex}"
    if e is None or e.empty:
        return _dump({"symbol": i.get("symbol"), "earnings": "no earnings dates on record"})
    rows = [{"date": str(ix)[:19], **{str(k): _clean(v) for k, v in row.items()}}
            for ix, row in e.iterrows()]
    return _dump({"symbol": i.get("symbol"), "earnings": rows})


@mcp.tool()
def yf_financials(symbol: str, statement: str = "income", period: str = "quarterly",
                  periods: int = 4) -> str:
    """A financial statement as reported.

    statement: income | balance | cashflow.
    period: quarterly or annual.
    periods: how many reporting periods back, newest first (default 4, max 8). A full balance
    sheet runs ~70 line items, so asking for more than 4 will start getting cut off — narrow
    this before widening it.
    Values are in the reporting currency, unscaled — 466822987776 is 466.8 billion, not 466."""
    r = _load(symbol)
    if isinstance(r, str):
        return r
    t, i = r
    s, p = statement.strip().lower(), period.strip().lower()
    if s not in ("income", "balance", "cashflow"):
        return f"ERROR: statement must be income, balance or cashflow (got '{statement}')."
    if p not in ("quarterly", "annual"):
        return f"ERROR: period must be quarterly or annual (got '{period}')."
    attr = {
        ("income", "quarterly"): "quarterly_income_stmt", ("income", "annual"): "income_stmt",
        ("balance", "quarterly"): "quarterly_balance_sheet", ("balance", "annual"): "balance_sheet",
        ("cashflow", "quarterly"): "quarterly_cashflow", ("cashflow", "annual"): "cashflow",
    }[(s, p)]
    try:
        df = getattr(t, attr)
    except Exception as e:
        return f"ERROR: {s} statement unavailable: {type(e).__name__}: {e}"
    if df is None or df.empty:
        return _dump({"symbol": i.get("symbol"), "statement": s, "period": p, "data": "not reported"})
    # Columns are period end dates, rows are line items. Yahoo pads every statement with rows
    # that are null in all periods (e.g. "Treasury Shares Number"); they carry no information
    # and on the annual balance sheet they alone pushed the reply past the truncation cap.
    cols = list(df.columns)[:max(1, min(int(periods), 8))]
    data, empty = {}, 0
    for li in df.index:
        vals = {str(col)[:10]: _clean(df.at[li, col]) for col in cols}
        if all(v is None for v in vals.values()):
            empty += 1
            continue
        data[str(li)] = vals
    return _dump({
        "symbol": i.get("symbol"), "statement": s, "period": p,
        "currency": i.get("financialCurrency") or i.get("currency"),
        "periods": [str(c)[:10] for c in cols],
        "line_items_returned": len(data),
        "line_items_omitted_as_empty": empty,
        "line_items": data,
    })


@mcp.tool()
def yf_history(symbol: str, period: str = "1mo", interval: str = "1d",
               max_bars: int = MAX_BARS) -> str:
    """OHLCV price history as CSV. Unmetered — prefer this over the Twelve Data price tools.

    period: 1d 5d 1mo 3mo 6mo 1y 2y 5y 10y ytd max.
    interval: 1m 2m 5m 15m 30m 60m 1d 5d 1wk 1mo (intraday only goes back ~60 days).
    max_bars: cap on rows returned, default 400, ceiling 1500.

    If the window holds more bars than max_bars, the series is RESAMPLED to a coarser interval
    (daily -> weekly -> monthly) instead of being cut short, so the whole window is still
    covered. When that happens `resampled_to` is set and `interval` reports what you actually
    got — read those before describing the bar spacing."""
    sym = (symbol or "").strip().upper()
    cap = max(2, min(int(max_bars), MAX_BARS_CEILING))
    try:
        df = yf.Ticker(sym).history(period=period, interval=interval)
    except Exception as e:
        return f"ERROR: history failed for {sym}: {type(e).__name__}: {e}"
    if df is None or df.empty:
        return (f"ERROR: no bars for '{sym}' at period={period} interval={interval}. "
                "Check the ticker, or widen the interval (intraday only covers ~60 days).")

    full_first = float(df["Close"].iloc[0])
    full_last = float(df["Close"].iloc[-1])
    full_high, full_low = float(df["High"].max()), float(df["Low"].min())
    full_bars, resampled = len(df), None

    # Coarsen until it fits. Aggregation is the standard OHLCV roll-up, not a sample of one row
    # per group — a sampled 'high' would understate the range and read as a real number.
    if len(df) > cap:
        for rule, label in (("W", "1wk"), ("ME", "1mo"), ("QE", "3mo")):
            try:
                r = df.resample(rule).agg({"Open": "first", "High": "max", "Low": "min",
                                            "Close": "last", "Volume": "sum"}).dropna(how="all")
                # Relabel each bucket with the LAST REAL trading date inside it. Pandas labels a
                # weekly bucket with its period end -- a Sunday, and for the current week a date
                # in the future, which reads as a bar that has not happened yet. Resampling the
                # index itself is what gives the true last trading day; Resampler.apply does not
                # (it aggregates columns rather than yielding each sub-frame).
                last = df.index.to_series().resample(rule).max()
                r.index = [last.get(ix, ix) for ix in r.index]
            except Exception:
                continue
            if len(r) <= cap:
                df, resampled, interval = r, label, label
                break
        else:
            df = df.tail(cap)

    def px(v):
        c = _clean(v)
        return round(c, 4) if isinstance(c, float) else c

    lines = ["date,open,high,low,close,volume"]
    for ix, r in df.iloc[::-1].iterrows():
        vol = _clean(r.get("Volume"))
        lines.append(f"{str(ix)[:19]},{px(r.get('Open'))},{px(r.get('High'))},"
                     f"{px(r.get('Low'))},{px(r.get('Close'))},"
                     f"{int(vol) if isinstance(vol, (int, float)) else ''}")

    out = {
        "symbol": sym, "period": period, "interval": interval,
        "rows_returned": len(df), "bars_in_window": full_bars,
        "pct_change_over_window": round((full_last - full_first) / full_first * 100, 2) if full_first else None,
        "window_high": round(full_high, 4), "window_low": round(full_low, 4),
    }
    if resampled:
        out["resampled_to"] = resampled
        out["note"] = (f"window held {full_bars} {interval if not resampled else 'original'}-interval "
                       f"bars, above max_bars={cap}; rolled up to {resampled} so the full window is "
                       "covered. Summary stats above are from the FULL series, not the rolled-up rows.")
    out["csv"] = "\n".join(lines)
    return json.dumps(out, indent=1)


@mcp.tool()
def yf_analysts(symbol: str) -> str:
    """Wall Street view: the strongBuy/buy/hold/sell/strongSell breakdown by month, the
    consensus key, how many analysts cover it, and the low/mean/high price targets.

    This is what analysts published, not a recommendation from you — report it as their view."""
    r = _load(symbol)
    if isinstance(r, str):
        return r
    t, i = r
    try:
        rec = t.recommendations
    except Exception:
        rec = None
    return _dump({
        "symbol": i.get("symbol"),
        "current_price": i.get("currentPrice"),
        "consensus": i.get("recommendationKey"),
        "analysts_covering": i.get("numberOfAnalystOpinions"),
        "target_low": i.get("targetLowPrice"),
        "target_mean": i.get("targetMeanPrice"),
        "target_high": i.get("targetHighPrice"),
        "ratings_by_period": [] if rec is None or rec.empty
        else [{str(k): _clean(v) for k, v in row.items()} for _, row in rec.iterrows()],
    })


@mcp.tool()
def yf_news(symbol: str, limit: int = 8) -> str:
    """Recent headlines for a symbol: title, publisher, timestamp and link.

    Headlines are third-party content, not verified fact — attribute them to the publisher
    rather than restating them as your own conclusion about the company."""
    sym = (symbol or "").strip().upper()
    try:
        items = yf.Ticker(sym).news or []
    except Exception as e:
        return f"ERROR: news unavailable for {sym}: {type(e).__name__}: {e}"
    out = []
    for n in items[:max(1, min(int(limit), 30))]:
        c = n.get("content") or n
        url = c.get("canonicalUrl") or c.get("clickThroughUrl") or {}
        prov = c.get("provider") or {}
        out.append({
            "title": c.get("title"),
            "publisher": prov.get("displayName") if isinstance(prov, dict) else _clean(prov),
            "published": c.get("pubDate") or c.get("displayTime"),
            "summary": (c.get("summary") or c.get("description") or "")[:300] or None,
            "url": url.get("url") if isinstance(url, dict) else _clean(url),
        })
    return _dump({"symbol": sym, "count": len(out),
                  "news": out or "no recent headlines returned by Yahoo"})


if __name__ == "__main__":
    mcp.run()
