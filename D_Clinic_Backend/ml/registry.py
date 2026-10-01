"""File-backed model registry (MLflow tracking stays in mlflow.db)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.settings import REPO_ROOT

REGISTRY_PATH = Path(__file__).resolve().parent / "registry" / "registry.json"


def load_registry(path: Path | None = None) -> dict:
    p = path or REGISTRY_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def production_version(name: str) -> str | None:
    for row in load_registry()["models"]:
        if row["name"] == name and row.get("stage") == "Production":
            return row["version"]
    return None


def upsert(name: str, version: str, *, metrics: dict | None = None,
           artifact: str | None = None, prompt_version: str | None = None,
           stage: str = "Production") -> dict:
    data = load_registry()
    found = False
    for row in data["models"]:
        if row["name"] == name:
            row["version"] = version
            row["stage"] = stage
            if metrics is not None:
                row["metrics"] = metrics
            if artifact is not None:
                row["artifact"] = artifact
            if prompt_version is not None:
                row["prompt_version"] = prompt_version
            found = True
            break
    if not found:
        data["models"].append({
            "name": name, "version": version, "stage": stage,
            "artifact": artifact, "prompt_version": prompt_version,
            "metrics": metrics or {},
        })
    data["updated_at"] = datetime.now(timezone.utc).date().isoformat()
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def tracking_uri() -> str:
    return f"sqlite:///{REPO_ROOT / 'mlflow.db'}"
