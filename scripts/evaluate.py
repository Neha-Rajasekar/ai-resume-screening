"""Evaluate our ranking against the dataset's own `matched_score` labels.

For each of the 28 jobs:
  * Spearman correlation between our final score and matched_score
    (1.0 = same ordering, 0 = unrelated)
  * Overlap@30: how many of our top 30 are in the dataset's top 30
    (dataset top 30 = everyone scoring >= the 30th best label, since labels often tie)

Also compares the full scorer with a semantic-only baseline, so the report
can show what the skill and experience parts add.

Usage:
    python scripts/evaluate.py --csv resume_data.csv            # MiniLM (real run)
    EMBEDDER=tfidf python scripts/evaluate.py --csv resume_data.csv
"""

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.dataset import load_dataset  # noqa: E402
from app.matcher import Ranker, get_embedder  # noqa: E402

TOP_K = 30


def evaluate(ranker, jobs, pairs, weights):
    ranker.weights = weights
    labels = pd.DataFrame(pairs)
    rows = []
    for job in jobs:
        truth = labels[labels.job_id == job["id"]].set_index("candidate_id")["matched_score"]
        ours = pd.Series({r["candidate_id"]: r["final"] for r in ranker.score_all(job)})
        common = truth.index.intersection(ours.index)
        t, o = truth[common], ours[common]
        # Dataset top 30 = all candidates scoring >= the 30th best label (labels tie a lot), as in the app.
        cutoff = t.sort_values(ascending=False).iloc[min(TOP_K, len(t)) - 1]
        top_truth = set(t[t >= cutoff].index)
        top_ours = set(o.sort_values(ascending=False).index[:TOP_K])
        rows.append({
            "job": job["title"],
            "candidates": len(common),
            "spearman": round(t.corr(o, method="spearman"), 3),
            f"overlap@{TOP_K}": len(top_truth & top_ours),
            "dataset_top_size": len(top_truth),  # > 30 when labels tie at the cut-off
            # Overlap a random shortlist would get on average (for comparison)
            "random_overlap": round(TOP_K * len(top_truth) / len(common), 1),
            "has_skills_list": bool(job["skills"]),
        })
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="resume_data.csv")
    parser.add_argument("--out", default="data/evaluation.csv")
    args = parser.parse_args()

    candidates, jobs, pairs = load_dataset(args.csv)
    ranker = Ranker(candidates, embedder=get_embedder(), cache_dir="data/cache")
    print(f"{len(candidates)} candidates, {len(jobs)} jobs, {len(pairs)} labelled pairs, "
          f"embedder={ranker.embedder.name}\n")

    configs = {
        "semantic only": {"semantic": 1.0, "skills": 0.0, "experience": 0.0},
        "full scorer": dict(ranker.weights),
    }
    summary = []
    for name, weights in configs.items():
        df = evaluate(ranker, jobs, pairs, weights)
        summary.append({"config": name, "weights": weights,
                        "mean_spearman": round(df.spearman.mean(), 3),
                        f"mean_overlap@{TOP_K}": round(df[f"overlap@{TOP_K}"].mean(), 1),
                        "random_shortlist_overlap": round(df.random_overlap.mean(), 1)})
        if name == "full scorer":
            os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
            df.to_csv(args.out, index=False)
            print(df.to_string(index=False), "\n")

    print(pd.DataFrame(summary).to_string(index=False))
    print(f"\nPer-job results saved to {args.out}")


if __name__ == "__main__":
    main()
