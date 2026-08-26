"""Compact, model-facing views of Zenith's retrieval contracts.

Library contracts carry everything a caller might need. A language model needs
far less, and every field it does not need costs context it could have spent on
evidence. These functions decide what a tool actually returns.
"""

from __future__ import annotations

from typing import Any

from zenith.core.contracts import (
    ContextExpansion,
    NoteContent,
    SearchResult,
)


# One entry is already bounded by the dense token window, so this cap only
# catches notes that overrun it. A whole note has no such bound.
MAX_ENTRY_CHARS = 1200
MAX_NOTE_CHARS = 12000


def entry(result: SearchResult) -> dict[str, Any]:
    """Project one search result down to what an answer needs to cite it."""
    text, truncated = _clip(result.text, MAX_ENTRY_CHARS)
    date, date_kind = _date(result)
    projected: dict[str, Any] = {
        "entry_id": result.entry_id,
        "note": result.note_title,
        "path": result.path,
        "heading": result.heading,
        "lines": f"{result.start_line}-{result.end_line}",
        "date": date,
        "date_kind": date_kind,
        "tags": list(result.tags),
        "text": text,
    }
    if truncated:
        projected["text_truncated"] = True
    # Only literal retrieval verifies an exact phrase. Similarity never does,
    # and must never be reported as if it had.
    if result.verified is not None:
        projected["exact_match_verified"] = result.verified
    if result.kanban is not None:
        projected["task"] = {
            "board": result.kanban.name,
            "column": result.kanban.column,
            "status": result.kanban.status,
            "checked": result.kanban.checked,
        }
    return projected


def entries(results: tuple[SearchResult, ...]) -> list[dict[str, Any]]:
    return [entry(result) for result in results]


def note(content: NoteContent) -> dict[str, Any]:
    text, truncated = _clip(content.content, MAX_NOTE_CHARS)
    projected: dict[str, Any] = {
        "note": content.title,
        "path": content.path,
        "note_type": str(content.note_type),
        "content": text,
    }
    if truncated:
        projected["content_truncated"] = True
    return projected


def context(expansion: ContextExpansion) -> dict[str, Any]:
    """Project expanded context, keeping every item's evidence label.

    The labels are the point. An answer must say whether a fact is direct
    evidence, something a link led to, or nearby history in another note.
    """
    items = []
    for item in expansion.items:
        projected = entry(item.result)
        projected["evidence"] = [str(label) for label in item.labels]
        projected["hops"] = item.depth
        items.append(projected)
    unresolved = [
        {"target": diagnostic.target_text, "reason": str(diagnostic.resolution)}
        for diagnostic in expansion.diagnostics
    ]
    projected = {"source_entry_id": expansion.source_entry_id, "items": items}
    if unresolved:
        projected["unresolved_links"] = unresolved
    return projected


def _date(result: SearchResult) -> tuple[str | None, str | None]:
    """Report which date an entry carries, and where that date came from.

    An entry date is the date written on the entry. A note date belongs to the
    dated note the entry sits in. An entry with neither is undated, and must
    never be presented as if it happened on any particular day.
    """
    if result.entry_date:
        return result.entry_date, "entry_date"
    if result.note_date:
        return result.note_date, "note_date"
    return None, None


def _clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip() + "\n[... truncated]", True
