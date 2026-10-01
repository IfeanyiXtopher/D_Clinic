"""Single LLM / embeddings client (ADR-0003). No other module may hit /v1.

Chat: none | ollama | openai. Embeddings: tfidf | ollama | openai.
Same OpenAI-shaped URLs; switching live vs laptop is .env only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from app.settings import settings

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
PROMPT_VERSION = "summary_v1"


@dataclass
class GatewayResult:
    text: str | None
    provider: str
    model: str | None
    prompt_version: str
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    error: str | None


def load_prompt(version: str = PROMPT_VERSION) -> str:
    path = PROMPT_DIR / f"{version}.txt"
    if not path.exists():
        raise FileNotFoundError(f"prompt file missing: {path}")
    return path.read_text(encoding="utf-8").strip()


def _endpoint() -> tuple[str, str | None, str | None]:
    """Return (base_url, model, bearer_token). Empty base means no remote call."""
    provider = (settings.llm_provider or "none").strip().lower()
    if provider in {"", "none", "off", "template"}:
        return "", None, None
    if provider == "ollama":
        return settings.ollama_base_url.rstrip("/"), settings.ollama_model, None
    if provider == "openai":
        key = settings.openai_api_key.strip()
        if not key:
            return "", None, None
        return settings.openai_base_url.rstrip("/"), settings.openai_model, key
    raise ValueError(f"unknown LLM_PROVIDER={provider!r} (use none, ollama, openai)")


def complete(user_payload: str, *, system: str | None = None, prompt_version: str = PROMPT_VERSION,
             json_mode: bool = False) -> GatewayResult:
    """Chat completion. Returns text=None on skip or transport failure (never raises)."""
    import time

    system = system or load_prompt(prompt_version)
    base, model, token = _endpoint()
    if not base or not model:
        return GatewayResult(None, "none", None, prompt_version, 0, None, None, None)

    url = f"{base}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_payload},
        ],
        "temperature": 0.2,
        "max_tokens": settings.llm_max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=settings.llm_timeout_s) as client:
            r = client.post(url, json=body, headers=headers)
        latency = int((time.perf_counter() - t0) * 1000)
        if r.status_code >= 400:
            return GatewayResult(None, settings.llm_provider, model, prompt_version, latency, None, None, f"http {r.status_code}")
        data = r.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content")
        usage = data.get("usage") or {}
        return GatewayResult(
            text=(text or "").strip() or None,
            provider=settings.llm_provider,
            model=model,
            prompt_version=prompt_version,
            latency_ms=latency,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            error=None,
        )
    except Exception as exc:  # transport / timeout / JSON — never fail the worker briefing
        latency = int((time.perf_counter() - t0) * 1000)
        return GatewayResult(None, settings.llm_provider, model, prompt_version, latency, None, None, str(exc)[:240])


@dataclass
class EmbedResult:
    vectors: list[list[float]] | None
    provider: str
    model: str | None
    error: str | None


def _embed_endpoint() -> tuple[str, str | None, str | None]:
    provider = (settings.embedding_provider or "tfidf").strip().lower()
    if provider in {"", "none", "off", "tfidf", "local-tfidf"}:
        return "", None, None
    if provider == "ollama":
        return settings.ollama_base_url.rstrip("/"), settings.ollama_embed_model, None
    if provider == "openai":
        key = settings.openai_api_key.strip()
        if not key:
            return "", None, None
        return settings.openai_base_url.rstrip("/"), settings.openai_embed_model, key
    raise ValueError(f"unknown EMBEDDING_PROVIDER={provider!r} (use tfidf, ollama, openai)")


def embed(texts: list[str]) -> EmbedResult:
    """OpenAI-compatible embeddings. Returns vectors=None on skip or failure (never raises)."""
    if not texts:
        return EmbedResult([], "none", None, None)
    base, model, token = _embed_endpoint()
    if not base or not model:
        return EmbedResult(None, "tfidf", None, None)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=settings.llm_timeout_s) as client:
            r = client.post(f"{base}/embeddings", json={"model": model, "input": texts}, headers=headers)
        if r.status_code >= 400:
            return EmbedResult(None, settings.embedding_provider, model, f"http {r.status_code}")
        rows = sorted((r.json().get("data") or []), key=lambda x: x.get("index", 0))
        vectors = [row.get("embedding") for row in rows]
        if not vectors or any(v is None for v in vectors):
            return EmbedResult(None, settings.embedding_provider, model, "empty embedding")
        return EmbedResult(vectors, settings.embedding_provider, model, None)
    except Exception as exc:
        return EmbedResult(None, settings.embedding_provider, model, str(exc)[:240])
