# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=2"]
# ///
"""Dependency vulnerability audit MCP: wraps Google's osv-scanner CLI.

One tool: scan a project folder or lockfile against the OSV advisory database and return a short,
readable list. The scan runs locally; the CLI sends package names and versions (not code) to OSV's
public API to fetch advisories.

The CLI is found on PATH, or set OSV_SCANNER to its full path."""
import json
import os
import shutil
import subprocess

from fastmcp import FastMCP

mcp = FastMCP("osv-scanner")


def _cli():
    return os.environ.get("OSV_SCANNER") or shutil.which("osv-scanner")


def _run(cli, args):
    return subprocess.run([cli, *args], capture_output=True, text=True, timeout=300)


@mcp.tool()
def scan_project(path: str) -> str:
    """Audit a project directory or lockfile for known-vulnerable dependencies (OSV database).

    Args:
        path: absolute path to a project folder or a lockfile (requirements.txt, package-lock.json, etc.)
    """
    cli = _cli()
    if not cli:
        return ("ERROR: osv-scanner is not installed. Install it (for example `brew install osv-scanner`) "
                "or set OSV_SCANNER to its full path.")
    if not os.path.exists(os.path.expanduser(path)):
        return f"ERROR: path not found: {path}"
    path = os.path.expanduser(path)
    # v2 CLI syntax first, then the older forms
    r = None
    for args in (["scan", "source", "--recursive", "--format", "json", path],
                 ["scan", "--recursive", "--format", "json", path],
                 ["--format", "json", "--recursive", path]):
        try:
            r = _run(cli, args)
        except Exception as e:
            return f"ERROR running osv-scanner: {e}"
        out = r.stdout.strip()
        if out.startswith("{"):
            break
    else:
        return (r.stdout or r.stderr or "no output")[:3000]
    try:
        data = json.loads(out)
    except Exception:
        return out[:3000]
    vulns = []
    for res in data.get("results", []):
        for pkg in res.get("packages", []):
            p = pkg.get("package", {})
            for v in pkg.get("vulnerabilities", []):
                vulns.append(f"- {p.get('name')} {p.get('version')}: {v.get('id')} - {(v.get('summary') or '')[:90]}")
    if not vulns:
        return "No known vulnerabilities found."
    more = f"\n(showing 60 of {len(vulns)})" if len(vulns) > 60 else ""
    return f"{len(vulns)} known vulnerabilities:\n" + "\n".join(vulns[:60]) + more


if __name__ == "__main__":
    mcp.run()
