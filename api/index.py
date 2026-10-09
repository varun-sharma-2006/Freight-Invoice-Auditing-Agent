"""Vercel serverless entry point: exposes the FastAPI app (all /api/* routes are rewritten here)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from freight_audit.api import app  # noqa: E402,F401
