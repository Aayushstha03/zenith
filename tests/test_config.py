from pathlib import Path

import pytest

from zenith.core.config import Settings


def test_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZENITH_QDRANT_URL", "http://localhost:6333/")
    monkeypatch.setenv("ZENITH_VAULT_PATH", "/tmp/vault")
    monkeypatch.setenv("ZENITH_MODEL_CACHE_PATH", "/tmp/models")
    monkeypatch.setenv("ZENITH_COLLECTION", "test_entries")
    monkeypatch.setenv("ZENITH_DENSE_MODEL", "dense/test")
    monkeypatch.setenv("ZENITH_SPARSE_MODEL", "sparse/test")
    monkeypatch.setenv("ZENITH_PORT", "9090")

    settings = Settings.from_env()

    assert settings.qdrant_url == "http://localhost:6333"
    assert settings.vault_path == Path("/tmp/vault")
    assert settings.model_cache_path == Path("/tmp/models")
    assert settings.collection_name == "test_entries"
    assert settings.port == 9090
    assert settings.dense_model == "dense/test"
    assert settings.sparse_model == "sparse/test"
    assert settings.validate() == ()


def test_settings_reject_invalid_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZENITH_PORT", "0")
    with pytest.raises(ValueError, match="positive"):
        Settings.from_env()


def test_settings_report_contract_errors(tmp_path: Path) -> None:
    settings = Settings("qdrant", Path("relative"), tmp_path, "", "0.0.0.0", 8080)
    assert len(settings.validate()) == 3


def test_tag_aliases_must_target_known_tags(tmp_path: Path) -> None:
    settings = Settings(
        "http://qdrant", tmp_path, tmp_path, "entries", "0.0.0.0", 8080,
        known_tags=("journal",), tag_aliases=(("recipes", "recipe"),),
    )
    assert "every tag alias must target a known canonical tag" in settings.validate()
