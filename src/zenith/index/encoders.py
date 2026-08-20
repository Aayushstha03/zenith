"""Pinned local dense and sparse encoding."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from qdrant_client import models

from zenith.core.config import Settings


DENSE_DIMENSIONS = 384


class LocalEncoders:
    """Load FastEmbed models once and encode batches into Qdrant vectors."""

    def __init__(
        self,
        settings: Settings,
        dense: Any | None = None,
        sparse: Any | None = None,
    ) -> None:
        if dense is None or sparse is None:
            from fastembed import SparseTextEmbedding, TextEmbedding

            dense = dense or TextEmbedding(
                model_name=settings.dense_model,
                cache_dir=str(settings.model_cache_path),
                local_files_only=True,
            )
            sparse = sparse or SparseTextEmbedding(
                model_name=settings.sparse_model,
                cache_dir=str(settings.model_cache_path),
                local_files_only=True,
                language="english",
                disable_stemmer=False,
            )
        self.dense = dense
        self.sparse = sparse

    def encode(self, texts: Sequence[str]) -> list[dict[str, object]]:
        dense_vectors = self.encode_dense(texts)
        sparse_vectors = self.encode_sparse(texts)
        return [
            {"semantic": dense, "text-bm25": sparse}
            for dense, sparse in zip(dense_vectors, sparse_vectors, strict=True)
        ]

    def encode_dense(self, texts: Sequence[str]) -> list[list[float]]:
        dense_vectors = list(self.dense.embed(list(texts)))
        if len(dense_vectors) != len(texts):
            raise RuntimeError("dense encoder returned a different number of vectors than inputs")

        result: list[list[float]] = []
        for dense in dense_vectors:
            dense_values = _float_list(dense)
            if len(dense_values) != DENSE_DIMENSIONS:
                raise RuntimeError(
                    f"dense model returned {len(dense_values)} dimensions; expected {DENSE_DIMENSIONS}"
                )
            result.append(dense_values)
        return result

    def encode_sparse(self, texts: Sequence[str]) -> list[models.SparseVector]:
        sparse_vectors = list(self.sparse.embed(list(texts)))
        if len(sparse_vectors) != len(texts):
            raise RuntimeError("sparse encoder returned a different number of vectors than inputs")

        result: list[models.SparseVector] = []
        for sparse in sparse_vectors:
            indices = _int_list(sparse.indices)
            values = _float_list(sparse.values)
            if not indices or len(indices) != len(values):
                raise RuntimeError("sparse model returned an invalid or empty vector")
            result.append(models.SparseVector(indices=indices, values=values))
        return result


def _float_list(values: Iterable[object]) -> list[float]:
    return [float(value) for value in values]


def _int_list(values: Iterable[object]) -> list[int]:
    return [int(value) for value in values]
