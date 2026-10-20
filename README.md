# Cloud-Based AI Resume Screening and Candidate Ranking System

CCD 3130 (Cloud Computing & DevOps) project · Neha Rajasekar (240905029), Pavani Raju (240905126)
School of Computer Engineering, MIT Manipal · 2026–27

A recruiter picks a job (or types a new job description). The system reads every resume
with an NLP model, scores how well each one fits the job **by meaning, not just keywords**,
and shortlists the **top 30**. It runs on AWS (EC2, RDS MySQL, S3, SNS) and is deployed
automatically by a GitHub Actions → Docker pipeline.

---

## Synopsis modules → where they are in the code

| # | Synopsis module | Implementation |
|---|---|---|
| 1 | Resume upload and storage | Dataset uploaded to **S3** (`s3://<bucket>/dataset/`), loaded into **RDS MySQL** by `scripts/load_db.py`; every ranked shortlist is stored in S3 as CSV (`app/aws.py`) |
| 2 | Resume information extraction | `app/extract.py`: skills, degrees, majors, institutions, companies, roles, certifications, languages, and **years of experience computed from employment dates** |
| 3 | AI/NLP resume matching | `app/matcher.py`: Hugging Face **MiniLM** sentence embeddings + **cosine similarity** between resume and job description |
| 4 | Candidate scoring and ranking | `app/matcher.py`: final score = semantic + skill match + experience fit; sorted, top 30 saved to RDS |
| 5 | Recruiter dashboard | `app/web.py` + `app/templates/`: Flask, HTML/CSS/JS; ranked list with score breakdown and the **exact matched skills** |
| 6 | Cloud and DevOps | `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci-cd.yml`, `docs/AWS_SETUP.md` (AWS CLI) |

## How a candidate is scored

Every part is between 0 and 1 (shown as %):

- **Semantic (55%)**: MiniLM turns the resume text and the job description into 384-number vectors;
  cosine similarity measures how close their meanings are.
- **Skills (30%)**: share of the job's required skills the candidate has. A skill counts if it is listed
  exactly **or** a listed skill is semantically close (MiniLM similarity ≥ 0.70), e.g. *Payroll* ↔ *Payroll processing*.
  The dashboard shows each pair that matched.
- **Experience (15%)**: years of experience vs the requirement (100% inside the range, partial below it).

If a job specifies no skills or no experience, those parts are skipped and the weights are re-balanced.
Weights can be changed with the `W_SEMANTIC`, `W_SKILLS`, `W_EXPERIENCE` environment variables.

## Dataset

[Kaggle: Resume Dataset (saugataroyarghya)](https://www.kaggle.com/datasets/saugataroyarghya/resume-dataset), `resume_data.csv`, 9,544 rows × 35 columns.

- Each row is **one resume paired with one job**, with a `matched_score` label (0–0.97).
  The rows reduce to **344 unique resumes × 28 unique jobs**. So the app ranks 344 candidates per job,
  and the labels act as **ground truth** to evaluate the ranking.
- Data quirk: the resume column `responsibilities` is identical to the job column `responsibilities.1` in
  every row (it holds the job's text). It is excluded from the resume, otherwise the job text would leak in.
- The dataset is not committed to git (`.gitignore`); download it from Kaggle.

## Run it on your laptop (Windows)

**Option A: Python directly (SQLite database)**

```bat
cd C:\Users\NEHA\ai_resume_working
python -m venv .venv
.venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt -r requirements-ml.txt
python scripts\load_db.py --csv resume_data.csv
python wsgi.py
```

Open <http://localhost:5000>. The first run downloads MiniLM (~90 MB) once.

**Option B: Docker Compose (MySQL, same as RDS)**: needs Docker Desktop

```bat
docker compose up -d --build
docker compose exec app python scripts/load_db.py --csv /dataset/resume_data.csv
```

Open <http://localhost:5000>.

## Evaluate the ranking

```bat
python scripts\evaluate.py --csv resume_data.csv
```

For each of the 28 jobs it reports the **Spearman correlation** between our score and the dataset's
`matched_score`, and **overlap@30** (how many of the dataset's top 30 we also shortlist), for the full
scorer and a semantic-only baseline. Results go to `data/evaluation.csv`.

## Tests

```bat
pip install -r requirements-dev.txt
set EMBEDDER=tfidf
pytest -v
```

20 tests cover extraction, scoring and the web app. CI uses a lightweight TF-IDF stand-in for MiniLM
(`EMBEDDER=tfidf`) so tests run in seconds without downloading PyTorch.

## Deploy to AWS

Follow [`docs/AWS_SETUP.md`](docs/AWS_SETUP.md): S3 → SNS → security groups → RDS → IAM role → EC2 →
GitHub secrets → push. After that, every `git push` to `main` tests, builds and redeploys automatically.

## Project structure

```
app/
  extract.py      resume + job information extraction
  dataset.py      CSV → candidates, jobs, labelled pairs
  matcher.py      MiniLM embeddings, skill matching, scoring, ranking
  db.py           RDS MySQL / SQLite tables and queries
  aws.py          S3 storage and SNS notifications (IAM role, no keys in code)
  web.py          Flask routes: dashboard, ranking, results, CSV, JSON API, /health
  templates/      HTML pages
  static/         CSS + JS
scripts/
  load_db.py      load the dataset (local file or s3://) into the database
  evaluate.py     compare our ranking with the dataset's matched_score
sql/schema.sql    MySQL DDL for RDS (the app also creates the tables itself)
tests/            pytest suite + a 60-row sample of the dataset
Dockerfile        production image (CPU PyTorch, MiniLM baked in, gunicorn, non-root, healthcheck)
docker-compose.yml  local app + MySQL
.github/workflows/ci-cd.yml   lint → test → build & push image → deploy to EC2
docs/AWS_SETUP.md AWS CLI setup, cost control and teardown
```

## API

- `GET /health`: database status and counts (used by Docker and the deploy pipeline)
- `GET /api/jobs`: list jobs
- `POST /api/rank` with `{"job_id": "j_..."}` or `{"title": "...", "description": "...", "skills": ["..."], "min_years": 2}`:
  runs a ranking and returns the top 30 as JSON
