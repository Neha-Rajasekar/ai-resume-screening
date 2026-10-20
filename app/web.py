"""Flask web app: recruiter dashboard (synopsis module 5).

Flow for one ranking:
    recruiter picks a job (or types a new JD)
      -> Ranker scores every candidate in the database
      -> top 30 saved to RDS (ranking_runs + ranking_results)
      -> CSV of the top 30 stored in S3
      -> SNS notification sent to subscribed recruiters
      -> dashboard shows the ranked list with score breakdown and matched skills
"""

import csv
import hashlib
import io
import logging
import os
import threading
import time

from flask import (Flask, Response, abort, flash, jsonify, redirect, render_template,
                   request, url_for)

from . import aws, db
from .extract import job_text, parse_skill_text
from .matcher import Ranker, get_embedder

log = logging.getLogger(__name__)

TOP_K = int(os.getenv("TOP_K", 30))


class RankerHolder:
    """Builds the Ranker once (loading MiniLM + embedding all resumes) and reuses it."""

    def __init__(self, engine, cache_dir):
        self.engine, self.cache_dir = engine, cache_dir
        self._ranker, self._lock = None, threading.Lock()
        self.candidates_by_id = {}

    def get(self):
        with self._lock:
            if self._ranker is None:
                cands = db.fetch_candidates(self.engine)
                if not cands:
                    return None
                started = time.time()
                self._ranker = Ranker(cands, embedder=get_embedder(), cache_dir=self.cache_dir)
                self.candidates_by_id = {c["id"]: c for c in cands}
                log.info("Ranker built in %.1fs", time.time() - started)
            return self._ranker

    def reset(self):
        with self._lock:
            self._ranker = None


def results_csv(job_title, rows) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["rank", "candidate", "candidate_id", "final_score_%", "semantic_%", "skill_match_%",
                     "experience_fit_%", "years_experience", "recent_roles", "matched_skills", "missing_skills"])
    for r in rows:
        writer.writerow([
            r["rank"], r.get("label", ""), r["candidate_id"], pct(r["final"]), pct(r["semantic"]),
            pct(r["skills"]), pct(r["experience"]), r.get("years_experience", ""),
            "; ".join((r.get("positions") or [])[:3]),
            "; ".join(f'{m["required"]} = {m["candidate_skill"]}' for m in r.get("matched_skills") or []),
            "; ".join(r.get("missing_skills") or []),
        ])
    return ("# Top candidates for: " + job_title + "\n" + buf.getvalue()).encode("utf-8")


def pct(value):
    return "" if value is None else round(float(value) * 100, 1)


def _float_or_none(text):
    if text is None or str(text).strip() == "":
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        raise ValueError(f"'{text}' is not a valid number of years.")


def create_app(config: dict = None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "dev-only-change-me"),
        DATABASE_URL=db.database_url(),
        CACHE_DIR=os.getenv("CACHE_DIR", "data/cache"),
        PUBLIC_URL=os.getenv("PUBLIC_URL", ""),
    )
    app.config.update(config or {})

    engine = db.get_engine(app.config["DATABASE_URL"])
    db.init_db(engine)
    holder = RankerHolder(engine, app.config["CACHE_DIR"])
    app.extensions["engine"] = engine
    app.extensions["ranker"] = holder

    app.jinja_env.filters["pct"] = lambda v: "–" if v is None else f"{float(v) * 100:.0f}%"
    app.jinja_env.globals["s3_enabled"] = aws.s3_enabled
    app.jinja_env.globals["sns_enabled"] = aws.sns_enabled

    # ------------------------------------------------------------ ranking core

    def run_ranking(job):
        ranker = holder.get()
        if ranker is None:
            raise RuntimeError("No candidates in the database. Run scripts/load_db.py first.")
        results = ranker.rank(job, top_k=TOP_K)
        run_id = db.save_run(engine, job, results, total=len(ranker.candidates), embedder=ranker.embedder.name)

        run, rows = db.fetch_run(engine, run_id)
        key = aws.upload_bytes(f"rankings/run-{run_id:05d}-{job['id']}.csv", results_csv(job["title"], rows))
        top5 = "\n".join(f'  {r["rank"]}. {r["label"]} — {pct(r["final"])}%' for r in rows[:5])
        link = f'{app.config["PUBLIC_URL"].rstrip("/")}/runs/{run_id}' if app.config["PUBLIC_URL"] else f"run #{run_id}"
        sent = aws.notify(
            f"Top {len(rows)} candidates ready: {job['title']}",
            f"Ranking finished for '{job['title']}'.\n"
            f"{len(ranker.candidates)} resumes screened, top {len(rows)} shortlisted.\n\nTop 5:\n{top5}\n\n"
            f"View the full list: {link}\n",
        )
        db.update_run(engine, run_id, s3_key=key, notified=sent)
        return run_id

    def custom_job_from(data):
        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip()
        skills = data.get("skills") or []
        if isinstance(skills, str):
            skills = parse_skill_text(skills)
        if not title or not (description or skills):
            raise ValueError("Give the job a title and either a description or a list of skills.")
        min_y, max_y = _float_or_none(data.get("min_years")), _float_or_none(data.get("max_years"))
        if min_y is not None and max_y is not None and max_y < min_y:
            raise ValueError("Maximum years cannot be less than minimum years.")
        exp = "" if min_y is None and max_y is None else (
            f"{min_y:g} to {max_y:g} years" if min_y is not None and max_y is not None
            else f"At least {min_y:g} years" if min_y is not None else f"Up to {max_y:g} years")
        education = (data.get("education") or "").strip()
        job = {
            "id": "u_" + hashlib.sha1(f"{title}|{description}|{skills}|{time.time()}".encode()).hexdigest()[:10],
            "title": title[:255], "description": description, "education": education, "experience": exp,
            "min_years": min_y, "max_years": max_y, "age": "", "skills": skills,
            "text": job_text(title, skills, education, exp, description),
        }
        return db.insert_job(engine, job)

    # ------------------------------------------------------------ pages

    @app.get("/")
    def index():
        return render_template("index.html", counts=db.counts(engine), jobs=db.fetch_jobs(engine, include_custom=False),
                               runs=db.fetch_runs(engine, limit=8), top_k=TOP_K)

    @app.post("/rank")
    def rank():
        try:
            if request.form.get("mode") == "custom":
                job = custom_job_from(request.form)
            else:
                job = db.fetch_job(engine, request.form.get("job_id", ""))
                if not job:
                    raise ValueError("Pick a job from the list.")
            run_id = run_ranking(job)
        except (ValueError, RuntimeError) as exc:
            flash(str(exc), "error")
            return redirect(url_for("index"))
        return redirect(url_for("run_page", run_id=run_id))

    @app.get("/runs/<int:run_id>")
    def run_page(run_id):
        run, rows = db.fetch_run(engine, run_id)
        if not run:
            abort(404)
        job = db.fetch_job(engine, run["job_id"])
        truth = db.label_scores(engine, run["job_id"])
        # Dataset top-k = every candidate scoring at least the k-th best label. Many labels tie,
        # so a cut-off is fairer than picking an arbitrary 30 out of the tied ones.
        cutoff = sorted(truth.values(), reverse=True)[min(run["top_k"], len(truth)) - 1] if truth else None
        for r in rows:
            r["dataset_score"] = truth.get(r["candidate_id"])
            r["in_dataset_top"] = r["dataset_score"] is not None and r["dataset_score"] >= cutoff
        overlap = sum(r["in_dataset_top"] for r in rows) if truth else None
        top_size = sum(1 for v in truth.values() if v >= cutoff) if truth else 0
        random_overlap = round(len(rows) * top_size / len(truth), 1) if truth else None
        return render_template("run.html", run=run, job=job, rows=rows, overlap=overlap, cutoff=cutoff,
                               top_size=top_size, random_overlap=random_overlap)

    @app.get("/runs/<int:run_id>.csv")
    def run_csv(run_id):
        run, rows = db.fetch_run(engine, run_id)
        if not run:
            abort(404)
        data = aws.download_bytes(run["s3_key"]) if run["s3_key"] else None
        if data is None:
            data = results_csv(run["job_title"], rows)
        return Response(data, mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=top{run['top_k']}-run{run_id}.csv"})

    @app.get("/candidates/<cand_id>")
    def candidate_page(cand_id):
        cand = db.fetch_candidate(engine, cand_id)
        if not cand:
            abort(404)
        row, run = None, None
        run_id = request.args.get("run", type=int)
        if run_id:
            run, rows = db.fetch_run(engine, run_id)
            row = next((r for r in rows if r["candidate_id"] == cand_id), None)
        return render_template("candidate.html", cand=cand, row=row, run=run)

    # ------------------------------------------------------------ API + health

    @app.post("/api/rank")
    def api_rank():
        data = request.get_json(silent=True) or {}
        try:
            job = db.fetch_job(engine, data["job_id"]) if data.get("job_id") else custom_job_from(data)
            if not job:
                return jsonify(error="unknown job_id"), 404
            run_id = run_ranking(job)
        except (ValueError, RuntimeError) as exc:
            return jsonify(error=str(exc)), 400
        run, rows = db.fetch_run(engine, run_id)
        fields = ("rank", "candidate_id", "label", "final", "semantic", "skills",
                  "experience", "matched_skills", "missing_skills")
        return jsonify(run_id=run_id, job=run["job_title"], s3_key=run["s3_key"], notified=run["notified"],
                       results=[{k: r[k] for k in fields} for r in rows])

    @app.get("/api/jobs")
    def api_jobs():
        return jsonify([{k: j[k] for k in ("id", "title", "experience", "skills", "is_custom")}
                        for j in db.fetch_jobs(engine)])

    @app.get("/health")
    def health():
        try:
            c = db.counts(engine)
            return jsonify(status="ok", database="up", candidates=c["candidates"], jobs=c["jobs"],
                           s3=aws.s3_enabled(), sns=aws.sns_enabled())
        except Exception as exc:  # the container health check uses this
            return jsonify(status="error", database="down", detail=str(exc)[:200]), 503

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", message="That page doesn't exist."), 404

    return app
