# Program definitions

These definitions drive labels, views, worklists and reports. They follow
Simple and the WHO HEARTS indicators so that results are comparable with a real
program. SQL lives in `D_Clinic_Backend/alembic/versions/0002_program_logic_views.py`.

| Term | Definition | Where |
| --- | --- | --- |
| Visit | A blood pressure recorded for the patient (Simple counts a BP as the visit) | `blood_pressures` |
| Appointment | Created at every visit with a `scheduled_date`; `status` is `scheduled`, `visited` or `cancelled` | `appointments` |
| Missed visit (label) | No BP recorded in the window `[scheduled_date − 3 d, scheduled_date + 7 d]` | `ml/features.py` (Step 2) |
| Attended | A BP recorded inside that window | |
| Overdue | Latest appointment still `scheduled`, its date has passed, and no visit on/after that date; patient is under care | view `overdue_patients` |
| Overdue list | Overdue **and** has an active phone (what nurses see on the phone) | `overdue_patients.has_phone = true` |
| Follow-up list | All overdue, including patients without a phone (dashboard) | `overdue_patients` |
| Under care | Alive, active, and a visit in the last 12 months | view `patients_under_care` |
| Lost to follow-up (LTFU) | Active, registered > 12 months ago, no visit in the last 12 months | view `lost_to_follow_up` |
| BP controlled | Latest BP < 140/90 | view `bp_controlled_latest` |
| Call result | `agreed_to_visit`, `remind_to_call_later`, `removed_from_overdue_list` (+ `remove_reason`) | `call_results` |
| Return after call | A visit within 15 days of a call (Simple's call-effectiveness metric) | Step 3 replay |
| Reminder consent | `patients.reminder_consent = 'granted'`; an inbound `stop` sets it to `denied` | |

## Expected ranges for the synthetic cohort

Used by `make seed` output and the generator tests as sanity checks.

| Indicator | Expected | Rationale |
| --- | --- | --- |
| Missed-visit rate | 20–35% | Published no-show rates in chronic-care follow-up |
| Overdue among under-care | 30–50% | Range seen on public Simple dashboards |
| BP controlled at latest visit | 30–50% | Typical program control rates |
| Call results split | ~50 / 30 / 20 | agreed / remind later / removed |

## Things the synthetic data deliberately encodes

- A latent adherence propensity per patient (in `_truth_patients.csv`, never loaded).
- Region has **no causal effect** on missing; it is correlated with distance
  band (`addresses.zone`), so a naive audit will show a regional gap mediated by
  distance. Step 2.8 must surface and explain this.
- Reminders reduce missing modestly; recent misses increase it; long lead
  times increase it; rainy-season months increase it.
