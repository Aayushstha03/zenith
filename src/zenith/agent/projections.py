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

# Most entries fit the dense token window, but `pack` deliberately emits a
# single paragraph larger than the budget rather than cutting a sentence in
# half, so an entry can still overrun this. A whole note has no bound at all.
MAX_ENTRY_CHARS = 1200
MAX_NOTE_CHARS = 12000


def entry(result: SearchResult, *, match: str | None = None) -> dict[str, Any]:
    """Project one search result down to what an answer needs to cite it.

    `match` is the literal phrase a caller verified. Clipping is centred on it,
    so an entry too large to send whole still carries the evidence for its own
    verification instead of an unrelated opening paragraph.
    """
    text, truncated = _clip(result.text, MAX_ENTRY_CHARS, match=match)
    date, date_kind = _date(result)
    # Citation fields lead. A model reads a result in key order and cites the
    # first identifier it meets, so `entry_id` sitting first got printed as the
    # citation. It is an argument for `expand_context`, not something to show a
    # reader, so it goes last.
    projected: dict[str, Any] = {
        "note": result.note_title,
        "heading": result.heading,
        "lines": f"{result.start_line}-{result.end_line}",
        "path": result.path,
        "date": date,
        "date_kind": date_kind,
        "tags": list(result.tags),
        "text": text,
        "entry_id": result.entry_id,
    }
    if truncated:
        projected["text_truncated"] = True
    # Only literal retrieval verifies an exact phrase. Similarity never does,
    # and must never be reported as if it had. Neither may a clipped body that
    # no longer contains the phrase: the model would be told the wording is
    # proven while holding text that does not show it.
    if result.verified is not None and (
        not result.verified or not truncated or _contains(text, match)
    ):
        projected["exact_match_verified"] = result.verified
    if result.board is not None:
        projected["task"] = {
            "board": result.note_title,
            "column": result.board.column,
            "status": result.board.status,
            "checked": result.board.checked,
        }
    return projected


def entries(
    results: tuple[SearchResult, ...], *, match: str | None = None
) -> list[dict[str, Any]]:
    return [entry(result, match=match) for result in results]


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


def _contains(text: str, match: str | None) -> bool:
    return bool(match) and match.casefold() in text.casefold()


def _clip(text: str, limit: int, *, match: str | None = None) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    start = 0
    if match:
        found = text.casefold().find(match.casefold())
        if found >= 0:
            # Centre the window on the phrase, then pull it back inside the text.
            start = max(0, min(found - (limit - len(match)) // 2, len(text) - limit))
    clipped = text[start : start + limit].strip()
    prefix = "[... truncated]\n" if start else ""
    return f"{prefix}{clipped}\n[... truncated]", True
