#!/usr/bin/env python3
"""Preflight script checking Gemini API key authentication and quota availability.

Makes one minimal generation call and one minimal embedding call to verify
connectivity without burning significant quota.

Usage:
    python3 backend/scripts/check_quota.py
"""

import asyncio
from pathlib import Path
import sys

# Ensure backend directory is in sys.path
script_dir = Path(__file__).resolve().parent
backend_dir = script_dir.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.services.llm import generate_embedding, generate_structured_json, DailyQuotaExceededError


async def run_preflight() -> bool:
    print("=" * 70)
    print("GEMINI API PREFLIGHT QUOTA CHECK")
    print("=" * 70)

    has_key = bool(settings.LLM_API_KEY and settings.LLM_API_KEY.strip())
    print(f"Provider:         {settings.LLM_PROVIDER}")
    print(f"API Key:          {'key set' if has_key else 'MISSING'}")
    print(f"Chat Model:       {settings.LLM_MODEL}")
    print(f"Embedding Model:  {settings.EMBEDDING_MODEL}")
    print(f"Cache Enabled:    {settings.LLM_CACHE_ENABLED}")
    print(f"Min Throttle:     {settings.LLM_MIN_INTERVAL_SECONDS}s")
    print("-" * 70)

    if not has_key:
        print("[!] ERROR: LLM_API_KEY is missing or empty in backend/.env")
        return False

    # 1. Test embedding generation
    print("1. Testing embedding generation... ", end="", flush=True)
    try:
        vec = await generate_embedding("preflight test")
        print(f"OK (vector dim: {len(vec)})")
    except DailyQuotaExceededError as exc:
        print(f"DAILY QUOTA EXHAUSTED\n    {exc}")
        return False
    except Exception as exc:
        print(f"FAILED\n    {exc}")
        return False

    # 2. Test structured JSON completion
    print("2. Testing structured generation... ", end="", flush=True)
    try:
        res = await generate_structured_json(
            prompt="Return JSON with key 'status' equal to 'ok'.",
            system_instruction="You are a system health checker.",
        )
        if isinstance(res, dict) and res.get("status") == "ok":
            print(f"OK (output: {res})")
        else:
            print(f"OK (parsed: {res})")
    except DailyQuotaExceededError as exc:
        print(f"DAILY QUOTA EXHAUSTED\n    {exc}")
        return False
    except Exception as exc:
        print(f"FAILED\n    {exc}")
        return False

    print("-" * 70)
    print("PREFLIGHT STATUS: OK - Model and embedding endpoints are ready.")
    print("=" * 70)
    await asyncio.sleep(0.2)
    return True


def main() -> None:
    try:
        success = asyncio.run(run_preflight())
    except Exception as exc:
        print(f"Preflight encountered unexpected error: {exc}")
        success = False
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
