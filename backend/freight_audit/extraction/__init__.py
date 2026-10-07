from __future__ import annotations

from ..config import get_settings
from .base import ExtractionError, ExtractionResult, assemble
from .heuristic import HeuristicExtractor, pdf_has_text

__all__ = ["ExtractionError", "ExtractionResult", "assemble", "extract", "HeuristicExtractor"]


def _gemini():
    from .gemini import GeminiExtractor

    return GeminiExtractor()


def extract(pdf_bytes: bytes, mode: str | None = None) -> ExtractionResult:
    """Route a PDF to an extractor.

    auto: Gemini when a key is configured, otherwise the heuristic parser.
    Scanned PDFs (no text layer) always need Gemini's vision input; without a key
    they raise ExtractionError so the invoice lands in "needs review".
    """
    mode = mode or get_settings().extractor
    has_key = bool(get_settings().api_key)
    if mode == "heuristic" or (mode == "auto" and not has_key):
        if not pdf_has_text(pdf_bytes):
            raise ExtractionError("Scanned PDF (no text layer) and no vision LLM configured")
        return HeuristicExtractor().extract(pdf_bytes)
    if mode == "gemini":
        return _gemini().extract(pdf_bytes)
    # auto with a key: prefer Gemini, but keep working when the API is down or over quota.
    try:
        return _gemini().extract(pdf_bytes)
    except Exception as e:
        if not pdf_has_text(pdf_bytes):
            raise ExtractionError(f"Gemini failed ({type(e).__name__}) and the PDF has no text layer") from e
        res = HeuristicExtractor().extract(pdf_bytes)
        res.notes.insert(0, f"Gemini unavailable ({type(e).__name__}); used the offline parser.")
        res.method = "heuristic (gemini fallback)"
        return res
