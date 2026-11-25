"""LLM and Embedding service interface supporting pluggable providers.

This module provides a provider-agnostic abstraction layer for:
1. Chat completions with structured JSON output
2. Vector embeddings generation

Currently implements Google Gemini as the default provider, swappable via
the `LLM_PROVIDER` configuration setting.
"""

import asyncio
import json
import logging
import random
import re
import time
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel
from google import genai
from google.genai import types

from app.core.config import settings
from app.services.llm_cache import (
    get_cached_completion,
    get_cached_embedding,
    set_cached_completion,
    set_cached_embedding,
)

logger = logging.getLogger(__name__)


class DailyQuotaExceededError(Exception):
    """Raised when the LLM provider returns a per-day quota exhaustion error."""

    pass


_last_request_timestamp: float = 0.0
_throttle_lock = asyncio.Lock()

_stats = {
    "live_completion_calls": 0,
    "cached_completion_calls": 0,
    "live_embedding_calls": 0,
    "cached_embedding_calls": 0,
    "retries_count": 0,
    "malformed_count": 0,
}


def get_llm_stats() -> Dict[str, int]:
    """Return a snapshot of LLM and embedding call statistics."""
    return dict(_stats)


def reset_llm_stats() -> None:
    """Reset LLM and embedding call statistics to zero."""
    for k in _stats:
        _stats[k] = 0


async def _apply_throttle() -> None:
    """Enforce minimum interval between consecutive live API requests."""
    global _last_request_timestamp
    min_interval = settings.LLM_MIN_INTERVAL_SECONDS
    if min_interval <= 0:
        return

    async with _throttle_lock:
        now = time.time()
        elapsed = now - _last_request_timestamp
        if elapsed < min_interval and _last_request_timestamp > 0:
            sleep_time = min_interval - elapsed
            logger.info("Throttling live API request: sleeping %.1fs to protect RPM quota", sleep_time)
            await asyncio.sleep(sleep_time)
        _last_request_timestamp = time.time()


def _clean_json_string(text: str) -> str:
    """Strip markdown code fence blocks if present in model output."""
    cleaned = text.strip()
    # Match ```json ... ``` or ``` ... ```
    fence_pattern = r"^```(?:json)?\s*([\s\S]*?)\s*```$"
    match = re.match(fence_pattern, cleaned)
    if match:
        return match.group(1).strip()
    return cleaned


def _parse_retry_delay(exc: Exception, default_delay: float = 10.0, max_cap: float = 60.0) -> float:
    """Extract recommended retry delay from API rate-limit errors capped at max_cap."""
    msg = str(exc)
    delay = default_delay
    m = re.search(r"retry in (\d+(?:\.\d+)?)s", msg, re.IGNORECASE)
    if m:
        delay = float(m.group(1)) + 1.0
    else:
        m2 = re.search(r"retryDelay':\s*'(\d+)", msg)
        if m2:
            delay = float(m2.group(1)) + 1.0
    return min(delay, max_cap)


def _get_gemini_client() -> genai.Client:
    """Initialize and return a Gemini API client."""
    api_key = settings.LLM_API_KEY.strip() if settings.LLM_API_KEY else None
    if not api_key:
        raise ValueError(
            "LLM_API_KEY is not set. Please configure LLM_API_KEY in backend/.env "
            "or set the environment variable."
        )
    return genai.Client(api_key=api_key)


async def _gemini_generate_structured_json(
    prompt: str,
    system_instruction: Optional[str] = None,
    response_schema: Optional[Union[Type[BaseModel], dict]] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate structured JSON response using Google Gemini."""
    target_model = model or settings.LLM_MODEL
    schema_name = getattr(response_schema, "__name__", str(response_schema))

    # 1. Check persistent on-disk cache
    cached = get_cached_completion(
        model=target_model,
        prompt=prompt,
        system_instruction=system_instruction,
        schema_name=schema_name,
    )
    if cached is not None:
        _stats["cached_completion_calls"] += 1
        logger.debug("Cache hit for structured JSON completion (model: %s)", target_model)
        return cached

    client = _get_gemini_client()
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=response_schema,
    )

    max_retries = 3
    response = None
    for attempt in range(max_retries + 1):
        try:
            await _apply_throttle()
            _stats["live_completion_calls"] += 1
            response = await client.aio.models.generate_content(
                model=target_model,
                contents=prompt,
                config=config,
            )
            break
        except Exception as exc:
            msg = str(exc).lower()
            is_daily_limit = (
                "per day" in msg
                or "generaterequestsperday" in msg
                or ("daily" in msg and "quota" in msg)
            )
            if is_daily_limit:
                logger.error("Gemini daily quota limit hit for model %s: %s", target_model, exc)
                raise DailyQuotaExceededError(f"Daily API quota exhausted: {exc}") from exc

            is_rate_limit = "429" in str(exc) or "resource_exhausted" in msg
            if is_rate_limit and attempt < max_retries:
                _stats["retries_count"] += 1
                delay = _parse_retry_delay(exc, default_delay=15.0 * (attempt + 1))
                delay = min(delay + random.uniform(1.0, 5.0), 60.0)
                logger.warning(
                    "Gemini structured JSON rate limit (429) hit. Waiting %.1fs before retry %d/%d...",
                    delay,
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(delay)
            else:
                logger.error("Gemini structured JSON generation failed: %s", exc)
                raise

    raw_text = response.text or "{}"
    cleaned = _clean_json_string(raw_text)

    try:
        parsed = json.loads(cleaned)
        result = parsed if isinstance(parsed, dict) else {"data": parsed}
        set_cached_completion(
            model=target_model,
            prompt=prompt,
            response=result,
            system_instruction=system_instruction,
            schema_name=schema_name,
        )
        return result
    except json.JSONDecodeError as err:
        _stats["malformed_count"] += 1
        logger.error("Failed to decode JSON from Gemini output: %s", raw_text)
        raise ValueError(f"Model returned invalid JSON: {err}") from err


async def _gemini_generate_embedding(
    text: Union[str, List[str]],
    model: Optional[str] = None,
) -> Union[List[float], List[List[float]]]:
    """Generate vector embeddings using Google Gemini with persistent cache support."""
    target_model = model or settings.EMBEDDING_MODEL
    is_single = isinstance(text, str)
    texts = [text] if is_single else text

    # Check cache for each text
    cached_map: Dict[int, List[float]] = {}
    missing_indices: List[int] = []
    missing_texts: List[str] = []

    for idx, t in enumerate(texts):
        vec = get_cached_embedding(target_model, t)
        if vec is not None:
            _stats["cached_embedding_calls"] += 1
            cached_map[idx] = vec
        else:
            missing_indices.append(idx)
            missing_texts.append(t)

    if missing_texts:
        client = _get_gemini_client()
        max_retries = 3
        response = None
        for attempt in range(max_retries + 1):
            try:
                await _apply_throttle()
                _stats["live_embedding_calls"] += 1
                response = await client.aio.models.embed_content(
                    model=target_model,
                    contents=missing_texts,
                )
                break
            except Exception as exc:
                msg = str(exc).lower()
                is_daily_limit = (
                    "per day" in msg
                    or "generaterequestsperday" in msg
                    or ("daily" in msg and "quota" in msg)
                )
                if is_daily_limit:
                    logger.error("Gemini daily quota limit hit for embeddings (%s): %s", target_model, exc)
                    raise DailyQuotaExceededError(f"Daily API quota exhausted: {exc}") from exc

                is_rate_limit = "429" in str(exc) or "resource_exhausted" in msg
                if is_rate_limit and attempt < max_retries:
                    _stats["retries_count"] += 1
                    delay = _parse_retry_delay(exc, default_delay=15.0 * (attempt + 1))
                    delay = min(delay + random.uniform(1.0, 5.0), 60.0)
                    logger.warning(
                        "Gemini embedding rate limit (429) hit. Waiting %.1fs before retry %d/%d...",
                        delay,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("Gemini embedding generation failed: %s", exc)
                    raise

        new_embeddings = [item.values for item in (response.embeddings or [])]
        if len(new_embeddings) != len(missing_texts):
            raise ValueError("Mismatched number of embeddings returned by Gemini API")

        for orig_idx, t, vec in zip(missing_indices, missing_texts, new_embeddings):
            set_cached_embedding(target_model, t, vec)
            cached_map[orig_idx] = vec

    results = [cached_map[i] for i in range(len(texts))]
    return results[0] if is_single else results


# ------------------------------------------------------------------------------
# Public Provider-Agnostic Interface
# ------------------------------------------------------------------------------


async def generate_structured_json(
    prompt: str,
    system_instruction: Optional[str] = None,
    response_schema: Optional[Union[Type[BaseModel], dict]] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate structured JSON output from LLM chat completion.

    Dispatches to the provider specified by `settings.LLM_PROVIDER`.

    Args:
        prompt: User prompt or message instructions.
        system_instruction: Optional system level guidance.
        response_schema: Pydantic model class or JSON schema dict defining expected structure.
        model: Optional model override (defaults to settings.LLM_MODEL).

    Returns:
        Parsed JSON dictionary response.

    Raises:
        NotImplementedError: If the configured provider is unsupported.
        ValueError: If API key is missing or model output cannot be parsed as JSON.
    """
    provider = (settings.LLM_PROVIDER or "gemini").lower()

    if provider == "gemini":
        return await _gemini_generate_structured_json(
            prompt=prompt,
            system_instruction=system_instruction,
            response_schema=response_schema,
            model=model,
        )
    else:
        raise NotImplementedError(
            f"LLM provider '{provider}' is not supported yet. "
            "Supported providers: 'gemini'."
        )


async def generate_embedding(
    text: Union[str, List[str]],
    model: Optional[str] = None,
) -> Union[List[float], List[List[float]]]:
    """Generate vector embeddings for input text.

    Dispatches to the provider specified by `settings.LLM_PROVIDER`.

    Args:
        text: Single string or list of text strings to embed.
        model: Optional model override (defaults to settings.EMBEDDING_MODEL).

    Returns:
        List of floats (if single string) or list of list of floats (if list of strings).

    Raises:
        NotImplementedError: If the configured provider is unsupported.
        ValueError: If API key is missing or no embeddings returned.
    """
    provider = (settings.LLM_PROVIDER or "gemini").lower()

    if provider == "gemini":
        return await _gemini_generate_embedding(
            text=text,
            model=model,
        )
    else:
        raise NotImplementedError(
            f"Embedding provider '{provider}' is not supported yet. "
            "Supported providers: 'gemini'."
        )
