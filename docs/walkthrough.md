# Walkthrough script (6–8 minutes)

Record this as the 6–8 minute demo. Speak to the **program**, not the hosting
box. Seeded list date: **2026-09-22**. SMS as-of: **2026-09-26**.

| Min | Screen | Say / do |
| ---: | --- | --- |
| 0:00–0:40 | README / browser | This is a follow-up layer beside Simple: missed-visit rank, briefing, SMS, protocol lookup. Synthetic patients. Identity never in a prompt. |
| 0:40–2:10 | Worklist `/` | Overdue vs pre-visit. Rank is risk, not oldest first. Open a high-risk case. Agreed to visit / Call later are Simple results. Score never removes anyone. |
| 2:10–4:00 | Patient `/patients/:id` | Case stub only. Facts, BP, drugs. Briefing checked against the record. Staff rating (required). Protocol next step. Ask a HEARTS question; show a refuse on something out of scope. |
| 4:00–6:00 | SMS `/chat` | Send reminder. Confirm in ordinary language. Then change day and pick “Wed 30 is fine”. Symptom line → callback. Show history (calls + SMS). Phone is the demo; production is the patient’s handset. |
| 6:00–7:30 | Evaluation `/eval` | Operating process. Extra returns +15%. Briefing check. SMS safety. Protocol refuse. Do not dwell on infra. |
| 7:30–8:00 | Close | Simple-shaped tables and call results. Next step is a replica, not a rewrite of Simple. |

**Do not** narrate RAM, templates-as-the-product, or unused model families.

Export a silent GIF of the four screens for the README if the host wants motion;
the still diagram is [`docs/demo-flow.svg`](demo-flow.svg).
