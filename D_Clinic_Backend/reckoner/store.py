"""Persist protocol chunk text. Dense pgvector is optional when the extension exists."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.engine import Engine

from reckoner.chunk import load_chunks


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def pgvector_available(engine: Engine) -> bool:
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
            return bool(c.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar())
    except Exception:
        return False


def persist_chunks(engine: Engine) -> int:
    chunks = load_chunks()
    now = _now()
    with engine.begin() as c:
        c.execute(text("DELETE FROM protocol_chunks"))
        for ch in chunks:
            c.execute(
                text(
                    """INSERT INTO protocol_chunks (id, source, title, body, created_at)
                       VALUES (:id, :source, :title, :body, :t)"""
                ),
                {"id": ch.id, "source": ch.source, "title": ch.title, "body": ch.body, "t": now},
            )
    return len(chunks)
