# texify: equation image to LaTeX

An MCP server with one tool, `ocr_equation`, that turns a cropped image of a single math expression (base64 PNG or JPEG) into LaTeX using the open-source [texify](https://github.com/VikParuchuri/texify) model. It lets a local chat model read equations out of screenshots and scans.

## Run

```bash
uv run texify/server.py
```

The first call downloads the texify model (about 1.3 GB) and is slow; later calls reuse the loaded model. It runs on the Apple GPU (MPS) with CPU fallback; set `TORCH_DEVICE` to change that. No API key. Runs fully offline after the download.

## Design notes

- **Lazy model load.** The model loads on the first tool call, not at start-up, so the server registers with a client quickly and costs no memory until used.
- **One equation per call.** A tight crop of a single expression works best; the tool is not a page OCR.
- **Plain errors.** An image that cannot be decoded returns an `ERROR ...` sentence.

## Status

This server was used in the author's local stack from a virtual environment with texify 0.2.1, mcp 1.29.1 and torch 2.13.0. For this repo, on 2026-11-13, only the tool listing and the bad-image error path were re-checked in that environment; the OCR itself was not re-run, and the inline `uv` dependency header was added for consistency and has not been exercised. Unlike the other servers it imports `mcp.server.fastmcp` from the official `mcp` package. texify and its model weights carry their own licenses; read them before use.
