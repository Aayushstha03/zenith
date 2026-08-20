# Markdown Knowledge Index: Final Architecture

## 1. Architecture Decision

Use Qdrant as the single derived search index for the Markdown vault.

The complete system is deployed through one Docker Compose project containing:

- A Python application container for parsing, indexing, embedding, querying, and the agent-facing API.
- A Qdrant container for all derived storage and retrieval.
- A persistent Qdrant data volume.
- A persistent model-cache volume.
- A read-only bind mount of the Markdown vault into the application container.

Qdrant runs only on the local machine. Its REST API and bundled dashboard are
bound to localhost on port `6333`; its gRPC port remains internal unless a
measured requirement justifies exposing it.

```text
Markdown vault (source of truth)
        |
        v
Deterministic parser and indexer
        |
        v
Qdrant
  - JSON payload metadata
  - dense semantic vectors
  - sparse BM25 vectors
        |
        v
Query and agent service
  - structured filtering
  - lexical search
  - semantic search
  - hybrid ranking
  - bounded link traversal
```

This supersedes the earlier SQLite-first storage proposal. SQLite and FTS5 are
not part of this architecture; Qdrant is the sole derived datastore.

Markdown files remain authoritative. Qdrant is disposable derived data and must be fully rebuildable without modifying the vault.

## 1.1 Encoding Decision

The Python application generates both vector representations locally with
FastEmbed and sends ordinary vectors to Qdrant. Qdrant does not own model
inference in the initial implementation.

- Dense vector name: `semantic`.
- Dense model: `sentence-transformers/all-MiniLM-L6-v2`.
- Dense dimensions: 384.
- Dense distance: cosine.
- Sparse vector name: `text-bm25`.
- Sparse model: `Qdrant/bm25`.
- Sparse language processing: English stemming and stopwords.
- Sparse collection modifier: Qdrant IDF.
- Initial hybrid fusion: reciprocal-rank fusion in Qdrant.

Model names, revisions, tokenizer options, and embedding-input versions are
pinned and recorded. Models are prefetched into a persistent Docker volume so
normal operation can run without network access.

## 2. Responsibilities

### Markdown parser and indexer

The application is responsible for:

- Discovering Markdown files.
- Parsing Markdown with a CommonMark-compatible AST.
- Recognizing log notes, standard open notes, and Kanban boards. Only the
  configured `/logs` and `/kanban` roots carry path semantics.
- Extracting sections, dated entries, Kanban cards, tags, links, and source lines.
- Resolving internal links.
- Validating the fixed tag pool.
- Normalizing dates and Kanban statuses.
- Assigning stable identifiers.
- Creating dense embeddings and sparse BM25 representations.
- Upserting changed points and deleting stale points.
- Reporting invalid dates, unknown tags, ambiguous links, and parser failures.

### Qdrant

Qdrant is responsible for:

- Storing searchable entry payloads.
- Metadata indexes and filters.
- Date and date-range queries.
- Tag, note, section, status, and checkbox filters.
- Dense-vector semantic retrieval.
- Sparse-vector BM25 lexical retrieval.
- Hybrid ranking and result fusion.
- Locating outgoing links and backlinks through indexed identifiers.

### Query and agent service

The service is responsible for:

- Translating natural-language requests into explicit query plans.
- Selecting exact, lexical, semantic, or hybrid search.
- Applying metadata filters.
- Verifying strict literal matches.
- Following links within a traversal budget.
- Separating direct evidence, related context, and inference.
- Returning source paths, heading paths, dates, and line ranges.

## 3. Searchable Unit

Create one Qdrant point for each independently searchable unit:

- `daily_section`: a section within a dated daily note.
- `project_update`: content under a date heading in a long-running project note.
- `freeform_section`: an ordinary heading-delimited section.
- `freeform_chunk`: a paragraph-aware subdivision of oversized or unstructured content.
- `kanban_card`: an individual task card in a Kanban column.

Do not use one point per whole file as the primary search representation. Section- and card-level points produce more precise results, embeddings, metadata filters, and citations.

Whole-note identity is carried in every point payload.

## 4. Qdrant Collection Model

Use one collection for all searchable entries unless scale or access-control requirements later justify separation.

Each point contains:

- A stable point ID.
- A named dense vector called `semantic`.
- A named sparse vector called `text-bm25`.
- A structured JSON payload.

Example:

```json
{
  "id": "stable-entry-uuid",
  "vector": {
    "semantic": [0.012, 0.935],
    "text-bm25": {
      "indices": [],
      "values": []
    }
  },
  "payload": {
    "schema_version": 1,
    "parser_version": "1.0.0",
    "embedding_model": "configured-model-name",

    "vault_id": "personal",
    "note_id": "news-resolution",
    "entry_id": "stable-entry-uuid",
    "path": "projects/News Resolution.md",
    "note_title": "News Resolution",
    "note_type": "standard",
    "entry_type": "project_update",

    "text": "Tracing the pipeline and investigating clustering...",
    "heading": "2026-08-19",
    "heading_path": ["News Resolution", "2026-08-19"],
    "start_line": 3,
    "end_line": 5,

    "note_date": null,
    "entry_date": "2026-08-19T00:00:00Z",
    "tags": ["work"],

    "outgoing_note_ids": [],
    "outgoing_links": [],
    "web_links": [],

    "content_hash": "sha256-value",
    "modified_at": "2026-08-20T12:00:00Z"
  }
}
```

## 5. Stable Identity

Generate deterministic IDs from stable logical inputs.

Recommended note ID input:

```text
vault_id + normalized vault-relative path
```

Recommended entry ID input:

```text
note_id + entry type + structural identity
```

Structural identity may use heading path, source order, and a content fingerprint. Renames and heading changes require reconciliation logic if preserving point identity is important.

Upserts must be idempotent. After indexing a note, delete prior points for that `note_id` that were not emitted by the current parse.

## 6. Payload Fields and Indexes

Create payload indexes for frequently filtered fields:

| Payload field | Index type | Purpose |
| --- | --- | --- |
| `vault_id` | keyword | Vault isolation |
| `note_id` | keyword | Within-note search |
| `path` | keyword | Exact path lookup |
| `note_title` | keyword | Note resolution |
| `note_type` | keyword | Log/standard/Kanban filtering |
| `entry_type` | keyword | Search-unit filtering |
| `note_date` | datetime | Daily-note lookup and ranges |
| `entry_date` | datetime | Project-update lookup and ranges |
| `tags` | keyword | Fixed-pool tag filtering |
| `outgoing_note_ids` | keyword | Backlink queries |
| `text` | text | Full-text filtering |
| `board.name` | keyword | Board lookup |
| `board.column` | keyword | Raw Kanban column filtering |
| `board.status` | keyword | Canonical Kanban status filtering |
| `board.checked` | bool | Completion filtering |
| `modified_at` | datetime | Maintenance and diagnostics |

Only index payload fields used in filtering or lookup. Keep display-only metadata in the payload without unnecessary indexes.

## 7. Parsing Rules

### Markdown structure

Use a Markdown AST to distinguish:

- `# Heading` from `#tag`.
- Prose from inline and fenced code.
- Internal links from web links.
- Heading hierarchy and section boundaries.
- Task-list items and nested content.

Tags are extracted only from eligible prose nodes and validated against the configured fixed tag pool.

### Log notes

Files whose first vault-relative path segment is the configured `/logs` root use
log semantics. Resolve the note date from the configured filename convention,
falling back to the first non-empty line when allowed.

Each meaningful section becomes a `daily_section` point. Inline tags and links attach to the smallest containing section.

### Standard open notes

Every Markdown file outside `/logs` and `/kanban` is a standard note, regardless
of its directory, nesting, filename, or layout. A standard note may mix dated
project updates, ordinary sections, and loose chunks.

A heading consisting solely of a recognized date establishes `entry_date` for
the structurally governed content. Each dated block becomes a `project_update`
point.

Undated material remains searchable as `freeform_section` content and must not inherit dates through proximity or links.

Ordinary headings create `freeform_section` entries. Loose content before or
between useful headings, and notes without headings, create paragraph-aware
`freeform_chunk` entries. Directory names such as `projects`, `work`, or
`archive` have no classification meaning.

### Kanban boards

Files beneath the configured `/kanban` directory receive a specialized parsing pass.

- `kanban-plugin: board` confirms the format.
- The filename stem is the default board name.
- H2 headings are ordered columns.
- Direct checkbox-list children are ordered cards.
- Checkbox state is stored independently from column status.
- Nested list items and paragraphs belong to their parent card.
- Non-card decorations are not cards.
- Plugin settings are stored as metadata and excluded from search text and embeddings.

Each card becomes a `kanban_card` point with additional payload:

```json
{
  "board": {
    "name": "Kitchen App",
    "column": "Doing",
    "status": "doing",
    "column_position": 1,
    "card_position": 0,
    "checked": false
  }
}
```

## 8. Date Semantics

Keep different date meanings separate:

- `note_date`: date represented by a daily note.
- `entry_date`: date explicitly assigned to a project update or entry.
- `modified_at`: filesystem modification timestamp.
- Mentioned dates: optional extracted metadata that does not establish chronology.

Normalize queryable dates to UTC datetime values while preserving the original text if needed for display.

An internal link from a dated entry does not transfer its date to the target note.

Answers must distinguish:

- Directly dated evidence.
- A target linked on the requested date.
- Nearby dated history in the target project.
- Agent inference.

## 9. Internal Links and Backlinks

Support:

```markdown
[[Note]]
[[Note|label]]
[[Note#Heading]]
[[Note#Heading|label]]
```

Resolve targets during indexing and store both the original link and resolved identifiers:

```json
{
  "outgoing_note_ids": ["news-resolution"],
  "outgoing_links": [
    {
      "target_text": "News Resolution",
      "target_note_id": "news-resolution",
      "target_heading": null,
      "alias": null,
      "resolution_status": "resolved"
    }
  ]
}
```

A backlink query filters points whose `outgoing_note_ids` contains the target note ID.

Graph traversal is performed by the application:

```text
retrieve source entry
-> inspect outgoing note IDs
-> retrieve target note
-> search within target note ID
-> optionally inspect one more hop
```

Default traversal limits:

- Depth: 1.
- Maximum depth: 2.
- Maximum linked notes inspected: 5.
- Nearby project-history window: plus or minus 3 days.

## 10. Retrieval Modes

### Metadata lookup

Use payload filters for exact structured conditions:

- A single date or date range.
- One or more tags.
- Exact note ID or path.
- Entry type or section.
- Kanban board, column, status, or checkbox state.
- Entries linking to a target note.

### Lexical search

Use the `text-bm25` sparse vector for ranked word-based retrieval. BM25 is appropriate for keywords and ordinary text queries.

BM25 tokenization, stemming, and stopword behavior must be explicitly configured and versioned.

### Strict literal search

Do not equate BM25 with character-for-character matching.

For a quoted phrase or strict substring request:

1. Retrieve candidates with BM25 or a text payload filter.
2. Verify the literal query against the original `text` payload.
3. If source fidelity matters, verify it against the cited file lines.

Case sensitivity and Unicode normalization must be explicit query options.

### Semantic search

Embed the query with the same model used at ingestion and search the named `semantic` vector.

Semantic retrieval finds conceptually related passages even when the wording differs.

### Hybrid search

For general natural-language questions:

1. Apply hard metadata filters.
2. Prefetch dense semantic results.
3. Prefetch sparse BM25 results.
4. Fuse rankings with reciprocal-rank fusion.
5. Expand through relevant links only when useful.

## 11. Example Queries

### What was I doing on 27 July 2026?

```text
filter:
  note_date = 2026-07-27 OR entry_date = 2026-07-27

retrieval:
  BM25("work progress doing")
  + semantic("what I was working on")

expansion:
  follow relevant direct links with depth 1
```

### Find clustering within News Resolution

```text
filter:
  note_id = news-resolution

retrieval:
  BM25("clustering")
```

### Find the exact phrase "status loops"

```text
candidate retrieval:
  BM25("status loops")

verification:
  literal phrase exists in payload text
```

### What unfinished Kanban tasks concern food expiration?

```text
filter:
  entry_type = kanban_card
  board.checked = false
  board.status IN [todo, doing]

retrieval:
  BM25("food expiration")
  + semantic("food going bad or expiring")
```

### Open a daily note, follow its project link, and search there

```text
filter daily sections by note_date
-> retrieve outgoing_note_ids
-> resolve selected project note_id
-> run constrained hybrid search where note_id = target
```

## 12. Embedding Input

Embed searchable content with enough structural context to disambiguate it.

Daily section:

```text
Note: 2026-08-20
Section: Thoughts
Tags: journal
Content: today was good, i worked and felt very productive
```

Project update:

```text
Project: News Resolution
Date: 2026-08-19
Content: Tracing the flow of the pipeline...
```

Kanban card:

```text
Board: Kitchen App
Column: ToDo
Status: todo
Task: Add items to shopping list if needed for recipe
```

Do not embed:

- Kanban settings JSON.
- Raw frontmatter by itself.
- Checkbox syntax.
- Empty headings.
- Decorative labels.
- Duplicate whole-note content when its entries are already embedded.

Store raw text independently from contextual embedding input.

## 13. Query API

Expose narrow operations:

```text
reindex(paths?, full=false)

find_entries(
  date_from?,
  date_to?,
  tags_all?,
  tags_any?,
  note?,
  section?,
  entry_types?,
  exact_text?,
  semantic_text?,
  limit?
)

get_note(path_or_title)
get_entry(entry_id)
get_outgoing_links(note_id, entry_id?)
get_backlinks(note_id)
resolve_link(source_note_id, target_text)
search_within(note_id, query, mode, section?)
expand_context(entry_id, link_depth=1, nearby_days=3, max_notes=5)

list_kanban_boards()
get_kanban_board(board_name_or_path)
find_kanban_cards(
  board?,
  columns?,
  statuses?,
  checked?,
  tags?,
  exact_text?,
  semantic_text?,
  limit?
)
```

Natural-language requests must compile to an inspectable structured query plan before execution.

## 14. Incremental Indexing

For each file:

1. Compute a content hash.
2. Skip unchanged files when parser and model versions also match.
3. Parse changed content.
4. Resolve links against the current vault catalog.
5. Reuse embeddings for unchanged entries when possible.
6. Generate dense and sparse representations for changed entries.
7. Upsert the current point set.
8. Delete stale points formerly associated with the note.
9. Record warnings and completion state.

Use a filesystem watcher with debouncing, plus a deterministic full rebuild command.

Re-resolve links when target notes are added, removed, renamed, or given new aliases.

## 15. Reliability Rules

- Never modify Markdown during indexing.
- Treat the Qdrant collection as rebuildable derived data.
- Keep parser, payload-schema, tokenizer, BM25, and embedding-model versions.
- Use deterministic point IDs and idempotent upserts.
- Do not silently resolve ambiguous note titles.
- Do not infer dates from links.
- Do not infer Kanban status solely from checkbox state.
- Do not return semantic similarity as proof of an exact phrase.
- Always retain paths, heading paths, and source line ranges.
- Bound all automatic link traversal.

## 16. Definition of Done

The architecture is implemented when the system can:

1. Rebuild Qdrant entirely from the Markdown vault.
2. Incrementally update changed, renamed, added, and deleted notes.
3. Parse daily sections, project updates, freeform content, and Kanban cards.
4. Filter by dates, ranges, tags, note identity, entry type, and Kanban state.
5. Perform BM25 lexical search and dense semantic search.
6. Fuse lexical and semantic results under metadata filters.
7. Verify strict literal phrase requests against original text.
8. Resolve internal links and find backlinks.
9. Follow a bounded chain from a daily entry to a linked note and search within it.
10. Return evidence with path, heading path, date, and line range.
11. Clearly distinguish directly dated evidence, linked context, nearby history, and inference.
