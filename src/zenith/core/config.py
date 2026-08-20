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


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip().strip("/") for item in os.getenv(name, default).split(",") if item.strip())


def _aliases(name: str, default: str) -> tuple[tuple[str, str], ...]:
    aliases: list[tuple[str, str]] = []
    for item in _csv(name, default):
        alias, separator, canonical = item.partition(":")
        if not separator or not alias.strip() or not canonical.strip():
            raise ValueError(f"{name} entries must use alias:canonical syntax")
        aliases.append((alias.strip().casefold(), canonical.strip().casefold()))
    return tuple(aliases)


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
    log_root: str = "logs"
    kanban_root: str = "kanban"
    excluded_directories: tuple[str, ...] = (".git", ".obsidian", ".trash")
    known_tags: tuple[str, ...] = ("journal", "recipe", "work")
    tag_aliases: tuple[tuple[str, str], ...] = (("journaling", "journal"), ("recipes", "recipe"))

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
            log_root=os.getenv("ZENITH_LOG_ROOT", "logs").strip("/"),
            kanban_root=os.getenv("ZENITH_KANBAN_ROOT", "kanban").strip("/"),
            excluded_directories=_csv("ZENITH_EXCLUDED_DIRECTORIES", ".git,.obsidian,.trash"),
            known_tags=_csv("ZENITH_KNOWN_TAGS", "journal,recipe,work"),
            tag_aliases=_aliases("ZENITH_TAG_ALIASES", "journaling:journal,recipes:recipe"),
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
        if not self.log_root or "/" in self.log_root:
            errors.append("ZENITH_LOG_ROOT must be one root directory name")
        if not self.kanban_root or "/" in self.kanban_root:
            errors.append("ZENITH_KANBAN_ROOT must be one root directory name")
        if self.log_root.casefold() == self.kanban_root.casefold():
            errors.append("log and Kanban roots must differ")
        known = {tag.casefold() for tag in self.known_tags}
        if any(canonical not in known for _, canonical in self.tag_aliases):
            errors.append("every tag alias must target a known canonical tag")
        return tuple(errors)
