from pathlib import Path

from watchdog.events import FileCreatedEvent, FileMovedEvent, FileOpenedEvent

from zenith.core.config import Settings
from zenith.parser.watcher import MarkdownChangeHandler


def settings(vault: Path) -> Settings:
    return Settings("http://qdrant:6333", vault, Path("/tmp/models"), "entries", "127.0.0.1", 8080)


def test_watcher_batches_normalized_markdown_paths(tmp_path: Path) -> None:
    received: list[tuple[str, ...]] = []
    handler = MarkdownChangeHandler(settings(tmp_path), received.append, debounce_seconds=60)
    first = tmp_path / "messy" / "Note.md"
    first.parent.mkdir()
    first.touch()
    second = tmp_path / "logs" / "2026-08-20.md"
    second.parent.mkdir()
    second.touch()

    handler.on_any_event(FileCreatedEvent(str(second)))
    handler.on_any_event(FileCreatedEvent(str(first)))
    handler.flush()

    assert received == [("logs/2026-08-20.md", "messy/Note.md")]
    handler.close()


def test_watcher_tracks_both_sides_of_rename_and_ignores_non_markdown(tmp_path: Path) -> None:
    received: list[tuple[str, ...]] = []
    handler = MarkdownChangeHandler(settings(tmp_path), received.append, debounce_seconds=60)
    old = tmp_path / "old.md"
    new = tmp_path / "nested" / "new.md"
    handler.on_any_event(FileMovedEvent(str(old), str(new)))
    handler.on_any_event(FileCreatedEvent(str(tmp_path / "image.png")))
    handler.on_any_event(FileOpenedEvent(str(tmp_path / "opened.md")))
    handler.flush()

    assert received == [("nested/new.md", "old.md")]
    handler.close()
