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
    # LM Studio runs on the host, so the zenith service needs a routed network
    # and a host gateway. Qdrant and the index path stay unroutable.
    assert '"host.docker.internal:host-gateway"' in compose
    assert compose.count("internal: true") == 1


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
        "ZENITH_LOG_ROOT",
        "ZENITH_KANBAN_ROOT",
        "ZENITH_EXCLUDED_DIRECTORIES",
        "ZENITH_KNOWN_TAGS",
        "ZENITH_TAG_ALIASES",
        "RESTART_POLICY",
        "ZENITH_LLM_BASE_URL",
        "ZENITH_LLM_MODEL",
        "ZENITH_LLM_API_KEY",
        "ZENITH_LLM_TIMEOUT",
        "ZENITH_LLM_TEMPERATURE",
    }
    for name in required:
        assert f"{name}=" in env
        assert f"{name}=" in example


def test_the_image_installs_every_declared_dependency() -> None:
    """The Dockerfile repeats the dependency list, so it can drift from it.

    The runtime stage installs the project with `--no-deps`, which means a
    dependency added to pyproject.toml and not added here is simply absent
    from the image, and only fails when the code path that needs it runs.
    """
    import re
    import tomllib

    declared = set(tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"])
    pinned = set(
        re.findall(r"^\s+\"?([A-Za-z0-9_.\[\]-]+==[0-9][^\s\\\"]*)", (ROOT / "Dockerfile").read_text(), re.M)
    )
    assert declared == pinned, f"Dockerfile and pyproject disagree: {declared ^ pinned}"


def test_runtime_has_no_sqlite_or_cloud_inference_dependency() -> None:
    runtime_files = [*(ROOT / "src").rglob("*.py"), ROOT / "pyproject.toml", ROOT / "compose.yaml"]
    runtime = "\n".join(path.read_text().lower() for path in runtime_files)
    assert "sqlite" not in runtime
    assert "fts5" not in runtime
    assert "cloud_inference" not in runtime
