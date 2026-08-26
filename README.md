# Zenith

Zenith is a local-first Markdown knowledge index. Markdown remains the source of
truth and is mounted read-only; Qdrant is the sole derived datastore.

## Phase 1 commands

```bash
uv sync --dev
uv run pytest
docker compose config
docker compose build
docker compose run --rm model-prefetch
docker compose up -d
docker compose ps
```

Parse the mounted vault once or watch it recursively with debounced Watchdog
events:

```bash
docker compose exec zenith zenith parse
docker compose exec zenith zenith watch
```

Build the complete derived index through a temporary collection, atomically
activate it through the configured alias, and inspect its schema:

```bash
docker compose exec zenith zenith index rebuild
docker compose exec zenith zenith index update
docker compose exec zenith zenith index inspect
```

A failed rebuild leaves the active alias unchanged and removes its incomplete
temporary collection.

Phase 6 adds two library operations over that active index:

```python
from zenith import Zenith

api = Zenith(settings)
context = api.expand_context(entry_id)
graph = api.export_graph()
```

Context expansion follows resolved outgoing links and backlinks with a default
depth of one, a hard maximum depth of two, and at most five linked notes. Each
returned item is labeled as direct evidence, followed-link context, backlink
context, or nearby history. Graph export is deliberately unbounded and emits
deterministically ordered note nodes plus internal-link, shared-tag, and exact
shared-date edges.

## Entry size and the encoder window

The pinned dense model accepts 128 input tokens and truncates the rest without
reporting it. Zenith therefore splits any section, preamble, or headless note
whose content would overrun that window into several entries, cutting only on
paragraph boundaries. Each piece keeps the heading, heading path, entry type,
and entry date of the section it came from, so chronology and evidence stay
intact.

The parser budgets tokens with a calibrated, dependency-free estimate so that
parsing stays hermetic and entry identifiers never depend on whether a model is
present. The estimate deliberately over-counts ordinary prose, which means a
section can split slightly earlier than strictly necessary.

Two cases cannot be divided: a single paragraph larger than the window, and a
Kanban card, which is one atomic point. Both emit a
`truncated_embedding_input` warning instead of losing text silently. Set
`ZENITH_DENSE_TOKEN_WINDOW` to match a different dense model.

## Kanban card dates

Kanban cards carry dates like every other entry type. Zenith reads the Obsidian
Kanban date annotation from card text and stores it as the card's `entry_date`,
so a date query returns cards next to daily sections and project updates:

```markdown
- [ ] Buy saffron @{2026-05-12}
- [x] Finished kitchen setup @{2026-08-20} @@{14:30}
- [ ] Dated by daily-note link @[[2026-08-20]]
```

Zenith records the date only. It does not decide whether a date means due,
scheduled, or done, because the plugin does not record that either. Every card
payload already carries `board.checked` and `board.status`, so a caller can
read that meaning from the board's own state.

The `@` and `@@` triggers come from the board's `kanban:settings` block when it
sets `date-trigger` or `time-trigger`, and fall back to the plugin defaults. The
time is kept as `board.card_time`. A date that is not a real calendar date
raises an `invalid_date` warning and dates nothing. A card carrying more than
one date warns and keeps the first.

The annotation never reaches the searchable text or the embedding input, so
plugin syntax cannot pollute BM25 terms or dense vectors. `@[[2026-08-20]]` is
read as a date, not as a link to a note named `2026-08-20`.

## Library and CLI

Phase 7 exposes the index as one composable `Zenith` library object and a
machine-readable JSON CLI. The library supports entry search, note and entry
lookup, outgoing links, backlinks, link resolution, note-scoped search,
bounded context expansion, warnings, Kanban operations, graph export, and
full or incremental reindexing.

The complete command, option, response-schema, exit-code, and Python API
reference is in [docs/cli-reference.md](docs/cli-reference.md).

Representative CLI commands:

```bash
docker compose exec zenith zenith index init
docker compose exec zenith zenith search "fried chicken" --mode literal
docker compose exec zenith zenith note get "News Resolution"
docker compose exec zenith zenith links backlinks NOTE_ID
docker compose exec zenith zenith context ENTRY_ID
docker compose exec zenith zenith warnings --type missing_link
docker compose exec zenith zenith kanban find --checked false
docker compose exec zenith zenith graph export
docker compose exec zenith zenith diagnose
```

Successful commands return JSON and exit zero. Invalid input or missing and
ambiguous identifiers return a JSON error on stderr with a nonzero exit code.

After model prefetch, the application health endpoint is available inside the
Compose network and the Qdrant dashboard is available at
<http://localhost:6333/dashboard>.

Deployment settings are documented in `.env`. To use a real vault, set
`ZENITH_VAULT_PATH` there to an absolute host path. The Compose mount remains
read-only. `.env.example` is the shareable template.

Architecture and phased acceptance criteria are documented in
`architecture-final.md` and `implementation-plan-final.md`.
