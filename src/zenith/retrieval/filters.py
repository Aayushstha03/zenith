"""Deterministic Qdrant filter construction from a QueryPlan."""

from __future__ import annotations

from qdrant_client import models

from zenith.core.contracts import QueryPlan


def build_filter(plan: QueryPlan, vault_id: str) -> models.Filter:
    must: list[models.Condition] = [
        models.FieldCondition(key="vault_id", match=models.MatchValue(value=vault_id))
    ]

    if plan.note_id:
        must.append(models.FieldCondition(key="note_id", match=models.MatchValue(value=plan.note_id)))

    if plan.entry_types:
        must.append(
            models.FieldCondition(
                key="entry_type",
                match=models.MatchAny(any=[entry_type.value for entry_type in plan.entry_types]),
            )
        )

    if plan.section:
        must.append(
            models.Filter(
                should=[
                    models.FieldCondition(key="heading", match=models.MatchValue(value=plan.section)),
                    models.FieldCondition(key="heading_path", match=models.MatchValue(value=plan.section)),
                ]
            )
        )

    for tag in plan.tags_all:
        must.append(models.FieldCondition(key="tags", match=models.MatchValue(value=tag)))

    if plan.tags_any:
        must.append(
            models.Filter(
                should=[
                    models.FieldCondition(key="tags", match=models.MatchValue(value=tag))
                    for tag in plan.tags_any
                ]
            )
        )

    if plan.date_from or plan.date_to:
        date_range = models.DatetimeRange(
            gte=f"{plan.date_from}T00:00:00Z" if plan.date_from else None,
            lte=f"{plan.date_to}T23:59:59Z" if plan.date_to else None,
        )
        must.append(
            models.Filter(
                should=[
                    models.FieldCondition(key="note_date", range=date_range),
                    models.FieldCondition(key="entry_date", range=date_range),
                ]
            )
        )

    if plan.kanban_board:
        must.append(models.FieldCondition(key="board.name", match=models.MatchValue(value=plan.kanban_board)))
    if plan.kanban_column:
        must.append(models.FieldCondition(key="board.column", match=models.MatchValue(value=plan.kanban_column)))
    if plan.kanban_columns:
        must.append(
            models.FieldCondition(
                key="board.column", match=models.MatchAny(any=list(plan.kanban_columns))
            )
        )
    if plan.kanban_status:
        must.append(models.FieldCondition(key="board.status", match=models.MatchValue(value=plan.kanban_status)))
    if plan.kanban_statuses:
        must.append(
            models.FieldCondition(
                key="board.status", match=models.MatchAny(any=list(plan.kanban_statuses))
            )
        )
    if plan.kanban_checked is not None:
        must.append(
            models.FieldCondition(key="board.checked", match=models.MatchValue(value=plan.kanban_checked))
        )

    return models.Filter(must=must)
