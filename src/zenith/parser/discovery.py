"""Vault discovery and the only path-based note classification rules."""

from __future__ import annotations

from pathlib import Path

from zenith.core.config import Settings
from zenith.core.contracts import NoteType
from zenith.core.identity import normalize_vault_path


def classify_path(relative_path: str, settings: Settings) -> NoteType:
    parts = Path(normalize_vault_path(relative_path)).parts
    root = parts[0].casefold() if len(parts) > 1 else ""
    if root == settings.log_root.casefold():
        return NoteType.LOG
    if root == settings.kanban_root.casefold():
        return NoteType.KANBAN
    return NoteType.STANDARD


def discover_markdown(settings: Settings, requested: list[str] | None = None) -> tuple[Path, ...]:
    vault = settings.vault_path.resolve()
    excluded = {name.casefold() for name in settings.excluded_directories}
    if requested:
        candidates = [vault / normalize_vault_path(path) for path in requested]
    else:
        candidates = list(vault.rglob("*.md"))

    discovered: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            relative = resolved.relative_to(vault)
        except ValueError as exc:
            raise ValueError(f"path escapes vault: {candidate}") from exc
        if resolved.suffix.casefold() != ".md" or not resolved.is_file():
            continue
        if any(part.casefold() in excluded for part in relative.parts[:-1]):
            continue
        discovered.append(resolved)
    return tuple(sorted(set(discovered), key=lambda path: path.relative_to(vault).as_posix().casefold()))
