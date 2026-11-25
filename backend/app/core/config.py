"""Core configuration module for the application."""

from functools import lru_cache
from typing import Optional
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env", "../backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General Application Info
    APP_NAME: str = "Contract Clause Risk-Flagging and Redline-Suggestion Agent"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # Advisory Notice
    LEGAL_DISCLAIMER: str = (
        "ADVISORY ONLY: Recommendations are based on the company negotiation playbook. "
        "Qualified legal professionals must review and approve all clauses and redlines."
    )

    # LLM & Embedding Settings
    LLM_PROVIDER: str = Field(
        default="gemini",
        description="LLM provider: 'gemini' (default), with extensibility for others",
    )
    LLM_API_KEY: str = Field(
        default="",
        description="API key for the active LLM provider",
    )
    LLM_MODEL: str = Field(
        default="gemini-3-flash-preview",
        description="Model identifier for chat completion and structured generation",
    )
    EMBEDDING_MODEL: str = Field(
        default="gemini-embedding-001",
        description="Model identifier for vector embeddings",
    )
    ENABLE_LLM_SEGMENT_REFINEMENT: bool = Field(
        default=False,
        description="Enable LLM refinement pass for clause boundary adjustments",
    )
    ENABLE_PLAYBOOK_AUTO_INGEST: bool = Field(
        default=False,
        description="Force re-ingest of playbook rules on startup even if collection exists",
    )
    PLAYBOOK_COLLECTION_NAME: str = Field(
        default="playbook_rules",
        description="ChromaDB collection name for playbook rules",
    )
    DEFAULT_TOP_K: int = Field(
        default=3,
        description="Default number of playbook rules to retrieve per query",
    )
    CONFIDENCE_THRESHOLD: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Confidence threshold below which clauses are flagged for human review",
    )
    CONCURRENCY_LIMIT: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum concurrent clause analyses across contract processing",
    )
    MAX_LLM_RETRIES: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Number of retries for LLM calls on error",
    )
    LLM_CACHE_ENABLED: bool = Field(
        default=False,
        description="Enable persistent on-disk cache for LLM completions and embeddings",
    )
    LLM_CACHE_DIR: str = Field(
        default="./data/cache",
        description="Directory path for persistent LLM cache",
    )
    LLM_MIN_INTERVAL_SECONDS: float = Field(
        default=6.0,
        ge=0.0,
        description="Minimum seconds between outgoing live LLM API requests",
    )

    @model_validator(mode="after")
    def adjust_concurrency_for_throttle(self) -> "Settings":
        if self.LLM_MIN_INTERVAL_SECONDS > 0:
            self.CONCURRENCY_LIMIT = 1
        return self

    # Storage Paths
    CHROMA_PATH: str = Field(
        default="./data/chroma",
        description="Local directory path for ChromaDB vector store",
    )
    DB_PATH: str = Field(
        default="./data/app.db",
        description="Path to relational SQLite database",
    )
    CHECKPOINT_DB_PATH: str = Field(
        default="./data/checkpoints.db",
        description="Path to LangGraph checkpoint SQLite database",
    )
    UPLOADS_DIR: str = Field(
        default="./data/uploads",
        description="Directory to store uploaded contract files",
    )
    MAX_UPLOAD_SIZE_BYTES: int = Field(
        default=10 * 1024 * 1024,
        description="Maximum allowed file upload size in bytes (10 MB)",
    )
    ENABLE_CHECKPOINTER: bool = Field(
        default=True,
        description="Enable SQLite checkpointer and interrupt in contract graph",
    )


@lru_cache()
def get_settings() -> Settings:
    """Return cached instance of application settings."""
    return Settings()


settings = get_settings()
