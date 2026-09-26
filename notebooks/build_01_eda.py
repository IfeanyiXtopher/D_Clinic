"""Builds notebooks/01_eda.ipynb from source cells. Run: python notebooks/build_01_eda.py"""

from pathlib import Path

import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s))  # noqa: E731
code = lambda s: cells.append(nbf.v4.new_code_cell(s))  # noqa: E731

md("""# 01 — Exploratory data analysis of the synthetic program cohort

**Purpose.** Understand the synthetic hypertension/diabetes program data before modelling:
who is registered, how often visits are missed, who is overdue or lost to follow-up, how well
blood pressure is controlled, what phone calls achieve, and what patients write back by SMS.

**Data.** PostgreSQL database `d_clinic`, tables named after Simple's schema, loaded by `make seed`.
All patients are synthetic. Definitions follow `docs/definitions.md`.

**Privacy note.** This notebook reads only structured, non-identifying columns. It never selects
`full_name`, phone numbers, or street addresses.""")

code("""import sys, warnings
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sqlalchemy import text

warnings.filterwarnings("ignore")
ROOT = Path.cwd().resolve()
ROOT = ROOT if (ROOT / "D_Clinic_Backend").exists() else ROOT.parent
sys.path.insert(0, str(ROOT / "D_Clinic_Backend"))
from app.db import engine  # noqa: E402

pd.set_option("display.width", 140)
plt.rcParams["figure.figsize"] = (9, 3.5)
AS_OF = pd.Timestamp.today().normalize()

def q(sql: str, **params) -> pd.DataFrame:
    with engine.connect() as c:
        return pd.read_sql(text(sql), c, params=params)

print("as of", AS_OF.date())""")

md("## 1. Cohort overview")

code("""patients = q('''
    SELECT p.id AS patient_id, p.age, p.gender, p.status, p.reminder_consent, p.recorded_at AS registered_at,
           f.name AS facility, a.zone AS distance_band, a.state AS region,
           mh.diabetes = 'yes' AS diabetic,
           EXISTS (SELECT 1 FROM patient_phone_numbers ph WHERE ph.patient_id = p.id AND ph.active) AS has_phone
    FROM patients p
    JOIN facilities f ON f.id = p.assigned_facility_id
    JOIN addresses a ON a.patient_id = p.id
    JOIN medical_histories mh ON mh.patient_id = p.id
''')
patients["age_band"] = pd.cut(patients.age, [0, 39, 49, 59, 69, 120], labels=["<40", "40-49", "50-59", "60-69", "70+"])
print(f"{len(patients):,} patients")
summary = {col: patients[col].astype(str).value_counts(normalize=True).round(3).to_dict()
           for col in ["gender", "status", "reminder_consent", "distance_band", "diabetic", "has_phone"]}
display(pd.Series(summary).to_frame("share by value"))
display(patients.groupby("facility").size().rename("patients").to_frame().T)""")

code("""fig, ax = plt.subplots(1, 2)
patients.age_band.value_counts().sort_index().plot.bar(ax=ax[0], title="Age band at registration", rot=0)
patients.set_index("registered_at").resample("MS").size().plot(ax=ax[1], title="Registrations per month")
plt.tight_layout()""")

md("""## 2. Appointments and the missed-visit label

An appointment is created at every visit. The label for Step 2 is **missed = no BP recorded within
[scheduled − 3 d, scheduled + 7 d]**. Only appointments whose window has closed are labelled.""")

code("""appts = q('''
    SELECT a.id AS appointment_id, a.patient_id, a.facility_id, a.scheduled_date, a.status,
           a.device_created_at AS booked_at, (a.scheduled_date - a.device_created_at::date) AS lead_days
    FROM appointments a
''')
bps = q("SELECT patient_id, recorded_at::date AS d, systolic, diastolic, recorded_at FROM blood_pressures WHERE deleted_at IS NULL")
appts["scheduled_date"] = pd.to_datetime(appts.scheduled_date)
bps["d"] = pd.to_datetime(bps.d)

due = appts[appts.scheduled_date <= AS_OF - pd.Timedelta(days=7)].copy()
m = due[["appointment_id", "patient_id", "scheduled_date"]].merge(bps[["patient_id", "d"]], on="patient_id", how="left")
hit = (m.d >= m.scheduled_date - pd.Timedelta(days=3)) & (m.d <= m.scheduled_date + pd.Timedelta(days=7))
due["missed"] = ~hit.groupby(m.appointment_id).any().reindex(due.appointment_id).values
due = due.merge(patients[["patient_id", "facility", "distance_band", "gender", "age_band", "region", "reminder_consent"]], on="patient_id")
print(f"{len(due):,} labelled appointments; missed rate = {due.missed.mean():.1%}")""")

code("""fig, ax = plt.subplots(1, 3, figsize=(13, 3.5))
due.groupby("facility").missed.mean().sort_values().plot.barh(ax=ax[0], title="Missed rate by facility")
due["lead_band"] = pd.cut(due.lead_days, [0, 20, 35, 60, 400], labels=["≤20 d", "21-35 d", "36-60 d", ">60 d"])
due.groupby("lead_band").missed.mean().plot.bar(ax=ax[1], title="Missed rate by lead time", rot=0)
due.groupby("distance_band").missed.mean().reindex(["near", "mid", "far"]).plot.bar(ax=ax[2], title="Missed rate by distance band", rot=0)
for a in ax: a.set_xlabel("")
plt.tight_layout()""")

code("""# Region shows a gap — but the generator gives region no causal effect. The gap is mediated by distance.
pd.concat({
    "by region": due.groupby("region").missed.mean().round(3),
    "far share": patients.groupby("region").distance_band.apply(lambda s: (s == "far").mean()).round(3),
}, axis=1)""")

code("""# Within each distance band, the regional gap largely disappears
due.pivot_table(index="distance_band", columns="region", values="missed", aggfunc="mean").round(3).reindex(["near", "mid", "far"])""")

md("## 3. Overdue and lost to follow-up (program views)")

code("""ov = q("SELECT * FROM overdue_patients")
uc = q("SELECT count(*) AS n FROM patients_under_care").n[0]
ltfu = q("SELECT count(*) AS n FROM lost_to_follow_up").n[0]
print(f"under care: {uc:,}   overdue: {len(ov):,} ({len(ov)/uc:.1%})   with phone (overdue list): {ov.has_phone.sum():,}   LTFU: {ltfu:,}")
fig, ax = plt.subplots(1, 2)
pd.cut(ov.days_overdue, [0, 15, 30, 60, 120, 365, 2000]).value_counts().sort_index().plot.bar(ax=ax[0], title="Days overdue", rot=45)
ov.merge(patients[["patient_id", "facility"]], on="patient_id").groupby("facility").size().plot.barh(ax=ax[1], title="Overdue by facility")
plt.tight_layout()""")

md("## 4. Blood pressure control")

code("""ctrl = q("SELECT controlled FROM bp_controlled_latest")
print(f"controlled (<140/90) at latest visit: {ctrl.controlled.mean():.1%}")
reg = patients.set_index("patient_id").registered_at
bps["months_in_program"] = ((bps.recorded_at - bps.patient_id.map(reg)).dt.days // 30).clip(0, 23)
trend = bps.groupby("months_in_program").agg(systolic=("systolic", "mean"), controlled=("systolic", lambda s: np.nan))
trend["controlled"] = bps.assign(c=(bps.systolic < 140) & (bps.diastolic < 90)).groupby("months_in_program").c.mean()
fig, ax = plt.subplots(1, 2)
trend.systolic.plot(ax=ax[0], title="Mean systolic by months in program"); ax[0].axhline(140, ls="--", c="grey")
trend.controlled.plot(ax=ax[1], title="Share controlled by months in program")
plt.tight_layout()""")

md("## 5. Overdue calls and what they achieve\n\nSimple's effectiveness metric: **did the patient visit within 15 days of the call?**")

code("""calls = q('''
    SELECT c.appointment_id, c.patient_id, c.result_type, c.remove_reason, c.device_created_at AS called_at
    FROM call_results c
''')
calls["called_at"] = pd.to_datetime(calls.called_at)
mm = calls.merge(bps[["patient_id", "recorded_at"]], on="patient_id", how="left")
within = (mm.recorded_at > mm.called_at) & (mm.recorded_at <= mm.called_at + pd.Timedelta(days=15))
calls["returned_15d"] = within.groupby([mm.appointment_id, mm.called_at]).any().reindex(pd.MultiIndex.from_frame(calls[["appointment_id", "called_at"]])).values
display(calls.result_type.value_counts(normalize=True).round(3).to_frame("share"))
display(calls.groupby("result_type").returned_15d.mean().round(3).to_frame("returned within 15 days"))
display(calls.remove_reason.value_counts().to_frame("removed reasons"))""")

md("## 6. SMS reminders and patient replies\n\nInbound replies are the raw material for the scheduling chatbot (Step 5). Intent labels come from the generator's truth file, which is never loaded into the database.")

code("""sms = q("SELECT communication_type, direction, delivery_status, language, body FROM communications")
display(sms.groupby(["communication_type", "direction"]).size().to_frame("n"))
out = sms[sms.direction == "outbound"]
print(f"outbound delivery status: {out.delivery_status.value_counts(normalize=True).round(3).to_dict()}")
print(f"reply rate per outbound SMS: {(sms.direction == 'inbound').sum() / (out.communication_type != 'voip_call').sum():.1%}")
intents = pd.read_csv(ROOT / "data/synth/out/_truth_sms_intents.csv")
fig, ax = plt.subplots(1, 2)
intents.intent.value_counts().plot.barh(ax=ax[0], title="Reply intents (truth)")
intents.language.value_counts().plot.bar(ax=ax[1], title="Reply language", rot=0)
plt.tight_layout()
sms[sms.direction == "inbound"].sample(10, random_state=0)[["language", "body"]]""")

md("""## 7. Takeaways for modelling

- **Label balance.** Roughly one in four labelled appointments is missed — imbalanced but not extreme; PR-AUC and precision at worklist capacity matter more than accuracy.
- **Strong signals.** Distance band, facility, and prior misses (to be built in Step 2) all separate the classes.
- **Lead time is confounded.** Very short intervals (≤20 d) are given to *uncontrolled* patients, who also miss more, so the raw curve is U-shaped; the >60 d group is still the riskiest. The model needs control status and interval together, not lead time alone.
- **Fairness trap.** Region shows a raw gap that disappears within distance band. Region must stay out of the features and appear only in the audit (`notebooks/03_fairness_and_calibration.ipynb`).
- **Operational reality.** About half the under-care patients are overdue at any time and only ~half of overdue patients with a phone get a call — capacity is the constraint the worklist (Step 3) must respect.
- **Chatbot data.** Replies are short, multilingual and noisy; ~13% confirm, ~6% ask to reschedule, ~3% describe symptoms that must be routed to a human.""")

nb["cells"] = cells
nb["metadata"] = {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}}
out = Path(__file__).parent / "01_eda.ipynb"
nbf.write(nb, out)
print("wrote", out)
