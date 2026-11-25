"""On-disk cache service for LLM completions and vector embeddings.

Stores model outputs in an on-disk SQLite database (data/cache/llm_cache.db)
to ensure deterministic reproducibility, avoid redundant API spend, and
respect Free-Tier daily quotas. Keyed by SHA-256 hash of the input parameters.
"""

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, Generator, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def _get_cache_db_path(cache_dir: Optional[str] = None) -> Path:
    if cache_dir:
        target_dir = Path(cache_dir).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / "llm_cache.db"

    # Search for an existing cache DB across repository root and backend directory
    cur_dir = Path.cwd()
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    backend_root = Path(__file__).resolve().parent.parent.parent
    candidates = [
        cur_dir / "data" / "cache" / "llm_cache.db",
        project_root / "data" / "cache" / "llm_cache.db",
        backend_root / "data" / "cache" / "llm_cache.db",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    target_dir = Path(settings.LLM_CACHE_DIR).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / "llm_cache.db"


@contextmanager
def get_cache_connection(cache_dir: Optional[str] = None) -> Generator[sqlite3.Connection, None, None]:
    db_path = _get_cache_db_path(cache_dir)
    conn = sqlite3.connect(
        str(db_path),
        timeout=30.0,
        isolation_level="IMMEDIATE",
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    try:
        yield conn
        if conn.in_transaction:
            conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def init_cache(cache_dir: Optional[str] = None) -> None:
    """Initialize SQLite cache tables if they do not exist."""
    with get_cache_connection(cache_dir) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS completion_cache (
                cache_key TEXT PRIMARY KEY,
                model TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS embedding_cache (
                cache_key TEXT PRIMARY KEY,
                model TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def hash_completion_key(
    model: str,
    prompt: str,
    system_instruction: Optional[str] = None,
    schema_name: Optional[str] = None,
) -> str:
    """Generate deterministic SHA-256 cache key for completion request."""
    raw = f"{model}|{system_instruction or ''}|{schema_name or ''}|{prompt}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_embedding_key(model: str, text: str) -> str:
    """Generate deterministic SHA-256 cache key for embedding request."""
    raw = f"{model}|{text.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_cached_completion(
    model: str,
    prompt: str,
    system_instruction: Optional[str] = None,
    schema_name: Optional[str] = None,
    cache_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve cached completion dictionary if present and caching is enabled."""
    if not settings.LLM_CACHE_ENABLED:
        return None

    init_cache(cache_dir)
    key = hash_completion_key(model, prompt, system_instruction, schema_name)
    with get_cache_connection(cache_dir) as conn:
        row = conn.execute(
            "SELECT response_json FROM completion_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if row:
            try:
                return json.loads(row["response_json"])
            except Exception:
                return None
    return None


def set_cached_completion(
    model: str,
    prompt: str,
    response: Dict[str, Any],
    system_instruction: Optional[str] = None,
    schema_name: Optional[str] = None,
    cache_dir: Optional[str] = None,
) -> None:
    """Store completion output dictionary into persistent cache."""
    if not settings.LLM_CACHE_ENABLED:
        return

    init_cache(cache_dir)
    key = hash_completion_key(model, prompt, system_instruction, schema_name)
    now = datetime.utcnow().isoformat()
    with get_cache_connection(cache_dir) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO completion_cache (cache_key, model, response_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (key, model, json.dumps(response), now),
        )


def get_cached_embedding(
    model: str,
    text: str,
    cache_dir: Optional[str] = None,
) -> Optional[List[float]]:
    """Retrieve cached embedding vector if present and caching is enabled."""
    if not settings.LLM_CACHE_ENABLED:
        return None

    init_cache(cache_dir)
    key = hash_embedding_key(model, text)
    with get_cache_connection(cache_dir) as conn:
        row = conn.execute(
            "SELECT embedding_json FROM embedding_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if row:
            try:
                return json.loads(row["embedding_json"])
            except Exception:
                return None
    return None


def set_cached_embedding(
    model: str,
    text: str,
    embedding: List[float],
    cache_dir: Optional[str] = None,
) -> None:
    """Store embedding vector into persistent cache."""
    if not settings.LLM_CACHE_ENABLED:
        return

    init_cache(cache_dir)
    key = hash_embedding_key(model, text)
    now = datetime.utcnow().isoformat()
    with get_cache_connection(cache_dir) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO embedding_cache (cache_key, model, embedding_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (key, model, json.dumps(embedding), now),
        )
