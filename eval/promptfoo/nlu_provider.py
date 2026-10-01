"""promptfoo Python provider — rule NLU only. No identity in, no booking out."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "D_Clinic_Backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from chatbot.nlu import understand_rules  # noqa: E402


def call_api(prompt: str, options: dict | None = None, context: dict | None = None) -> dict:
    state = "idle"
    if context and isinstance(context.get("vars"), dict):
        state = context["vars"].get("state") or "idle"
    nlu = understand_rules(str(prompt), state=state)
    return {"output": nlu.as_dict()}
