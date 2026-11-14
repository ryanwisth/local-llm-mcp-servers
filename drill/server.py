# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=2"]
# ///
"""Read-only MCP over a running Adaptive Drill Engine (https://github.com/ryanwisth/adaptive-drill-engine).

Lets a local model act as a study coach: it can see which mistake patterns are mastered, which are
leaking, how recent timed sets went and whether the question bank has problems.

Deliberately exposes ONLY non-mutating routes. /api/next, /api/answer, /api/set/start and
/api/set/finish are excluded: a model that fetched or answered items would retire questions and
distort the learner's mastery record.

Set DRILL_URL if the engine is not at http://127.0.0.1:8780."""
import json
import os
import urllib.parse
import urllib.request

from fastmcp import FastMCP

BASE = os.environ.get("DRILL_URL", "http://127.0.0.1:8780").rstrip("/")
CAP = 12000
mcp = FastMCP("drill")


def _get(path: str, **params) -> str:
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    url = f"{BASE}{path}" + (f"?{q}" if q else "")
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception as e:
        return f"ERROR: drill engine not reachable at {url}: {e}. Start it with `python3 drill.py serve`."
    try:
        text = json.dumps(json.loads(body), indent=1)
    except Exception:
        text = body
    if len(text) > CAP:
        text = text[:CAP] + f"\n... [truncated at {CAP} characters]"
    return text


@mcp.tool()
def drill_sections() -> str:
    """List the sections in the question bank with their live item counts. Call this first."""
    return _get("/api/sections")


@mcp.tool()
def drill_archetypes(section: str = "") -> str:
    """Mastery table: one row per archetype (mistake pattern) with status, streak, live items,
    accuracy and average time against target. Use it to see what is mastered and what is leaking.

    Args:
        section: a section name from drill_sections, or empty for all sections.
    """
    return _get("/api/archetypes", section=section)


@mcp.tool()
def drill_progress(hours: float = 24) -> str:
    """Practice summary for a recent window: attempts, accuracy, on-time answers, minutes,
    a per-section breakdown, archetypes mastered and the misses.

    Args:
        hours: window length in hours (24 = last day, 168 = last week).
    """
    return _get("/api/progress", hours=hours)


@mcp.tool()
def drill_sets() -> str:
    """Recent timed sets with their scores and ids (use an id with drill_pace)."""
    return _get("/api/sets")


@mcp.tool()
def drill_pace(set_id: int) -> str:
    """Pacing report for one finished timed set: checkpoints against plan, items over the
    per-item cap, flags, answer changes and a pass or fail grade.

    Args:
        set_id: a set id from drill_sets.
    """
    return _get("/api/pace", id=set_id)


@mcp.tool()
def drill_audit() -> str:
    """Question-bank health: unverified items, retired items and archetypes running short of live items."""
    return _get("/api/audit")


if __name__ == "__main__":
    mcp.run()
