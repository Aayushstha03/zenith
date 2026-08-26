"""Specialized `/kanban` parsing layered on the CommonMark AST."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from markdown_it.token import Token

from zenith.core.config import Settings
from zenith.core.contracts import (
    EntryType,
    IndexWarning,
    KanbanData,
    NoteType,
    ParsedEntry,
    SourceRange,
    WarningType,
)
from zenith.core.identity import entry_id
from zenith.parser.tokens import estimate_tokens
from zenith.parser.markdown import Frontmatter, Heading, meaningful_line_range, prose_between


CARD_RE = re.compile(r"^- \[([ xX])\]\s+(.*)$")
SETTINGS_START_RE = re.compile(r"^%%\s*kanban:settings\s*$")
STATUS_ALIASES = {
    "todo": {"todo", "to do", "backlog"},
    "doing": {"doing", "in progress", "active"},
    "complete": {"complete", "completed", "done"},
}


def canonical_status(column: str) -> str | None:
    normalized = " ".join(column.casefold().split())
    return next((status for status, aliases in STATUS_ALIASES.items() if normalized in aliases), None)


def parse_settings(lines: list[str], path: str) -> tuple[dict[str, Any] | None, IndexWarning | None, int | None]:
    start = next((index for index, line in enumerate(lines) if SETTINGS_START_RE.fullmatch(line.strip())), None)
    if start is None:
        return None, None, None
    fence_start = next((index for index in range(start + 1, len(lines)) if lines[index].strip() == "```json"), None)
    fence_end = (
        next((index for index in range(fence_start + 1, len(lines)) if lines[index].strip() == "```"), None)
        if fence_start is not None
        else None
    )
    if fence_start is None or fence_end is None:
        warning = IndexWarning(WarningType.INVALID_KANBAN_SETTINGS, path, "Kanban settings block is incomplete", start + 1)
        return None, warning, start
    try:
        value = json.loads("\n".join(lines[fence_start + 1 : fence_end]))
    except json.JSONDecodeError as exc:
        warning = IndexWarning(WarningType.INVALID_KANBAN_SETTINGS, path, f"invalid Kanban settings JSON: {exc.msg}", fence_start + 2)
        return None, warning, start
    return value, None, start


def parse_kanban_entries(
    *,
    lines: list[str],
    tokens: list[Token],
    parsed_headings: tuple[Heading, ...],
    frontmatter: Frontmatter,
    path: str,
    title: str,
    note_uuid: str,
    settings: Settings,
) -> tuple[tuple[ParsedEntry, ...], tuple[IndexWarning, ...], dict[str, Any]]:
    warnings: list[IndexWarning] = []
    if frontmatter.values.get("kanban-plugin") != "board":
        warnings.append(IndexWarning(WarningType.MISSING_KANBAN_MARKER, path, "Kanban note is missing `kanban-plugin: board`"))
    plugin_settings, settings_warning, settings_start = parse_settings(lines, path)
    if settings_warning:
        warnings.append(settings_warning)

    columns = [heading for heading in parsed_headings if heading.level == 2]
    entries: list[ParsedEntry] = []
    for column_position, column in enumerate(columns):
        column_start = column.content_start
        column_end = column.content_end
        if settings_start is not None:
            column_end = min(column_end, settings_start)
        cards = [
            (line_index, match)
            for line_index in range(column_start, column_end)
            if (match := CARD_RE.match(lines[line_index])) is not None
        ]
        for card_position, (line_index, match) in enumerate(cards):
            next_card = cards[card_position + 1][0] if card_position + 1 < len(cards) else column_end
            prose = prose_between(
                tokens, line_index, next_card, path, settings.known_tags, settings.tag_aliases
            )
            visible = re.sub(r"^\[[ xX]\]\s*", "", prose.text).strip()
            if not visible:
                visible = match.group(2).strip()
            structural_key = f"{column.text}/{card_position}:{visible.casefold()}"
            card_id = str(entry_id(note_uuid, EntryType.KANBAN_CARD, structural_key))
            body_range = meaningful_line_range(lines, line_index, next_card)
            entries.append(
                ParsedEntry(
                    entry_id=card_id,
                    note_id=note_uuid,
                    path=path,
                    note_title=title,
                    note_type=NoteType.KANBAN,
                    entry_type=EntryType.KANBAN_CARD,
                    text=visible,
                    embedding_text=(
                        f"Board: {title}\nColumn: {column.text}\n"
                        f"Status: {canonical_status(column.text) or 'custom'}\nTask: {visible}"
                    ),
                    heading=column.text,
                    heading_path=column.path,
                    source=SourceRange(line_index + 1, body_range.end_line if body_range else line_index + 1),
                    tags=prose.tags,
                    outgoing_links=prose.links,
                    web_links=prose.web_links,
                    content_hash=hashlib.sha256(visible.encode("utf-8")).hexdigest(),
                    kanban=KanbanData(
                        name=title,
                        column=column.text,
                        status=canonical_status(column.text),
                        column_position=column_position,
                        card_position=card_position,
                        checked=match.group(1).casefold() == "x",
                    ),
                )
            )
            warnings.extend(prose.warnings)
            # A card is one atomic point, so it is never divided. When its text
            # overruns the encoder the only honest signal is a warning.
            cost = estimate_tokens(entries[-1].embedding_text)
            if cost > settings.dense_token_window:
                warnings.append(
                    IndexWarning(
                        WarningType.TRUNCATED_EMBEDDING_INPUT,
                        path,
                        f"Kanban card needs about {cost} tokens but only "
                        f"{settings.dense_token_window} reach the dense model; a card is never "
                        "divided, so the rest is not semantically searchable",
                        line_index + 1,
                    )
                )
    metadata = {"kanban_settings": plugin_settings, "columns": [column.text for column in columns]}
    return tuple(entries), tuple(warnings), metadata
