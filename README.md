# Zenith

*Work in progress. I am building it as I go, and it is just getting started.*

## Why

I work on many projects at the same time. AI makes each one move fast. I test an
idea, build it, check the result against the last attempt, and make a decision.
Some decisions are right. Some are wrong. There are many of them, and they come
quickly.

So I take notes. I write a journal entry each day, a log for each experiment, a
card for each task, and a record of each decision and its reason. The notes work
well when I write them. They work badly when I must find them again. The
information is in the vault, but it takes a long time to open each file, read
each heading, and remember which day held the answer.

Zenith is the tool for that second part. It makes the lookup fast, simple, and
one step. I ask a question in the words I remember, and Zenith gives me the
entries I wrote.

It is also one tool for all of it. My journals, my Kanban boards, my project
updates, and my freeform logs are different shapes of Markdown, but they hold
one history. Zenith reads all of them, indexes each entry the same way, and
searches them together.

## What it is

A local-first search index for a Markdown vault. The Markdown stays the source
of truth and is mounted read-only. Qdrant holds the derived index and nothing
else, so the whole index can be thrown away and rebuilt from the notes.

Zenith cuts notes into entries — daily sections, dated project updates,
freeform sections, and Kanban cards — and indexes each one with a dense vector,
a BM25 sparse vector, and a payload carrying its path, heading path, dates, and
line range. Search it by metadata, exact phrase, keyword, meaning, or a hybrid
of the last two. Then ask a local model a question and get an answer that cites
the entries it actually read.


## Start it

```bash
cp .env.example .env          # then set ZENITH_VAULT_PATH to your vault
docker compose build
docker compose run --rm model-prefetch
docker compose up -d
```

`.env.example` is the template, and it documents every setting.
The default vault path points at the fixture vault, which is safe to index as-is.

Build the index, then ask it something:

```bash
docker compose exec zenith zenith index rebuild
docker compose exec zenith zenith search "pipeline clustering" --mode hybrid
docker compose exec zenith zenith ask "what did I work on last week?"
```

The watcher runs as its own service and reindexes each saved file, so the index
follows the vault without another command.

`zenith ask` needs LM Studio running on the host with "Serve on Local Network"
enabled. Nothing else does. Parsing, indexing, and the watcher all run with LM
Studio closed, so the index never competes with a chat model for VRAM.

The Qdrant dashboard is at <http://localhost:6333/dashboard>.

## Working on it

```bash
uv sync --dev
uv run pytest
```

Compose binds `./src` over the image, and `PYTHONPATH` puts the mount first, so
the containers run the working tree. Edit a file and the next
`docker compose exec` picks it up with no rebuild. The two long-running
processes hold their own code:

```bash
docker compose restart zenith watch
```

Rebuild the image only when a dependency changes.

## Documentation

- [docs/design.md](docs/design.md) — how Zenith works, and why. The decisions,
  the indexing pipeline, the retrieval modes, the invariants, and the known
  limits.
- [docs/cli-reference.md](docs/cli-reference.md) — every command, option,
  response shape, exit code, and Python API method.
