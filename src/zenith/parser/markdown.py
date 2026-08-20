"""CommonMark AST helpers and eligible-prose extraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token
import yaml

from zenith.core.contracts import IndexWarning, Link, SourceRange, WarningType


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TAG_RE = re.compile(r"(?<![\w/#])#([A-Za-z][\w-]*)")
WIKI_RE = re.compile(r"\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]")
URL_RE = re.compile(r"https?://[^\s<>]+")


@dataclass(frozen=True, slots=True)
class Frontmatter:
    values: dict[str, Any]
    body_start: int
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class Heading:
    level: int
    text: str
    line: int
    content_start: int
    content_end: int
    path: tuple[str, ...]
    active_date: str | None


@dataclass(frozen=True, slots=True)
class Prose:
    text: str
    tags: tuple[str, ...]
    links: tuple[Link, ...]
    web_links: tuple[str, ...]
    warnings: tuple[IndexWarning, ...]


def parse_frontmatter(content: str) -> Frontmatter:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return Frontmatter({}, 0)
    try:
        closing = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration:
        return Frontmatter({}, 0, "frontmatter opening marker has no closing marker")
    raw = "\n".join(lines[1:closing])
    try:
        values = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        return Frontmatter({}, closing + 1, f"invalid frontmatter: {exc}")
    if not isinstance(values, dict):
        return Frontmatter({}, closing + 1, "frontmatter must be a mapping")
    return Frontmatter(values, closing + 1)


def markdown_tokens(content: str) -> list[Token]:
    return MarkdownIt("commonmark").parse(content)


def valid_iso_date(value: str) -> str | None:
    candidate = value.strip()
    if not DATE_RE.fullmatch(candidate):
        return None
    try:
        date.fromisoformat(candidate)
    except ValueError:
        return None
    return candidate


def headings(tokens: list[Token], total_lines: int) -> tuple[Heading, ...]:
    raw: list[tuple[int, int, str]] = []
    for index, token in enumerate(tokens):
        if token.type != "heading_open" or token.map is None:
            continue
        inline = tokens[index + 1]
        raw.append((int(token.tag[1:]), token.map[0], inline.content.strip()))

    result: list[Heading] = []
    stack: list[tuple[int, str, str | None]] = []
    for index, (level, line, text) in enumerate(raw):
        while stack and stack[-1][0] >= level:
            stack.pop()
        own_date = valid_iso_date(text)
        inherited_date = next((item[2] for item in reversed(stack) if item[2]), None)
        path = tuple(item[1] for item in stack) + (text,)
        next_line = raw[index + 1][1] if index + 1 < len(raw) else total_lines
        result.append(Heading(level, text, line + 1, line + 1, next_line, path, own_date or inherited_date))
        stack.append((level, text, own_date or inherited_date))
    return tuple(result)


def note_title(frontmatter: Frontmatter, parsed_headings: tuple[Heading, ...], fallback: str) -> str:
    explicit = frontmatter.values.get("title")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    first_h1 = next((heading.text for heading in parsed_headings if heading.level == 1), None)
    return first_h1 or fallback


def prose_between(
    tokens: list[Token],
    start_zero: int,
    end_zero: int,
    path: str,
    known_tags: tuple[str, ...],
    tag_aliases: tuple[tuple[str, str], ...],
) -> Prose:
    chunks: list[str] = []
    web_links: list[str] = []
    line_by_chunk: list[int] = []
    for token in tokens:
        if token.type != "inline" or token.map is None:
            continue
        if token.map[0] < start_zero or token.map[0] >= end_zero:
            continue
        parts: list[str] = []
        for child in token.children or ():
            if child.type in {"text", "softbreak", "hardbreak"}:
                parts.append("\n" if child.type != "text" else child.content)
            elif child.type == "link_open":
                href = child.attrGet("href")
                if href and href.startswith(("http://", "https://")):
                    web_links.append(href)
        text = "".join(parts).strip()
        if text:
            chunks.append(text)
            line_by_chunk.append(token.map[0] + 1)

    text = "\n".join(chunks).strip()
    for match in URL_RE.finditer(text):
        web_links.append(match.group(0).rstrip(".,);"))

    known = {tag.casefold() for tag in known_tags}
    aliases = dict(tag_aliases)
    tags: list[str] = []
    warnings: list[IndexWarning] = []
    for match in TAG_RE.finditer(text):
        raw_tag = match.group(1).casefold()
        tag = aliases.get(raw_tag, raw_tag)
        if tag in known:
            if tag not in tags:
                tags.append(tag)
        else:
            warnings.append(IndexWarning(WarningType.UNKNOWN_TAG, path, f"unknown tag: #{raw_tag}"))

    links: list[Link] = []
    for match in WIKI_RE.finditer(text):
        links.append(
            Link(
                target_text=match.group(1).strip(),
                target_heading=match.group(2).strip() if match.group(2) else None,
                alias=match.group(3).strip() if match.group(3) else None,
                line=line_by_chunk[0] if line_by_chunk else None,
            )
        )
    return Prose(
        text=text,
        tags=tuple(tags),
        links=tuple(links),
        web_links=tuple(dict.fromkeys(web_links)),
        warnings=tuple(warnings),
    )


def meaningful_line_range(lines: list[str], start_zero: int, end_zero: int) -> SourceRange | None:
    meaningful = [index for index in range(start_zero, min(end_zero, len(lines))) if lines[index].strip()]
    if not meaningful:
        return None
    return SourceRange(meaningful[0] + 1, meaningful[-1] + 1)
