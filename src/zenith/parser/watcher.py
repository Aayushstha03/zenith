"""Watchdog-based, debounced Markdown change observation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Lock, Timer, current_thread

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from zenith.core.config import Settings

ChangeCallback = Callable[[tuple[str, ...]], None]


class MarkdownChangeHandler(FileSystemEventHandler):
    def __init__(self, settings: Settings, callback: ChangeCallback, debounce_seconds: float = 0.5) -> None:
        super().__init__()
        self.settings = settings
        self.callback = callback
        self.debounce_seconds = debounce_seconds
        self._pending: set[str] = set()
        self._timer: Timer | None = None
        self._lock = Lock()

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory or event.event_type not in {"created", "modified", "deleted", "moved"}:
            return
        paths = [event.src_path]
        destination = getattr(event, "dest_path", None)
        if destination:
            paths.append(destination)
        accepted = [relative for path in paths if (relative := self._relative_markdown(path)) is not None]
        if not accepted:
            return
        with self._lock:
            self._pending.update(accepted)
            if self._timer is not None:
                self._timer.cancel()
            self._timer = Timer(self.debounce_seconds, self.flush)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> None:
        with self._lock:
            timer = self._timer
            paths = tuple(sorted(self._pending, key=str.casefold))
            self._pending.clear()
            self._timer = None
        if timer is not None and timer is not current_thread():
            timer.cancel()
        if paths:
            self.callback(paths)

    def close(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self.flush()

    def _relative_markdown(self, raw_path: str) -> str | None:
        path = Path(raw_path)
        if path.suffix.casefold() != ".md":
            return None
        try:
            relative = path.resolve().relative_to(self.settings.vault_path.resolve())
        except ValueError:
            return None
        excluded = {name.casefold() for name in self.settings.excluded_directories}
        if any(part.casefold() in excluded for part in relative.parts[:-1]):
            return None
        return relative.as_posix()


class VaultWatcher:
    def __init__(self, settings: Settings, callback: ChangeCallback, debounce_seconds: float = 0.5) -> None:
        self.handler = MarkdownChangeHandler(settings, callback, debounce_seconds)
        self.observer = Observer()
        self.observer.schedule(self.handler, str(settings.vault_path), recursive=True)

    def start(self) -> None:
        self.observer.start()

    def stop(self) -> None:
        self.observer.stop()
        self.observer.join()
        self.handler.close()

    def __enter__(self) -> VaultWatcher:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
