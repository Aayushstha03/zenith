# Indexing

How a Markdown vault becomes searchable points in Qdrant.

## The pipeline

```
files → parse → entries → resolve links → encode → points → Qdrant
```

| Stage | Module | What it does |
|---|---|---|
| find | `parser/discovery.py` | Collect every `.md` file. Skip excluded folders. The top folder sets the note type. |
| parse | `parser/service.py` | Cut a note into **entries** at its headings, then split any section too long for the embedding model. |
| name | `core/identity.py` | Give every note and entry a permanent UUID. |
| link | `index/links.py` | Resolve each `[[wikilink]]` to `resolved`, `ambiguous`, or `missing`. |
| encode | `index/encoders.py` | Build one dense vector and one sparse vector per entry. |
| store | `index/rebuild.py`, `index/incremental.py` | Write the points to Qdrant. |

## Names decide everything

A **note id** is a hash of the vault name and the file path.
An **entry id** is a hash of the note id, the entry type, and a **structural key**.

The structural key sets what an edit costs:

- A section key is its heading path plus an occurrence number. It holds no text, so you can rewrite the section and the entry id stays. The point updates in place.
- A chunk with no heading uses a digest of its text. An edit makes a new entry id, and the old point is left with no owner.

The second case is why the stale sweep is not optional. Without it, every such edit leaves a duplicate in the search results.

Because a note id comes from the **path**, a rename is a delete plus a create. Every entry id under it changes.

## Two write modes

**Rebuild** — `zenith index rebuild`. Writes into a new collection, counts the points, then moves the alias. It is atomic. A failure never touches the live index. The old collection is dropped after the swap.

**Incremental** — `zenith index update`, and the watcher. Writes into the live collection. It compares two sets:

- **desired** — every entry just parsed.
- **existing** — the points already stored.

| Case | Action |
|---|---|
| not in existing | insert |
| payload changed | update |
| payload identical | skip |
| in existing, not desired | delete |

## Scoped updates

`reindex()` with no paths reparses the whole vault. `reindex(paths)` narrows the work, which is what the watcher calls on every save.

Narrowing is not as simple as parsing one file, for two reasons.

1. **Link resolution is vault-wide.** Adding a note named `Target` must change a `[[Target]]` in a file nobody edited.
2. **The stale sweep subtracts.** If `desired` held one file, then `existing − desired` would be the whole rest of the index.

So a scoped update does this:

1. Take the changed note ids from the **paths**, not from the parse. A deleted file has no parse, but it still has an id, so its points stay in scope.
2. Read a **header** for every note — path, id, title, aliases — from the file head. This is the catalog link resolution needs. It costs a small fraction of a full parse.
3. Collect the changed **names**: the old ones from the index, the new ones from the catalog.
4. Widen the scope with two queries: notes whose `outgoing_link_keys` match those names, and notes whose `outgoing_note_ids` match the changed ids.
5. Parse only the scope. Resolve its links against the **whole** catalog.
6. Read existing points for the scope only, and sweep inside it.

A note pulled in only because a link moved keeps its entry ids and its embedding fingerprint. Its vector is reused and the encoder is never called.

### Payload fields the scope depends on

- `note_aliases` — the other names a note answers to. Read back from the index to learn what a **deleted** note used to be called.
- `outgoing_link_keys` — one normalized key per link, the exact string link resolution compares. Indexed, so the notes pointing at a change are one query away.

## Vectors follow the fingerprint, not the id

Each point stores an `embedding_fingerprint`: a digest of the parser version, both model names, the encoder and tokenizer versions, the input format, and the embedding text.

Vector reuse is keyed by that fingerprint, not by entry id. The embedding text holds the note **title**, not its path. So renaming a note that has a heading or a frontmatter title changes every entry id but no fingerprint, and the rename costs no encoding. Rename a note titled by its filename and the title really did change, so re-encoding is correct.

## Operational notes

- `note_aliases` and `outgoing_link_keys` are new. Run `zenith index rebuild` once so scoped updates can find reverse links.
- `zenith index inspect` reports the collection schema and any missing payload index.
