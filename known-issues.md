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

## 2026-08-26 — The token estimate over-counts ordinary prose by about two times

**Where:** `src/zenith/parser/tokens.py`, `estimate_tokens`.

**What:** The parser cannot load the real tokenizer without making chunk
boundaries, and therefore entry identifiers, depend on whether a model has been
downloaded. It approximates instead. The divisors were fitted against the
pinned tokenizer over the fixture vault plus English, Spanish, Russian,
Japanese, and Korean samples, and chosen as the loosest values that never
under-count any of them. The result over-counts ordinary English prose by
roughly two times, so a section can split into two entries when one would have
fit.

**Why this is fine for now:** Splitting early costs extra points and extra
embedding time. It loses no content. The alternative failure, under-counting,
silently drops text from the dense vector, which is the defect this work
existed to remove. Erring toward more chunks is the correct direction.

**Where it gets real:** A large real vault. Extra points mean more storage,
longer rebuilds, and more fragmented evidence spans in cited answers.

**The fix, when it's worth doing:** Measure the true ratio on the real vault
using `LocalEncoders.truncated_inputs` and the real tokenizer, then either
raise `ZENITH_DENSE_TOKEN_WINDOW` by the measured headroom or replace the
approximation with a small vocabulary-derived table shipped alongside the
pinned model. A shipped table stays hermetic because it versions with the
model.

**Decision:** Deferred. Revisit during Phase 9 real-vault validation, when the
ratio can be measured on real notes instead of a calibration corpus.

**Update 2026-08-26:** Partly mitigated. The window moved from FastEmbed's 128
default to the 256 the model declares, so the effective budget roughly doubled
even with the same over-count. Fixture entries dropped from 48 points to 45,
and `freeform/Reference.md` went back to a single entry instead of being split
in two. The ratio itself is unchanged and still worth measuring on a real
vault.

## 2026-08-26 — Deliberately adversarial text can still overrun the window

**Where:** `src/zenith/parser/tokens.py` and `src/zenith/index/encoders.py`.

**What:** Long random identifiers, base64 blobs, and hashes fragment into
roughly one token per two characters, faster than the estimate assumes. Such an
entry can still exceed the encoder window.

**Why this is fine for now:** It is no longer silent. `VaultParser` warns from
its own estimate when a single paragraph exceeds the budget, and
`LocalEncoders.truncated_inputs` counts what the real tokenizer actually cut, so
drift between the approximation and the model is observable rather than
invisible.

**The fix, when it's worth doing:** Surface `truncated_inputs` in the rebuild
report and in `zenith diagnose`, so an operator sees the count without reading
warnings note by note.

**Decision:** Deferred until the counter has real-vault numbers behind it.

## 2026-08-26 — The 256-token window is a model choice, and embedding must stay in-process

**Where:** `src/zenith/core/config.py` (`DENSE_MODEL`, `DENSE_TOKEN_WINDOW`),
`src/zenith/index/encoders.py`.

**What:** The two entries above both exist because the pinned dense model,
`all-MiniLM-L6-v2`, accepts 256 tokens. The parser splits sections to fit that
window, and the token estimate over-counts to stay safely inside it. A dense
model with a larger window removes both problems at the source instead of
mitigating them.

**The constraint that decides the shape of any fix:** Embedding inference and
the Watchdog watcher must keep working while LM Studio is closed. LM Studio
holds a chat model in VRAM. Parsing, indexing, and incremental updates must not
compete for that VRAM, and must not depend on a desktop application being open.
FastEmbed runs the dense model in the application process on CPU, which is why
`zenith parse`, `zenith watch`, and `zenith index update` work offline after a
model prefetch. Phase 9 requires exactly that. Therefore any replacement model
must also run in-process through FastEmbed. Serving embeddings from LM Studio,
or from any other external inference server, is rejected.

**What this rules out:** `bge-m3` is present in the local LM Studio model
directory and accepts 8192 tokens, but FastEmbed does not list it. Using it
would mean serving embeddings from LM Studio, which the constraint above
forbids.

**What remains available.** FastEmbed lists these in-process alternatives:

| Model | Dimensions | Window |
| --- | --- | --- |
| `nomic-ai/nomic-embed-text-v1.5` | 768 | 8192 |
| `snowflake/snowflake-arctic-embed-m-long` | 768 | 2048 |
| `jinaai/jina-embeddings-v3` | 1024 | 1024 |
| `sentence-transformers/all-MiniLM-L6-v2` (current) | 384 | 256 |

**Why this is fine for now:** The current model works, runs on CPU, and costs
no VRAM. Changing the dense model changes the collection's vector dimension,
so it forces a full rebuild and a schema change. The parser's token budget must
also stay hermetic: entry identifiers must never depend on which model is
installed. A new model changes the budget, and therefore changes every entry
identifier in the vault.

**Where it gets real:** A real vault with long sections. Splitting fragments
the evidence spans that Phase 8 answers cite, which weakens the citations
rather than the retrieval.

**The fix, when it's worth doing:** Pick one of the in-process models above,
change the dense dimension in `src/zenith/index/schema.py`, raise
`ZENITH_DENSE_TOKEN_WINDOW` to the new model's declared window, and rebuild.
Note that the "never set this above 512" guidance in `.env.example` and
`README.md` describes `all-MiniLM-L6-v2` only; a different model carries a
different ceiling, and that text must be updated with the model.

**Decision:** Deferred. Revisit after Phase 9 measures real splitting on the
real vault. The in-process and VRAM constraints stand whatever that measurement
shows.
