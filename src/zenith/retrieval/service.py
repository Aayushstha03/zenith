"""Metadata, literal, lexical, semantic, and hybrid retrieval over the active index."""

from __future__ import annotations

from typing import Any

from qdrant_client import QdrantClient, models

from zenith.core.config import Settings
from zenith.core.contracts import (
    EntryType,
    KanbanData,
    Link,
    LinkResolution,
    NoteType,
    QueryPlan,
    RetrievalMode,
    SearchResult,
)
from zenith.index.encoders import LocalEncoders
from zenith.retrieval.filters import build_filter
from zenith.retrieval.literal import verify_literal


class Retriever:
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
        self._encoders = encoders

    @property
    def encoders(self) -> Any:
        if self._encoders is None:
            self._encoders = LocalEncoders(self.settings)
        return self._encoders

    def search(self, plan: QueryPlan) -> tuple[SearchResult, ...]:
        filter_ = build_filter(plan, self.vault_id)
        if plan.mode is RetrievalMode.METADATA:
            return self._metadata(filter_, plan)
        if plan.mode is RetrievalMode.LITERAL:
            return self._literal(filter_, plan)
        if plan.mode is RetrievalMode.LEXICAL:
            return self._lexical(filter_, plan)
        if plan.mode is RetrievalMode.SEMANTIC:
            return self._semantic(filter_, plan)
        return self._hybrid(filter_, plan)

    def get_entry(self, entry_id: str) -> SearchResult | None:
        filter_ = models.Filter(
            must=[
                models.FieldCondition(key="vault_id", match=models.MatchValue(value=self.vault_id)),
                models.FieldCondition(key="entry_id", match=models.MatchValue(value=entry_id)),
            ]
        )
        records = self._scroll_all(filter_)
        if not records:
            return None
        records.sort(key=lambda record: (record.payload["path"], record.payload["start_line"]))
        return _result(records[0].payload, RetrievalMode.METADATA)

    def get_note_entries(self, note_id: str) -> tuple[SearchResult, ...]:
        return self.metadata_all(
            QueryPlan(mode=RetrievalMode.METADATA, note_id=note_id)
        )

    def metadata_all(self, plan: QueryPlan | None = None) -> tuple[SearchResult, ...]:
        plan = plan or QueryPlan(mode=RetrievalMode.METADATA)
        if plan.mode is not RetrievalMode.METADATA:
            raise ValueError("metadata_all requires metadata mode")
        records = self._scroll_all(build_filter(plan, self.vault_id))
        records.sort(key=lambda record: (record.payload["path"], record.payload["start_line"]))
        return tuple(_result(record.payload, RetrievalMode.METADATA) for record in records)

    def get_backlinks(self, note_id: str) -> tuple[SearchResult, ...]:
        filter_ = models.Filter(
            must=[
                models.FieldCondition(key="vault_id", match=models.MatchValue(value=self.vault_id)),
                models.FieldCondition(
                    key="outgoing_note_ids", match=models.MatchValue(value=note_id)
                ),
            ]
        )
        records = self._scroll_all(filter_)
        records.sort(key=lambda record: (record.payload["path"], record.payload["start_line"]))
        return tuple(_result(record.payload, RetrievalMode.METADATA) for record in records)

    def search_within(
        self,
        note_id: str,
        query: str,
        *,
        mode: RetrievalMode = RetrievalMode.HYBRID,
        section: str | None = None,
        limit: int = 1,
    ) -> tuple[SearchResult, ...]:
        if mode is RetrievalMode.METADATA:
            return self.search(
                QueryPlan(mode=mode, note_id=note_id, section=section, limit=limit)
            )
        if mode is RetrievalMode.LITERAL:
            return self.search(
                QueryPlan(
                    mode=mode,
                    note_id=note_id,
                    section=section,
                    literal_text=query,
                    limit=limit,
                )
            )
        if mode is RetrievalMode.LEXICAL:
            return self.search(
                QueryPlan(
                    mode=mode,
                    note_id=note_id,
                    section=section,
                    lexical_text=query,
                    limit=limit,
                )
            )
        if mode is RetrievalMode.SEMANTIC:
            return self.search(
                QueryPlan(
                    mode=mode,
                    note_id=note_id,
                    section=section,
                    semantic_text=query,
                    limit=limit,
                )
            )
        return self.search(
            QueryPlan(
                mode=mode,
                note_id=note_id,
                section=section,
                lexical_text=query,
                semantic_text=query,
                limit=limit,
            )
        )

    def _metadata(self, filter_: models.Filter, plan: QueryPlan) -> tuple[SearchResult, ...]:
        records = self._scroll_all(filter_)
        records.sort(key=lambda record: (record.payload["path"], record.payload["start_line"]))
        return tuple(_result(record.payload, plan.mode) for record in records[: plan.limit])

    def _literal(self, filter_: models.Filter, plan: QueryPlan) -> tuple[SearchResult, ...]:
        if not plan.literal_text:
            raise ValueError("literal mode requires literal_text")
        candidates = self._scroll_all(filter_)
        verified = [record for record in candidates if verify_literal(plan.literal_text, record.payload["text"])]
        verified.sort(key=lambda record: (record.payload["path"], record.payload["start_line"]))
        return tuple(_result(record.payload, plan.mode, verified=True) for record in verified[: plan.limit])

    def _lexical(self, filter_: models.Filter, plan: QueryPlan) -> tuple[SearchResult, ...]:
        if not plan.lexical_text:
            raise ValueError("lexical mode requires lexical_text")
        sparse_vector = self.encoders.encode_sparse([plan.lexical_text])[0]
        response = self.client.query_points(
            collection_name=self.settings.collection_name,
            query=sparse_vector,
            using="text-bm25",
            query_filter=filter_,
            limit=plan.limit,
            with_payload=True,
        )
        return tuple(_result(point.payload, plan.mode, score=point.score) for point in response.points)

    def _semantic(self, filter_: models.Filter, plan: QueryPlan) -> tuple[SearchResult, ...]:
        if not plan.semantic_text:
            raise ValueError("semantic mode requires semantic_text")
        dense_vector = self.encoders.encode_dense([plan.semantic_text])[0]
        response = self.client.query_points(
            collection_name=self.settings.collection_name,
            query=dense_vector,
            using="semantic",
            query_filter=filter_,
            limit=plan.limit,
            with_payload=True,
        )
        return tuple(_result(point.payload, plan.mode, score=point.score) for point in response.points)

    def _hybrid(self, filter_: models.Filter, plan: QueryPlan) -> tuple[SearchResult, ...]:
        if not plan.lexical_text or not plan.semantic_text:
            raise ValueError("hybrid mode requires both lexical_text and semantic_text")
        dense_vector = self.encoders.encode_dense([plan.semantic_text])[0]
        sparse_vector = self.encoders.encode_sparse([plan.lexical_text])[0]
        prefetch_limit = max(plan.limit * 4, plan.limit)
        response = self.client.query_points(
            collection_name=self.settings.collection_name,
            prefetch=[
                models.Prefetch(query=dense_vector, using="semantic", filter=filter_, limit=prefetch_limit),
                models.Prefetch(query=sparse_vector, using="text-bm25", filter=filter_, limit=prefetch_limit),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=filter_,
            limit=plan.limit,
            with_payload=True,
        )
        return tuple(_result(point.payload, plan.mode, score=point.score) for point in response.points)

    def _scroll_all(self, filter_: models.Filter) -> list[Any]:
        result: list[Any] = []
        offset: object | None = None
        while True:
            records, offset = self.client.scroll(
                collection_name=self.settings.collection_name,
                scroll_filter=filter_,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            result.extend(records)
            if offset is None:
                return result


def _result(
    payload: dict[str, Any],
    mode: RetrievalMode,
    *,
    score: float | None = None,
    verified: bool | None = None,
) -> SearchResult:
    board = payload.get("board")
    return SearchResult(
        entry_id=payload["entry_id"],
        note_id=payload["note_id"],
        path=payload["path"],
        note_title=payload["note_title"],
        note_type=NoteType(payload["note_type"]),
        entry_type=EntryType(payload["entry_type"]),
        mode=mode,
        text=payload["text"],
        excerpt=payload["text"],
        heading=payload["heading"],
        heading_path=tuple(payload["heading_path"]),
        start_line=payload["start_line"],
        end_line=payload["end_line"],
        note_date=_short_date(payload["note_date"]),
        entry_date=_short_date(payload["entry_date"]),
        tags=tuple(payload["tags"]),
        outgoing_links=tuple(_link(link) for link in payload["outgoing_links"]),
        score=score,
        verified=verified,
        kanban=KanbanData(**board) if board is not None else None,
    )


def _short_date(value: str | None) -> str | None:
    return value.split("T", 1)[0] if value else None


def _link(payload: dict[str, Any]) -> Link:
    return Link(
        target_text=payload["target_text"],
        target_note_id=payload["target_note_id"],
        target_heading=payload["target_heading"],
        alias=payload["alias"],
        resolution=LinkResolution(payload["resolution"]),
        line=payload["line"],
    )
