# osv-scanner: dependency vulnerability audit

An MCP server with one tool, `scan_project`, that wraps Google's [osv-scanner](https://github.com/google/osv-scanner) command-line tool. Point it at a project folder or a lockfile and it returns a short list of known-vulnerable dependencies from the [OSV](https://osv.dev) advisory database.

## Run

```bash
brew install osv-scanner          # or any other install; the binary must be on PATH
uv run osv-scanner/server.py
```

Set `OSV_SCANNER=/full/path/to/osv-scanner` if the binary is not on PATH. No API key.

## Design notes

- **One line per finding.** The CLI's JSON report for a small project runs to hundreds of kilobytes. The tool reduces it to `package version: advisory id - summary`, capped at 60 lines, with the total count stated when the list is cut.
- **Tries the v2 command first, then older forms.** `scan source --recursive`, then `scan --recursive`, then the flag-only form, so the server works across CLI versions.
- **Plain errors.** A missing binary or a missing path returns an `ERROR ...` sentence with the fix, not a stack trace.
- **What leaves the machine.** The scan runs locally. The CLI sends package names and versions (not source code) to OSV's public API to fetch advisories.
- **Read-only.** It reports; it does not upgrade or edit anything.

## Status

Checked on 2026-11-13 through an in-memory fastmcp client with osv-scanner 2.5.1: a two-line `requirements.txt` with old pins returned 58 findings; a missing path and a missing binary each returned the setup error. Only the v2 command form was exercised; the fallbacks for older CLI versions were not.
