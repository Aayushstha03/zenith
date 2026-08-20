"""Deterministic vault-wide internal-link resolution."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from pathlib import PurePosixPath
import unicodedata

from zenith.core.contracts import (
    IndexWarning,
    Link,
    LinkResolution,
    ParsedEntry,
    ParsedNote,
    WarningType,
)


def resolve_links(notes: tuple[ParsedNote, ...]) -> tuple[ParsedNote, ...]:
    by_name: defaultdict[str, list[ParsedNote]] = defaultdict(list)
    by_path: dict[str, ParsedNote] = {}
    for note in notes:
        path = _key(PurePosixPath(note.path).with_suffix("").as_posix())
        by_path[path] = note
        names = {PurePosixPath(note.path).stem, note.title, *_aliases(note)}
        for name in names:
            if name.strip():
                by_name[_key(name)].append(note)

    return tuple(_resolve_note(note, by_name, by_path) for note in notes)


def _resolve_note(
    note: ParsedNote,
    by_name: dict[str, list[ParsedNote]],
    by_path: dict[str, ParsedNote],
) -> ParsedNote:
    warnings = list(note.warnings)
    entries: list[ParsedEntry] = []
    for entry in note.entries:
        links: list[Link] = []
        for link in entry.outgoing_links:
            candidates = _candidates(link.target_text, by_name, by_path)
            if len(candidates) == 1:
                links.append(
                    replace(
                        link,
                        target_note_id=candidates[0].note_id,
                        resolution=LinkResolution.RESOLVED,
                    )
                )
            elif len(candidates) > 1:
                links.append(replace(link, resolution=LinkResolution.AMBIGUOUS))
                warnings.append(
                    IndexWarning(
                        WarningType.AMBIGUOUS_LINK,
                        note.path,
                        f"ambiguous internal link: [[{link.target_text}]]",
                        link.line,
                    )
                )
            else:
                links.append(replace(link, resolution=LinkResolution.MISSING))
                warnings.append(
                    IndexWarning(
                        WarningType.MISSING_LINK,
                        note.path,
                        f"missing internal link: [[{link.target_text}]]",
                        link.line,
                    )
                )
        entries.append(replace(entry, outgoing_links=tuple(links)))
    return replace(note, entries=tuple(entries), warnings=tuple(_dedupe(warnings)))


def _candidates(
    target: str,
    by_name: dict[str, list[ParsedNote]],
    by_path: dict[str, ParsedNote],
) -> list[ParsedNote]:
    normalized = target.strip().replace("\\", "/")
    without_suffix = normalized[:-3] if normalized.casefold().endswith(".md") else normalized
    if "/" in without_suffix:
        match = by_path.get(_key(without_suffix.strip("/")))
        return [match] if match is not None else []
    unique = {note.note_id: note for note in by_name.get(_key(without_suffix), [])}
    return sorted(unique.values(), key=lambda note: note.path.casefold())


def _aliases(note: ParsedNote) -> tuple[str, ...]:
    metadata = note.metadata or {}
    raw = metadata.get("aliases", metadata.get("alias", ()))
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list):
        return tuple(item for item in raw if isinstance(item, str))
    return ()


def _key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold().strip()


def _dedupe(warnings: list[IndexWarning]) -> list[IndexWarning]:
    result: list[IndexWarning] = []
    seen: set[tuple[object, ...]] = set()
    for warning in warnings:
        key = (warning.kind, warning.path, warning.message, warning.line)
        if key not in seen:
            seen.add(key)
            result.append(warning)
    return result
