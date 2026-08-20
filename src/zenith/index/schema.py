"""Versioned Qdrant collection schema."""

from __future__ import annotations

from qdrant_client import models


SCHEMA_VERSION = 1
DENSE_VECTOR = "semantic"
SPARSE_VECTOR = "text-bm25"

PAYLOAD_INDEXES: tuple[tuple[str, models.PayloadSchemaType], ...] = (
    ("vault_id", models.PayloadSchemaType.KEYWORD),
    ("note_id", models.PayloadSchemaType.KEYWORD),
    ("path", models.PayloadSchemaType.KEYWORD),
    ("note_title", models.PayloadSchemaType.KEYWORD),
    ("note_type", models.PayloadSchemaType.KEYWORD),
    ("entry_type", models.PayloadSchemaType.KEYWORD),
    ("note_date", models.PayloadSchemaType.DATETIME),
    ("entry_date", models.PayloadSchemaType.DATETIME),
    ("tags", models.PayloadSchemaType.KEYWORD),
    ("outgoing_note_ids", models.PayloadSchemaType.KEYWORD),
    ("text", models.PayloadSchemaType.TEXT),
    ("board.name", models.PayloadSchemaType.KEYWORD),
    ("board.column", models.PayloadSchemaType.KEYWORD),
    ("board.status", models.PayloadSchemaType.KEYWORD),
    ("board.checked", models.PayloadSchemaType.BOOL),
    ("modified_at", models.PayloadSchemaType.DATETIME),
)


def create_collection(client: object, name: str) -> None:
    client.create_collection(
        collection_name=name,
        vectors_config={
            DENSE_VECTOR: models.VectorParams(size=384, distance=models.Distance.COSINE),
        },
        sparse_vectors_config={
            SPARSE_VECTOR: models.SparseVectorParams(
                index=models.SparseIndexParams(on_disk=False),
                modifier=models.Modifier.IDF,
            )
        },
    )
    for field_name, field_schema in PAYLOAD_INDEXES:
        client.create_payload_index(
            collection_name=name,
            field_name=field_name,
            field_schema=field_schema,
            wait=True,
        )
