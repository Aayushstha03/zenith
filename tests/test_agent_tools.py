"""The tool surface the answering model is given, tested without a model."""

from pathlib import Path
import re
import shutil
import typing
import warnings

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import Tool
from pydantic_ai.usage import RunUsage
from qdrant_client import QdrantClient, models

from zenith.agent import tools
from zenith.agent.projections import MAX_ENTRY_CHARS, MAX_NOTE_CHARS
from zenith.core.config import Settings
from zenith.index.rebuild import IndexRebuilder
from zenith.library import Zenith


FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "vault"


class HashEncoders:
    def encode(self, texts: list[str]):
        return [
            {"semantic": dense, "text-bm25": sparse}
            for dense, sparse in zip(
                self.encode_dense(texts), self.encode_sparse(texts), strict=True
            )
        ]

    def encode_dense(self, texts: list[str]) -> list[list[float]]:
        return [[float(hash((text, index)) % 7) for index in range(384)] for text in texts]

    def encode_sparse(self, texts: list[str]) -> list[models.SparseVector]:
        vectors = []
        for text in texts:
            indices = sorted({abs(hash(word)) % 997 for word in re.findall(r"[a-z0-9]+", text.lower())}) or [0]
            vectors.append(models.SparseVector(indices=indices, values=[1.0] * len(indices)))
        return vectors


@pytest.fixture
def ctx(tmp_path: Path) -> RunContext[Zenith]:
    vault = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, vault)
    settings = Settings(
        "http://unused", vault, tmp_path / "models", "entries", "127.0.0.1", 8080
    )
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    encoders = HashEncoders()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        IndexRebuilder(settings, client=client, encoders=encoders).rebuild()
    api = Zenith(settings, client=client, encoders=encoders)
    return RunContext(deps=api, model=TestModel(), usage=RunUsage())


def test_every_tool_declares_a_flat_described_schema() -> None:
    for function in tools.TOOLS:
        definition = Tool(function, require_parameter_descriptions=True).tool_def
        assert definition.description
        schema = definition.parameters_json_schema
        for name, spec in schema.get("properties", {}).items():
            assert spec.get("description"), f"{definition.name}.{name} has no description"
            # Flat arguments only: a local model handles scalars and string
            # lists, and fumbles nested objects.
            types = {spec.get("type")} | {
                option.get("type") for option in spec.get("anyOf", [])
            }
            assert types <= {"string", "integer", "boolean", "array", "null", None}
            if "array" in types:
                assert spec.get("items", spec.get("anyOf", [{}])[0].get("items", {})).get(
                    "type"
                ) == "string"


def test_every_tool_takes_an_annotated_run_context() -> None:
    """An unannotated `ctx` is silently treated as a model-supplied argument.

    pydantic-ai decides by annotation, not by parameter name, so dropping the
    annotation would hand the model a `ctx` argument to invent and would stop
    the run's tool calls being counted against the usage limits.
    """
    import inspect

    for function in tools.TOOLS:
        first = next(iter(inspect.signature(function).parameters.values()))
        annotation = inspect.get_annotations(function, eval_str=True)[first.name]
        assert typing.get_origin(annotation) is RunContext
        assert typing.get_args(annotation) == (Zenith,)


def test_the_write_and_unbounded_operations_are_not_offered() -> None:
    offered = {function.__name__ for function in tools.TOOLS}
    assert offered == {
        "search_notes",
        "read_note",
        "expand_context",
        "find_backlinks",
        "find_tasks",
    }
    assert "reindex" not in offered
    assert "export_graph" not in offered


def test_search_projects_entries_with_citable_fields(ctx: RunContext[Zenith]) -> None:
    results = tools.search_notes(ctx, "pipeline", limit=3)
    assert results
    first = results[0]
    assert set(first) >= {"entry_id", "note", "path", "lines", "date", "date_kind", "text"}
    assert re.fullmatch(r"\d+-\d+", first["lines"])
    # Similarity is not proof of an exact phrase, so it must not claim to be.
    assert "exact_match_verified" not in first


def test_exact_search_reports_a_verified_literal_match(ctx: RunContext[Zenith]) -> None:
    results = tools.search_notes(ctx, "fried chicken", exact=True)
    assert results
    assert all(result["exact_match_verified"] is True for result in results)


def test_an_undated_entry_is_never_given_a_date(ctx: RunContext[Zenith]) -> None:
    results = tools.search_notes(ctx, "pipeline", limit=20)
    for result in results:
        if result["date_kind"] is None:
            assert result["date"] is None
        else:
            assert result["date_kind"] in {"entry_date", "note_date"}
            assert result["date"]


def test_read_note_returns_the_whole_file_within_a_cap(ctx: RunContext[Zenith]) -> None:
    note = tools.read_note(ctx, "News Resolution")
    assert note["path"] == "projects/News Resolution.md"
    assert note["content"].startswith("# News Resolution")
    assert len(note["content"]) <= MAX_NOTE_CHARS + 32
    assert "content_truncated" not in note


def test_expand_context_keeps_the_evidence_labels(ctx: RunContext[Zenith]) -> None:
    entry_id = tools.search_notes(ctx, "pipeline", limit=1)[0]["entry_id"]
    expansion = tools.expand_context(ctx, entry_id)
    assert expansion["source_entry_id"] == entry_id
    assert expansion["items"]
    labels = {label for item in expansion["items"] for label in item["evidence"]}
    assert "direct_evidence" in labels
    assert all("hops" in item for item in expansion["items"])


def test_backlinks_and_tasks_resolve_by_name(ctx: RunContext[Zenith]) -> None:
    backlinks = tools.find_backlinks(ctx, "News Resolution")
    assert backlinks
    assert all("path" in result for result in backlinks)

    open_cards = tools.find_tasks(ctx, board="Kitchen App", columns=["ToDo"], checked=False)
    assert open_cards
    assert all(card["task"]["column"] == "ToDo" for card in open_cards)
    assert all(card["task"]["checked"] is False for card in open_cards)


def test_a_bad_name_becomes_an_instruction_the_model_can_act_on(
    ctx: RunContext[Zenith],
) -> None:
    with pytest.raises(ModelRetry, match="note not found"):
        tools.read_note(ctx, "No Such Note")

    # An ambiguous name must hand back the candidates, not just the failure.
    with pytest.raises(ModelRetry, match="ambiguous note title") as ambiguous:
        tools.read_note(ctx, "Shared")
    assert ".md" in str(ambiguous.value)

    with pytest.raises(ModelRetry, match="entry not found"):
        tools.expand_context(ctx, "not-an-entry")


def test_limits_are_clamped_rather_than_trusted(ctx: RunContext[Zenith]) -> None:
    assert len(tools.search_notes(ctx, "the", limit=999)) <= 20
    assert tools.search_notes(ctx, "the", limit=0)


def test_a_clipped_entry_only_claims_a_verified_match_it_can_show() -> None:
    """`pack` emits an oversized single paragraph rather than cut a sentence.

    Such an entry gets clipped here, so a head-clip can drop the very phrase
    the match was verified against and still assert it was proven.
    """
    from zenith.agent import projections
    from zenith.core.contracts import EntryType, NoteType, RetrievalMode, SearchResult

    phrase = "fried chicken"
    text = "a" * 3000 + f" {phrase} " + "b" * 3000
    result = SearchResult(
        "e", "n", "p.md", "N", NoteType.STANDARD, EntryType.FREEFORM_SECTION,
        RetrievalMode.LITERAL, text, text, None, (), 1, 9, None, None, (), (),
        verified=True,
    )

    windowed = projections.entry(result, match=phrase)
    assert windowed["text_truncated"] is True
    assert phrase in windowed["text"]
    assert windowed["exact_match_verified"] is True
    assert len(windowed["text"]) <= MAX_ENTRY_CHARS + 64

    # Without the phrase to centre on, the clip cannot show the proof, so the
    # claim of proof is withheld rather than made on unseen text.
    blind = projections.entry(result)
    assert blind["text_truncated"] is True
    assert phrase not in blind["text"]
    assert "exact_match_verified" not in blind


def test_an_unknown_kanban_column_names_the_real_ones(ctx: RunContext[Zenith]) -> None:
    """A case-sensitive miss would otherwise read as an empty board."""
    with pytest.raises(ModelRetry, match="unknown Kanban column") as unknown:
        tools.find_tasks(ctx, board="Kitchen App", columns=["To Do"])
    assert "ToDo" in str(unknown.value)

    # A different case is a near miss, not a mistake, so it is resolved.
    assert tools.find_tasks(ctx, board="Kitchen App", columns=["todo"])


def test_find_tasks_never_claims_a_card_contains_the_query(ctx: RunContext[Zenith]) -> None:
    cards = tools.find_tasks(ctx, board="Kitchen App", query="recipe", limit=3)
    assert cards
    assert all("exact_match_verified" not in card for card in cards)


def test_search_narrows_by_tag_and_by_date(ctx: RunContext[Zenith]) -> None:
    """The filters are how a question about a period, or a topic, stays honest.

    A model that cannot narrow searches the whole vault and answers from
    whatever ranked highest, which is not the same as what the question asked.
    """
    tagged = tools.search_notes(ctx, "tag", tags=["journal"], limit=5)
    assert tagged
    assert all("journal" in result["tags"] for result in tagged)

    dated = tools.search_notes(
        ctx, "pipeline", date_from="2026-08-19", date_to="2026-08-19", limit=10
    )
    assert dated
    assert all(result["date"] == "2026-08-19" for result in dated)


def test_expand_context_reports_the_links_it_could_not_resolve(
    ctx: RunContext[Zenith],
) -> None:
    """A link that leads nowhere is evidence too.

    Dropping it silently would leave the model to read the remaining items as
    the whole of what the entry points at, and answer as if nothing were
    missing.
    """
    entry_id = tools.search_notes(ctx, "Missing", exact=True, limit=5)[0]["entry_id"]
    unresolved = tools.expand_context(ctx, entry_id)["unresolved_links"]
    reasons = {item["target"]: item["reason"] for item in unresolved}
    assert reasons["Does Not Exist"] == "missing"
    assert reasons["Shared"] == "ambiguous"


def test_a_column_is_resolved_across_every_board_when_none_is_named(
    ctx: RunContext[Zenith],
) -> None:
    """Without a board, a column has to be checked against all of them.

    `Done` exists on one board only. Resolving it against a single board would
    reject a column that really does exist somewhere in the vault.
    """
    assert tools.find_tasks(ctx, columns=["Done"], limit=20)

    # Named against the board that lacks it, the same column is still a miss,
    # and the reply names that board's columns rather than the whole vault's.
    with pytest.raises(ModelRetry, match="unknown Kanban column") as missing:
        tools.find_tasks(ctx, board="Kitchen App", columns=["Done"])
    listed = str(missing.value).split("this board has ")[1]
    assert "ToDo" in listed
    assert "Done" not in listed


def test_an_oversized_note_is_marked_as_a_fragment() -> None:
    """A whole note has no size bound, so `read_note` can still clip one.

    The flag is what stops the model concluding that a note does not mention
    something, from a part of it that does not.
    """
    from zenith.agent import projections
    from zenith.core.contracts import NoteContent, NoteType

    content = NoteContent("n", "p.md", "N", NoteType.STANDARD, "a" * (MAX_NOTE_CHARS + 500))
    projected = projections.note(content)

    assert projected["content_truncated"] is True
    assert projected["content"].endswith("[... truncated]")
    assert len(projected["content"]) <= MAX_NOTE_CHARS + 64


def test_a_library_bug_is_not_disguised_as_a_model_mistake() -> None:
    """`_repair` turns a bad argument into a retry. A defect is not one.

    Handing a real fault back to the model as a retry would spend the whole
    usage limit re-calling a tool that cannot work, and hide the fault.
    """
    with pytest.raises(TypeError):
        with tools._repair():
            raise TypeError("the library is broken")
