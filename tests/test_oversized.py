"""Coverage for the chunking path: no entry silently overruns the encoder."""

from pathlib import Path

import pytest

from zenith.core.config import Settings
from zenith.core.contracts import EntryType, WarningType
from zenith.parser.service import VaultParser
from zenith.parser.tokens import content_budget, estimate_tokens


FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "vault"


def settings(vault: Path) -> Settings:
    return Settings("http://unused", vault, vault / "models", "entries", "127.0.0.1", 8080)


def parse(vault: Path):
    return {note.path: note for note in VaultParser(settings(vault)).parse_vault()}


def test_oversized_section_becomes_several_entries_that_keep_their_heading() -> None:
    note = parse(FIXTURE_VAULT)["freeform/Oversized.md"]
    pieces = [entry for entry in note.entries if entry.heading == "Migration Notes"]

    assert len(pieces) > 1
    assert {entry.entry_type for entry in pieces} == {EntryType.FREEFORM_SECTION}
    assert {entry.heading_path for entry in pieces} == {("Oversized Reference", "Migration Notes")}
    assert len({entry.entry_id for entry in pieces}) == len(pieces)


def test_the_tail_of_an_oversized_section_is_still_indexed() -> None:
    note = parse(FIXTURE_VAULT)["freeform/Oversized.md"]
    text = "\n".join(entry.text for entry in note.entries)
    # Before section chunking this term sat past the encoder window and was
    # unreachable by dense search even though the entry claimed those lines.
    assert "saffron" in text
    tail = next(entry for entry in note.entries if "saffron" in entry.text)
    assert estimate_tokens(tail.embedding_text) <= 128


def test_a_section_that_fits_stays_one_entry() -> None:
    note = parse(FIXTURE_VAULT)["freeform/Oversized.md"]
    assert len([entry for entry in note.entries if entry.heading == "Short Section"]) == 1


def test_a_headless_note_produces_freeform_chunks() -> None:
    note = parse(FIXTURE_VAULT)["freeform/Headless Long.md"]
    assert len(note.entries) > 1
    assert {entry.entry_type for entry in note.entries} == {EntryType.FREEFORM_CHUNK}
    assert all(entry.heading is None for entry in note.entries)
    assert all(entry.heading_path == () for entry in note.entries)


def test_every_fixture_entry_fits_the_dense_token_budget() -> None:
    for note in parse(FIXTURE_VAULT).values():
        for entry in note.entries:
            # The label block always ends at the first "Content: " marker.
            prefix = entry.embedding_text.split("Content: ", 1)[0] + "Content: "
            budget = content_budget(prefix)
            assert estimate_tokens(entry.text) <= budget, f"{entry.path} {entry.heading}"


def test_chunk_line_ranges_stay_inside_the_note_and_never_overlap(tmp_path: Path) -> None:
    for note in parse(FIXTURE_VAULT).values():
        total = len((FIXTURE_VAULT / note.path).read_text().splitlines())
        for entry in note.entries:
            assert 1 <= entry.source.start_line <= entry.source.end_line <= total


def test_chunk_identity_survives_an_insertion_earlier_in_the_note(tmp_path: Path) -> None:
    # Paragraphs wide enough that each fills its own chunk, which is the shape
    # an oversized note actually has.
    def paragraph(index: int) -> str:
        return (
            f"Paragraph {index} discusses deterministic identifiers, incremental "
            "reindexing, stale point removal, alias switching, and the reuse of "
            "embeddings whose input did not change between two runs of the indexer."
        )

    body = "\n\n".join(paragraph(index) for index in range(5))
    note_path = tmp_path / "Loose.md"
    note_path.write_text(body + "\n")
    before = {entry.text: entry.entry_id for entry in parse(tmp_path)["Loose.md"].entries}

    note_path.write_text("A brand new opening paragraph added at the very top.\n\n" + body + "\n")
    after = {entry.text: entry.entry_id for entry in parse(tmp_path)["Loose.md"].entries}

    shared = set(before) & set(after)
    assert len(shared) >= 3, "unchanged paragraphs should keep their chunk"
    # A positional key would renumber every chunk after the insertion and force
    # a re-encode of text that did not change.
    assert all(before[text] == after[text] for text in shared)


def test_repeated_identical_chunks_keep_distinct_identifiers(tmp_path: Path) -> None:
    paragraph = "This paragraph repeats word for word inside the very same note."
    (tmp_path / "Repeat.md").write_text("\n\n".join([paragraph] * 3) + "\n")
    entries = parse(tmp_path)["Repeat.md"].entries
    assert len({entry.entry_id for entry in entries}) == len(entries)


def test_an_unsplittable_paragraph_warns_instead_of_truncating_silently(tmp_path: Path) -> None:
    giant = " ".join(f"sentence{index} about indexing and retrieval" for index in range(120))
    (tmp_path / "Giant.md").write_text(f"# Giant\n\n## Section\n\n{giant}\n")
    note = parse(tmp_path)["Giant.md"]

    warning = next(w for w in note.warnings if w.kind is WarningType.TRUNCATED_EMBEDDING_INPUT)
    assert "not semantically searchable" in warning.message
    # One paragraph cannot be divided without cutting a sentence, so it stays
    # a single entry and the warning is the only honest signal available.
    assert len([entry for entry in note.entries if entry.heading == "Section"]) == 1


def test_parsing_is_repeatable(tmp_path: Path) -> None:
    first = parse(FIXTURE_VAULT)
    second = parse(FIXTURE_VAULT)
    assert [(p, [e.entry_id for e in n.entries]) for p, n in sorted(first.items())] == [
        (p, [e.entry_id for e in n.entries]) for p, n in sorted(second.items())
    ]


def test_an_oversized_kanban_card_warns_and_stays_one_point(tmp_path: Path) -> None:
    body = " ".join(f"detail{index} about the migration and the rollback plan" for index in range(80))
    (tmp_path / "kanban").mkdir()
    (tmp_path / "kanban" / "Board.md").write_text(
        f"---\nkanban-plugin: board\n---\n\n# Board\n\n## ToDo\n\n- [ ] Card one\n\t{body}\n"
    )
    note = parse(tmp_path)["kanban/Board.md"]

    assert len(note.entries) == 1
    assert note.entries[0].entry_type is EntryType.KANBAN_CARD
    warning = next(w for w in note.warnings if w.kind is WarningType.TRUNCATED_EMBEDDING_INPUT)
    assert "a card is never divided" in warning.message


def test_a_normal_kanban_card_does_not_warn() -> None:
    note = parse(FIXTURE_VAULT)["kanban/Kitchen App.md"]
    assert not [w for w in note.warnings if w.kind is WarningType.TRUNCATED_EMBEDDING_INPUT]
