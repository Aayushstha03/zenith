"""Application and dependency health checks."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from zenith.core.config import Settings
from zenith.index.diagnostics import inspect_collection
from zenith.runtime.models import readiness


def qdrant_health(settings: Settings, timeout: float = 2.0) -> dict[str, Any]:
    try:
        with urlopen(f"{settings.qdrant_url}/healthz", timeout=timeout) as response:
            return {"ready": response.status == 200, "status": response.status}
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return {"ready": False, "error": str(exc)}


def index_health(settings: Settings) -> dict[str, Any]:
    try:
        return inspect_collection(settings)
    except Exception as exc:
        return {"ready": False, "collection": settings.collection_name, "error": str(exc)}


def health_report(settings: Settings) -> dict[str, Any]:
    config_errors = settings.validate()
    qdrant = qdrant_health(settings)
    models = readiness(settings)
    index = index_health(settings) if qdrant["ready"] else {
        "ready": False,
        "collection": settings.collection_name,
        "reason": "Qdrant is unreachable",
    }
    vault = {
        "ready": settings.vault_path.is_dir(),
        "path": str(settings.vault_path),
        "read_only_expected": True,
    }
    ready = (
        not config_errors
        and qdrant["ready"]
        and index["ready"]
        and models["ready"]
        and vault["ready"]
    )
    return {
        "ready": ready,
        "configuration": {"ready": not config_errors, "errors": list(config_errors)},
        "qdrant": qdrant,
        "index": index,
        "models": models,
        "vault": vault,
    }


def encode_report(report: dict[str, Any]) -> bytes:
    return (json.dumps(report, sort_keys=True) + "\n").encode("utf-8")
