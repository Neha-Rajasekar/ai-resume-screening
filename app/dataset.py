"""Load the Kaggle resume dataset CSV into candidates, jobs and labelled pairs.

The CSV has 9,544 rows, but each row is ONE resume paired with ONE job:
roughly 344 unique resumes x 28 unique jobs. This module splits it back
into those two tables plus the (candidate, job, matched_score) pairs,
which serve as ground truth for evaluating our ranking.
"""

import io
from datetime import date

import pandas as pd

from .extract import build_candidate, build_job


def read_csv(source) -> pd.DataFrame:
    """Read the dataset from a local path, an s3://bucket/key URL, or a file object."""
    if isinstance(source, str) and source.startswith("s3://"):
        from .aws import read_s3_bytes
        source = io.BytesIO(read_s3_bytes(source))
    df = pd.read_csv(source, encoding="utf-8-sig")
    # One header has a byte-order mark and some have stray spaces.
    df.columns = [str(c).replace("﻿", "").strip() for c in df.columns]
    return df


def split_dataset(df: pd.DataFrame, today: date = None):
    """Return (candidates, jobs, pairs) built from the raw dataframe."""
    candidates, jobs, pairs = {}, {}, {}
    for row in df.to_dict(orient="records"):
        cand = build_candidate(row, today)
        job = build_job(row)
        candidates.setdefault(cand["id"], cand)
        jobs.setdefault(job["id"], job)
        score = row.get("matched_score")
        if score is not None and score == score:  # skip NaN
            pairs[(cand["id"], job["id"])] = float(score)

    # Number candidates in first-seen order so the dashboard can show "Candidate 0042".
    for n, cand in enumerate(candidates.values(), start=1):
        cand["label"] = f"Candidate {n:04d}"

    pair_rows = [{"candidate_id": c, "job_id": j, "matched_score": s} for (c, j), s in pairs.items()]
    return list(candidates.values()), list(jobs.values()), pair_rows


def load_dataset(source, today: date = None):
    return split_dataset(read_csv(source), today)
