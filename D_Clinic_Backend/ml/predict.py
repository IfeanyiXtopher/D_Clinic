"""Score upcoming appointments and persist the results.

Used by the nightly Celery task and by ``POST /risk/score``. Scores are appended
to ``risk_scores`` (history is kept); ``latest_risk_scores`` exposes the newest
row per appointment.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ml.cold_start import add_pooled_feature
from ml.features import build_feature_table, load_tables_from_db
from ml.train import MODEL_FEATURES, band, explain_rows, load_artifact


def score_frame(frame: pd.DataFrame, artifact: dict) -> pd.DataFrame:
    """Score any rows of a feature table. Returns one row per appointment."""
    cs = artifact["cold_start"]
    pooled = cs.pooled(frame)
    f = add_pooled_feature(frame, cs)
    p = artifact["model"].predict_proba(f[MODEL_FEATURES])[:, 1]
    reasons = explain_rows(artifact["reason_model"], f)
    return pd.DataFrame({
        "appointment_id": frame.appointment_id.values,
        "patient_id": frame.patient_id.values,
        "facility_id": frame.facility_id.values,
        "scheduled_date": pd.to_datetime(frame.scheduled_date).dt.date.values,
        "p_missed": np.round(p, 4),
        "band": band(p, artifact["thresholds"]),
        "basis": pooled.basis.values,
        "group_size": pooled.group_size.astype(int).values,
        "group_level": pooled.group_level.values,
        "reasons": reasons,
        "model_version": artifact["version"],
    })


def score_upcoming(engine: Engine, as_of: pd.Timestamp | None = None, artifact_path: Path | None = None,
                   appointment_ids: list[str] | None = None, facility_id: str | None = None,
                   horizon_days: int = 60) -> pd.DataFrame:
    """Score appointments that are still 'scheduled' and due within ``horizon_days`` (or the given ids)."""
    as_of = pd.Timestamp(as_of or pd.Timestamp.today()).normalize()
    artifact = load_artifact(artifact_path) if artifact_path else load_artifact()
    tables = load_tables_from_db(engine)
    ft = build_feature_table(tables, as_of)
    f = ft.frame
    sd = pd.to_datetime(f.scheduled_date)
    if appointment_ids:
        sel = f[f.appointment_id.astype(str).isin([str(a) for a in appointment_ids])]
    else:
        sel = f[(f.status == "scheduled") & (sd >= as_of - pd.Timedelta(days=1)) & (sd <= as_of + pd.Timedelta(days=horizon_days))]
        if facility_id:
            sel = sel[sel.facility_id.astype(str) == str(facility_id)]
    if sel.empty:
        return pd.DataFrame()
    return score_frame(sel.reset_index(drop=True), artifact)


def write_scores(scores: pd.DataFrame, engine: Engine) -> int:
    if scores.empty:
        return 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [
        {
            "id": str(uuid.uuid4()),
            "appointment_id": str(r.appointment_id),
            "patient_id": str(r.patient_id),
            "facility_id": str(r.facility_id),
            "scheduled_date": r.scheduled_date,
            "p_missed": float(r.p_missed),
            "band": r.band,
            "basis": r.basis,
            "group_size": int(r.group_size),
            "group_level": r.group_level,
            "reasons": __import__("json").dumps(list(r.reasons)),
            "model_version": r.model_version,
            "scored_at": now,
        }
        for r in scores.itertuples(index=False)
    ]
    sql = text("""
        INSERT INTO risk_scores (id, appointment_id, patient_id, facility_id, scheduled_date, p_missed, band, basis,
                                 group_size, group_level, reasons, model_version, scored_at)
        VALUES (:id, :appointment_id, :patient_id, :facility_id, :scheduled_date, :p_missed, :band, :basis,
                :group_size, :group_level, CAST(:reasons AS jsonb), :model_version, :scored_at)
    """)
    with engine.begin() as conn:
        conn.execute(sql, rows)
    return len(rows)
