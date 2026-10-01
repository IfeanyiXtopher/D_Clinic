"""Split protocol markdown into one chunk per '## ID Title' heading."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from app.settings import REPO_ROOT

PROTOCOL_DIR = REPO_ROOT / "data" / "protocols"
HEADING = re.compile(r"^##\s+([A-Z]+-\d+)\s+(.+)$")


@dataclass(frozen=True)
class Chunk:
    id: str
    source: str
    title: str
    body: str

    @property
    def text(self) -> str:
        return f"{self.id} {self.title}\n{self.body}"

    def as_dict(self) -> dict:
        return asdict(self)


def load_chunks(directory: Path | None = None) -> list[Chunk]:
    directory = directory or PROTOCOL_DIR
    chunks: list[Chunk] = []
    for path in sorted(directory.glob("*.md")):
        current_id = current_title = None
        buf: list[str] = []
        source = path.stem
        for line in path.read_text(encoding="utf-8").splitlines():
            m = HEADING.match(line.strip())
            if m:
                if current_id and buf:
                    chunks.append(Chunk(current_id, source, current_title or "", "\n".join(buf).strip()))
                current_id, current_title = m.group(1), m.group(2).strip()
                buf = []
                continue
            if current_id:
                buf.append(line)
        if current_id and buf:
            chunks.append(Chunk(current_id, source, current_title or "", "\n".join(buf).strip()))
    if not chunks:
        raise FileNotFoundError(f"no protocol chunks in {directory}")
    return chunks
