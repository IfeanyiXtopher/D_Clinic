"""Protocol index: TF-IDF always, optional dense vectors from the gateway.

Dense vectors are built only when you pass ``dense=True``
(``make index-protocols DENSE=1``). Tests and ``make eval-reckoner`` stay on
TF-IDF so they never call OpenAI.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from reckoner.chunk import Chunk, load_chunks

ARTIFACT = Path(__file__).resolve().parent / "artifacts" / "protocol_tfidf_v1.joblib"
INDEX_VERSION = "protocol_tfidf_v1"


def _tfidf_matrix(chunks: list[Chunk]):
    from sklearn.feature_extraction.text import TfidfVectorizer

    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, lowercase=True)
    matrix = vec.fit_transform([c.text for c in chunks]).astype(np.float32)
    return vec, matrix


def _dense_matrix(chunks: list[Chunk]) -> tuple[np.ndarray | None, str | None, str | None]:
    from llm.gateway import embed

    res = embed([c.text for c in chunks])
    if not res.vectors or len(res.vectors) != len(chunks):
        return None, res.model, res.error
    return np.asarray(res.vectors, dtype=np.float32), res.model, None


def build_index(chunks: list[Chunk] | None = None, path: Path | None = None,
                dense: bool = False) -> dict:
    import joblib

    chunks = chunks or load_chunks()
    vectorizer, matrix = _tfidf_matrix(chunks)
    dense_matrix, embed_model, embed_error = (None, None, None)
    if dense:
        dense_matrix, embed_model, embed_error = _dense_matrix(chunks)
    payload = {
        "version": INDEX_VERSION,
        "vectorizer": vectorizer,
        "matrix": matrix,
        "dense": dense_matrix,
        "embed_model": embed_model,
        "embed_error": embed_error,
        "ids": [c.id for c in chunks],
        "chunks": [c.as_dict() for c in chunks],
    }
    path = path or ARTIFACT
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(payload, path)
    return payload


def load_index(path: Path | None = None) -> dict:
    path = path or ARTIFACT
    if not path.exists():
        return build_index(path=path, dense=False)
    import joblib

    return joblib.load(path)


def encode_query(index: dict, question: str) -> np.ndarray:
    """TF-IDF query vector. Dense query encoding is in ``retrieve``."""
    return index["vectorizer"].transform([question]).astype(np.float32)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the protocol retrieval index")
    parser.add_argument("--dense", action="store_true",
                        help="Also embed chunks via EMBEDDING_PROVIDER (ollama or openai)")
    args = parser.parse_args()
    payload = build_index(dense=args.dense)
    extra = ""
    if args.dense:
        extra = f", dense={payload['dense'] is not None} model={payload.get('embed_model')}"
        if payload.get("embed_error"):
            extra += f" error={payload['embed_error']}"
    print(f"indexed {len(payload['ids'])} chunks -> {ARTIFACT}{extra}")
