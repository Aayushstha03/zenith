from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_compose_contract_is_local_persistent_and_read_only() -> None:
    compose = (ROOT / "compose.yaml").read_text()
    assert "image: ${QDRANT_IMAGE}" in compose
    assert '"${QDRANT_BIND_ADDRESS}:${QDRANT_PORT}:6333"' in compose
    assert "qdrant-data:/qdrant/storage" in compose
    assert "model-cache:/models" in compose
    assert "read_only: true" in compose
    assert "internal: true" in compose
    assert 'QDRANT__TELEMETRY_DISABLED: "true"' in compose
    assert "dashboard:" in compose
    assert "condition: service_healthy" in compose
    assert 'profiles: ["tools"]' in compose
    assert 'command: ["zenith", "models", "prefetch"]' in compose


def test_documented_env_contains_all_compose_settings() -> None:
    env = (ROOT / ".env").read_text()
    example = (ROOT / ".env.example").read_text()
    required = {
        "QDRANT_IMAGE",
        "QDRANT_BIND_ADDRESS",
        "QDRANT_PORT",
        "ZENITH_VAULT_PATH",
        "ZENITH_COLLECTION",
        "ZENITH_DENSE_MODEL",
        "ZENITH_SPARSE_MODEL",
        "RESTART_POLICY",
    }
    for name in required:
        assert f"{name}=" in env
        assert f"{name}=" in example


def test_runtime_has_no_sqlite_or_cloud_inference_dependency() -> None:
    runtime_files = list((ROOT / "src").rglob("*.py")) + [ROOT / "pyproject.toml", ROOT / "compose.yaml"]
    runtime = "\n".join(path.read_text().lower() for path in runtime_files)
    assert "sqlite" not in runtime
    assert "fts5" not in runtime
    assert "cloud_inference" not in runtime
