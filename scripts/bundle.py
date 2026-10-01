"""Pack local artifacts for an offline host. Does not touch the network."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "dist" / "offline-bundle"

COPIES = [
    ("docker-compose.yml", "docker-compose.yml"),
    (".env.example", ".env.example"),
    ("docs/mlops.md", "docs/mlops.md"),
    ("docs/responsible_ai.md", "docs/responsible_ai.md"),
    ("D_Clinic_Backend/ml/registry/registry.json", "registry.json"),
]

GLOBS = [
    "D_Clinic_Backend/llm/prompts/*.txt",
    "D_Clinic_Backend/ml/artifacts/*.joblib",
    "D_Clinic_Backend/reckoner/artifacts/*.joblib",
    "D_Clinic_Backend/chatbot/artifacts/*.joblib",
]


def main() -> int:
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    copied: list[str] = []
    for src_rel, dest_rel in COPIES:
        src = ROOT / src_rel
        if not src.exists():
            continue
        dest = DEST / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(dest_rel)
    for pattern in GLOBS:
        for src in ROOT.glob(pattern):
            rel = f"artifacts/{src.name}"
            dest = DEST / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied.append(rel)
    manifest = DEST / "MANIFEST.txt"
    lines = [
        f"Followup-AI offline bundle  {datetime.now(timezone.utc):%Y-%m-%dT%H:%M}Z",
        "Built from local files only. No download.",
        "Live VPS: LLM_PROVIDER=none or openai; EMBEDDING_PROVIDER=tfidf or openai.",
        "Do not copy Ollama GGUF weights onto a 1–2 GB host.",
        "",
        "Files:",
        *[f"  {p}" for p in copied],
        "",
    ]
    manifest.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {DEST} ({len(copied)} files)")
    print(manifest.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
