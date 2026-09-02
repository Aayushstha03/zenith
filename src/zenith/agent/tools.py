"""The tool surface the answering model is given over the notes vault.

Deliberately narrow. Every tool takes flat arguments, returns a compact
projection, and reports a failure the model can act on rather than raising.
The library keeps the wider surface; `reindex` writes and `export_graph` is
unbounded, so neither is offered here.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from pydantic_ai import ModelRetry, RunContext

from zenith.agent import projections
from zenith.library import Zenith

_ENTRY_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def search_notes(
    ctx: RunContext[Zenith],
    query: str,
    exact: bool = False,
    date_from: str | None = None,
    date_to: str | None = None,
    tags: list[str] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search the notes vault and return the entries that match.

    Args:
        query: What to look for. Plain language works; so does a phrase.
        exact: Return only entries containing the query as a literal phrase.
            Use this when the question depends on the exact wording. Results
            then carry `exact_match_verified`.
        date_from: Earliest date to include, written as YYYY-MM-DD.
        date_to: Latest date to include, written as YYYY-MM-DD.
        tags: Return only entries that carry all of these tags.
        limit: How many entries to return, at most 20.
    """
    with _repair():
        results = ctx.deps.find_entries(
            exact_text=query if exact else None,
            lexical_text=None if exact else query,
            semantic_text=None if exact else query,
            date_from=date_from,
            date_to=date_to,
            tags_all=tuple(tags or ()),
            limit=max(1, min(limit, 20)),
        )
    return projections.entries(results, match=query if exact else None)


def read_note(ctx: RunContext[Zenith], name: str) -> dict[str, Any]:
    """Read one complete note as Markdown.

    Search returns fragments of a note. Read the whole note when the question
    is about the note itself, or when a fragment is not enough to answer it.

    Args:
        name: The note's title, or its path inside the vault. A search result's
            `note` or `path` value works.
    """
    # An `entry_id` reaches here often enough to be worth naming: it is the one
    # identifier every result carries, and the library would only answer "note
    # not found", which does not say what to send instead.
    if _ENTRY_ID.fullmatch(name.strip()):
        raise ModelRetry(
            f"{name!r} is an entry_id, not a note name. Pass the `note` or "
            "`path` value from the same result instead."
        )
    with _repair():
        return projections.note(ctx.deps.read_note(name))


def expand_context(ctx: RunContext[Zenith], entry_id: str) -> dict[str, Any]:
    """Find what surrounds one entry: linked notes, backlinks, nearby days.

    Each returned item is labelled with how it relates to the entry, so an
    answer can separate direct evidence from context that was reached through
    a link or from history that merely happened nearby in time.

    Args:
        entry_id: The `entry_id` of an entry returned by another tool.
    """
    with _repair():
        return projections.context(ctx.deps.expand_context(entry_id))


def find_backlinks(ctx: RunContext[Zenith], name: str) -> list[dict[str, Any]]:
    """Find the entries in other notes that link to this note.

    Use this to learn where a note is referred to, and in what terms.

    Args:
        name: The note's title, or its path inside the vault.
    """
    with _repair():
        note = ctx.deps.get_note(name)
        return projections.entries(ctx.deps.get_backlinks(note.note_id))


def find_tasks(
    ctx: RunContext[Zenith],
    board: str | None = None,
    columns: list[str] | None = None,
    checked: bool | None = None,
    query: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Find task cards on the Kanban boards in the vault.

    Args:
        board: Restrict to one board by name or path. Omit to search them all.
        columns: Restrict to these columns, for example ToDo or Doing. An
            unknown column name is rejected, and the reply names the real ones.
        checked: True for completed cards, False for open cards, omit for both.
        query: Words to search for by meaning. This finds related cards; it
            does not prove any card contains these words.
        limit: How many cards to return, at most 50.
    """
    with _repair():
        results = ctx.deps.find_kanban_cards(
            board=board,
            columns=_columns(ctx, board, columns),
            checked=checked,
            semantic_text=query,
            limit=max(1, min(limit, 50)),
        )
    return projections.entries(results)


def _columns(
    ctx: RunContext[Zenith], board: str | None, requested: list[str] | None
) -> tuple[str, ...]:
    """Resolve column names against the boards, and reject the ones that miss.

    Columns reach Qdrant as a case-sensitive match, so "To Do" against a stored
    "ToDo" silently returns nothing. The model would then report that a board
    has no such cards. A bad board name already fails loudly; a bad column name
    must too, and the failure names the columns that exist.
    """
    if not requested:
        return ()
    boards = (
        (ctx.deps.get_kanban_board(board),) if board else ctx.deps.list_kanban_boards()
    )
    known = {column.casefold(): column for item in boards for column in item.columns}
    unknown = [name for name in requested if name.casefold() not in known]
    if unknown:
        raise ValueError(
            f"unknown Kanban column {', '.join(repr(name) for name in unknown)}; "
            f"this board has {', '.join(sorted(known.values()))}"
        )
    return tuple(known[name.casefold()] for name in requested)


TOOLS = [search_notes, read_note, expand_context, find_backlinks, find_tasks]


@contextmanager
def _repair() -> Iterator[None]:
    """Turn a library error into an instruction the model can act on.

    The library already says what went wrong and, for an ambiguous name, which
    notes it could have meant. `ModelRetry` hands that text back to the model
    so it can correct the call instead of the run failing.
    """
    try:
        yield
    except (LookupError, ValueError) as error:
        raise ModelRetry(str(error)) from error
