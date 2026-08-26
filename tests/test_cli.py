import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from zenith.core.config import Settings
from zenith.runtime.cli import build_parser, main


@pytest.fixture
def cli_settings(monkeypatch, tmp_path: Path) -> Settings:
    settings = Settings(
        "http://unused", tmp_path, tmp_path, "entries", "127.0.0.1", 8080
    )
    monkeypatch.setattr("zenith.runtime.cli.Settings.from_env", lambda: settings)
    return settings


@pytest.mark.parametrize(
    "argv",
    [
        ["index", "init"],
        ["index", "rebuild"],
        ["search", "query", "--mode", "hybrid"],
        ["note", "get", "Note"],
        ["note", "read", "Note"],
        ["entry", "get", "entry-id"],
        ["links", "outgoing", "note-id"],
        ["links", "backlinks", "note-id"],
        ["links", "resolve", "note-id", "Target"],
        ["search-within", "note-id", "query"],
        ["context", "entry-id"],
        ["warnings", "--type", "missing_link"],
        ["kanban", "list"],
        ["kanban", "get", "Board"],
        ["kanban", "find", "task", "--checked", "false"],
        ["graph", "export"],
        ["diagnose"],
    ],
)
def test_phase_7_command_surface_parses(argv: list[str]) -> None:
    assert build_parser().parse_args(argv).command


def test_search_command_emits_stable_json(monkeypatch, cli_settings, capsys) -> None:
    calls: list[dict[str, object]] = []

    class FakeZenith:
        def __init__(self, settings: Settings) -> None:
            assert settings is cli_settings

        def find_entries(self, **kwargs: object):
            calls.append(kwargs)
            return (SimpleNamespace(to_dict=lambda: {"entry_id": "entry-1"}),)

    monkeypatch.setattr("zenith.runtime.cli.Zenith", FakeZenith)
    code = main(
        [
            "search",
            "fried chicken",
            "--mode",
            "literal",
            "--tag-all",
            "recipe",
            "--limit",
            "3",
        ]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {"results": [{"entry_id": "entry-1"}]}
    assert calls[0]["exact_text"] == "fried chicken"
    assert calls[0]["tags_all"] == ("recipe",)
    assert calls[0]["limit"] == 3


def test_cli_validation_errors_are_json_and_exit_two(monkeypatch, cli_settings, capsys) -> None:
    monkeypatch.setattr("zenith.runtime.cli.Zenith", lambda _: object())

    code = main(["search", "--mode", "literal"])
    error = json.loads(capsys.readouterr().err)

    assert code == 2
    assert error["error"]["type"] == "ValueError"
    assert "requires query text" in error["error"]["message"]


def test_unknown_command_is_json_and_exit_two(cli_settings, capsys) -> None:
    code = main(["not-a-command"])
    error = json.loads(capsys.readouterr().err)
    assert code == 2
    assert error["error"]["type"] == "ValueError"


def test_note_read_command_emits_the_markdown_file(monkeypatch, cli_settings, capsys) -> None:
    class FakeZenith:
        def __init__(self, settings: Settings) -> None:
            assert settings is cli_settings

        def read_note(self, path_or_title: str):
            assert path_or_title == "News Resolution"
            return SimpleNamespace(
                to_dict=lambda: {
                    "content": "# News Resolution\n",
                    "note_id": "uuid",
                    "note_type": "standard",
                    "path": "projects/News Resolution.md",
                    "title": "News Resolution",
                }
            )

        def get_note(self, path_or_title: str):  # pragma: no cover - must not run
            raise AssertionError("note read must not fall through to note get")

    monkeypatch.setattr("zenith.runtime.cli.Zenith", FakeZenith)
    assert main(["note", "read", "News Resolution"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["content"] == "# News Resolution\n"
    assert list(payload) == sorted(payload)
