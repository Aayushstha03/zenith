"""Typed runtime configuration loaded from environment variables."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


DENSE_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
SPARSE_MODEL = "Qdrant/bm25"


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    qdrant_url: str
    vault_path: Path
    model_cache_path: Path
    collection_name: str
    host: str
    port: int
    dense_model: str = DENSE_MODEL
    sparse_model: str = SPARSE_MODEL

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            qdrant_url=os.getenv("ZENITH_QDRANT_URL", "http://qdrant:6333").rstrip("/"),
            vault_path=Path(os.getenv("ZENITH_VAULT_PATH", "/vault")),
            model_cache_path=Path(os.getenv("ZENITH_MODEL_CACHE_PATH", "/models")),
            collection_name=os.getenv("ZENITH_COLLECTION", "zenith_entries"),
            host=os.getenv("ZENITH_HOST", "0.0.0.0"),
            port=_positive_int("ZENITH_PORT", 8080),
            dense_model=os.getenv("ZENITH_DENSE_MODEL", DENSE_MODEL),
            sparse_model=os.getenv("ZENITH_SPARSE_MODEL", SPARSE_MODEL),
        )

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.qdrant_url.startswith(("http://", "https://")):
            errors.append("ZENITH_QDRANT_URL must use http or https")
        if not self.collection_name.strip():
            errors.append("ZENITH_COLLECTION cannot be empty")
        if not self.vault_path.is_absolute():
            errors.append("ZENITH_VAULT_PATH must be absolute")
        if not self.model_cache_path.is_absolute():
            errors.append("ZENITH_MODEL_CACHE_PATH must be absolute")
        return tuple(errors)
