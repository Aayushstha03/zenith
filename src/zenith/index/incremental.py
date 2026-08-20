"""Idempotent incremental indexing that converges to a clean rebuild."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from qdrant_client import models

from zenith.core.config import Settings
from zenith.core.contracts import ParsedEntry
from zenith.core.identity import normalize_vault_path
from zenith.index.links import resolve_links
from zenith.index.rebuild import IndexRebuilder
from zenith.parser.service import VaultParser


@dataclass(frozen=True, slots=True)
class IncrementalReport:
    collection: str
    requested_paths: tuple[str, ...]
    notes: int
    inserted: int
    updated: int
    deleted: int
    skipped: int
    embeddings_generated: int
    embeddings_reused: int
    warnings: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class IncrementalIndexer(IndexRebuilder):
    def reindex(self, paths: list[str] | None = None) -> IncrementalReport:
        requested = tuple(sorted({normalize_vault_path(path) for path in paths or ()}, key=str.casefold))
        notes = resolve_links(VaultParser(self.settings, self.vault_id).parse_vault())
        entries = [entry for note in notes for entry in note.entries]
        existing = self._existing_points()
        desired_ids = {entry.entry_id for entry in entries}
        stale_ids = sorted(set(existing) - desired_ids)

        payloads = {entry.entry_id: self._payload(entry) for entry in entries}
        encode_entries: list[ParsedEntry] = []
        reused_vectors: dict[str, object] = {}
        skipped = 0
        updated = 0
        inserted = 0
        for entry in entries:
            record = existing.get(entry.entry_id)
            payload = payloads[entry.entry_id]
            if record is None:
                inserted += 1
                encode_entries.append(entry)
                continue
            compatible = _embedding_compatible(record.payload, payload) and _has_vectors(record.vector)
            if record.payload == payload and compatible:
                skipped += 1
                continue
            updated += 1
            if compatible:
                reused_vectors[entry.entry_id] = record.vector
            else:
                encode_entries.append(entry)

        generated = self.encoders.encode([entry.embedding_text for entry in encode_entries])
        generated_vectors = {
            entry.entry_id: vector for entry, vector in zip(encode_entries, generated, strict=True)
        }
        points = [
            models.PointStruct(
                id=entry.entry_id,
                vector=generated_vectors.get(entry.entry_id, reused_vectors.get(entry.entry_id)),
                payload=payloads[entry.entry_id],
            )
            for entry in entries
            if entry.entry_id in generated_vectors or entry.entry_id in reused_vectors
        ]

        self._verify_sources_unchanged(notes)
        for start in range(0, len(points), 64):
            self.client.upsert(
                collection_name=self.settings.collection_name,
                points=points[start : start + 64],
                wait=True,
            )
        if stale_ids:
            self.client.delete(
                collection_name=self.settings.collection_name,
                points_selector=stale_ids,
                wait=True,
            )

        return IncrementalReport(
            collection=self.settings.collection_name,
            requested_paths=requested,
            notes=len(notes),
            inserted=inserted,
            updated=updated,
            deleted=len(stale_ids),
            skipped=skipped,
            embeddings_generated=len(encode_entries),
            embeddings_reused=len(reused_vectors),
            warnings=sum(len(note.warnings) for note in notes),
        )

    def _existing_points(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        offset: object | None = None
        vault_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="vault_id",
                    match=models.MatchValue(value=self.vault_id),
                )
            ]
        )
        while True:
            records, offset = self.client.scroll(
                collection_name=self.settings.collection_name,
                scroll_filter=vault_filter,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            result.update({str(record.id): record for record in records})
            if offset is None:
                return result


def _embedding_compatible(existing: dict[str, object], desired: dict[str, object]) -> bool:
    keys = (
        "schema_version",
        "parser_version",
        "embedding_model",
        "sparse_model",
        "encoder_version",
        "tokenizer_version",
        "embedding_input_version",
        "embedding_input_hash",
    )
    return all(existing.get(key) == desired.get(key) for key in keys)


def _has_vectors(vector: object) -> bool:
    return isinstance(vector, dict) and "semantic" in vector and "text-bm25" in vector
