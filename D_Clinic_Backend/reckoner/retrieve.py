"""Retrieve top-k protocol chunks. Code decides; the model never picks sources."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from reckoner.chunk import Chunk
from reckoner.index import encode_query, load_index

DEFAULT_K = 4
# TF-IDF scores are small; dense cosine is larger. Tuned so HEARTS questions
# retrieve and malaria/cancer stay out when paired with the OOS keyword gate.
MIN_SCORE_TFIDF = 0.08
MIN_SCORE_DENSE = 0.22


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float
    method: str = "tfidf"


def _chunk(d: dict) -> Chunk:
    return Chunk(id=d["id"], source=d["source"], title=d["title"], body=d["body"])


def _hits_from_scores(index: dict, scores: np.ndarray, k: int, method: str) -> list[Hit]:
    order = np.argsort(-scores)[:k]
    return [Hit(_chunk(index["chunks"][i]), float(scores[i]), method) for i in order]


def retrieve(question: str, *, k: int = DEFAULT_K, index: dict | None = None) -> list[Hit]:
    index = index or load_index()
    dense = index.get("dense")
    if dense is not None:
        from llm.gateway import embed

        res = embed([question])
        if res.vectors:
            q = np.asarray(res.vectors, dtype=np.float32)
            scores = cosine_similarity(q, dense)[0]
            return _hits_from_scores(index, scores, k, "dense")
    q = encode_query(index, question)
    scores = cosine_similarity(q, index["matrix"])[0]
    return _hits_from_scores(index, scores, k, "tfidf")


def is_covered(hits: list[Hit], min_score: float | None = None) -> bool:
    if not hits:
        return False
    if min_score is None:
        min_score = MIN_SCORE_DENSE if hits[0].method == "dense" else MIN_SCORE_TFIDF
    return hits[0].score >= min_score
