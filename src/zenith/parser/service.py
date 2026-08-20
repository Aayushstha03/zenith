"""Deterministic orchestration for log, standard, and Kanban notes."""

from __future__ import annotations

from collections import defaultdict
import hashlib
from pathlib import Path

from zenith.core.config import Settings
from zenith.core.contracts import (
    EntryType,
    IndexWarning,
    NoteType,
    ParsedEntry,
    ParsedNote,
    SourceRange,
    WarningType,
)
from zenith.core.identity import entry_id, note_id
from zenith.parser.chunking import paragraph_chunks
from zenith.parser.discovery import classify_path, discover_markdown
from zenith.parser.kanban import parse_kanban_entries
from zenith.parser.markdown import (
    Heading,
    headings,
    markdown_tokens,
    note_title,
    parse_frontmatter,
    prose_between,
    meaningful_line_range,
    valid_iso_date,
)


PARSER_VERSION = "2.1.0"


class VaultParser:
    def __init__(self, settings: Settings, vault_id: str = "personal") -> None:
        self.settings = settings
        self.vault_id = vault_id

    def parse_vault(self, requested: list[str] | None = None) -> tuple[ParsedNote, ...]:
        return tuple(self.parse_file(path) for path in discover_markdown(self.settings, requested))

    def parse_file(self, file_path: Path) -> ParsedNote:
        vault = self.settings.vault_path.resolve()
        resolved = file_path.resolve()
        relative = resolved.relative_to(vault).as_posix()
        content = resolved.read_text(encoding="utf-8")
        lines = content.splitlines()
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        note_uuid = str(note_id(self.vault_id, relative))
        note_type = classify_path(relative, self.settings)
        frontmatter = parse_frontmatter(content)
        tokens = markdown_tokens(content)
        parsed_headings = tuple(
            heading for heading in headings(tokens, len(lines)) if heading.line > frontmatter.body_start
        )
        title = note_title(frontmatter, parsed_headings, resolved.stem)
        warnings: list[IndexWarning] = []
        if frontmatter.warning:
            warnings.append(IndexWarning(WarningType.PARSER_FAILURE, relative, frontmatter.warning, 1))

        metadata = dict(frontmatter.values)
        if note_type is NoteType.KANBAN:
            entries, kanban_warnings, kanban_metadata = parse_kanban_entries(
                lines=lines,
                tokens=tokens,
                parsed_headings=parsed_headings,
                frontmatter=frontmatter,
                path=relative,
                title=title,
                note_uuid=note_uuid,
                settings=self.settings,
            )
            metadata.update(kanban_metadata)
            warnings.extend(kanban_warnings)
        else:
            note_date = self._log_date(resolved.stem, lines, frontmatter.body_start) if note_type is NoteType.LOG else None
            entries, entry_warnings = self._parse_open_entries(
                note_type=note_type,
                note_date=note_date,
                lines=lines,
                tokens=tokens,
                parsed_headings=parsed_headings,
                body_start=frontmatter.body_start,
                relative=relative,
                title=title,
                note_uuid=note_uuid,
                content_hash=content_hash,
            )
            warnings.extend(entry_warnings)
            if note_type is NoteType.LOG and note_date is None:
                warnings.append(IndexWarning(WarningType.INVALID_DATE, relative, "log note has no valid date"))

        return ParsedNote(
            note_id=note_uuid,
            path=relative,
            title=title,
            note_type=note_type,
            content_hash=content_hash,
            entries=entries,
            warnings=tuple(_dedupe_warnings(warnings)),
            metadata=metadata,
        )

    def _log_date(self, stem: str, lines: list[str], body_start: int) -> str | None:
        from_filename = valid_iso_date(stem)
        if from_filename:
            return from_filename
        first = next((line.strip() for line in lines[body_start:] if line.strip()), "")
        return valid_iso_date(first)

    def _parse_open_entries(
        self,
        *,
        note_type: NoteType,
        note_date: str | None,
        lines: list[str],
        tokens: list,
        parsed_headings: tuple[Heading, ...],
        body_start: int,
        relative: str,
        title: str,
        note_uuid: str,
        content_hash: str,
    ) -> tuple[tuple[ParsedEntry, ...], tuple[IndexWarning, ...]]:
        entries: list[ParsedEntry] = []
        warnings: list[IndexWarning] = []
        occurrences: defaultdict[tuple[str, ...], int] = defaultdict(int)
        first_heading_zero = parsed_headings[0].line - 1 if parsed_headings else len(lines)

        loose_start = body_start
        if note_type is NoteType.LOG and note_date:
            first_nonempty = next((index for index in range(body_start, first_heading_zero) if lines[index].strip()), None)
            if first_nonempty is not None and valid_iso_date(lines[first_nonempty].strip()) == note_date:
                loose_start = first_nonempty + 1
        for chunk_index, chunk in enumerate(paragraph_chunks(lines, loose_start, first_heading_zero)):
            prose = prose_between(
                tokens, chunk.start_zero, chunk.end_zero, relative,
                self.settings.known_tags, self.settings.tag_aliases,
            )
            if not prose.text:
                continue
            entry_type = EntryType.DAILY_SECTION if note_type is NoteType.LOG else EntryType.FREEFORM_CHUNK
            entries.append(
                self._entry(
                    note_uuid, relative, title, note_type, entry_type, prose.text, None, (),
                    SourceRange(chunk.start_zero + 1, chunk.end_zero), note_date, None, prose,
                    f"preamble:{chunk_index}",
                )
            )
            warnings.extend(prose.warnings)

        for heading in parsed_headings:
            prose = prose_between(
                tokens, heading.content_start, heading.content_end, relative,
                self.settings.known_tags, self.settings.tag_aliases,
            )
            if not prose.text:
                continue
            occurrences[heading.path] += 1
            if note_type is NoteType.LOG:
                entry_type = EntryType.DAILY_SECTION
                entry_date = None
            elif heading.active_date:
                entry_type = EntryType.PROJECT_UPDATE
                entry_date = heading.active_date
            else:
                entry_type = EntryType.FREEFORM_SECTION
                entry_date = None
            structural_key = f"{'/'.join(heading.path)}:{occurrences[heading.path]}"
            body_range = meaningful_line_range(lines, heading.content_start, heading.content_end)
            source_end = body_range.end_line if body_range else heading.line
            entries.append(
                self._entry(
                    note_uuid, relative, title, note_type, entry_type, prose.text, heading.text,
                    heading.path, SourceRange(heading.line, source_end),
                    note_date, entry_date, prose, structural_key,
                )
            )
            warnings.extend(prose.warnings)
        return tuple(entries), tuple(warnings)

    @staticmethod
    def _entry(
        note_uuid: str,
        relative: str,
        title: str,
        note_type: NoteType,
        entry_type: EntryType,
        text: str,
        heading: str | None,
        heading_path: tuple[str, ...],
        source: SourceRange,
        note_date: str | None,
        entry_date: str | None,
        prose,
        structural_key: str,
    ) -> ParsedEntry:
        identifier = str(entry_id(note_uuid, entry_type, structural_key))
        return ParsedEntry(
            entry_id=identifier,
            note_id=note_uuid,
            path=relative,
            note_title=title,
            note_type=note_type,
            entry_type=entry_type,
            text=text,
            embedding_text=_embedding_text(note_type, entry_type, title, heading, note_date, entry_date, prose.tags, text),
            heading=heading,
            heading_path=heading_path,
            source=source,
            note_date=note_date,
            entry_date=entry_date,
            tags=prose.tags,
            outgoing_links=prose.links,
            web_links=prose.web_links,
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )


def _dedupe_warnings(warnings: list[IndexWarning]) -> list[IndexWarning]:
    result: list[IndexWarning] = []
    seen: set[tuple[object, ...]] = set()
    for warning in warnings:
        key = (warning.kind, warning.path, warning.message, warning.line)
        if key not in seen:
            seen.add(key)
            result.append(warning)
    return result


def _embedding_text(
    note_type: NoteType,
    entry_type: EntryType,
    title: str,
    heading: str | None,
    note_date: str | None,
    entry_date: str | None,
    tags: tuple[str, ...],
    text: str,
) -> str:
    labels = [f"Note: {title}"]
    if note_type is NoteType.LOG and note_date:
        labels.append(f"Date: {note_date}")
    if entry_date:
        labels.append(f"Date: {entry_date}")
    if heading:
        labels.append(f"Section: {heading}")
    if tags:
        labels.append(f"Tags: {', '.join(tags)}")
    labels.append(f"Content: {text}")
    return "\n".join(labels)
