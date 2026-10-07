"""Thin Gemini wrapper: structured JSON output, token accounting, Pydantic validation + retry."""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .config import get_settings

T = TypeVar("T", bound=BaseModel)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    attempts: list[str] = field(default_factory=list)

    def add(self, resp) -> None:
        um = getattr(resp, "usage_metadata", None)
        self.calls += 1
        if um:
            self.input_tokens += um.prompt_token_count or 0
            self.output_tokens += (um.candidates_token_count or 0) + (getattr(um, "thoughts_token_count", 0) or 0)

    @property
    def cost_usd(self) -> float:
        s = get_settings()
        return (self.input_tokens * s.llm_price_in + self.output_tokens * s.llm_price_out) / 1e6


class LLMUnavailable(RuntimeError):
    pass


class GeminiClient:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        s = get_settings()
        key = api_key or s.api_key
        if not key:
            raise LLMUnavailable("No GEMINI_API_KEY / GOOGLE_API_KEY configured")
        from google import genai

        from google.genai import types

        # Bounded per-request timeout so an overloaded API can't hang a request indefinitely.
        self.client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=int(s.llm_timeout_s * 1000)))
        self.model = model or s.gemini_model

    def _generate(self, **kw):
        """generate_content with exponential backoff on rate limits / overload (429, 5xx)."""
        import httpx
        from google.genai import errors

        delay = 2.0
        for attempt in range(6):
            try:
                return self.client.models.generate_content(model=self.model, **kw)
            except (errors.APIError, httpx.TransportError) as e:
                retryable = isinstance(e, httpx.TransportError) or e.code in (429, 500, 502, 503, 504)
                if retryable and getattr(e, "code", None) == 429 and "PerDay" in str(e):
                    retryable = False  # daily quota: waiting seconds won't help
                if not retryable or attempt == 5:
                    raise
                time.sleep(delay + random.random())
                delay = min(delay * 2, 60)

    def structured(self, contents: list, schema: type[T], system: str, usage: Usage, retries: int = 2) -> T:
        """Ask for JSON matching `schema`; on validation failure, retry with the error appended."""
        from google.genai import types

        NO_AFC = types.AutomaticFunctionCallingConfig(disable=True)
        convo = list(contents)
        last_err: Exception | None = None
        for _ in range(retries + 1):
            resp = self._generate(
                contents=convo,
                config=types.GenerateContentConfig(system_instruction=system, temperature=0, automatic_function_calling=NO_AFC,
                                                   response_mime_type="application/json", response_schema=schema))
            usage.add(resp)
            try:
                return schema.model_validate(json.loads(resp.text))
            except (ValidationError, json.JSONDecodeError, TypeError) as e:
                last_err = e
                usage.attempts.append(str(e)[:300])
                convo = list(contents) + [f"Your previous answer failed validation: {e}. Return corrected JSON only."]
        raise ValueError(f"LLM output failed validation after {retries + 1} attempts: {last_err}")

    def text(self, contents: list, system: str, usage: Usage, temperature: float = 0.2) -> str:
        from google.genai import types

        NO_AFC = types.AutomaticFunctionCallingConfig(disable=True)
        resp = self._generate(
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=system, temperature=temperature,
                                               automatic_function_calling=NO_AFC))
        usage.add(resp)
        return resp.text or ""


def pdf_part(pdf_bytes: bytes):
    from google.genai import types

    return types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
