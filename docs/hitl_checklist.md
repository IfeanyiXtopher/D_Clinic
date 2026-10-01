# Human-in-the-loop checklist (Step 8.5)

Each row is a feature that can act on a patient. `[x]` means the code path
was verified: the model or score cannot complete the action alone.

| Feature | Human decision | What code forbids | Verified |
| --- | --- | --- | --- |
| Risk score | Worker decides whether to call | Score never sets `patients.status` or removes from care | [x] `POST /risk/score` writes `risk_scores` only |
| Worklist | Worker skips or records the call | List is suggestion; `POST /call-results` is the write | [x] skip and call-result APIs; rebuild keeps actioned rows |
| Summary | Worker reads facts + briefing | Identity refused; invented numbers fall back to template | [x] `tests/test_deid.py`, `tests/test_privacy_boundary.py` |
| Chatbot | Medical / unknown → staff task | Tools book only open slots; dates inserted by code | [x] `tests/test_dialogue.py`; medical → `staff_tasks` |
| Ready-reckoner | Worker applies protocol | Extractive + dose check; out-of-scope refused | [x] `tests/test_reckoner.py`; next-step table is deterministic |

A score **adds** a support task. It never withholds a visit, a drug, or a
slot. Promotion of a new model still requires the fairness gate in
`docs/responsible_ai.md`.
