"""Deterministic vault-wide internal-link resolution."""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from dataclasses import replace
from pathlib import PurePosixPath

from zenith.core.contracts import (
    IndexWarning,
    Link,
    LinkResolution,
    ParsedEntry,
    ParsedNote,
    WarningType,
)


def resolve_links(notes: tuple[ParsedNote, ...]) -> tuple[ParsedNote, ...]:
    by_name, by_path = _catalog(notes)
    return tuple(_resolve_note(note, by_name, by_path) for note in notes)


def resolve_link(
    notes: tuple[ParsedNote, ...], source_note_id: str, target_text: str
) -> Link:
    if not any(note.note_id == source_note_id for note in notes):
        raise LookupError(f"source note not found: {source_note_id}")
    raw = target_text.strip()
    if raw.startswith("[[") and raw.endswith("]]"):
        raw = raw[2:-2].strip()
    destination, alias_separator, alias = raw.partition("|")
    target, separator, heading = destination.partition("#")
    if not target.strip():
        raise ValueError("target_text must name a note")
    by_name, by_path = _catalog(notes)
    candidates = _candidates(target, by_name, by_path)
    if len(candidates) == 1:
        return Link(
            target_text=target.strip(),
            target_note_id=candidates[0].note_id,
            target_heading=heading.strip() if separator and heading.strip() else None,
            alias=alias.strip() if alias_separator and alias.strip() else None,
            resolution=LinkResolution.RESOLVED,
        )
    return Link(
        target_text=target.strip(),
        target_heading=heading.strip() if separator and heading.strip() else None,
        alias=alias.strip() if alias_separator and alias.strip() else None,
        resolution=(LinkResolution.AMBIGUOUS if candidates else LinkResolution.MISSING),
    )


def _catalog(
    notes: tuple[ParsedNote, ...],
) -> tuple[defaultdict[str, list[ParsedNote]], dict[str, ParsedNote]]:
    by_name: defaultdict[str, list[ParsedNote]] = defaultdict(list)
    by_path: dict[str, ParsedNote] = {}
    for note in notes:
        path = _key(PurePosixPath(note.path).with_suffix("").as_posix())
        by_path[path] = note
        names = {PurePosixPath(note.path).stem, note.title, *_aliases(note)}
        for name in names:
            if name.strip():
                by_name[_key(name)].append(note)
    return by_name, by_path


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
    return replace(note, entries=tuple(entries), warnings=tuple(dict.fromkeys(warnings)))


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
