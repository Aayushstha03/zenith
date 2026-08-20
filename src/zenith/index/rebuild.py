"""Atomic, deterministic full-vault rebuilds."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

from qdrant_client import QdrantClient, models

from zenith.core.config import Settings
from zenith.core.contracts import ParsedEntry, ParsedNote, QdrantPayload
from zenith.index.encoders import LocalEncoders
from zenith.index.schema import SCHEMA_VERSION, create_collection
from zenith.parser.service import PARSER_VERSION, VaultParser


ENCODER_VERSION = "fastembed-0.7.3"
TOKENIZER_VERSION = "bm25-english-stemming-stopwords-v1"
EMBEDDING_INPUT_VERSION = "1"


@dataclass(frozen=True, slots=True)
class RebuildReport:
    collection: str
    physical_collection: str
    notes: int
    points: int
    warnings: int
    previous_collection: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class IndexRebuilder:
    def __init__(
        self,
        settings: Settings,
        *,
        vault_id: str = "personal",
        client: Any | None = None,
        encoders: Any | None = None,
    ) -> None:
        self.settings = settings
        self.vault_id = vault_id
        self.client = client or QdrantClient(url=settings.qdrant_url)
        self.encoders = encoders or LocalEncoders(settings)

    def rebuild(self) -> RebuildReport:
        notes = VaultParser(self.settings, self.vault_id).parse_vault()
        entries = [entry for note in notes for entry in note.entries]
        temporary = f"{self.settings.collection_name}__build_{uuid4().hex}"
        previous = self._alias_target()

        try:
            create_collection(self.client, temporary)
            self._upsert(temporary, entries)
            actual = self.client.count(collection_name=temporary, exact=True).count
            if actual != len(entries):
                raise RuntimeError(f"rebuild validation failed: expected {len(entries)} points, found {actual}")
            self._verify_sources_unchanged(notes)
            self._activate(temporary, previous)
        except Exception:
            if self.client.collection_exists(temporary):
                self.client.delete_collection(temporary)
            raise

        return RebuildReport(
            collection=self.settings.collection_name,
            physical_collection=temporary,
            notes=len(notes),
            points=len(entries),
            warnings=sum(len(note.warnings) for note in notes),
            previous_collection=previous,
        )

    def _upsert(self, collection: str, entries: list[ParsedEntry], batch_size: int = 64) -> None:
        for start in range(0, len(entries), batch_size):
            batch = entries[start : start + batch_size]
            vectors = self.encoders.encode([entry.embedding_text for entry in batch])
            points = [
                models.PointStruct(
                    id=entry.entry_id,
                    vector=vector,
                    payload=self._payload(entry),
                )
                for entry, vector in zip(batch, vectors, strict=True)
            ]
            self.client.upsert(collection_name=collection, points=points, wait=True)

    def _payload(self, entry: ParsedEntry) -> dict[str, object]:
        modified_at = datetime.fromtimestamp(
            (self.settings.vault_path / Path(entry.path)).stat().st_mtime, UTC
        ).isoformat()
        outgoing_ids = tuple(
            link.target_note_id for link in entry.outgoing_links if link.target_note_id is not None
        )
        return QdrantPayload(
            schema_version=SCHEMA_VERSION,
            parser_version=PARSER_VERSION,
            embedding_model=self.settings.dense_model,
            sparse_model=self.settings.sparse_model,
            vault_id=self.vault_id,
            note_id=entry.note_id,
            entry_id=entry.entry_id,
            path=entry.path,
            note_title=entry.note_title,
            note_type=entry.note_type,
            entry_type=entry.entry_type,
            text=entry.text,
            heading=entry.heading,
            heading_path=entry.heading_path,
            start_line=entry.source.start_line,
            end_line=entry.source.end_line,
            note_date=_qdrant_date(entry.note_date),
            entry_date=_qdrant_date(entry.entry_date),
            tags=entry.tags,
            outgoing_note_ids=outgoing_ids,
            outgoing_links=entry.outgoing_links,
            web_links=entry.web_links,
            content_hash=entry.content_hash,
            modified_at=modified_at,
            board=entry.kanban,
            encoder_version=ENCODER_VERSION,
            tokenizer_version=TOKENIZER_VERSION,
            embedding_input_version=EMBEDDING_INPUT_VERSION,
        ).to_dict()

    def _alias_target(self) -> str | None:
        aliases = self.client.get_aliases().aliases
        return next(
            (
                alias.collection_name
                for alias in aliases
                if alias.alias_name == self.settings.collection_name
            ),
            None,
        )

    def _verify_sources_unchanged(self, notes: tuple[ParsedNote, ...]) -> None:
        for note in notes:
            source = self.settings.vault_path / Path(note.path)
            current_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            if current_hash != note.content_hash:
                raise RuntimeError(f"vault changed during rebuild: {note.path}")

    def _activate(self, temporary: str, previous: str | None) -> None:
        operations: list[object] = []
        if previous is not None:
            operations.append(
                models.DeleteAliasOperation(
                    delete_alias=models.DeleteAlias(alias_name=self.settings.collection_name)
                )
            )
        operations.append(
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(
                    collection_name=temporary,
                    alias_name=self.settings.collection_name,
                )
            )
        )
        self.client.update_collection_aliases(change_aliases_operations=operations)


def _qdrant_date(value: str | None) -> str | None:
    return f"{value}T00:00:00Z" if value else None
