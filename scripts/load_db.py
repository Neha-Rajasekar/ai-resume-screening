"""Load the Kaggle resume dataset into the database (RDS MySQL or local SQLite).

Typical cloud flow (run on the EC2 instance, which can reach the private RDS):
    1. Upload the dataset to S3 once:
         aws s3 cp resume_data.csv s3://<bucket>/dataset/resume_data.csv
    2. Load it from S3 into RDS:
         docker exec resume-app python scripts/load_db.py --csv s3://<bucket>/dataset/resume_data.csv

Local:
    python scripts/load_db.py --csv resume_data.csv          # -> sqlite:///data/app.db
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import db  # noqa: E402
from app.dataset import load_dataset  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", default=os.getenv("DATASET_CSV", "resume_data.csv"),
                        help="local path or s3://bucket/key of resume_data.csv")
    parser.add_argument("--database-url", default=None, help="overrides DATABASE_URL")
    args = parser.parse_args()

    start = time.time()
    candidates, jobs, labels = load_dataset(args.csv)
    print(f"Extracted {len(candidates)} unique candidates, {len(jobs)} jobs, {len(labels)} labelled pairs")

    engine = db.get_engine(args.database_url)
    db.init_db(engine)
    db.load_records(engine, candidates, jobs, labels)
    print(f"Loaded into {engine.url.render_as_string(hide_password=True)} in {time.time() - start:.1f}s")
    print("Row counts:", db.counts(engine))


if __name__ == "__main__":
    main()
