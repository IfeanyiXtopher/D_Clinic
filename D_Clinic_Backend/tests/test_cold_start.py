from __future__ import annotations

import numpy as np
import pandas as pd

from ml.cold_start import ColdStartModel, add_pooled_feature


def _frame(n=600, seed=0):
    rng = np.random.default_rng(seed)
    f = pd.DataFrame({
        "facility_id": rng.choice(["A", "B"], n),
        "diabetic": rng.choice([0, 1], n),
        "n_protocol_drugs": rng.choice([1, 2, 3], n),
        "age_band": rng.choice(["40-49", "50-59", "60-69"], n),
        "prior_appointments": rng.integers(0, 10, n),
    })
    f["prior_miss_rate"] = np.where(f.prior_appointments > 0, rng.random(n), np.nan)
    # facility B misses more
    f["missed"] = (rng.random(n) < np.where(f.facility_id == "B", 0.45, 0.15)).astype(float)
    return f


def test_new_patients_get_group_estimate_and_basis_group():
    f = _frame()
    cs = ColdStartModel(k=3, min_group_size=30).fit(f)
    new = f[f.prior_appointments == 0]
    p = cs.pooled(new)
    assert (p.basis == "group").all()
    assert np.allclose(p.pooled_miss_rate, p.group_rate)
    assert (p.group_size >= 30).all() | (p.group_level == "program").all()


def test_personal_history_dominates_with_many_visits():
    f = _frame()
    cs = ColdStartModel(k=3).fit(f)
    row = f.iloc[[0]].copy()
    row["prior_appointments"] = 50
    row["prior_miss_rate"] = 0.9
    p = cs.pooled(row)
    assert p.basis.iloc[0] == "personal"
    assert abs(p.pooled_miss_rate.iloc[0] - 0.9) < 0.05


def test_partial_pooling_formula():
    f = _frame()
    cs = ColdStartModel(k=3).fit(f)
    row = f.iloc[[0]].copy()
    row["prior_appointments"] = 2
    row["prior_miss_rate"] = 1.0
    p = cs.pooled(row)
    expected = (2 * 1.0 + 3 * p.group_rate.iloc[0]) / 5
    assert abs(p.pooled_miss_rate.iloc[0] - expected) < 1e-9
    assert p.basis.iloc[0] == "mixed"


def test_backoff_to_facility_when_group_small():
    f = _frame(n=80)
    cs = ColdStartModel(k=3, min_group_size=30).fit(f)
    p = cs.pooled(f)
    assert set(p.group_level) <= {"facility_id", "facility_id × age_band", "program",
                                  "facility_id × diabetic × n_protocol_drugs × age_band"}
    assert (p.group_level != "facility_id × diabetic × n_protocol_drugs × age_band").all()


def test_group_estimate_reflects_facility_difference():
    f = _frame(n=2000)
    cs = ColdStartModel(k=3, min_group_size=30).fit(f)
    p = cs.pooled(f.assign(prior_appointments=0, prior_miss_rate=np.nan))
    assert p.group_rate[f.facility_id == "B"].mean() > p.group_rate[f.facility_id == "A"].mean() + 0.15


def test_add_pooled_feature_fills_missing_prior_rate():
    f = _frame()
    cs = ColdStartModel().fit(f)
    out = add_pooled_feature(f, cs)
    assert out.prior_miss_rate.notna().all()
    assert "pooled_miss_rate" in out.columns
    assert out.pooled_miss_rate.between(0, 1).all()


def test_no_protected_attributes_in_groups():
    from ml.cold_start import GROUP_LEVELS
    flat = {c for level in GROUP_LEVELS for c in level}
    assert not flat & {"region", "state", "ethnicity", "religion", "nationality", "gender"}
