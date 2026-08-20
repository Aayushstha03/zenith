"""Paragraph-aware chunking for loose and headingless Markdown."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Chunk:
    start_zero: int
    end_zero: int


def paragraph_chunks(lines: list[str], start_zero: int, end_zero: int, max_chars: int = 1200) -> tuple[Chunk, ...]:
    paragraphs: list[Chunk] = []
    cursor = start_zero
    while cursor < end_zero:
        while cursor < end_zero and not lines[cursor].strip():
            cursor += 1
        if cursor >= end_zero:
            break
        paragraph_start = cursor
        while cursor < end_zero and lines[cursor].strip():
            cursor += 1
        paragraphs.append(Chunk(paragraph_start, cursor))

    chunks: list[Chunk] = []
    current_start: int | None = None
    current_end = 0
    current_size = 0
    for paragraph in paragraphs:
        size = sum(len(line) + 1 for line in lines[paragraph.start_zero : paragraph.end_zero])
        if current_start is not None and current_size + size > max_chars:
            chunks.append(Chunk(current_start, current_end))
            current_start = None
            current_size = 0
        if current_start is None:
            current_start = paragraph.start_zero
        current_end = paragraph.end_zero
        current_size += size
    if current_start is not None:
        chunks.append(Chunk(current_start, current_end))
    return tuple(chunks)
