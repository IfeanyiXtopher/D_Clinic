"""Cold-start estimates for patients with little or no attendance history.

Method: **partial pooling** (a shrinkage estimator). For a patient with ``n``
resolved prior appointments and personal miss rate ``p_personal``, the pooled
estimate is

    p = (n * p_personal + k * p_group) / (n + k)

where ``p_group`` is the observed miss rate of *clinically and operationally*
similar patients and ``k`` (default 3) is the number of pseudo-observations the
group prior is worth. New patients get ``p_group`` exactly; after ~5 visits the
personal record dominates.

Groups are defined by facility × diabetes status × number of protocol drugs ×
age band. If a group has fewer than ``min_group_size`` resolved appointments we
back off to facility × age band, then facility, then the program-wide rate.

Ethnicity, region, religion and nationality are never used to form groups.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

GROUP_LEVELS: list[list[str]] = [
    ["facility_id", "diabetic", "n_protocol_drugs", "age_band"],
    ["facility_id", "age_band"],
    ["facility_id"],
    [],
]


@dataclass
class ColdStartModel:
    k: float = 3.0
    min_group_size: int = 30
    tables: list[pd.DataFrame] = field(default_factory=list)
    global_rate: float = 0.25

    # ------------------------------------------------------------------ fit
    def fit(self, frame: pd.DataFrame) -> "ColdStartModel":
        """``frame`` must contain the group columns and a resolved ``missed`` label."""
        f = frame[frame["missed"].notna()].copy()
        f["missed"] = f["missed"].astype(float)
        self.global_rate = float(f["missed"].mean())
        self.tables = []
        for cols in GROUP_LEVELS:
            if not cols:
                continue
            t = f.groupby(cols, observed=True)["missed"].agg(group_rate="mean", group_size="size").reset_index()
            self.tables.append(t)
        return self

    # -------------------------------------------------------------- predict
    def group_estimate(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return ``group_rate``, ``group_size``, ``group_level`` per row, backing off as needed."""
        out = pd.DataFrame(index=frame.index)
        out["group_rate"] = np.nan
        out["group_size"] = 0
        out["group_level"] = ""
        for level, (cols, table) in enumerate(zip([c for c in GROUP_LEVELS if c], self.tables)):
            merged = frame[cols].merge(table, on=cols, how="left")
            merged.index = frame.index
            ok = out.group_rate.isna() & (merged.group_size.fillna(0) >= self.min_group_size)
            out.loc[ok, "group_rate"] = merged.loc[ok, "group_rate"]
            out.loc[ok, "group_size"] = merged.loc[ok, "group_size"].astype(int)
            out.loc[ok, "group_level"] = " × ".join(cols)
        rest = out.group_rate.isna()
        out.loc[rest, "group_rate"] = self.global_rate
        out.loc[rest, "group_level"] = "program"
        return out

    def pooled(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Partial-pooling estimate plus ``basis`` (group / mixed / personal)."""
        g = self.group_estimate(frame)
        n = frame["prior_appointments"].fillna(0).astype(float)
        p_personal = frame["prior_miss_rate"].fillna(0.0)
        pooled = (n * p_personal + self.k * g.group_rate) / (n + self.k)
        basis = np.select([n == 0, n < 5], ["group", "mixed"], default="personal")
        return pd.DataFrame(
            {"pooled_miss_rate": pooled, "group_rate": g.group_rate, "group_size": g.group_size,
             "group_level": g.group_level, "basis": basis},
            index=frame.index,
        )


def add_pooled_feature(frame: pd.DataFrame, model: ColdStartModel) -> pd.DataFrame:
    """Append ``pooled_miss_rate`` and fill NaN ``prior_miss_rate`` with the group rate."""
    p = model.pooled(frame)
    out = frame.copy()
    out["pooled_miss_rate"] = p.pooled_miss_rate.values
    out["prior_miss_rate"] = out["prior_miss_rate"].fillna(p.group_rate)
    return out
