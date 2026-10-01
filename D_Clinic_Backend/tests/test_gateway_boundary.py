"""4.7 — only llm/gateway.py may talk to a model provider."""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
BANNED_MODULES = {"openai", "ollama", "anthropic", "litellm", "langchain", "llama_cpp"}
BANNED_SUBSTRINGS = ("chat/completions", "api.openai.com")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_only_gateway_imports_an_llm_client():
    offenders = []
    for path in BACKEND.rglob("*.py"):
        if "alembic" in path.parts or path.name.startswith("test_"):
            continue
        if path.resolve() == (BACKEND / "llm" / "gateway.py").resolve():
            continue
        hits = _imports(path) & BANNED_MODULES
        if hits:
            offenders.append(f"{path.relative_to(BACKEND)}: {sorted(hits)}")
    assert not offenders, "LLM clients imported outside llm/gateway.py:\n" + "\n".join(offenders)


def test_only_gateway_contains_provider_urls():
    offenders = []
    gateway = (BACKEND / "llm" / "gateway.py").resolve()
    for path in BACKEND.rglob("*.py"):
        if path.suffix != ".py" or path.resolve() == gateway:
            continue
        if "alembic" in path.parts or "tests" in path.parts:
            continue
        if path.name == "settings.py":
            continue
        text = path.read_text(encoding="utf-8")
        for s in BANNED_SUBSTRINGS:
            if s in text:
                offenders.append(f"{path.relative_to(BACKEND)}: {s}")
    assert not offenders, offenders
