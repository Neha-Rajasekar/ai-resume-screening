"""Database layer: Amazon RDS MySQL in the cloud, SQLite on a laptop.

Set DATABASE_URL to choose:
    mysql+pymysql://admin:PASSWORD@<rds-endpoint>:3306/resumedb   (AWS RDS)
    sqlite:///data/app.db                                          (local default)

Tables (see sql/schema.sql for the MySQL DDL):
    candidates       one row per unique resume (extracted fields)
    jobs             the 28 dataset job descriptions + any custom JDs typed by recruiters
    labels           dataset matched_score for each (candidate, job) pair = ground truth
    ranking_runs     one row each time a recruiter ranks candidates for a job
    ranking_results  the top-30 rows of each run with the score breakdown
"""

import os
from datetime import datetime, timezone

import sqlalchemy as sa

metadata = sa.MetaData()

candidates = sa.Table(
    "candidates", metadata,
    sa.Column("id", sa.String(16), primary_key=True),
    sa.Column("label", sa.String(32), nullable=False),
    sa.Column("objective", sa.Text),
    sa.Column("skills", sa.JSON),
    sa.Column("degrees", sa.JSON),
    sa.Column("majors", sa.JSON),
    sa.Column("institutions", sa.JSON),
    sa.Column("positions", sa.JSON),
    sa.Column("companies", sa.JSON),
    sa.Column("languages", sa.JSON),
    sa.Column("certifications", sa.JSON),
    sa.Column("years_experience", sa.Float, nullable=False, default=0.0),
    sa.Column("text", sa.Text, nullable=False),
)

jobs = sa.Table(
    "jobs", metadata,
    sa.Column("id", sa.String(16), primary_key=True),
    sa.Column("title", sa.String(255), nullable=False),
    sa.Column("description", sa.Text),
    sa.Column("education", sa.Text),
    sa.Column("experience", sa.String(100)),
    sa.Column("min_years", sa.Float),
    sa.Column("max_years", sa.Float),
    sa.Column("age", sa.String(100)),
    sa.Column("skills", sa.JSON),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("is_custom", sa.Boolean, nullable=False, default=False),
    sa.Column("created_at", sa.DateTime),
)

labels = sa.Table(
    "labels", metadata,
    sa.Column("candidate_id", sa.String(16), sa.ForeignKey("candidates.id"), primary_key=True),
    sa.Column("job_id", sa.String(16), sa.ForeignKey("jobs.id"), primary_key=True),
    sa.Column("matched_score", sa.Float, nullable=False),
)

ranking_runs = sa.Table(
    "ranking_runs", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("job_id", sa.String(16), sa.ForeignKey("jobs.id"), nullable=False),
    sa.Column("job_title", sa.String(255), nullable=False),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.Column("total_candidates", sa.Integer, nullable=False),
    sa.Column("top_k", sa.Integer, nullable=False),
    sa.Column("embedder", sa.String(32), nullable=False),
    sa.Column("s3_key", sa.String(255)),
    sa.Column("notified", sa.Boolean, nullable=False, default=False),
)

ranking_results = sa.Table(
    "ranking_results", metadata,
    sa.Column("run_id", sa.Integer, sa.ForeignKey("ranking_runs.id"), primary_key=True),
    sa.Column("rank", sa.Integer, primary_key=True),
    sa.Column("candidate_id", sa.String(16), sa.ForeignKey("candidates.id"), nullable=False),
    sa.Column("final", sa.Float, nullable=False),
    sa.Column("semantic", sa.Float, nullable=False),
    sa.Column("skills", sa.Float),
    sa.Column("experience", sa.Float),
    sa.Column("matched_skills", sa.JSON),
    sa.Column("missing_skills", sa.JSON),
)

CANDIDATE_FIELDS = [c.name for c in candidates.columns]
JOB_FIELDS = [c.name for c in jobs.columns]


def database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///data/app.db")


def get_engine(url: str = None):
    url = url or database_url()
    if url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:"):
        os.makedirs(os.path.dirname(url[len("sqlite:///"):]) or ".", exist_ok=True)
    # pool_pre_ping reconnects if RDS dropped an idle connection.
    return sa.create_engine(url, pool_pre_ping=True, pool_recycle=1800, future=True)


def init_db(engine):
    metadata.create_all(engine)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def load_records(engine, cand_rows, job_rows, label_rows):
    """Replace dataset candidates/jobs/labels. Ranking history and custom jobs are kept."""
    with engine.begin() as conn:
        conn.execute(labels.delete())
        conn.execute(jobs.delete().where(jobs.c.is_custom.is_(False))
                     .where(~jobs.c.id.in_(sa.select(ranking_runs.c.job_id))))
        existing_jobs = set(conn.execute(sa.select(jobs.c.id)).scalars())
        used_cands = set(conn.execute(sa.select(ranking_results.c.candidate_id)).scalars())
        conn.execute(candidates.delete().where(~candidates.c.id.in_(used_cands)) if used_cands
                     else candidates.delete())
        existing_cands = set(conn.execute(sa.select(candidates.c.id)).scalars())

        new_c = [{k: c.get(k) for k in CANDIDATE_FIELDS} for c in cand_rows if c["id"] not in existing_cands]
        new_j = [dict({k: j.get(k) for k in JOB_FIELDS}, is_custom=False, description=None, created_at=_now())
                 for j in job_rows if j["id"] not in existing_jobs]
        for chunk_start in range(0, len(new_c), 200):
            conn.execute(candidates.insert(), new_c[chunk_start:chunk_start + 200])
        if new_j:
            conn.execute(jobs.insert(), new_j)
        for chunk_start in range(0, len(label_rows), 1000):
            conn.execute(labels.insert(), label_rows[chunk_start:chunk_start + 1000])


def fetch_candidates(engine):
    with engine.connect() as conn:
        rows = conn.execute(sa.select(candidates).order_by(candidates.c.label)).mappings().all()
    return [dict(r) for r in rows]


def fetch_candidate(engine, cand_id):
    with engine.connect() as conn:
        row = conn.execute(sa.select(candidates).where(candidates.c.id == cand_id)).mappings().first()
    return dict(row) if row else None


def fetch_jobs(engine, include_custom=True):
    q = sa.select(jobs).order_by(jobs.c.is_custom, jobs.c.title)
    if not include_custom:
        q = q.where(jobs.c.is_custom.is_(False))
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(q).mappings().all()]


def fetch_job(engine, job_id):
    with engine.connect() as conn:
        row = conn.execute(sa.select(jobs).where(jobs.c.id == job_id)).mappings().first()
    return dict(row) if row else None


def insert_job(engine, job: dict):
    row = {k: job.get(k) for k in JOB_FIELDS}
    row["is_custom"] = True
    row["created_at"] = _now()
    with engine.begin() as conn:
        conn.execute(jobs.insert(), [row])
    return row


def label_scores(engine, job_id) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(sa.select(labels.c.candidate_id, labels.c.matched_score)
                            .where(labels.c.job_id == job_id)).all()
    return {cid: score for cid, score in rows}


def save_run(engine, job, results, total, embedder, s3_key=None, notified=False):
    with engine.begin() as conn:
        run_id = conn.execute(ranking_runs.insert().values(
            job_id=job["id"], job_title=job["title"], created_at=_now(), total_candidates=total,
            top_k=len(results), embedder=embedder, s3_key=s3_key, notified=notified,
        )).inserted_primary_key[0]
        if results:
            conn.execute(ranking_results.insert(), [{
                "run_id": run_id, "rank": r["rank"], "candidate_id": r["candidate_id"],
                "final": r["final"], "semantic": r["semantic"], "skills": r["skills"],
                "experience": r["experience"], "matched_skills": r["matched_skills"],
                "missing_skills": r["missing_skills"],
            } for r in results])
    return run_id


def update_run(engine, run_id, **values):
    with engine.begin() as conn:
        conn.execute(ranking_runs.update().where(ranking_runs.c.id == run_id).values(**values))


def fetch_run(engine, run_id):
    with engine.connect() as conn:
        run = conn.execute(sa.select(ranking_runs).where(ranking_runs.c.id == run_id)).mappings().first()
        if not run:
            return None, []
        rows = conn.execute(
            sa.select(ranking_results, candidates.c.label, candidates.c.positions,
                      candidates.c.years_experience, candidates.c.degrees)
            .join(candidates, candidates.c.id == ranking_results.c.candidate_id)
            .where(ranking_results.c.run_id == run_id)
            .order_by(ranking_results.c.rank)).mappings().all()
    return dict(run), [dict(r) for r in rows]


def fetch_runs(engine, limit=10):
    with engine.connect() as conn:
        rows = conn.execute(sa.select(ranking_runs).order_by(ranking_runs.c.id.desc()).limit(limit)).mappings().all()
    return [dict(r) for r in rows]


def counts(engine) -> dict:
    with engine.connect() as conn:
        return {
            "candidates": conn.execute(sa.select(sa.func.count()).select_from(candidates)).scalar(),
            "jobs": conn.execute(sa.select(sa.func.count()).select_from(jobs)
                                 .where(jobs.c.is_custom.is_(False))).scalar(),
            "runs": conn.execute(sa.select(sa.func.count()).select_from(ranking_runs)).scalar(),
        }
