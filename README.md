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

After model prefetch, the application health endpoint is available inside the
Compose network and the Qdrant dashboard is available at
<http://localhost:6333/dashboard>.

Deployment settings are documented in `.env`. To use a real vault, set
`ZENITH_VAULT_PATH` there to an absolute host path. The Compose mount remains
read-only. `.env.example` is the shareable template.

Architecture and phased acceptance criteria are documented in
`architecture-final.md` and `implementation-plan-final.md`.
