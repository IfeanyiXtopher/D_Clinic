# ADR-0002: Scheduling chatbot — "LLM understands, code decides"

**Status:** Accepted — 2026-09-26

## Context

The posting asks for a chatbot for appointment scheduling. Patients in these
programs mostly interact over SMS. Clinical programs will not accept a model
that chooses which appointment to book or gives medical advice.

## Decision

- A **Python dialogue state machine** owns the conversation: states `idle`,
  `confirming`, `choosing_slot`, `rescheduling`, `cancelling`, `handoff`.
- The LLM is used for **understanding only**, returning JSON constrained to a
  schema (`intent`, `date_hint`, `time_hint`, `confirm`, `language`,
  `needs_human`) via Ollama structured outputs.
- **Tools are called by the state machine**, never selected by the model:
  `get_available_slots`, `book`, `reschedule`, `cancel`, `record_reply`.
- Replies are **templated**; the model may rephrase into the patient's
  language and register. Dates/times are injected by code after rephrasing.
- Any medical or symptom intent yields a fixed "contact the facility" reply
  and creates a staff call task. `stop` turns off messaging consent.
- Patients are identified by phone number or a BP-Passport-style random code,
  resolved server-side. The model never sees either.
- A small supervised intent classifier is trained alongside the LLM path and
  compared on accuracy and CPU latency.

## Alternatives considered

- *Rasa.* Rasa Open Source is in maintenance mode; its LLM-native CALM engine
  requires a Rasa Pro licence. Rejected for a free/open MVP.
- *LLM with free-form tool calling.* Rejected: non-deterministic booking
  decisions are unacceptable in a clinical workflow and hard to evaluate.

## Consequences

- Evaluation is tractable: intent/slot accuracy, task completion, unsafe rate,
  PII-leak rate, measured on scripted dialogues.
- Adding a channel (web chat, real SMS provider) is an adapter, not a rewrite.
