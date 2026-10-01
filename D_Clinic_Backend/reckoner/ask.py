"""Grounded protocol Q&A. Retrieval + extractive answer; LLM optional; dose check."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from llm.check import extra_drugs
from llm.deid import Packet
from llm.scan import scan_text
from reckoner.chunk import Chunk
from reckoner.retrieve import Hit, is_covered, retrieve

OOS_HINTS = (
    "malaria", "artemether", "cancer", "chemotherapy", "fracture", "plaster",
    "warfarin", "inr", "asthma", "salbutamol", "covid vaccine", "measles",
    "depression", "ssri", "appendicitis", "cataract",
)
REFUSAL = (
    "This question is not covered by the hypertension protocol in this tool. "
    "Use the appropriate guideline or ask a clinician."
)
_SENT = re.compile(r"[^.!?]+[.!?]")
_NUM = re.compile(r"\d+(?:\.\d+)?")


@dataclass
class ReckonerAnswer:
    question: str
    answer: str
    refused: bool
    covered: bool
    citations: list[dict]
    source: str  # extractive | llm | refused
    check: str
    fallback_used: bool

    def as_api(self) -> dict:
        return {
            "question": self.question,
            "answer": self.answer,
            "refused": self.refused,
            "covered": self.covered,
            "citations": self.citations,
            "source": self.source,
            "check": self.check,
            "fallback_used": self.fallback_used,
        }


def looks_out_of_scope(question: str) -> bool:
    q = question.lower()
    return any(h in q for h in OOS_HINTS)


def _cite(hits: list[Hit]) -> list[dict]:
    return [{"id": h.chunk.id, "title": h.chunk.title, "source": h.chunk.source, "score": round(h.score, 3)}
            for h in hits]


def _passage_blob(hits: list[Hit]) -> str:
    return "\n".join(h.chunk.text for h in hits)


def extractive_answer(question: str, hits: list[Hit]) -> str:
    """Pick the most overlapping sentences from the top passages; cite chunk ids."""
    q_terms = {w for w in re.findall(r"[a-z0-9]+", question.lower()) if len(w) > 2}
    scored: list[tuple[float, str, str]] = []
    for h in hits:
        for sent in _SENT.findall(h.chunk.body.replace("\n", " ")):
            s = sent.strip()
            if len(s) < 40:
                continue
            terms = {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}
            overlap = len(q_terms & terms) / max(len(q_terms), 1)
            scored.append((overlap + 0.15 * h.score, s, h.chunk.id))
    scored.sort(reverse=True)
    picked: list[str] = []
    cites: list[str] = []
    seen = set()
    for _, sent, cid in scored:
        if sent in seen:
            continue
        seen.add(sent)
        picked.append(sent)
        if cid not in cites:
            cites.append(cid)
        if len(picked) >= 2:
            break
    if not picked:
        picked = [hits[0].chunk.body.split(".")[0].strip() + "."]
        cites = [hits[0].chunk.id]
    cite = " ".join(f"[{c}]" for c in cites[:3])
    return " ".join(picked) + f" {cite}"


def _packet_from_passages(hits: list[Hit]) -> Packet:
    """Reuse the summary post-check: numbers/drugs must exist in retrieved text."""
    blob = _passage_blob(hits)
    drugs = []
    for name in (
        "Amlodipine", "Telmisartan", "Chlorthalidone", "Metformin",
        "Insulin", "Losartan", "Lisinopril",
    ):
        if name.lower() in blob.lower():
            drugs.append({"name": name, "dosage": ""})
    # Fake a packet whose allowed tokens are the passage numbers + protocol drugs.
    return Packet(
        case_code="C-REC",
        age_band="55-64",
        sex="unknown",
        conditions=["hypertension"],
        bp_history=[],
        last_bp=None,
        bs_history=[],
        last_bs=None,
        drugs=drugs,
        attendance={"visits_12m": 0, "missed_12m": 0, "last_visit": "never",
                    "next_scheduled": None, "days_overdue": None},
        last_call=None,
        risk=None,
        program_status="under_care",
        suggested_next_step="",
        extra={"passage": blob},
    )


def _allowed_from_hits(hits: list[Hit]) -> set[str]:
    blob = _passage_blob(hits)
    allow = set(_NUM.findall(blob))
    allow.update({"140", "90", "180", "120", "5", "10", "40", "80", "12.5", "4", "18", "28"})
    return allow


def dose_check(text: str, hits: list[Hit]) -> bool:
    allow = _allowed_from_hits(hits)
    extras = [tok for tok in _NUM.findall(text) if tok not in allow]
    # Drug names not in passages.
    packet = _packet_from_passages(hits)
    extra_d = extra_drugs(text, packet)
    return not extras and not extra_d


def _llm_answer(question: str, hits: list[Hit]) -> str | None:
    from app.settings import settings
    from llm.gateway import complete

    if (settings.llm_provider or "none").lower() in {"", "none", "off", "template"}:
        return None
    passages = "\n\n".join(f"[{i+1} {h.chunk.id}] {h.chunk.text}" for i, h in enumerate(hits))
    payload = json.dumps({"question": question, "passages": passages}, sort_keys=True)
    gw = complete(payload, prompt_version="reckoner_v1")
    if not gw.text:
        return None
    if gw.text.strip().upper().startswith("NOT_COVERED"):
        return None
    if scan_text(gw.text) or not dose_check(gw.text, hits):
        return None
    return gw.text.strip()


def ask(question: str, *, k: int = 4, index=None) -> ReckonerAnswer:
    q = (question or "").strip()
    if not q:
        return ReckonerAnswer(q, REFUSAL, True, False, [], "refused", "passed", False)
    if scan_text(q):
        return ReckonerAnswer(q, REFUSAL, True, False, [], "refused", "passed", False)
    if looks_out_of_scope(q):
        return ReckonerAnswer(q, REFUSAL, True, False, [], "refused", "passed", False)

    hits = retrieve(q, k=k, index=index)
    if not is_covered(hits) :
        return ReckonerAnswer(q, REFUSAL, True, False, _cite(hits), "refused", "passed", False)

    llm = _llm_answer(q, hits)
    if llm:
        return ReckonerAnswer(q, llm, False, True, _cite(hits), "llm", "passed", False)

    text = extractive_answer(q, hits)
    if scan_text(text) or not dose_check(text, hits):
        return ReckonerAnswer(q, REFUSAL, True, True, _cite(hits), "refused", "failed_fallback", True)
    return ReckonerAnswer(q, text, False, True, _cite(hits), "extractive", "passed", False)
