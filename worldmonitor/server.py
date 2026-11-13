# /// script
# requires-python = ">=3.12"
# dependencies = ["fastmcp==4.1.0"]
# ///
"""MCP over World Monitor (worldmonitor.app) — live world events for the local model.

Wraps World Monitor's hosted MCP server rather than exposing it directly, because the upstream
tools/list is 90 tools and ~100k tokens of schema: at ~300-450 tok/s local prefill that is
minutes per new chat for a local model and most of a 131k context. This server re-exposes 15
of them with short hand-written signatures (~3k tokens), small default limits, and replies capped
at 12 000 chars.

Auth, in priority order:
  1. Static key  — $WORLDMONITOR_API_KEY, sent as X-WorldMonitor-Key. Only API Starter+ plans issue wm_ keys; a self-hosted stack takes
     whatever key you put in its WORLDMONITOR_VALID_KEYS.
  2. Browser login — free account or Pro. Pro is OAuth-only (no static key exists), and mcpo
     can only forward a static header, so the OAuth client lives here. Run once in a terminal:
         uv run worldmonitor/server.py --login
     Tokens land in $WORLDMONITOR_OAUTH_DIR (default ~/.config/mcp-worldmonitor/oauth, dir 700). The access token lasts 1 h and
     is refreshed silently; the refresh token lasts 7 days, so a week of disuse means one more
     --login. This server never opens a browser on its own — a tool call without a valid login
     returns a setup message instead of hanging a chat turn on a consent page.

Endpoint: $WORLDMONITOR_MCP_URL overrides the hosted
https://worldmonitor.app/mcp — a self-hosted Docker stack serves http://localhost:3000/api/mcp.

Budget (probed 2026-10-09): free account = 5 calls/UTC day and only the cache-read tools;
Pro = 50/day and everything. Every tool here is one upstream call except wm_allowance, which
is quota-free. Tools marked "Pro only" fail on a free account with the upstream's own message.
"""
import asyncio
import json
import os
import sys
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from fastmcp import Client, FastMCP
from fastmcp.client.auth.oauth import OAuth, TokenStorageAdapter
from fastmcp.client.transports import StreamableHttpTransport
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)

HOSTED = "https://worldmonitor.app/mcp"
OAUTH_DIR = Path(os.environ.get("WORLDMONITOR_OAUTH_DIR")
                 or Path.home() / ".config" / "mcp-worldmonitor" / "oauth").expanduser()
# Fixed so the redirect_uri registered at --login matches every later re-login.
CALLBACK_PORT = 8766
MAX_CHARS = 12000
LOGIN_CMD = "uv run worldmonitor/server.py --login"

mcp = FastMCP("worldmonitor")


class LoginRequired(Exception):
    pass


class HeadlessOAuth(OAuth):
    """OAuth that refuses to start a browser consent flow unless run from --login."""

    def __init__(self, *args, interactive: bool = False, **kwargs):
        self._interactive = interactive
        super().__init__(*args, **kwargs)

    async def redirect_handler(self, authorization_url: str) -> None:
        if not self._interactive:
            raise LoginRequired(authorization_url)
        print(f"Opening your browser to sign in to World Monitor:\n  {authorization_url}\n")
        await super().redirect_handler(authorization_url)


def _read(env: str) -> str | None:
    return os.environ.get(env, "").strip() or None


def _url() -> str:
    return (_read("WORLDMONITOR_MCP_URL") or HOSTED).rstrip("/")


def _key() -> str | None:
    return _read("WORLDMONITOR_API_KEY")


def _store() -> FileTreeStore:
    OAUTH_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(OAUTH_DIR, 0o700)
    return FileTreeStore(
        data_directory=OAUTH_DIR,
        key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(OAUTH_DIR),
        collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(OAUTH_DIR),
    )


async def _has_login(url: str) -> bool:
    return await TokenStorageAdapter(async_key_value=_store(), server_url=url).get_tokens() is not None


def _client(url: str, interactive: bool = False) -> Client:
    key = _key()
    if key:
        transport = StreamableHttpTransport(url, headers={"X-WorldMonitor-Key": key})
    else:
        auth = HeadlessOAuth(
            mcp_url=url,
            scopes="mcp",
            client_name="mcp-worldmonitor (local LLM)",
            token_storage=_store(),
            callback_port=CALLBACK_PORT,
            interactive=interactive,
        )
        transport = StreamableHttpTransport(url, auth=auth)
    return Client(transport, timeout=90)


def _find(exc: BaseException, cls: type) -> BaseException | None:
    """Search an exception's cause/context chain and any exception-group members."""
    seen, stack = set(), [exc]
    while stack:
        e = stack.pop()
        if e is None or id(e) in seen:
            continue
        seen.add(id(e))
        if isinstance(e, cls):
            return e
        stack.extend(getattr(e, "exceptions", ()))
        stack.extend((e.__cause__, e.__context__))
    return None


def _login_msg(why: str) -> str:
    return (
        f"ERROR: World Monitor is not signed in ({why}). Run this once in a terminal, "
        f"sign in with a World Monitor account in the browser, and then retry:\n  {LOGIN_CMD}"
    )


def _prune(v):
    """Drop null / empty values: they are most of the bytes in a sparse feed and carry nothing."""
    if isinstance(v, dict):
        out = {k: _prune(x) for k, x in v.items()}
        return {k: x for k, x in out.items() if x not in (None, "", [], {})}
    if isinstance(v, list):
        return [x for x in (_prune(i) for i in v) if x not in (None, "", [], {})]
    return v


def _render(result) -> str:
    if result.structured_content is not None:
        body = json.dumps(_prune(result.structured_content), separators=(",", ":"), ensure_ascii=False)
    else:
        parts = [getattr(c, "text", "") for c in result.content]
        body = "\n".join(p for p in parts if p)
        try:
            body = json.dumps(_prune(json.loads(body)), separators=(",", ":"), ensure_ascii=False)
        except ValueError:
            pass
    if len(body) > MAX_CHARS:
        body = (
            body[:MAX_CHARS]
            + f"\n…[truncated at {MAX_CHARS} of {len(body)} chars — call again with a lower limit "
            "or a country/query filter]"
        )
    return body


async def _call(tool: str, args: dict, url: str | None = None, interactive: bool = False) -> str:
    url = url or _url()
    args = {k: v for k, v in args.items() if v is not None}
    if not _key() and not interactive and not await _has_login(url):
        return _login_msg("no saved login")
    try:
        async with _client(url, interactive) as c:
            r = await c.call_tool(tool, args, raise_on_error=False)
    except Exception as e:
        if _find(e, LoginRequired):
            return _login_msg("the saved login expired after 7 days unused")
        return f"ERROR: World Monitor call {tool} failed: {type(e).__name__}: {str(e)[:600]}"
    if r.is_error:
        text = " ".join(getattr(c, "text", "") for c in r.content).strip()
        return f"ERROR from World Monitor ({tool}): {text[:1500]}"
    return _render(r)


# --- Tools on the free account (cache reads) -------------------------------------------------

@mcp.tool
async def wm_news(
    topic: Literal["conflict", "economy", "cyber", "nuclear", "intelligence", "maritime"] | None = None,
    country: str | None = None,
    query: str | None = None,
    alerts_only: bool = False,
    limit: int = 10,
) -> str:
    """Top world news stories, AI-classified threat level, GDELT signals and travel advisories.
    country = ISO-2 code or English name. query = substring that must appear in the headline."""
    return await _call("get_news_intelligence", {
        "topic": topic, "country": country, "query": query,
        "alerts_only": alerts_only or None, "limit": limit,
    })


@mcp.tool
async def wm_conflicts(country: str | None = None, min_fatalities: int | None = None, limit: int = 10) -> str:
    """Active armed-conflict events (UCDP), unrest/protests with coordinates, and country risk scores."""
    return await _call("get_conflict_events", {"country": country, "min_fatalities": min_fatalities, "limit": limit})


@mcp.tool
async def wm_disasters(
    kind: Literal["earthquakes", "wildfires", "other"] | None = None,
    min_magnitude: float | None = None,
    limit: int = 10,
) -> str:
    """Recent M4.5+ earthquakes, active wildfires (NASA FIRMS) and other natural hazards (storms, floods, volcanoes)."""
    return await _call("get_natural_disasters", {
        "dataset": [kind] if kind else None, "min_magnitude": min_magnitude, "limit": limit,
    })


@mcp.tool
async def wm_markets(
    symbols: list[str] | None = None,
    asset_class: Literal["equity", "commodity", "crypto", "sectors", "etf", "gulf", "sentiment"] | None = None,
    limit: int = 10,
) -> str:
    """Live quotes: major stocks, commodities (gold "GC=F", oil), crypto, sector ETFs, fear/greed sentiment."""
    return await _call("get_market_data", {
        "symbols": symbols, "asset_class": [asset_class] if asset_class else None, "limit": limit,
    })


@mcp.tool
async def wm_prediction_markets(
    category: Literal["geopolitical", "tech", "finance"] | None = None,
    query: str | None = None,
    limit: int = 10,
) -> str:
    """Polymarket / Kalshi odds (real-money probabilities) on elections, wars, tech and the economy."""
    return await _call("get_prediction_markets", {"category": category, "query": query, "limit": limit})


@mcp.tool
async def wm_military(theater: str | None = None, limit: int = 10) -> str:
    """Military posture by theater with risk scores. theater = substring, e.g. "taiwan", "iran", "baltic", "korea"."""
    return await _call("get_military_posture", {"theater": theater, "limit": limit})


@mcp.tool
async def wm_chokepoints(chokepoint: str | None = None, limit: int = 10) -> str:
    """Shipping chokepoint status and vessel transit counts (Hormuz, Suez, Bab el-Mandeb, Panama, Malacca...)."""
    return await _call("get_chokepoint_status", {"chokepoint": chokepoint, "limit": limit})


@mcp.tool
async def wm_energy(
    dataset: Literal["eia-petroleum", "electricity", "ember", "gas-storage", "fuel-shortages",
                     "disruptions", "crisis-policies", "fossil-share", "renewable"] | None = None,
    country: str | None = None,
    limit: int = 10,
) -> str:
    """Energy: US petroleum stocks (EIA), electricity prices and mix, gas storage, fuel shortages, supply disruptions."""
    return await _call("get_energy_intelligence", {
        "dataset": [dataset] if dataset else None, "country": country, "limit": limit,
    })


@mcp.tool
async def wm_cyber(
    min_severity: Literal["low", "medium", "high", "critical"] = "high",
    country: str | None = None,
    limit: int = 10,
) -> str:
    """Active cyber threats: exploited vulnerabilities (CISA KEV), malware and botnet command servers."""
    return await _call("get_cyber_threats", {"min_severity": min_severity, "country": country, "limit": limit})


@mcp.tool
async def wm_health(country: str | None = None, disease: str | None = None, limit: int = 10) -> str:
    """Active disease outbreaks (WHO / ECDC) by country or disease name."""
    return await _call("get_health_signals", {
        "signal_type": ["outbreaks"], "country": country, "disease": disease, "limit": limit,
    })


@mcp.tool
async def wm_aviation(country: str | None = None, iata: str | None = None, limit: int = 10) -> str:
    """Airports with delays or closures, airspace closures (NOTAMs), tracked military aircraft. iata e.g. "ORD"."""
    return await _call("get_aviation_status", {
        "country": country, "iata": iata, "disrupted_only": True, "limit": limit,
    })


@mcp.tool
async def wm_allowance() -> str:
    """How many World Monitor calls are left today and when the count resets. Free to call."""
    return await _call("get_mcp_allowance", {})


# --- Pro only (fail on a free account with the upstream's own message) -----------------------

@mcp.tool
async def wm_world_brief() -> str:
    """Pro only. Today's citation-grounded world intelligence brief — the best single overview."""
    return await _call("get_world_brief", {})


@mcp.tool
async def wm_country_risk(country: str) -> str:
    """Pro only. One country's instability index (0-100) with its drivers. country = ISO-2/3 code or name."""
    return await _call("get_country_risk", {"country_code": country})


@mcp.tool
async def wm_hotspots(limit: int = 10) -> str:
    """Pro only. The 29 curated geopolitical hotspots ranked by current escalation (1-5)."""
    return await _call("get_hotspot_escalation", {"limit": limit})


# --- CLI: --login / --status / --selftest ----------------------------------------------------

async def _cli(cmd: str) -> int:
    url = _url()
    if cmd == "--status":
        mode = "static key" if _key() else ("browser login saved" if await _has_login(url) else "NOT signed in")
        print(f"endpoint: {url}\nauth:     {mode}\ntokens:   {OAUTH_DIR}")
        return 0
    if cmd == "--login":
        if _key():
            print("A static key is set ($WORLDMONITOR_API_KEY); browser login is not used. Checking it instead.")
        out = await _call("get_mcp_allowance", {}, url=url, interactive=True)
        print(out)
        return 1 if out.startswith("ERROR") else 0
    if cmd == "--selftest":
        # Credential-free: proves the endpoint and the reply rendering without spending quota.
        # An anonymous `initialize` is answered 401, so this is one stateless tools/call of
        # get_sources (the one anonymous data tool) — not a Client session.
        req = urllib.request.Request(url, method="POST", data=json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "get_sources", "arguments": {}},
        }).encode(), headers={"Content-Type": "application/json",
                              "Accept": "application/json, text/event-stream"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", "replace")
        res = json.loads(raw[raw.find("{"):]).get("result", {})
        r = SimpleNamespace(
            structured_content=res.get("structuredContent"),
            content=[SimpleNamespace(text=c.get("text", "")) for c in res.get("content", [])],
            is_error=bool(res.get("isError")),
        )
        body = _render(r)
        print(f"get_sources -> {len(body)} chars rendered, error={r.is_error}")
        print(body[:400])
        return 1 if r.is_error or not body else 0
    print(f"usage: {sys.argv[0]} [--login | --status | --selftest]   (no args = run the MCP server)")
    return 2


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(asyncio.run(_cli(sys.argv[1])))
    mcp.run()
