# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp", "texify", "pillow"]
# ///
"""Math-OCR MCP server: crop of a math equation (base64 PNG or JPEG) -> LaTeX, via texify.

Loads the texify model once (about 1.3 GB, downloaded from Hugging Face on first use) and reuses it.
Runs on MPS (Apple GPU) with CPU fallback; set TORCH_DEVICE to change that."""
import base64
import io
import os

os.environ.setdefault("TORCH_DEVICE", "mps")
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

from PIL import Image
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("texify")

_model = None
_processor = None


def _ensure_loaded():
    global _model, _processor
    if _model is None:
        from texify.model.model import load_model
        from texify.model.processor import load_processor
        _model = load_model()
        _processor = load_processor()
    return _model, _processor


@mcp.tool()
def ocr_equation(image_base64: str, katex: bool = True) -> str:
    """OCR a cropped image of a single math equation or expression into LaTeX.

    Args:
        image_base64: base64-encoded PNG/JPEG of the equation crop (tight crop works best).
        katex: return KaTeX-compatible LaTeX (recommended for chat front ends that render KaTeX).
    """
    from texify.inference import batch_inference
    try:
        raw = base64.b64decode(image_base64)
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:
        return f"ERROR: could not decode image: {e}"
    model, processor = _ensure_loaded()
    results = batch_inference([img], model, processor)
    latex = results[0] if results else ""
    return latex or "(no LaTeX produced)"


if __name__ == "__main__":
    mcp.run()
