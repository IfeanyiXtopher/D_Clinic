"""Generate (or reuse) the synthetic cohort and load it into PostgreSQL.

Usage:
    python -m scripts.seed                # generate with settings.synth_* and load
    python -m scripts.seed --no-generate  # load existing CSVs from settings.synth_out_dir

Idempotent: truncates the target tables first. Truth files (prefixed `_`) are
never loaded.
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

import pandas as pd
import psycopg

from app.models import Base
from app.settings import REPO_ROOT, settings

sys.path.insert(0, str(REPO_ROOT / "data" / "synth"))
from generate import Generator, write  # noqa: E402

# Parent tables first so foreign keys resolve.
LOAD_ORDER = [
    "facilities", "users", "patients", "patient_phone_numbers", "addresses", "medical_histories",
    "blood_pressures", "blood_sugars", "prescription_drugs", "appointments", "call_results", "communications",
]


def _conninfo() -> str:
    s = settings
    return f"host={s.pg_host} port={s.pg_port} dbname={s.pg_db} user={s.pg_user} password='{s.pg_password}'"


def copy_frame(cur: psycopg.Cursor, table: str, df: pd.DataFrame) -> None:
    cols = [c.name for c in Base.metadata.tables[table].columns if c.name in df.columns]
    buf = io.StringIO()
    df[cols].to_csv(buf, index=False, header=False, na_rep="")
    buf.seek(0)
    col_list = ", ".join(cols)
    with cur.copy(f"COPY {table} ({col_list}) FROM STDIN WITH (FORMAT csv, NULL '')") as cp:
        cp.write(buf.getvalue())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-generate", action="store_true", help="load CSVs already in the output dir")
    ap.add_argument("--patients", type=int, default=settings.synth_patients)
    ap.add_argument("--seed", type=int, default=settings.synth_seed)
    args = ap.parse_args()

    out: Path = settings.synth_out_dir
    t0 = time.time()
    if not args.no_generate:
        frames = Generator(args.patients, args.seed).run()
        write(frames, out)
        print(f"generated {args.patients} patients in {time.time() - t0:.1f}s -> {out}")
    frames = {t: pd.read_csv(out / f"{t}.csv") for t in LOAD_ORDER}

    with psycopg.connect(_conninfo()) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE " + ", ".join(reversed(LOAD_ORDER)) + " CASCADE")
        for table in LOAD_ORDER:
            copy_frame(cur, table, frames[table])
            print(f"  loaded {table:24s} {len(frames[table]):>8,d}")
        conn.commit()
        n_overdue = cur.execute("SELECT count(*) FROM overdue_patients").fetchone()[0]
        n_uc = cur.execute("SELECT count(*) FROM patients_under_care").fetchone()[0]
        n_ltfu = cur.execute("SELECT count(*) FROM lost_to_follow_up").fetchone()[0]
        ctrl = cur.execute("SELECT avg(controlled::int) FROM bp_controlled_latest").fetchone()[0]
    print(f"under care: {n_uc:,}  overdue: {n_overdue:,} ({n_overdue / max(n_uc, 1):.1%})  LTFU: {n_ltfu:,}  controlled: {float(ctrl):.1%}")
    print(f"done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
