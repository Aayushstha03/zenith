"""Stable JSON command line and lightweight health service."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
from threading import Event
from typing import Any, TextIO

from qdrant_client import QdrantClient

from zenith.core.config import Settings
from zenith.core.contracts import EntryType, RetrievalMode, WarningType
from zenith.index.diagnostics import inspect_collection
from zenith.index.incremental import IncrementalIndexer
from zenith.index.schema import initialize_index
from zenith.library import Zenith
from zenith.parser.service import VaultParser
from zenith.parser.watcher import VaultWatcher
from zenith.runtime.health import encode_report, health_report
from zenith.runtime.models import prefetch, readiness


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _print(data: object, *, file: TextIO | None = None) -> None:
    print(json.dumps(data, indent=2, sort_keys=True, default=str), file=file or sys.stdout)


def _handler(settings: Settings) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path not in {"/health", "/healthz"}:
                self.send_error(404)
                return
            report = health_report(settings)
            body = encode_report(report)
            self.send_response(200 if report["ready"] else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="zenith")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the application health service")
    commands.add_parser("health", help="check Qdrant, index, models, vault, and configuration")
    commands.add_parser("diagnose", help="emit combined health and index diagnostics")

    parse = commands.add_parser("parse", help="parse the configured vault without indexing")
    parse.add_argument("paths", nargs="*", help="optional vault-relative Markdown paths")
    commands.add_parser("watch", help="watch the vault and index debounced Markdown changes")

    index = commands.add_parser("index", help="manage the Qdrant index")
    index_commands = index.add_subparsers(dest="index_command", required=True)
    index_commands.add_parser("init", help="initialize an empty active collection")
    index_commands.add_parser("rebuild", help="atomically rebuild the complete vault index")
    update = index_commands.add_parser("update", help="incrementally converge the active index")
    update.add_argument("paths", nargs="*", help="optional changed vault-relative paths")
    index_commands.add_parser("inspect", help="inspect active collection integrity")

    models = commands.add_parser("models", help="manage local embedding models")
    model_commands = models.add_subparsers(dest="model_command", required=True)
    model_commands.add_parser("prefetch", help="download and validate pinned models")
    model_commands.add_parser("ready", help="inspect model-cache readiness")

    search = commands.add_parser("search", help="search indexed entries")
    search.add_argument("query", nargs="?", help="query text; omit for metadata mode")
    search.add_argument("--mode", choices=_values(RetrievalMode), default="hybrid")
    _add_entry_filters(search)

    note = commands.add_parser("note", help="retrieve notes")
    note_commands = note.add_subparsers(dest="note_command", required=True)
    note_get = note_commands.add_parser("get")
    note_get.add_argument("path_or_title")

    entry = commands.add_parser("entry", help="retrieve entries")
    entry_commands = entry.add_subparsers(dest="entry_command", required=True)
    entry_get = entry_commands.add_parser("get")
    entry_get.add_argument("entry_id")

    links = commands.add_parser("links", help="inspect and resolve internal links")
    link_commands = links.add_subparsers(dest="link_command", required=True)
    outgoing = link_commands.add_parser("outgoing")
    outgoing.add_argument("note_id")
    outgoing.add_argument("--entry-id")
    backlinks = link_commands.add_parser("backlinks")
    backlinks.add_argument("note_id")
    resolve = link_commands.add_parser("resolve")
    resolve.add_argument("source_note_id")
    resolve.add_argument("target_text")

    within = commands.add_parser("search-within", help="search within one note")
    within.add_argument("note_id")
    within.add_argument("query")
    within.add_argument("--mode", choices=_values(RetrievalMode), default="hybrid")
    within.add_argument("--section")
    within.add_argument("--limit", type=int, default=10)

    context = commands.add_parser("context", help="expand bounded linked context")
    context.add_argument("entry_id")
    context.add_argument("--link-depth", type=int, default=1)
    context.add_argument("--nearby-days", type=int, default=3)
    context.add_argument("--max-notes", type=int, default=5)

    warnings = commands.add_parser("warnings", help="list index warnings")
    warnings.add_argument("--type", choices=_values(WarningType))
    warnings.add_argument("--path")

    kanban = commands.add_parser("kanban", help="query Kanban boards and cards")
    kanban_commands = kanban.add_subparsers(dest="kanban_command", required=True)
    kanban_commands.add_parser("list")
    kanban_get = kanban_commands.add_parser("get")
    kanban_get.add_argument("board")
    kanban_find = kanban_commands.add_parser("find")
    kanban_find.add_argument("query", nargs="?")
    kanban_find.add_argument("--board")
    kanban_find.add_argument("--column", action="append", default=[])
    kanban_find.add_argument("--status", action="append", default=[])
    kanban_find.add_argument("--checked", choices=("true", "false"))
    kanban_find.add_argument("--tag", action="append", default=[])
    kanban_find.add_argument("--exact", action="store_true")
    kanban_find.add_argument("--limit", type=int, default=10)

    graph = commands.add_parser("graph", help="export the complete note network")
    graph.add_subparsers(dest="graph_command", required=True).add_parser("export")
    return parser


def _add_entry_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    parser.add_argument("--tag-all", action="append", default=[])
    parser.add_argument("--tag-any", action="append", default=[])
    parser.add_argument("--note")
    parser.add_argument("--section")
    parser.add_argument("--entry-type", action="append", choices=_values(EntryType), default=[])
    parser.add_argument("--limit", type=int, default=10)


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return _run(args, Settings.from_env())
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        _print(
            {"error": {"message": str(exc), "type": type(exc).__name__}},
            file=sys.stderr,
        )
        return 2 if isinstance(exc, (LookupError, ValueError)) else 1


def _run(args: argparse.Namespace, settings: Settings) -> int:
    if args.command == "serve":
        server = ThreadingHTTPServer((settings.host, settings.port), _handler(settings))
        server.serve_forever()
        return 0
    if args.command == "health":
        report = health_report(settings)
        _print(report)
        return 0 if report["ready"] else 1
    if args.command == "diagnose":
        report = {"health": health_report(settings), "index": inspect_collection(settings)}
        _print(report)
        return 0 if report["health"]["ready"] and report["index"]["ready"] else 1
    if args.command == "parse":
        result = VaultParser(settings).parse_vault(args.paths or None)
        _print({"notes": [asdict(note) for note in result]})
        return 0
    if args.command == "watch":
        indexer = IncrementalIndexer(settings)

        def changed(paths: tuple[str, ...]) -> None:
            _print(indexer.reindex(list(paths)).to_dict())

        try:
            with VaultWatcher(settings, changed):
                Event().wait()
        except KeyboardInterrupt:
            return 0
        return 0

    if args.command == "models":
        report = prefetch(settings) if args.model_command == "prefetch" else readiness(settings)
        _print(report)
        return 0 if report["ready"] else 1

    if args.command == "index":
        if args.index_command == "init":
            report = initialize_index(settings, QdrantClient(url=settings.qdrant_url)).to_dict()
        elif args.index_command == "rebuild":
            report = Zenith(settings).reindex(full=True).to_dict()
        elif args.index_command == "update":
            report = Zenith(settings).reindex(args.paths or None).to_dict()
        else:
            report = inspect_collection(settings)
        _print(report)
        return 0 if report.get("ready", True) else 1

    api = Zenith(settings)
    if args.command == "search":
        mode = RetrievalMode(args.mode)
        texts = _query_texts(mode, args.query)
        results = api.find_entries(
            date_from=args.date_from,
            date_to=args.date_to,
            tags_all=tuple(args.tag_all),
            tags_any=tuple(args.tag_any),
            note=args.note,
            section=args.section,
            entry_types=tuple(EntryType(value) for value in args.entry_type),
            mode=mode,
            limit=args.limit,
            **texts,
        )
        _print({"results": [result.to_dict() for result in results]})
    elif args.command == "note":
        _print(api.get_note(args.path_or_title).to_dict())
    elif args.command == "entry":
        _print(api.get_entry(args.entry_id).to_dict())
    elif args.command == "links":
        if args.link_command == "outgoing":
            links = api.get_outgoing_links(args.note_id, args.entry_id)
            _print({"links": [asdict(link) for link in links]})
        elif args.link_command == "backlinks":
            results = api.get_backlinks(args.note_id)
            _print({"results": [result.to_dict() for result in results]})
        else:
            _print(asdict(api.resolve_link(args.source_note_id, args.target_text)))
    elif args.command == "search-within":
        results = api.search_within(
            args.note_id,
            args.query,
            RetrievalMode(args.mode),
            args.section,
            limit=args.limit,
        )
        _print({"results": [result.to_dict() for result in results]})
    elif args.command == "context":
        _print(
            api.expand_context(
                args.entry_id,
                link_depth=args.link_depth,
                nearby_days=args.nearby_days,
                max_notes=args.max_notes,
            ).to_dict()
        )
    elif args.command == "warnings":
        warnings = api.get_index_warnings(
            WarningType(args.type) if args.type else None,
            args.path,
        )
        _print({"warnings": [asdict(warning) for warning in warnings]})
    elif args.command == "kanban":
        if args.kanban_command == "list":
            _print({"boards": [board.to_dict() for board in api.list_kanban_boards()]})
        elif args.kanban_command == "get":
            _print(api.get_kanban_board(args.board).to_dict())
        else:
            results = api.find_kanban_cards(
                board=args.board,
                columns=tuple(args.column),
                statuses=tuple(args.status),
                checked=_optional_bool(args.checked),
                tags=tuple(args.tag),
                exact_text=args.query if args.exact else None,
                semantic_text=args.query if args.query and not args.exact else None,
                limit=args.limit,
            )
            _print({"results": [result.to_dict() for result in results]})
    else:
        _print(api.export_graph().to_dict())
    return 0


def _query_texts(mode: RetrievalMode, query: str | None) -> dict[str, str | None]:
    if mode is RetrievalMode.METADATA:
        return {}
    if not query:
        raise ValueError(f"{mode.value} mode requires query text")
    if mode is RetrievalMode.LITERAL:
        return {"exact_text": query}
    if mode is RetrievalMode.LEXICAL:
        return {"lexical_text": query}
    if mode is RetrievalMode.SEMANTIC:
        return {"semantic_text": query}
    return {"lexical_text": query, "semantic_text": query}


def _optional_bool(value: str | None) -> bool | None:
    return None if value is None else value == "true"


def _values(enum: Any) -> tuple[str, ...]:
    return tuple(item.value for item in enum)


if __name__ == "__main__":
    sys.exit(main())
