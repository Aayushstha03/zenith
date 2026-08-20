from zenith.parser.chunking import paragraph_chunks


def test_paragraph_chunking_preserves_boundaries() -> None:
    lines = ["a" * 10, "", "b" * 10, "", "c" * 10]
    chunks = paragraph_chunks(lines, 0, len(lines), max_chars=22)
    assert [(chunk.start_zero, chunk.end_zero) for chunk in chunks] == [(0, 3), (4, 5)]


def test_empty_ranges_make_no_chunks() -> None:
    assert paragraph_chunks(["", "  "], 0, 2) == ()
