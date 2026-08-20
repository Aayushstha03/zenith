"""Zenith command line and lightweight health service."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
from threading import Event

from zenith.core.config import Settings
from zenith.parser.service import VaultParser
from zenith.parser.watcher import VaultWatcher
from zenith.index.diagnostics import inspect_collection
from zenith.index.incremental import IncrementalIndexer
from zenith.index.rebuild import IndexRebuilder
from zenith.runtime.health import encode_report, health_report
from zenith.runtime.models import prefetch, readiness


def _print(data: object) -> None:
    print(json.dumps(data, indent=2, sort_keys=True, default=str))


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
    parser = argparse.ArgumentParser(prog="zenith")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the application health service")
    commands.add_parser("health", help="check Qdrant, models, vault, and configuration")
    parse = commands.add_parser("parse", help="parse the configured vault without indexing")
    parse.add_argument("paths", nargs="*", help="optional vault-relative Markdown paths")
    commands.add_parser("watch", help="watch the vault and parse debounced Markdown changes")
    index = commands.add_parser("index", help="manage the Qdrant index")
    index_commands = index.add_subparsers(dest="index_command", required=True)
    index_commands.add_parser("rebuild", help="atomically rebuild the complete vault index")
    update = index_commands.add_parser("update", help="incrementally converge the active index")
    update.add_argument("paths", nargs="*", help="optional changed vault-relative paths")
    index_commands.add_parser("inspect", help="inspect active collection integrity")
    models = commands.add_parser("models", help="manage local embedding models")
    model_commands = models.add_subparsers(dest="model_command", required=True)
    model_commands.add_parser("prefetch", help="download and validate pinned models")
    model_commands.add_parser("ready", help="inspect model-cache readiness")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    if args.command == "serve":
        server = ThreadingHTTPServer((settings.host, settings.port), _handler(settings))
        server.serve_forever()
        return 0
    if args.command == "health":
        report = health_report(settings)
        _print(report)
        return 0 if report["ready"] else 1
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
    if args.command == "index":
        if args.index_command == "rebuild":
            _print(IndexRebuilder(settings).rebuild().to_dict())
            return 0
        if args.index_command == "update":
            _print(IncrementalIndexer(settings).reindex(args.paths or None).to_dict())
            return 0
        report = inspect_collection(settings)
        _print(report)
        return 0 if report["ready"] else 1
    if args.model_command == "prefetch":
        _print(prefetch(settings))
        return 0
    report = readiness(settings)
    _print(report)
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
