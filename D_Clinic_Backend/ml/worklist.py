"""Optimized daily worklist for frontline health workers.

Who should the facility call today? Candidates are overdue patients as defined
by Simple (latest appointment still `scheduled`, date passed, no visit since,
patient under care). Eligibility rules mirror how programs already run the
overdue list; the risk model orders the eligible patients; a share of the
capacity is protected for patients whose blood pressure was uncontrolled at
their last visit.

Everything is computed **as of** a date so the same code powers today's list,
a rebuilt list for any past day, and the replay evaluation.

Rules (see docs/BUILD_PLAN.md step 3.1)
--------------------------------------
* Skip patients called in the last ``agreed_cooldown_days`` who agreed to visit.
* Resurface ``remind_to_call_later`` only once the requested callback date arrives.
* Drop patients removed from the overdue list (died, moved, refused, wrong number, ...).
* Patients without a phone stay on the *follow-up* list with a home-visit action,
  ranked after callable patients.
* Reserve ``protected_share`` of capacity for uncontrolled BP.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ml.features import build_feature_table
from ml.predict import score_frame


@dataclass
class WorklistConfig:
    capacity: int = 20  # calls per facility per day
    protected_share: float = 0.25  # of capacity reserved for uncontrolled BP
    agreed_cooldown_days: int = 15
    callback_default_days: int = 7
    under_care_days: int = 365
    pre_visit_slots: int = 5
    pre_visit_horizon_days: int = 7
    rank_by: str = "risk"  # risk | days_overdue | random
    seed: int = 0
    extra: dict = field(default_factory=dict)


REMOVED = "removed_from_overdue_list"
AGREED = "agreed_to_visit"
CALLBACK = "remind_to_call_later"


# --------------------------------------------------------------------------- as-of state


def _as_of_state(tables: dict[str, pd.DataFrame], as_of: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Restrict every table to what was known at ``as_of`` (end of that day)."""
    end = as_of.normalize() + pd.Timedelta(hours=23, minutes=59)
    a = tables["appointments"].copy()
    a["booked_at"] = pd.to_datetime(a.booked_at)
    a["scheduled_date"] = pd.to_datetime(a.scheduled_date).dt.normalize()
    a = a[a.booked_at <= end]
    if "device_updated_at" in a.columns:
        upd = pd.to_datetime(a.device_updated_at)
        a.loc[(a.status != "scheduled") & (upd > end), "status"] = "scheduled"  # outcome not yet known then
    bp = tables["blood_pressures"].copy()
    bp["recorded_at"] = pd.to_datetime(bp.recorded_at)
    bp = bp[bp.recorded_at <= end]
    calls = tables["call_results"].copy()
    calls["device_created_at"] = pd.to_datetime(calls.device_created_at)
    calls = calls[calls.device_created_at <= end]
    return {"appointments": a, "blood_pressures": bp, "call_results": calls, "patients": tables["patients"]}


def overdue_candidates(tables: dict[str, pd.DataFrame], as_of: pd.Timestamp, cfg: WorklistConfig,
                       facility_id: str | None = None) -> pd.DataFrame:
    """Overdue patients as of a date, with eligibility flags. One row per patient."""
    as_of = pd.Timestamp(as_of).normalize()
    s = _as_of_state(tables, as_of)
    a, bp, calls, patients = s["appointments"], s["blood_pressures"], s["call_results"], s["patients"]

    latest_appt = a.sort_values(["scheduled_date", "booked_at"]).groupby("patient_id").tail(1)
    latest_appt = latest_appt.rename(columns={"status": "appointment_status"})
    latest_bp = bp.sort_values("recorded_at").groupby("patient_id").tail(1)[["patient_id", "systolic", "diastolic", "recorded_at"]]
    pcols = ["patient_id", "status", "assigned_facility_id", "has_phone", "reminder_consent"]
    c = latest_appt.merge(latest_bp, on="patient_id", how="left").merge(
        patients[pcols].rename(columns={"status": "patient_status"}), on="patient_id", how="left")

    c = c[(c.appointment_status == "scheduled") & (c.scheduled_date < as_of)]
    c = c[c.patient_status == "active"]
    c["last_visit_at"] = c.recorded_at
    c = c[c.last_visit_at.notna() & (c.last_visit_at.dt.normalize() < c.scheduled_date)]
    c["under_care"] = c.last_visit_at >= as_of - pd.Timedelta(days=cfg.under_care_days)
    c["days_overdue"] = (as_of - c.scheduled_date).dt.days
    c["uncontrolled"] = ((c.systolic >= 140) | (c.diastolic >= 90)).fillna(False)
    if facility_id is not None:
        c = c[c.facility_id.astype(str) == str(facility_id)]

    # last call on the overdue appointment
    last_call = (calls.sort_values("device_created_at").groupby("appointment_id").tail(1)
                 [["appointment_id", "result_type", "remove_reason", "device_created_at"]]
                 .rename(columns={"result_type": "last_call_result", "remove_reason": "last_call_remove_reason",
                                  "device_created_at": "last_called_at"}))
    c = c.merge(last_call, on="appointment_id", how="left")
    n_calls = calls.groupby("appointment_id").size().rename("calls_on_this_appointment")
    c = c.merge(n_calls, left_on="appointment_id", right_index=True, how="left")
    c["calls_on_this_appointment"] = c.calls_on_this_appointment.fillna(0).astype(int)
    c["days_since_call"] = (as_of - c.last_called_at.dt.normalize()).dt.days

    # eligibility
    removed = c.last_call_result == REMOVED
    cooling = (c.last_call_result == AGREED) & (c.days_since_call < cfg.agreed_cooldown_days)
    # Prefer the stored remind_on (what the worker recorded); fall back to +7 days from the call.
    if "remind_on" in c.columns:
        remind = pd.to_datetime(c.remind_on, errors="coerce")
        callback_due_date = remind.fillna(c.last_called_at.dt.normalize() + pd.Timedelta(days=cfg.callback_default_days))
    else:
        callback_due_date = c.last_called_at.dt.normalize() + pd.Timedelta(days=cfg.callback_default_days)
    callback_due = (c.last_call_result == CALLBACK) & (callback_due_date <= as_of)
    callback_wait = (c.last_call_result == CALLBACK) & ~callback_due
    c["eligible"] = c.under_care & ~removed & ~cooling & ~callback_wait
    c["ineligible_reason"] = np.select(
        [~c.under_care, removed, cooling, callback_wait],
        ["lost to follow-up (no visit in 12 months)", "removed from overdue list", "agreed to visit recently", "callback not yet due"],
        default="")
    c["callback_due"] = callback_due
    return c.reset_index(drop=True)


# --------------------------------------------------------------------------- ranking


def _operational_reasons(row) -> list[str]:
    r = [f"{int(row.days_overdue)} days overdue"]
    if row.uncontrolled:
        r.append("BP uncontrolled at last visit")
    if row.callback_due:
        r.append("asked to be called back")
    if not row.has_phone:
        r.append("no phone on record")
    if row.calls_on_this_appointment >= 2:
        r.append(f"already called {int(row.calls_on_this_appointment)} times")
    return r


def rank_candidates(cands: pd.DataFrame, cfg: WorklistConfig) -> pd.DataFrame:
    """Order eligible candidates and apply capacity with protected slots. Adds ``rank`` (1..n) and ``selected``."""
    e = cands[cands.eligible].copy()
    if e.empty:
        e["rank"] = pd.Series(dtype=int); e["selected"] = pd.Series(dtype=bool); e["priority"] = pd.Series(dtype=float)
        return e
    rng = np.random.default_rng(cfg.seed)
    if cfg.rank_by == "risk":
        e["priority"] = e.p_missed.fillna(e.p_missed.median() if e.p_missed.notna().any() else 0.3)
    elif cfg.rank_by == "days_overdue":
        e["priority"] = e.days_overdue.astype(float)
    elif cfg.rank_by == "random":
        e["priority"] = rng.random(len(e))
    else:
        raise ValueError(cfg.rank_by)
    # callable patients first; then priority; then longer overdue first
    e = e.sort_values(["has_phone", "priority", "days_overdue"], ascending=[False, False, False]).reset_index(drop=True)

    cap = cfg.capacity
    n_protected = int(np.ceil(cfg.protected_share * cap))
    prot_idx = e.index[e.uncontrolled & e.has_phone][:n_protected].tolist()
    rest_idx = [i for i in e.index if i not in prot_idx][: max(cap - len(prot_idx), 0)]
    chosen = sorted(prot_idx + rest_idx)  # keep priority order within the selection
    e["selected"] = False
    e.loc[chosen, "selected"] = True
    e["protected_slot"] = False
    e.loc[prot_idx, "protected_slot"] = True
    # final rank: selected first in priority order, then the rest
    e = pd.concat([e[e.selected], e[~e.selected]]).reset_index(drop=True)
    e["rank"] = np.arange(1, len(e) + 1)
    e["suggested_action"] = np.where(~e.has_phone, "home_visit", np.where(e.callback_due, "call_back", "call"))
    e["list_type"] = "overdue"
    return e


def build_worklist(tables: dict[str, pd.DataFrame], as_of: pd.Timestamp, artifact: dict, cfg: WorklistConfig,
                   facility_id: str | None = None, scores: pd.DataFrame | None = None) -> pd.DataFrame:
    """Full worklist for one facility and date: overdue section + pre-visit high-risk section."""
    as_of = pd.Timestamp(as_of).normalize()
    if scores is None:
        ft = build_feature_table(tables, as_of)
        scores = score_frame(ft.frame, artifact)
    sc = scores.set_index(scores.appointment_id.astype(str))

    cands = overdue_candidates(tables, as_of, cfg, facility_id)
    cands["_aid"] = cands.appointment_id.astype(str)
    cands = cands.merge(sc[["p_missed", "band", "basis", "group_size", "reasons"]], left_on="_aid",
                        right_index=True, how="left").drop(columns=["_aid"])
    ranked = rank_candidates(cands, cfg)
    if not ranked.empty:
        ranked["reasons"] = [list(m) + _operational_reasons(r) for m, r in zip(ranked.reasons.apply(lambda x: x if isinstance(x, list) else []), ranked.itertuples())]

    # pre-visit: upcoming high-risk appointments in the next few days
    s = _as_of_state(tables, as_of)
    a = s["appointments"]
    up = a[(a.status == "scheduled") & (a.scheduled_date > as_of) & (a.scheduled_date <= as_of + pd.Timedelta(days=cfg.pre_visit_horizon_days))]
    if facility_id is not None:
        up = up[up.facility_id.astype(str) == str(facility_id)]
    up = up.copy()
    up["_aid"] = up.appointment_id.astype(str)
    up = up.merge(sc[["p_missed", "band", "basis", "group_size", "reasons"]], left_on="_aid", right_index=True, how="left").drop(columns=["_aid"])
    up = up.merge(tables["patients"][["patient_id", "has_phone", "status"]], on="patient_id", how="left")
    up = up[(up.band == "high") & (up.status_y == "active") & up.has_phone].sort_values("p_missed", ascending=False).head(cfg.pre_visit_slots).copy()
    if not up.empty:
        up["list_type"] = "pre_visit"
        up["suggested_action"] = "reminder_call"
        up["days_overdue"] = -(up.scheduled_date - as_of).dt.days
        up["uncontrolled"] = False
        up["selected"] = True
        up["protected_slot"] = False
        up["priority"] = up.p_missed
        up["rank"] = np.arange(1, len(up) + 1)
        up["reasons"] = [list(m if isinstance(m, list) else []) + [f"visit in {-d} days"] for m, d in zip(up.reasons, up.days_overdue)]

    cols = ["list_type", "rank", "selected", "protected_slot", "patient_id", "appointment_id", "facility_id", "scheduled_date",
            "days_overdue", "priority", "p_missed", "band", "basis", "group_size", "uncontrolled", "has_phone",
            "suggested_action", "reasons"]
    out = pd.concat([ranked.reindex(columns=cols), up.reindex(columns=cols)], ignore_index=True)
    out["list_date"] = as_of.date()
    return out
