# worldmonitor: live world events

An MCP server over [World Monitor](https://worldmonitor.app): news, conflicts, disasters, markets, prediction markets, military posture, shipping chokepoints, energy, cyber threats, disease outbreaks and aviation. 15 tools, all prefixed `wm_`.

## Run

```bash
uv run worldmonitor/server.py              # MCP server over stdio (your client starts this)
uv run worldmonitor/server.py --login      # once: sign in in the browser, prints remaining allowance
uv run worldmonitor/server.py --status     # endpoint, auth mode, token folder
uv run worldmonitor/server.py --selftest   # one anonymous call, no quota spent
```

Environment: `WORLDMONITOR_API_KEY` (static key, optional), `WORLDMONITOR_MCP_URL` (self-hosted endpoint, optional), `WORLDMONITOR_OAUTH_DIR` (token folder, default `~/.config/mcp-worldmonitor/oauth`, created with mode 700).

## Tools

Free account: `wm_news`, `wm_conflicts`, `wm_disasters`, `wm_markets`, `wm_prediction_markets`, `wm_military`, `wm_chokepoints`, `wm_energy`, `wm_cyber`, `wm_health`, `wm_aviation`, `wm_allowance`.
Pro only (their docstrings say so): `wm_world_brief`, `wm_country_risk`, `wm_hotspots`.

## Design notes

- **Why a wrapper.** The hosted server's `tools/list` is 90 tools, about 398,000 characters (roughly 100k tokens) of schema, measured 2026-10-09. These 15 tools are about 9,200 characters. Free and Pro accounts are OAuth-only, and a static-header bridge such as mcpo cannot run OAuth, so the OAuth client (dynamic registration, PKCE, silent refresh) lives here.
- **Never opens a browser from a tool call.** `HeadlessOAuth.redirect_handler` raises `LoginRequired` unless the process was started with `--login`; `_call` turns that into a plain setup message. With no saved tokens it returns before any network call.
- **Token lifetimes** (from World Monitor's OAuth docs): access 1 hour, refresh 7 days. A week unused means one more `--login`.
- **Fixed callback port 8766**, so the redirect URI registered at the first login matches later ones.
- **Compact replies.** Null and empty fields are pruned, JSON is compact, replies cap at 12,000 characters with a "narrow it" note, and every list tool defaults to `limit=10`.
- **Paid-refresh parameters are not exposed.** Each upstream refresh spends allowance, and live-LLM upstream tools are left out for the same reason.
- **`--selftest`** makes one stateless JSON-RPC call to `get_sources`, the only credential-free data tool, because an anonymous MCP `initialize` is answered 401.

## Self-hosting

World Monitor can be self-hosted with Docker (see `SELF_HOSTING.md` in its repository), which is unmetered. Set a key in that stack's `WORLDMONITOR_VALID_KEYS`, then set the same value in `WORLDMONITOR_API_KEY` and the stack's MCP URL in `WORLDMONITOR_MCP_URL`. This path was not tested.
