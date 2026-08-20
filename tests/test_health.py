from pathlib import Path

from zenith.core.config import Settings
from zenith.runtime.health import health_report


def test_health_report_combines_dependencies(monkeypatch, tmp_path: Path) -> None:
    settings = Settings(
        "http://qdrant:6333", tmp_path, tmp_path / "models", "entries", "127.0.0.1", 8080
    )
    monkeypatch.setattr("zenith.runtime.health.qdrant_health", lambda _: {"ready": True})
    monkeypatch.setattr("zenith.runtime.health.readiness", lambda _: {"ready": True})
    report = health_report(settings)
    assert report["ready"] is True
    assert report["vault"]["read_only_expected"] is True


def test_health_is_false_when_any_dependency_fails(monkeypatch, tmp_path: Path) -> None:
    settings = Settings(
        "http://qdrant:6333", tmp_path, tmp_path / "models", "entries", "127.0.0.1", 8080
    )
    monkeypatch.setattr("zenith.runtime.health.qdrant_health", lambda _: {"ready": False})
    monkeypatch.setattr("zenith.runtime.health.readiness", lambda _: {"ready": True})
    assert health_report(settings)["ready"] is False
