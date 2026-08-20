# Markdown Knowledge Index: Final Implementation Plan

## 1. Goal and Frozen Decisions

Build a local, containerized knowledge index for a Markdown vault. Markdown is
the source of truth; Qdrant is the sole derived datastore and is disposable and
rebuildable. The indexer never rewrites the vault.

- Python 3.13 application and Qdrant run in one Docker Compose project.
- Qdrant uses a persistent volume; the vault is mounted read-only.
- The dashboard is available at `http://localhost:6333/dashboard` and bound to
  localhost. Service traffic uses the private Compose network.
- Dense encoding runs in the application with FastEmbed using
  `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions, cosine distance.
- Sparse encoding runs in the application with FastEmbed using `Qdrant/bm25`,
  English stemming and stopwords, plus Qdrant's IDF modifier.
- Dense and sparse candidates are fused in Qdrant with RRF.
- Strict literal requests are verified against original payload text and, when
  authoritative verification is needed, the cited Markdown lines.
- Dates establish chronology only when they are valid calendar dates represented
  by the complete ASCII value `YYYY-MM-DD`; no alternative format is accepted.
- A pinned model-prefetch command populates a persistent model cache so normal
  operation can run offline.
- SQLite, FTS5, cloud inference, hosted embedding APIs, and a separate graph
  database are outside the architecture.

## 2. Build Discipline

Work proceeds in numbered phases. A phase is complete only after its automated
tests and validation gate pass. Each phase leaves tested code, reproducible
Compose commands, versioned fixtures, actionable diagnostics, and a record of
material decisions or deviations.

Note kinds are `log`, `standard`, and `kanban`. Only the configured first-level
`/logs` and `/kanban` roots carry path semantics. All other notes are standard,
may live anywhere, and may mix dated and undated entries.

Search units are `daily_section`, `project_update`, `freeform_section`,
`freeform_chunk`, and `kanban_card`. Each becomes one Qdrant point. Whole-note
identity and evidence metadata are carried in every point payload.

## 3. Phase 1 — Contracts, Containers, and Fixture Vault

### Build

1. Create the Python package layout and typed configuration.
2. Add the application Dockerfile and Compose services `zenith` and `qdrant`.
3. Pin the Qdrant image and Python dependencies.
4. Add Qdrant health checks, application dependency ordering, persistent Qdrant
   and model-cache volumes, a private network, and localhost-only port exposure.
5. Mount a configurable fixture vault read-only.
6. Define parser output, Qdrant payload, warning, and query-plan contracts.
7. Define deterministic note- and entry-ID algorithms.
8. Build a fixture vault with exact expected outputs for every documented case.
9. Add model-prefetch and model-readiness commands.

### Fixture coverage

- Daily dates from paths and first content lines.
- Ascending and descending project date headings.
- Standard notes with headings, without headings, mixed dated content, and oversized sections.
- Known, aliased, unknown, and mixed-case tags.
- Hashes in headings, URLs, inline code, fenced code, and prose.
- Resolved, missing, ambiguous, anchored, and aliased internal links.
- Duplicate filenames and titles.
- Kanban custom columns, inconsistent checkbox/status combinations, nested card
  content, decorations, and valid/invalid settings.
- Added, changed, renamed, and deleted files.

### Validation gate

- `docker compose config` succeeds.
- One Compose command starts both containers from a clean checkout.
- Qdrant becomes healthy and its localhost dashboard loads.
- Application health reports Qdrant reachable and model cache ready.
- The fixture vault mount is demonstrably read-only.
- Configuration and contract tests pass.
- The fixture inventory covers every regression listed in this plan.
- No SQLite, FTS5, cloud inference, or hidden host Python dependency exists.

## 4. Phase 2 — Deterministic Markdown Parser

### Build

1. Discover Markdown recursively under configured roots and exclusions.
2. Parse frontmatter and Markdown with a CommonMark-compatible AST.
3. Classify only `/logs` as log and `/kanban` as Kanban; classify every other
   Markdown file as a standard open note.
4. Build heading paths and source-line boundaries.
5. Extract entries, dates, tags, internal links, web links, and warnings.
6. Apply the specialized Kanban pass after generic AST parsing.
7. Construct separate raw search text and contextual embedding input.
8. Emit deterministic, storage-independent parse results.
9. Allow standard notes to mix `project_update`, `freeform_section`, and
   `freeform_chunk` entries without inferring meaning from their directories.
10. Use Watchdog to observe recursive Markdown changes and emit debounced,
    normalized vault-relative path batches. Incremental storage updates remain
    Phase 4 work.

### Validation gate

- Unit tests and golden fixture snapshots pass.
- Repeated parses produce identical structures and identifiers.
- Tags do not leak or arise from headings, URLs, or code.
- Mentioned dates do not establish chronology; links never transfer dates.
- Root, deeply nested, and messily organized standard notes parse identically
  when their Markdown content is identical.
- Kanban ordering, checkbox state, status, decorations, and settings are exact.
- Every entry has a valid vault-relative path and line range.

## 5. Phase 3 — Qdrant Collection and Full Rebuild

### Build

1. Create one collection with named `semantic` and `text-bm25` vectors.
2. Configure 384-dimensional cosine dense search and IDF sparse search.
3. Create payload indexes only for frequently filtered fields.
4. Generate dense and sparse vectors locally in the application container.
5. Upsert deterministic points with complete evidence payloads.
6. Rebuild into a temporary collection and switch an alias only after validation.
7. Record schema, parser, encoder, tokenizer, and embedding-input versions.
8. Add collection inspection and integrity diagnostics.

### Validation gate

- A clean rebuild produces exactly the expected fixture points.
- Two rebuilds produce identical logical collection contents.
- Dense vectors have 384 dimensions and eligible sparse vectors are non-empty.
- Payloads map back to exact fixture lines and point counts match parser output.
- A failed rebuild leaves the active collection usable.
- Hashes prove that no Markdown was modified.

## 6. Phase 4 — Incremental Indexing and Link Resolution

### Build

1. Skip unchanged files under compatible parser and encoder versions.
2. Upsert changed entries and delete stale points for changed notes.
3. Handle added, renamed, and deleted files.
4. Reuse unchanged embeddings when safe.
5. Resolve links deterministically after building the note catalog.
6. Re-resolve affected links after target or alias changes.
7. Implement explicit incremental commands before a debounced watcher.

### Validation gate

- Add/edit/rename/delete scenarios pass.
- Incremental indexing equals a clean rebuild.
- No stale points remain and unresolved links stay explicit.
- Only changed embedding inputs are re-encoded.
- Interrupted work is recoverable by rerunning the command.

## 7. Phase 5 — Retrieval

### Build

1. Add payload-filtered metadata lookup and BM25 sparse retrieval.
2. Add strict literal, phrase, case, and Unicode-normalization verification.
3. Add MiniLM dense retrieval and Qdrant RRF hybrid retrieval.
4. Add note, date/range, tag, section, entry-type, and Kanban filters.
5. Return scores, excerpts, and evidence locations.

### Validation gate

- Exact phrase results are reproducible and literally verified.
- Hard filters never leak in lexical, semantic, or hybrid modes.
- `note_date` and `entry_date` remain distinct.
- Multi-tag `all` and `any` behavior is tested.
- Conceptual queries work without exact wording.
- Every result contains valid evidence metadata.
- A labeled query set compares dense, BM25, and hybrid quality before RRF
  parameters are frozen.

## 8. Phase 6 — Graph-Aware Context Expansion

### Build

1. Retrieve outgoing links and backlinks from payloads.
2. Search within resolved targets instead of loading notes wholesale.
3. Rank linked targets and retrieve nearby dated project history.
4. Enforce default depth 1, maximum depth 2, maximum 5 linked notes, and an
   initial nearby-history window of plus or minus 3 days.
5. Label direct evidence, followed links, backlinks, nearby history, and
   inference inputs.

### Validation gate

- Daily-to-project traversal works.
- Cycles terminate and budgets cannot be exceeded.
- Linked or nearby material is never presented as directly dated evidence.
- Missing or ambiguous links stop deterministic traversal with diagnostics.

## 9. Phase 7 — Library, CLI, and Diagnostics

### Build

Expose composable operations through a Python library and CLI:

```text
reindex(paths?, full=false)
find_entries(...)
get_note(path_or_title)
get_entry(entry_id)
get_outgoing_links(note_id, entry_id?)
get_backlinks(note_id)
resolve_link(source_note_id, target_text)
search_within(note_id, query, mode, section?)
expand_context(entry_id, link_depth=1, nearby_days=3, max_notes=5)
get_index_warnings(type?, path?)
list_kanban_boards()
get_kanban_board(board_name_or_path)
find_kanban_cards(...)
```

Add health, model-prefetch, collection initialization, rebuild, incremental,
search, link, context, Kanban, warning, and diagnostic commands. MCP can later be
a thin adapter over this tested library.

### Validation gate

- CLI contracts and exit codes pass inside the application container.
- Health detects unreachable Qdrant, missing models, and incompatible indexes.
- Commands produce stable machine-readable output.
- No command requires direct host Python execution.

## 10. Phase 8 — Agent Query Planning and Answers

### Build

1. Compile natural language into inspectable query plans.
2. Select metadata, literal, lexical, semantic, hybrid, or graph retrieval.
3. Produce cited answers separating facts, context, history, and inference.
4. Expose interpreted filters when ambiguity matters.

### Validation gate

- Golden end-to-end questions pass.
- Answers cite path, heading, date semantics, and lines.
- Similarity is never presented as proof of a literal match.
- Chronological answers never date undated content.

## 11. Phase 9 — Real-Vault Validation and Release

### Build

1. Run against the real vault through a read-only mount.
2. Review warnings and ranking misses without rewriting notes.
3. Measure rebuild time, incremental time, latency, model cold start, memory,
   disk use, and embedding reuse.
4. Test Qdrant snapshot/restore and rebuild-based recovery.
5. Document schema, parser, Qdrant, and model upgrades.
6. Pin the validated images and dependencies.

### Validation gate

- Representative real-vault queries satisfy the definition of done.
- A fresh Compose deployment can prefetch models, rebuild, and answer queries.
- Normal operation works offline after prefetch.
- Data survives container recreation and can also be rebuilt from Markdown.
- No application path writes to the vault.

## 12. Permanent Regression Rules

- `# Heading` never becomes a tag; section tags never leak.
- Code, URLs, and plugin settings never pollute searchable prose.
- Links never transfer dates and mentioned dates do not establish chronology.
- Ambiguous links are never silently resolved; link cycles remain bounded.
- Kanban status and checkbox state remain independent.
- Renames, deletions, and version upgrades leave no stale points.
- Exact requests are verified literally rather than inferred from BM25 or vectors.
- Every returned fact remains traceable to Markdown source lines.

## 13. Definition of Done

One Docker Compose project can:

1. Start the Python application and local Qdrant with a working dashboard.
2. Prefetch and use pinned dense and sparse models locally.
3. Fully and incrementally index the vault without modifying it.
4. Parse daily, project, freeform, and Kanban content correctly.
5. Filter by dates, ranges, tags, note identity, entry type, and Kanban state.
6. Perform BM25, MiniLM semantic, strict literal, and RRF hybrid retrieval.
7. Resolve links and backlinks with ambiguity reporting.
8. Follow bounded context links without corrupting chronology.
9. Return evidence with path, heading path, date semantics, and line range.
10. Recover through persistence, snapshots, or a deterministic rebuild.
