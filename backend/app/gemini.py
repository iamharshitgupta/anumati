"""Thin Gemini wrapper (google-genai SDK).

Design rule: every call has a deterministic fallback. Gemini sharpens the
semantic checks; it is never a single point of failure for a payment decision.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any

from .config import settings

log = logging.getLogger("anumati.gemini")

_client = None
_available: bool | None = None

# --- cost guardrail --------------------------------------------------------
# A single process-wide limiter in front of every model call. The sandbox is
# reachable with free anonymous tokens, so without this a scripted caller could
# drive unbounded Gemini spend. Every caller already handles a None return by
# falling back to heuristics, so exceeding a cap degrades gracefully instead of
# failing. Caps are env-tunable (0 = unlimited); see config.py.
_rl_lock = threading.Lock()
_rl_window_start = 0.0
_rl_window_count = 0
_rl_total = 0
_rl_warned_total = False


def _rate_limit_ok() -> bool:
    global _rl_window_start, _rl_window_count, _rl_total, _rl_warned_total
    per_min = settings.gemini_max_calls_per_min
    total_cap = settings.gemini_max_calls_total
    with _rl_lock:
        if total_cap and _rl_total >= total_cap:
            if not _rl_warned_total:
                log.warning("Gemini total call cap (%d) reached; using heuristics for the rest of this process", total_cap)
                _rl_warned_total = True
            return False
        now = time.monotonic()
        if now - _rl_window_start >= 60.0:
            _rl_window_start = now
            _rl_window_count = 0
        if per_min and _rl_window_count >= per_min:
            log.warning("Gemini per-minute cap (%d) reached; using heuristics until the window resets", per_min)
            return False
        _rl_window_count += 1
        _rl_total += 1
        return True


def available() -> bool:
    global _client, _available
    if _available is not None:
        return _available
    if not settings.gemini_enabled:
        _available = False
        return False
    try:
        from google import genai  # type: ignore

        if settings.use_vertex:
            _client = genai.Client(vertexai=True, project=settings.gcp_project, location=settings.vertex_location)
        elif settings.gemini_api_key:
            _client = genai.Client(api_key=settings.gemini_api_key)
        else:
            _available = False
            return False
        _available = True
    except Exception as e:  # pragma: no cover
        log.warning("Gemini unavailable: %s", e)
        _available = False
    return _available


def generate_json(system: str, prompt: str, schema: dict | None = None, temperature: float = 0.1) -> dict | None:
    """Return parsed JSON from Gemini or None on any failure."""
    if not available() or not _rate_limit_ok():
        return None
    try:
        from google.genai import types  # type: ignore

        cfg = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=schema,
            http_options=types.HttpOptions(timeout=int(settings.gemini_timeout_s * 1000)),
        )
        resp = _client.models.generate_content(model=settings.gemini_model, contents=prompt, config=cfg)
        text = resp.text or ""
        return _parse_json(text)
    except Exception as e:
        log.warning("Gemini call failed, using fallback: %s", e)
        return None


def generate_text(system: str, prompt: str, temperature: float = 0.3) -> str | None:
    if not available() or not _rate_limit_ok():
        return None
    try:
        from google.genai import types  # type: ignore

        cfg = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            http_options=types.HttpOptions(timeout=int(settings.gemini_timeout_s * 1000)),
        )
        resp = _client.models.generate_content(model=settings.gemini_model, contents=prompt, config=cfg)
        return resp.text
    except Exception as e:
        log.warning("Gemini call failed, using fallback: %s", e)
        return None


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def engine_name() -> str:
    return "gemini" if available() else "heuristic"
