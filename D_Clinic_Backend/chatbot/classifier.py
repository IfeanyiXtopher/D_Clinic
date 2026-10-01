"""Small supervised SMS intent classifier (TF-IDF + logistic).

DistilBERT / Qwen 0.6B were considered (Step 5.7) and rejected for the same
reason Ollama is not on the 1 GB VPS: they need more RAM than the live host
has. This linear model trains in under a second, loads in a few MB, and is
compared with the rule NLU and an optional LLM in the eval report.
"""

from __future__ import annotations

from pathlib import Path

from chatbot.nlu import INTENTS

ARTIFACT = Path(__file__).resolve().parent / "artifacts" / "sms_intent_v1.joblib"
MODEL_VERSION = "sms_intent_v1"

# Extra lines beyond data/synth/generate.py so cancel is represented.
EXTRA: list[tuple[str, str]] = [
    ("cancel", "Please cancel my appointment"),
    ("cancel", "I will not come at all"),
    ("cancel", "I don travel, cancel am"),
    ("cancel", "Cancel the visit"),
    ("confirm", "I will be there"),
    ("confirm", "See you then"),
    ("reschedule", "Can we do Thursday instead"),
    ("reschedule", "Move it to next Friday"),
    ("ask_slot", "When can I come"),
    ("stop", "unsubscribe"),
    ("symptom_or_medical", "I feel dizzy after the tablet"),
    ("wrong_number", "You have the wrong person"),
    ("unknown", "God bless"),
]


def training_rows() -> list[tuple[str, str]]:
    import sys

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from data.synth.generate import SMS_TEMPLATES

    rows: list[tuple[str, str]] = []
    for intent, pairs in SMS_TEMPLATES.items():
        if intent == "none":
            continue
        label = "unknown" if intent == "unknown" else intent
        for _, text in pairs:
            rows.append((text, label))
    rows.extend(EXTRA)
    return rows


def train_and_save(path: Path | None = None):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    import joblib

    path = path or ARTIFACT
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = training_rows()
    X = [t for t, _ in rows]
    y = [lab for _, lab in rows]
    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1, lowercase=True)),
        ("clf", LogisticRegression(max_iter=400, class_weight="balanced")),
    ])
    pipe.fit(X, y)
    joblib.dump({"pipeline": pipe, "version": MODEL_VERSION, "labels": sorted(set(y))}, path)
    return pipe


def load(path: Path | None = None):
    import joblib

    path = path or ARTIFACT
    if not path.exists():
        return train_and_save(path)
    return joblib.load(path)["pipeline"]


def predict_intent(text: str, model=None) -> str:
    model = model or load()
    label = model.predict([text])[0]
    return label if label in INTENTS else "unknown"
