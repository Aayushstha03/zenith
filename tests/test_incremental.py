from pathlib import Path
from types import SimpleNamespace

import pytest
from qdrant_client import models

from zenith.core.config import Settings
from zenith.index.incremental import IncrementalIndexer
from zenith.index.links import resolve_links
from zenith.parser.service import VaultParser


class TrackingEncoders:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def encode(self, texts: list[str]):
        self.texts.extend(texts)
        return [
            {
                "semantic": [float(len(text))] * 384,
                "text-bm25": models.SparseVector(indices=[1], values=[1.0]),
            }
            for text in texts
        ]


class StateClient:
    def __init__(self) -> None:
        self.records: dict[str, SimpleNamespace] = {}
        self.upsert_calls = 0
        self.deleted: list[str] = []
        self.fail_delete_once = False

    def scroll(self, **_: object):
        return list(self.records.values()), None

    def upsert(self, *, points: list[object], **_: object) -> None:
        self.upsert_calls += 1
        for point in points:
            self.records[str(point.id)] = SimpleNamespace(
                id=point.id,
                payload=point.payload,
                vector=point.vector,
            )

    def delete(self, *, points_selector: list[str], **_: object) -> None:
        if self.fail_delete_once:
            self.fail_delete_once = False
            raise RuntimeError("interrupted delete")
        self.deleted.extend(points_selector)
        for point_id in points_selector:
            self.records.pop(point_id)


def settings(vault: Path) -> Settings:
    return Settings("http://unused", vault, vault / "models", "entries", "127.0.0.1", 8080)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_unchanged_run_skips_writes_and_embeddings(tmp_path: Path) -> None:
    write(tmp_path / "Note.md", "# Note\n\n## Section\nhello\n")
    client = StateClient()
    encoders = TrackingEncoders()
    indexer = IncrementalIndexer(settings(tmp_path), client=client, encoders=encoders)

    first = indexer.reindex()
    calls_after_first = client.upsert_calls
    encoded_after_first = len(encoders.texts)
    second = indexer.reindex()

    assert first.inserted == first.embeddings_generated == 1
    assert second.skipped == 1
    assert second.updated == second.inserted == second.deleted == 0
    assert second.embeddings_generated == 0
    assert client.upsert_calls == calls_after_first
    assert len(encoders.texts) == encoded_after_first

    write(tmp_path / "Note.md", "# Note\n\n## Section\ngoodbye\n")
    changed = indexer.reindex(["Note.md"])
    assert changed.updated == changed.embeddings_generated == 1
    assert changed.inserted == changed.deleted == 0


def test_change_add_and_delete_converge_without_reencoding_unchanged_inputs(tmp_path: Path) -> None:
    source_path = tmp_path / "Source.md"
    first_target = tmp_path / "one" / "Target.md"
    second_target = tmp_path / "two" / "Target.md"
    write(source_path, "# Source\n\nSee [[Target]].\n")
    write(first_target, "# First Target\n\nBody one.\n")
    client = StateClient()
    encoders = TrackingEncoders()
    indexer = IncrementalIndexer(settings(tmp_path), client=client, encoders=encoders)
    initial = indexer.reindex()
    assert initial.embeddings_generated == 2

    write(second_target, "# Second Target\n\nBody two.\n")
    added = indexer.reindex(["two/Target.md"])
    assert added.inserted == 1
    assert added.embeddings_generated == 1
    assert added.embeddings_reused == 1
    source = next(record for record in client.records.values() if record.payload["path"] == "Source.md")
    assert source.payload["outgoing_links"][0]["resolution"] == "ambiguous"

    second_target.unlink()
    deleted = indexer.reindex(["two/Target.md"])
    assert deleted.deleted == 1
    assert deleted.embeddings_generated == 0
    assert deleted.embeddings_reused == 1
    source = next(record for record in client.records.values() if record.payload["path"] == "Source.md")
    assert source.payload["outgoing_links"][0]["resolution"] == "resolved"

    renamed_target = tmp_path / "one" / "Renamed.md"
    first_target.rename(renamed_target)
    renamed = indexer.reindex(["one/Target.md", "one/Renamed.md"])
    assert renamed.inserted == renamed.deleted == renamed.embeddings_generated == 1
    assert renamed.embeddings_reused == 1
    source = next(record for record in client.records.values() if record.payload["path"] == "Source.md")
    assert source.payload["outgoing_links"][0]["resolution"] == "missing"

    expected_notes = resolve_links(VaultParser(settings(tmp_path)).parse_vault())
    expected_entries = [entry for note in expected_notes for entry in note.entries]
    expected_payloads = {entry.entry_id: indexer._payload(entry) for entry in expected_entries}
    assert {point_id: record.payload for point_id, record in client.records.items()} == expected_payloads


def test_interrupted_update_converges_when_rerun(tmp_path: Path) -> None:
    first = tmp_path / "First.md"
    second = tmp_path / "Second.md"
    write(first, "# First\n\nOne.\n")
    write(second, "# Second\n\nTwo.\n")
    client = StateClient()
    indexer = IncrementalIndexer(
        settings(tmp_path), client=client, encoders=TrackingEncoders()
    )
    assert indexer.reindex().inserted == 2

    second.unlink()
    client.fail_delete_once = True
    with pytest.raises(RuntimeError, match="interrupted"):
        indexer.reindex(["Second.md"])

    recovered = indexer.reindex(["Second.md"])
    assert recovered.deleted == 1
    assert {record.payload["path"] for record in client.records.values()} == {"First.md"}
