"""Application settings, loaded from environment variables (see .env.example)."""
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    app_name: str = "MEMORA"
    environment: Literal["development", "production", "test"] = "development"
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    # --- MongoDB -----------------------------------------------------------
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "memora"
    # "mongodb" = $vectorSearch (MongoDB Atlas, or the mongodb-atlas-local image).
    # "local"   = in-process cosine similarity. DEVELOPMENT/TEST FALLBACK ONLY - not Atlas Vector Search.
    vector_backend: Literal["mongodb", "local"] = "mongodb"
    memory_vector_index: str = "memory_vector_index"
    episode_vector_index: str = "episode_vector_index"
    vector_num_candidates: int = 150
    ttl_grace_seconds: int = 3600  # TTL index deletes docs this long after expires_at
    message_retention_days: int = 0  # 0 = keep conversation messages until deleted by the user
    episode_retention_days: int = 30
    forget_redacts_evidence: bool = True

    # --- LLM ---------------------------------------------------------------
    # "mock" is an offline fallback for development and automated tests only.
    llm_provider: Literal["anthropic", "openai", "mock"] = "mock"
    chat_model: str = "claude-sonnet-5-5"
    extractor_model: str = "claude-haiku-5-5"
    anthropic_api_key: str | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 3
    chat_max_tokens: int = 1200

    # --- Embeddings --------------------------------------------------------
    # "hash" is a deterministic offline fallback for development and tests only.
    embedding_provider: Literal["openai", "voyage", "hash"] = "hash"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 256
    voyage_api_key: str | None = None
    voyage_base_url: str = "https://api.voyageai.com/v1"

    # --- Auth --------------------------------------------------------------
    auth_secret: str = "dev-only-change-me"
    token_ttl_hours: int = 24
    allow_signup: bool = True
    enable_demo_tools: bool = True
    demo_username: str = "demo"
    demo_password: str = "memora-demo"

    # --- Memory policy -----------------------------------------------------
    duplicate_threshold: float = 0.93  # normalised similarity (0..1) treated as the same memory
    forget_match_threshold: float = 0.70
    confirm_threshold: float = 0.75  # inferred memories below this need user confirmation
    pinned_min_confidence: float = 0.75
    min_similarity: float = 0.60  # normalised similarity gate for retrieval

    # --- Ranking weights (configurable) -------------------------------------
    w_similarity: float = 0.40
    w_importance: float = 0.15
    w_confidence: float = 0.10
    w_strength: float = 0.15
    w_type: float = 0.05
    w_graph: float = 0.10
    w_scope: float = 0.05

    # --- Working memory budgets (approximate tokens) -------------------------
    budget_core: int = 220
    budget_bridge: int = 120
    budget_episode_summary: int = 250
    budget_recent_turns: int = 700
    budget_memories: int = 600
    budget_evidence: int = 300
    recent_turn_window: int = 6
    activation_gamma: float = 0.7
    activation_evict: float = 0.15
    bridge_turns: int = 3

    # --- Episode boundaries ------------------------------------------------
    boundary_threshold: float = 0.55
    soft_boundary_threshold: float = 0.42
    boundary_gap_minutes: float = 30.0
    min_episode_turns: int = 2

    # --- Extraction batching -----------------------------------------------
    extraction_batch_size: int = 4

    subject_aliases: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "mathematics": ["math", "maths", "mathematics", "calculus", "algebra", "geometry",
                            "probability", "statistics", "derivative", "integral", "matrix", "theorem"],
            "physics": ["physics", "mechanics", "thermodynamics", "electromagnetism", "quantum"],
            "chemistry": ["chemistry", "organic", "reaction", "molecule"],
            "programming": ["programming", "coding"],
        }
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
