from pathlib import Path

import pytest

from zenith.core.config import Settings
from zenith.core.contracts import NoteType
from zenith.parser.discovery import classify_path, discover_markdown


VAULT = Path(__file__).parent / "fixtures" / "vault"


def settings() -> Settings:
    return Settings("http://qdrant:6333", VAULT.resolve(), Path("/tmp/models"), "entries", "127.0.0.1", 8080)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("logs/2026-08-20.md", NoteType.LOG),
        ("logs/nested/another.md", NoteType.LOG),
        ("kanban/Kitchen App.md", NoteType.KANBAN),
        ("projects/News Resolution.md", NoteType.STANDARD),
        ("misc/logs/not-special.md", NoteType.STANDARD),
        ("Daily/2026-08-20.md", NoteType.STANDARD),
        ("root.md", NoteType.STANDARD),
    ],
)
def test_only_configured_first_path_segments_are_special(path: str, expected: NoteType) -> None:
    assert classify_path(path, settings()) is expected


def test_discovery_is_recursive_sorted_and_excludes_configured_directories() -> None:
    paths = discover_markdown(settings())
    relative = [path.relative_to(VAULT).as_posix() for path in paths]
    assert relative == sorted(relative, key=str.casefold)
    assert "messy/deep/random/Mixed Note.md" in relative
    assert ".obsidian/ignored.md" not in relative


def test_requested_paths_cannot_escape_vault() -> None:
    with pytest.raises(ValueError):
        discover_markdown(settings(), ["../outside.md"])
