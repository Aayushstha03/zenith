# Known Issues and Deferred Work

This file tracks known gaps that are not blocking, with the reasoning behind
the deferral. Add a dated entry when you find something worth remembering but
not worth fixing now.

## 2026-08-20 — Literal and metadata retrieval scan the full filtered match set

**Where:** `src/zenith/retrieval/service.py`, `Retriever._literal` and
`Retriever._metadata`, via the shared `_scroll_all` helper.

**What:** Both modes paginate every point that matches the plan's structural
filter (`vault_id` plus any note/tag/date/kanban/entry-type filters) before
doing anything else. Literal mode then runs an exact, case-insensitive,
contiguous-phrase check against `payload["text"]` in Python. Metadata mode
sorts the fetched set by `(path, start_line)` and slices to `limit`.

**Why this is fine for now:** The fixture vault and any small personal vault
scan in well under a second. Qdrant's own `order_by` only sorts on one
indexed field, and metadata mode's ordering is a compound key
`(path, start_line)`, so a full-fetch-then-sort-then-slice is the pragmatic
shape for that mode regardless of vault size. Metadata mode is also meant for
narrow, already-filtered lookups (`get_note`, `get_entry` in Phase 7), not
open-ended browsing.

**Where it gets real:** Literal mode with few or no other filters, on a
multi-year real vault. The match set becomes "the whole vault," and every
literal query pays for a full scroll of it.

**The fix, when it's worth doing:** `text` already has a Qdrant `TEXT`
payload index declared in `src/zenith/index/schema.py`, currently unused.
Add a `MatchText` condition on the literal query as a server-side pre-filter
before `_scroll_all`, narrowing what gets fetched. Keep the Python exact
check afterward unchanged — Qdrant's text index is not phrase- or
order-aware, so it cannot replace the verification step, only narrow the
candidates in front of it. Estimated at roughly 10 lines in
`Retriever._literal`. No correctness change expected; worst case (a very
short or common query word) it narrows nothing and behavior matches today.

**Decision:** Deferred. Revisit during Phase 9 real-vault validation, when
actual scan cost on a real vault can be measured instead of guessed.
