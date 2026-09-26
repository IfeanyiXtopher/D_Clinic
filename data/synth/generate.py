"""Synthetic hypertension/diabetes program cohort, shaped like Simple's tables.

Design goals
------------
* Deterministic for a given seed.
* Realistic *behaviour*: a latent per-patient adherence propensity drives
  missed visits; missing is also affected by distance to facility, facility,
  lead time, number of drugs, age, season, reminders and recent misses.
* Program logic mirrors Simple: an appointment is created at every visit; a
  missed appointment stays `scheduled` and makes the patient overdue; overdue
  patients with a phone get a reminder SMS and, often, a phone call whose
  outcome is recorded in `call_results` with Simple's exact values; a return
  visit marks the overdue appointment `visited`.
* Ethnicity / region has **no causal effect** on missing in this generator.
  Region is correlated with distance band, so a fairness audit will see a
  disparity mediated by distance. That is deliberate and documented.
* Identity fields (names, phone numbers) are fake and never used by any model.

Outputs a dict of pandas DataFrames keyed by table name, plus two "truth"
frames (`_truth_patients`, `_truth_sms_intents`) that are **not** loaded into
the database. They exist for validation and as labels for the chatbot.
"""

from __future__ import annotations

import argparse
import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

PROGRAM_START = date(2024, 9, 1)
PROGRAM_END = date(2026, 9, 25)  # "as of" date for the generated history

# ----------------------------------------------------------------------------
# Reference data
# ----------------------------------------------------------------------------

FACILITIES = [
    # name, type, district, state, size, miss log-odds effect, call capacity (prob a call happens)
    ("Agege Primary Health Centre", "PHC", "Agege", "Lagos", "medium", -0.20, 0.70),
    ("Ikorodu General Hospital", "District Hospital", "Ikorodu", "Lagos", "large", 0.05, 0.55),
    ("Abeokuta South Comprehensive HC", "CHC", "Abeokuta South", "Ogun", "medium", 0.20, 0.65),
    ("Ijebu Ode Primary Health Centre", "PHC", "Ijebu Ode", "Ogun", "small", -0.10, 0.75),
    ("Sagamu Model PHC", "PHC", "Sagamu", "Ogun", "small", 0.35, 0.50),
]

REGIONS = ["Lagos", "Ogun", "Oyo"]
# distance band probabilities [near, mid, far] by region (the only region effect)
REGION_ZONE_P = {
    "Lagos": [0.55, 0.35, 0.10],
    "Ogun": [0.40, 0.40, 0.20],
    "Oyo": [0.25, 0.40, 0.35],
}
ZONE_EFFECT = {"near": 0.0, "mid": 0.25, "far": 0.60}

FIRST_NAMES = {
    "female": [
        "Adaeze", "Aisha", "Amina", "Bisi", "Blessing", "Chioma", "Fatima", "Folake", "Funmi", "Grace",
        "Hadiza", "Halima", "Ifeoma", "Kemi", "Khadija", "Maryam", "Ngozi", "Nkechi", "Oluwaseun", "Patience",
        "Rukayat", "Sade", "Temitope", "Titilayo", "Yetunde", "Zainab", "Comfort", "Esther", "Ruth", "Mercy",
    ],
    "male": [
        "Abubakar", "Adewale", "Ahmed", "Babatunde", "Chinedu", "Emeka", "Femi", "Ibrahim", "Ikenna", "Kunle",
        "Musa", "Nnamdi", "Obinna", "Olamide", "Olusegun", "Sani", "Segun", "Tunde", "Usman", "Yusuf",
        "Chukwudi", "Bello", "Gbenga", "Idris", "Kelechi", "Lateef", "Moses", "Peter", "Rotimi", "Umar",
    ],
}
SURNAMES = [
    "Adebayo", "Adeyemi", "Afolabi", "Akinyemi", "Balogun", "Bello", "Chukwu", "Danjuma", "Eze", "Garba",
    "Ibrahim", "Igwe", "Lawal", "Mohammed", "Nwachukwu", "Nwosu", "Obi", "Ogunleye", "Okafor", "Okeke",
    "Okonkwo", "Oladipo", "Olawale", "Onyeka", "Salami", "Suleiman", "Uche", "Umar", "Yakubu", "Yusuf",
]
VILLAGES = ["Ogba", "Oke-Odo", "Ipaja", "Ijede", "Imota", "Kuto", "Panseke", "Ijebu-Igbo", "Ogijo", "Ikenne", "Ibafo", "Mowe"]

# WHO HEARTS-style ladder used by many programs: step -> list of (drug, dosage)
HTN_LADDER = {
    1: [("Amlodipine", "5 mg")],
    2: [("Amlodipine", "10 mg")],
    3: [("Amlodipine", "10 mg"), ("Telmisartan", "40 mg")],
    4: [("Amlodipine", "10 mg"), ("Telmisartan", "80 mg")],
    5: [("Amlodipine", "10 mg"), ("Telmisartan", "80 mg"), ("Chlorthalidone", "12.5 mg")],
}
RXNORM = {"Amlodipine": "17767", "Telmisartan": "73494", "Chlorthalidone": "2409", "Metformin": "6809"}

REMOVE_REASONS = ["not_responding", "invalid_phone_number", "moved", "refused_to_return", "dead", "public_hospital_transfer", "other"]
REMOVE_REASON_P = [0.40, 0.20, 0.15, 0.10, 0.05, 0.05, 0.05]

SMS_INTENTS = ["none", "confirm", "reschedule", "ask_slot", "wrong_number", "stop", "symptom_or_medical", "unknown"]
SMS_INTENT_P = [0.68, 0.13, 0.06, 0.04, 0.02, 0.01, 0.03, 0.03]

SMS_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "confirm": [
        ("en", "Ok I will come"), ("en", "Yes"), ("en", "Noted, thank you"), ("en", "1"), ("en", "Alright see you tomorrow"),
        ("pcm", "I go come"), ("pcm", "Na ok, I dey come"), ("pcm", "No wahala, I go show"),
        ("ha", "To, zan zo"), ("ha", "Na gode, zan zo gobe"),
        ("yo", "Mo ma wa"), ("yo", "O da, ma wa lola"),
    ],
    "reschedule": [
        ("en", "I can't come on that day, can I come next week"), ("en", "Cant make it tomorrow"), ("en", "2"),
        ("en", "Please change my appointment to Friday"), ("pcm", "I no fit come tomorrow, abeg shift am"),
        ("pcm", "Make I come next week instead"), ("ha", "Ba zan iya zuwa gobe ba, mako mai zuwa"), ("yo", "Mi o le wa ni ola, ose to n bo"),
    ],
    "ask_slot": [
        ("en", "Which day should I come?"), ("en", "What time does the clinic open"), ("en", "Is Saturday possible?"),
        ("pcm", "Wetin time clinic dey open?"), ("pcm", "Which day I fit come?"), ("ha", "Wace rana zan zo?"), ("yo", "Ojo wo ni ki n wa?"),
    ],
    "wrong_number": [
        ("en", "Who is this?"), ("en", "Wrong number"), ("en", "I don't know this person"),
        ("pcm", "I no know this person o"), ("ha", "Wannan lambar ba tawa ba"), ("yo", "Nomba yi ko tọ"),
    ],
    "stop": [
        ("en", "STOP"), ("en", "Stop sending me messages"), ("en", "Please remove my number"),
        ("pcm", "No dey send me message again"), ("ha", "Daina aiko min da sako"), ("yo", "E ma fi ranṣẽ si mi mọ"),
    ],
    "symptom_or_medical": [
        ("en", "My head is paining me and my BP is high"), ("en", "I have finished my drugs"), ("en", "Can I stop the tablets? I feel fine now"),
        ("en", "My leg is swelling since I started the medicine"), ("pcm", "Drug don finish"), ("pcm", "My body dey weak, wetin I go do"),
        ("ha", "Ina jin ciwon kai, magani ya kare"), ("yo", "Ori n fo mi, oogun mi ti tan"),
    ],
    "unknown": [
        ("en", "?"), ("en", "Ok ok ok pls"), ("en", "Thanks be to God"), ("en", "Amen"), ("pcm", "Abeg"), ("en", "Hello"),
    ],
}

NOISE_MAP = {"come": "cme", "tomorrow": "tomorow", "please": "pls", "appointment": "apointment", "clinic": "clinc", "next": "nxt"}


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _logit(p: float) -> float:
    return math.log(p / (1 - p))


# Return-to-care behaviour after a missed visit depends on the hidden propensity `theta`.
# Patients who miss for circumstantial reasons (low theta) mostly come back on their own; hard-to-reach
# patients (high theta) rarely return unaided and return somewhat less even after a call. The *uplift*
# of a call (p_call - p_no_call) therefore grows with theta: calls help most where they are most needed.
# These functions are imported by the worklist evaluation to compute counterfactual uplift.
def p_return_after_call(theta: float) -> float:
    """P(visit within 15 days | called and agreed to visit)."""
    return _sigmoid(_logit(0.65) - 0.35 * theta)


def p_return_no_call(theta: float) -> float:
    """P(visit within ~45 days | no call made)."""
    return _sigmoid(_logit(0.50) - 0.80 * theta)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class Ids:
    """Deterministic UUIDs from the seeded RNG."""

    def __init__(self, rng: np.random.Generator):
        self.rng = rng

    def new(self) -> str:
        return str(uuid.UUID(bytes=self.rng.bytes(16), version=4))


def _dt(d: date, hour_lo: int = 8, hour_hi: int = 16, rng: np.random.Generator | None = None) -> datetime:
    h = int(rng.integers(hour_lo, hour_hi)) if rng is not None else 10
    m = int(rng.integers(0, 60)) if rng is not None else 0
    return datetime(d.year, d.month, d.day, h, m)


@dataclass
class PatientState:
    pid: str
    facility_idx: int
    reg_date: date
    age_at_reg: int
    gender: str
    diabetic: bool
    has_phone: bool
    consent: bool
    zone: str
    theta: float  # latent miss propensity (higher = misses more)
    adherence: float  # 0..1 medication adherence, negatively related to theta
    systolic: float
    diastolic: float
    step: int = 1
    consecutive_misses: int = 0
    alive: bool = True
    active: bool = True
    phone_active: bool = True
    drugs_active: list[str] = field(default_factory=list)
    # direct references to this patient's rows, to avoid scanning whole tables
    patient_row: dict = field(default_factory=dict)
    phone_rows: list[dict] = field(default_factory=list)
    active_rx_rows: list[dict] = field(default_factory=list)
    has_metformin: bool = False


class Generator:
    def __init__(self, n_patients: int = 6000, seed: int = 42):
        self.n = n_patients
        self.rng = np.random.default_rng(seed)
        self.ids = Ids(self.rng)
        self.rows: dict[str, list[dict]] = {
            k: []
            for k in [
                "facilities", "users", "patients", "patient_phone_numbers", "addresses", "medical_histories",
                "blood_pressures", "blood_sugars", "prescription_drugs", "appointments", "call_results",
                "communications", "_truth_patients", "_truth_sms_intents",
            ]
        }
        self.facility_ids: list[str] = []
        self.users_by_facility: list[list[str]] = []

    # ------------------------------------------------------------------ setup
    def _setup_facilities(self) -> None:
        created = datetime(2024, 8, 15, 9, 0)
        roles = ["nurse", "nurse", "counselor", "medical_officer"]
        for name, ftype, district, state, size, _eff, _cap in FACILITIES:
            fid = self.ids.new()
            self.facility_ids.append(fid)
            self.rows["facilities"].append(
                dict(id=fid, name=name, facility_type=ftype, district=district, state=state, country="Nigeria",
                     facility_size=size, created_at=created)
            )
            n_users = {"small": 3, "medium": 4, "large": 6}[size]
            uids = []
            for i in range(n_users):
                uid = self.ids.new()
                gender = "female" if self.rng.random() < 0.7 else "male"
                full_name = f"{self.rng.choice(FIRST_NAMES[gender])} {self.rng.choice(SURNAMES)}"
                self.rows["users"].append(
                    dict(id=uid, full_name=full_name, role=roles[i % len(roles)], registration_facility_id=fid, created_at=created)
                )
                uids.append(uid)
            self.users_by_facility.append(uids)

    # --------------------------------------------------------------- patients
    def _new_patient(self) -> PatientState:
        rng = self.rng
        facility_idx = int(rng.choice(len(FACILITIES), p=[0.22, 0.30, 0.20, 0.15, 0.13]))
        fid = self.facility_ids[facility_idx]
        reg_offset = int(rng.integers(0, (PROGRAM_END - PROGRAM_START).days - 30))
        reg_date = PROGRAM_START + timedelta(days=reg_offset)
        gender = "female" if rng.random() < 0.56 else "male"
        age = int(np.clip(rng.normal(55, 12), 25, 90))
        diabetic = rng.random() < 0.25
        has_phone = rng.random() < 0.90
        consent = has_phone and rng.random() < 0.80
        # region correlates with facility state but not perfectly
        fac_state = FACILITIES[facility_idx][3]
        region = fac_state if rng.random() < 0.75 else str(rng.choice(REGIONS))
        zone = str(rng.choice(["near", "mid", "far"], p=REGION_ZONE_P[region]))
        theta = float(rng.normal(0, 1))
        adherence = float(np.clip(_sigmoid(-0.9 * theta + rng.normal(0, 0.6)), 0.05, 0.98))
        systolic = float(np.clip(rng.normal(158, 18), 125, 220))
        diastolic = float(np.clip(rng.normal(96, 11), 75, 130))

        pid = self.ids.new()
        reg_user = str(rng.choice(self.users_by_facility[facility_idx]))
        full_name = f"{rng.choice(FIRST_NAMES[gender])} {rng.choice(SURNAMES)}"
        reg_dt = _dt(reg_date, rng=rng)
        dob = date(reg_date.year - age, int(rng.integers(1, 13)), int(rng.integers(1, 28)))

        patient_row = dict(id=pid, full_name=full_name, age=age, age_updated_at=reg_dt, date_of_birth=dob, gender=gender,
                           status="active", reminder_consent="granted" if consent else "denied",
                           registration_facility_id=fid, assigned_facility_id=fid, registration_user_id=reg_user,
                           recorded_at=reg_dt, deleted_at=None)
        self.rows["patients"].append(patient_row)
        phone_rows: list[dict] = []
        if has_phone:
            number = "080" + "".join(str(int(x)) for x in rng.integers(0, 10, 8))
            phone_row = dict(id=self.ids.new(), patient_id=pid, number=number, phone_type="mobile", active=True,
                             dnd_status=False, created_at=reg_dt)
            self.rows["patient_phone_numbers"].append(phone_row)
            phone_rows.append(phone_row)
        self.rows["addresses"].append(
            dict(id=self.ids.new(), patient_id=pid, street_address=f"{int(rng.integers(1, 120))} {rng.choice(SURNAMES)} Street",
                 village_or_colony=str(rng.choice(VILLAGES)), district=FACILITIES[facility_idx][2], zone=zone,
                 state=region, country="Nigeria", created_at=reg_dt)
        )
        self.rows["medical_histories"].append(
            dict(id=self.ids.new(), patient_id=pid, hypertension="yes", diabetes="yes" if diabetic else "no",
                 prior_heart_attack="yes" if rng.random() < 0.04 else "no", prior_stroke="yes" if rng.random() < 0.05 else "no",
                 chronic_kidney_disease="yes" if rng.random() < 0.06 else "no", receiving_treatment_for_hypertension="yes",
                 created_at=reg_dt)
        )
        st = PatientState(pid, facility_idx, reg_date, age, gender, diabetic, has_phone, consent, zone, theta, adherence, systolic, diastolic,
                          patient_row=patient_row, phone_rows=phone_rows)
        self.rows["_truth_patients"].append(dict(patient_id=pid, theta=theta, adherence=adherence, region=region, zone=zone))
        return st

    # ------------------------------------------------------------- clinical
    def _record_visit(self, st: PatientState, d: date, returned_after_miss: bool) -> None:
        rng = self.rng
        fid = self.facility_ids[st.facility_idx]
        uid = str(rng.choice(self.users_by_facility[st.facility_idx]))
        when = _dt(d, rng=rng)

        # BP evolves: treatment pulls towards ~128/82 scaled by adherence and ladder step; misses push up.
        n_drugs = len(HTN_LADDER[st.step])
        effect = 7.0 * n_drugs * st.adherence
        if returned_after_miss:
            st.systolic += rng.normal(6, 5)
            st.diastolic += rng.normal(3, 3)
        st.systolic = max(105.0, st.systolic - effect * (1 if st.systolic > 128 else 0.2) + rng.normal(0, 7))
        st.diastolic = max(65.0, st.diastolic - effect * 0.5 * (1 if st.diastolic > 82 else 0.2) + rng.normal(0, 5))
        self.rows["blood_pressures"].append(
            dict(id=self.ids.new(), systolic=int(round(st.systolic)), diastolic=int(round(st.diastolic)), patient_id=st.pid,
                 facility_id=fid, user_id=uid, recorded_at=when, deleted_at=None)
        )
        if st.diabetic and rng.random() < 0.7:
            val = float(np.clip(rng.normal(170 - 40 * st.adherence, 45), 70, 450))
            self.rows["blood_sugars"].append(
                dict(id=self.ids.new(), blood_sugar_type="random", blood_sugar_value=round(val, 1), patient_id=st.pid,
                     facility_id=fid, user_id=uid, recorded_at=when, deleted_at=None)
            )

        uncontrolled = st.systolic >= 140 or st.diastolic >= 90
        first_visit = not st.drugs_active
        if first_visit:
            self._prescribe(st, when, fid, uid)
        elif uncontrolled and st.step < 5 and rng.random() < 0.6:
            st.step += 1
            self._prescribe(st, when, fid, uid)

    def _prescribe(self, st: PatientState, when: datetime, fid: str, uid: str) -> None:
        # soft-delete current protocol drugs, then add the new ladder step
        for row in st.active_rx_rows:
            row["is_deleted"] = True
            row["device_updated_at"] = when
        st.active_rx_rows = []
        for name, dosage in HTN_LADDER[st.step]:
            row = dict(id=self.ids.new(), name=name, rxnorm_code=RXNORM[name], dosage=dosage, frequency="OD",
                       is_protocol_drug=True, is_deleted=False, patient_id=st.pid, facility_id=fid, user_id=uid,
                       device_created_at=when, device_updated_at=when)
            self.rows["prescription_drugs"].append(row)
            st.active_rx_rows.append(row)
        if st.diabetic and not st.has_metformin:
            self.rows["prescription_drugs"].append(
                dict(id=self.ids.new(), name="Metformin", rxnorm_code=RXNORM["Metformin"], dosage="500 mg", frequency="BD",
                     is_protocol_drug=False, is_deleted=False, patient_id=st.pid, facility_id=fid, user_id=uid,
                     device_created_at=when, device_updated_at=when)
            )
            st.has_metformin = True
        st.drugs_active = [n for n, _ in HTN_LADDER[st.step]] + (["Metformin"] if st.diabetic else [])

    # ----------------------------------------------------------- behaviour
    def _p_miss(self, st: PatientState, scheduled: date, lead_days: int) -> float:
        fac_eff = FACILITIES[st.facility_idx][5]
        x = -1.45
        x += 0.90 * st.theta
        x += ZONE_EFFECT[st.zone]
        x += fac_eff
        x += 0.15 if st.gender == "male" else 0.0
        x += 0.30 if st.age_at_reg < 40 else (0.20 if st.age_at_reg >= 70 else 0.0)
        x += 0.10 if st.diabetic else 0.0
        # long lead times raise no-show risk (dominant effect in published no-show models)
        x += 0.55 if lead_days > 35 else 0.0
        x += 0.45 if lead_days > 60 else 0.0
        x += 0.15 * (len(HTN_LADDER[st.step]) - 1)
        x += 0.10 if (st.systolic >= 140 or st.diastolic >= 90) else 0.0
        x += 0.30 * min(st.consecutive_misses, 2)
        x -= 0.25 if st.consent else 0.0
        x += 0.15 if scheduled.month in (6, 7, 8, 9) else 0.0  # rainy season
        return _sigmoid(x)

    def _sms(self, st: PatientState, appt_id: str, ctype: str, when: datetime, body: str) -> None:
        if not st.consent or not st.phone_active:
            return
        status = str(self.rng.choice(["delivered", "sent", "failed"], p=[0.82, 0.10, 0.08]))
        cid = self.ids.new()
        self.rows["communications"].append(
            dict(id=cid, patient_id=st.pid, appointment_id=appt_id, user_id=None, communication_type=ctype,
                 direction="outbound", body=body, language="en", delivery_status=status, device_created_at=when)
        )
        if status == "failed":
            return
        intent = str(self.rng.choice(SMS_INTENTS, p=SMS_INTENT_P))
        if intent == "none":
            return
        lang, text = SMS_TEMPLATES[intent][int(self.rng.integers(0, len(SMS_TEMPLATES[intent])))]
        if self.rng.random() < 0.25:
            for k, v in NOISE_MAP.items():
                text = text.replace(k, v)
        if self.rng.random() < 0.3:
            text = text.lower()
        reply_id = self.ids.new()
        self.rows["communications"].append(
            dict(id=reply_id, patient_id=st.pid, appointment_id=appt_id, user_id=None, communication_type="sms",
                 direction="inbound", body=text, language=lang, delivery_status="delivered",
                 device_created_at=when + timedelta(minutes=int(self.rng.integers(2, 600))))
        )
        self.rows["_truth_sms_intents"].append(dict(communication_id=reply_id, intent=intent, language=lang))
        if intent == "stop":
            st.consent = False
            st.patient_row["reminder_consent"] = "denied"

    # ------------------------------------------------------------- lifecycle
    def _simulate_patient(self, st: PatientState) -> None:
        rng = self.rng
        fid = self.facility_ids[st.facility_idx]
        fac_name = FACILITIES[st.facility_idx][0]
        call_cap = FACILITIES[st.facility_idx][6]

        visit_date = st.reg_date
        self._record_visit(st, visit_date, returned_after_miss=False)

        guard = 0
        while guard < 60:
            guard += 1
            controlled = st.systolic < 140 and st.diastolic < 90
            interval = int(rng.choice([28, 56, 84], p=[0.35, 0.50, 0.15])) if controlled else int(rng.choice([14, 28], p=[0.25, 0.75]))
            interval += int(rng.integers(-3, 4))
            scheduled = visit_date + timedelta(days=max(7, interval))
            booked_at = _dt(visit_date, rng=rng)
            appt_id = self.ids.new()
            appt = dict(id=appt_id, patient_id=st.pid, facility_id=fid, creation_facility_id=fid,
                        user_id=str(rng.choice(self.users_by_facility[st.facility_idx])), scheduled_date=scheduled,
                        status="scheduled", cancel_reason=None, remind_on=None, agreed_to_visit=None,
                        appointment_type="automatic", device_created_at=booked_at, device_updated_at=booked_at)
            self.rows["appointments"].append(appt)

            if scheduled > PROGRAM_END:
                break  # future appointment: stays scheduled, not yet due

            # random death / migration between visits
            yrs = (scheduled - visit_date).days / 365.0
            if rng.random() < 0.008 * yrs:
                st.alive = False
                self._set_patient_status(st, "dead")
                appt["status"] = "cancelled"; appt["cancel_reason"] = "dead"; appt["device_updated_at"] = _dt(scheduled, rng=rng)
                break
            if rng.random() < 0.01 * yrs:
                st.active = False
                self._set_patient_status(st, "migrated")
                appt["status"] = "cancelled"; appt["cancel_reason"] = "moved"; appt["device_updated_at"] = _dt(scheduled, rng=rng)
                break

            # pre-visit reminder
            self._sms(st, appt_id, "appointment_reminder", _dt(scheduled - timedelta(days=1), 9, 11, rng),
                      f"Reminder: your BP check at {fac_name} is tomorrow. Reply 1 to confirm or 2 to change the day.")

            lead_days = (scheduled - visit_date).days
            p = self._p_miss(st, scheduled, lead_days)
            if rng.random() >= p:
                # attended within the window (-3 .. +7 days)
                actual = scheduled + timedelta(days=int(rng.choice([-3, -2, -1, 0, 0, 0, 1, 2, 3, 5, 7], p=[.03, .04, .08, .35, .15, .10, .10, .06, .04, .03, .02])))
                actual = min(actual, PROGRAM_END)
                appt["status"] = "visited"; appt["device_updated_at"] = _dt(actual, rng=rng)
                st.consecutive_misses = 0
                self._record_visit(st, actual, returned_after_miss=False)
                visit_date = actual
                continue

            # ---- missed: patient is overdue -------------------------------------------------
            st.consecutive_misses += 1
            remind_on = scheduled + timedelta(days=3)
            appt["remind_on"] = remind_on
            if remind_on <= PROGRAM_END:
                self._sms(st, appt_id, "missed_visit_sms_reminder", _dt(remind_on, 9, 11, rng),
                          f"You missed your BP visit at {fac_name}. Please come this week. Reply 2 if you need another day.")

            return_days: int | None = None
            call_day = scheduled + timedelta(days=int(rng.integers(5, 21)))
            if st.has_phone and st.phone_active and call_day <= PROGRAM_END and rng.random() < call_cap:
                result = str(rng.choice(["agreed_to_visit", "remind_to_call_later", "removed_from_overdue_list"], p=[0.50, 0.30, 0.20]))
                reason = str(rng.choice(REMOVE_REASONS, p=REMOVE_REASON_P)) if result == "removed_from_overdue_list" else None
                call_dt = _dt(call_day, 9, 17, rng)
                self.rows["call_results"].append(
                    dict(id=self.ids.new(), user_id=str(rng.choice(self.users_by_facility[st.facility_idx])), appointment_id=appt_id,
                         patient_id=st.pid, facility_id=fid, result_type=result, remove_reason=reason,
                         device_created_at=call_dt, device_updated_at=call_dt)
                )
                self.rows["communications"].append(
                    dict(id=self.ids.new(), patient_id=st.pid, appointment_id=appt_id, user_id=None, communication_type="voip_call",
                         direction="outbound", body=None, language=None, delivery_status="completed" if result != "removed_from_overdue_list" or reason != "not_responding" else "no_answer",
                         device_created_at=call_dt)
                )
                offset = (call_day - scheduled).days
                if result == "agreed_to_visit":
                    appt["agreed_to_visit"] = True
                    if rng.random() < p_return_after_call(st.theta):
                        return_days = offset + int(rng.integers(1, 15))
                    elif rng.random() < 0.50:
                        return_days = offset + int(rng.integers(15, 60))
                elif result == "remind_to_call_later":
                    appt["remind_on"] = call_day + timedelta(days=7)
                    if rng.random() < 0.50 * p_return_after_call(st.theta) / 0.65:
                        return_days = offset + int(rng.integers(3, 30))
                else:
                    if reason == "dead":
                        st.alive = False; self._set_patient_status(st, "dead")
                        appt["status"] = "cancelled"; appt["cancel_reason"] = "dead"; appt["device_updated_at"] = call_dt
                        break
                    if reason in ("moved", "public_hospital_transfer"):
                        st.active = False; self._set_patient_status(st, "migrated")
                        appt["status"] = "cancelled"; appt["cancel_reason"] = reason; appt["device_updated_at"] = call_dt
                        break
                    if reason == "invalid_phone_number":
                        st.phone_active = False
                        for ph in st.phone_rows:
                            ph["active"] = False
                        if rng.random() < 0.20:
                            return_days = offset + int(rng.integers(10, 60))
                    elif reason == "refused_to_return":
                        if rng.random() < 0.10:
                            return_days = offset + int(rng.integers(30, 120))
                    else:  # not_responding, other
                        if rng.random() < 0.20:
                            return_days = offset + int(rng.integers(10, 60))
            else:
                # no call happened: spontaneous return depends strongly on the hidden propensity
                if rng.random() < p_return_no_call(st.theta):
                    return_days = int(rng.integers(8, 45))
                elif rng.random() < 0.40:
                    return_days = int(rng.integers(45, 120))

            if return_days is None and rng.random() < 0.35:
                return_days = int(rng.integers(60, 240))  # late return after long gap

            if return_days is None:
                break  # lost to follow-up; appointment stays scheduled and overdue

            ret = scheduled + timedelta(days=return_days)
            if ret > PROGRAM_END:
                break  # still overdue as of program end
            appt["status"] = "visited"; appt["device_updated_at"] = _dt(ret, rng=rng)
            self._record_visit(st, ret, returned_after_miss=True)
            visit_date = ret

    def _set_patient_status(self, st: PatientState, status: str) -> None:
        st.patient_row["status"] = status

    # ------------------------------------------------------------------ run
    def run(self) -> dict[str, pd.DataFrame]:
        self._setup_facilities()
        for _ in range(self.n):
            st = self._new_patient()
            self._simulate_patient(st)
        return {k: pd.DataFrame(v) for k, v in self.rows.items()}


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


def write(frames: dict[str, pd.DataFrame], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in frames.items():
        df.to_csv(out_dir / f"{name}.csv", index=False)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a synthetic Simple-shaped cohort")
    ap.add_argument("--patients", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "out")
    args = ap.parse_args()

    frames = Generator(args.patients, args.seed).run()
    write(frames, args.out)
    for name, df in frames.items():
        print(f"{name:24s} {len(df):>8,d} rows")


if __name__ == "__main__":
    main()
