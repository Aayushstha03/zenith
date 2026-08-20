from qdrant_client import models

from zenith.index.schema import PAYLOAD_INDEXES, create_collection


class Client:
    def __init__(self) -> None:
        self.created = None
        self.indexes: list[tuple[str, object]] = []

    def create_collection(self, **kwargs: object) -> None:
        self.created = kwargs

    def create_payload_index(self, **kwargs: object) -> None:
        self.indexes.append((kwargs["field_name"], kwargs["field_schema"]))


def test_collection_has_named_dense_sparse_and_filter_indexes() -> None:
    client = Client()
    create_collection(client, "build")

    dense = client.created["vectors_config"]["semantic"]
    sparse = client.created["sparse_vectors_config"]["text-bm25"]
    assert dense.size == 384
    assert dense.distance is models.Distance.COSINE
    assert sparse.modifier is models.Modifier.IDF
    assert client.indexes == list(PAYLOAD_INDEXES)
