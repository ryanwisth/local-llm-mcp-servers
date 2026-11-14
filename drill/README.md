# drill: read-only study coach tools

An MCP server over a running [Adaptive Drill Engine](https://github.com/ryanwisth/adaptive-drill-engine), a local practice app that tracks mastery per mistake pattern. Six tools let a local model see how practice is going and coach from real numbers: `drill_sections`, `drill_archetypes`, `drill_progress`, `drill_sets`, `drill_pace`, `drill_audit`.

## Run

```bash
# in the adaptive-drill-engine folder
python3 drill.py serve            # http://127.0.0.1:8780

# in this repo
uv run drill/server.py
```

Set `DRILL_URL` if the engine listens somewhere else. No API key.

## Design notes

- **Only routes that change nothing.** The engine also has routes that serve the next question, record an answer and start or finish a timed set. They are left out on purpose: a model that fetched or answered items would retire questions and distort the learner's mastery record. The model can read the scoreboard; it cannot play.
- **Standard library HTTP.** The engine is a local service with JSON routes, so the server uses `urllib` and has no dependency beyond fastmcp.
- **Same reply rules as the other servers.** JSON is passed through with light indentation, capped at 12,000 characters with the cut announced. If the engine is not running, the reply says so and gives the command to start it.

## Status

Checked on 2026-11-13 through an in-memory fastmcp client against the engine serving its 21-item sample bank: all six tools returned the engine's data, and with the engine stopped the tools returned the setup error. The sample bank had no practice history, so the progress, sets and pace replies were the empty case; replies on a long history have not been measured against the cap.
