"""PII scan for packets and model text (inbound and outbound).

Uses Microsoft Presidio pattern recognisers when the optional ``llm`` extra is
installed. A regex pass always runs so tests and a 1 GB host work without spaCy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Nigerian mobile (080x / 070x / 090x / 081x) and +234 forms.
_PHONE = re.compile(
    r"(?:\+?234[\s-]?\d{10}\b|\b0[789]\d{2}[\s-]?\d{3}[\s-]?\d{4}\b|\b\d{3}[-.]?\d{3}[-.]?\d{4}\b)"
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_SLASH_DATE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_NIN = re.compile(r"\b\d{11}\b")
_HONORIFIC = re.compile(
    r"\b(?:Mr|Mrs|Ms|Dr|Alhaji|Alhaja)\.?\s+[A-Z][A-Za-z'-]{1,30}\b"
)
# Street-style addresses (HIPAA Safe Harbor: smaller than state).
_ADDRESS = re.compile(
    r"(?i)\b(?:no\.?\s*)?\d{1,5}[a-z]?\s+[a-z][a-z'-]+(?:\s+[a-z][a-z'-]+){0,4}\s+"
    r"(?:street|st\.?|avenue|ave\.?|road|rd\.?|close|crescent|estate|lane|drive)\b"
)
_LONG_DATE = re.compile(
    r"(?i)\b(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+\d{1,2},?\s+\d{4}\b"
)

_PRESIDIO_PATTERNS = [
    ("PHONE_NUMBER", r"(?:\+?234[\s-]?\d{10}|\b0[789]\d{2}[\s-]?\d{3}[\s-]?\d{4}\b)", 0.8),
    ("EMAIL_ADDRESS", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", 0.8),
    ("DATE_TIME", r"\d{4}-\d{2}-\d{2}", 0.6),
    ("NG_NIN", r"\b\d{11}\b", 0.5),
]


@dataclass(frozen=True)
class Finding:
    entity: str
    text: str
    start: int
    end: int
    score: float
    source: str


def _regex_scan(text: str) -> list[Finding]:
    out: list[Finding] = []
    for entity, rx in (
        ("PHONE_NUMBER", _PHONE),
        ("EMAIL_ADDRESS", _EMAIL),
        ("DATE_TIME", _ISO_DATE),
        ("DATE_TIME", _SLASH_DATE),
        ("DATE_TIME", _LONG_DATE),
        ("NG_NIN", _NIN),
        ("PERSON", _HONORIFIC),
        ("ADDRESS", _ADDRESS),
    ):
        for m in rx.finditer(text):
            out.append(Finding(entity, m.group(), m.start(), m.end(), 0.7, "regex"))
    return out


def _presidio_scan(text: str) -> list[Finding]:
    try:
        from presidio_analyzer import Pattern, PatternRecognizer
    except ImportError:
        return []
    findings: list[Finding] = []
    for entity, pattern, score in _PRESIDIO_PATTERNS:
        rec = PatternRecognizer(
            supported_entity=entity,
            patterns=[Pattern(name=entity.lower(), regex=pattern, score=score)],
        )
        for r in rec.analyze(text, entities=[entity]):
            findings.append(
                Finding(entity, text[r.start : r.end], r.start, r.end, float(r.score), "presidio")
            )
    return findings


def scan_text(text: str) -> list[Finding]:
    """Return PII-like spans in ``text``. Empty means the text is clean enough to send."""
    if not text:
        return []
    seen: set[tuple[str, int, int]] = set()
    out: list[Finding] = []
    for f in (*_regex_scan(text), *_presidio_scan(text)):
        key = (f.entity, f.start, f.end)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def walk_strings(obj) -> list[str]:
    found: list[str] = []
    if isinstance(obj, str):
        found.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                found.append(k)
            found.extend(walk_strings(v))
    elif isinstance(obj, (list, tuple)):
        for x in obj:
            found.extend(walk_strings(x))
    return found


def scan_obj(obj) -> list[Finding]:
    findings: list[Finding] = []
    for s in walk_strings(obj):
        findings.extend(scan_text(s))
    return findings
