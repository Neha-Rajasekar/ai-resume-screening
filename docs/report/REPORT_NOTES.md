# Report notes: CCD Lab mini-project (running log)

Template: CCD_Lab-Mini_Project-Report_Template.doc (4 chapters + references, IEEE refs, numbered
equations, captions on every figure/table, no code in Methodology, Ch. 4 has no subsections).

## Cover / certificate
- Title: Cloud-Based AI Resume Screening and Candidate Ranking System
- Neha Rajasekar (240905029), Pavani Raju (240905126); students 3 and 4 rows removed
- Date DD/MM/2026: fill on submission

## Chapter 1: Introduction
- Domain: high-volume placement/internship drives; manual screening is slow and inconsistent; keyword ATS misses synonyms
- Why cloud: worldwide access, scalability, managed services, pay-as-you-go (NIST: on-demand, elasticity, measured service)
- Services: EC2 (IaaS compute), RDS MySQL (managed DB), S3 (object storage), SNS (pub/sub notifications), IAM role (no keys in code), security groups
- 1.1 Objectives: preprocess dataset; build MiniLM + skill + experience ranker (top 30); evaluate vs labels and a baseline;
  Flask dashboard; deploy on AWS; automate with Docker + GitHub Actions
- Table 1.1: AWS service → role in project → cloud feature

## Chapter 2: Methodology (figures ready in this folder)
- Fig 2.1 fig2_1_architecture.png · Fig 2.2 fig2_2_workflow.png · Fig 2.3 fig2_3_cicd.png
- 2.1 Dataset: 9,544 rows × 35 cols = 344 unique resumes × 28 jobs; matched_score 0–0.97 (mean 0.661, 345 distinct values)
  - Quirk: resume `responsibilities` == job `responsibilities.1` in 100% of rows → excluded (data leak)
- 2.2 Extraction: list-string parsing; skills (mean 26.8, median 18 per resume; ~3,900 distinct); degrees, majors,
  institutions, companies, roles, certifications, languages; years of experience from start/end dates with overlapping jobs
  merged (median 7.5 yrs, 17 resumes with 0); only 171/344 have a career objective; 23/28 jobs list skills, 24/28 give experience
- 2.3 Semantic: all-MiniLM-L6-v2 (6 layers, 384-dim, max 256 word pieces); eq. cosine similarity; S_sem = max(0, cos)
- 2.4 Skills: required skill matched if exact or MiniLM sim ≥ τ = 0.70; "X or Y" accepts either; S_skill = mean credit
- 2.5 Experience: 1 inside range, y/a below, max(0.5, 1-(y-b)/10) above
- 2.6 Final = weighted mean of available parts, weights 0.55 / 0.30 / 0.15, re-normalised if a part is missing; ties broken by semantic
- 2.7 Evaluation: Spearman (average ranks for ties); overlap@30 where dataset top 30 = everyone ≥ 30th label (ties);
  random baseline E = 30·|T_data|/N; baseline = semantic-only
- 2.8 Dashboard: Flask + HTML/CSS/JS; pages: job select / custom JD, ranked list, candidate detail, CSV download, JSON API, /health
- 2.9 Storage: RDS tables candidates, jobs, labels, ranking_runs, ranking_results; S3 dataset/ + rankings/ (SSE, public access blocked)
- 2.10 SNS email "top 30 ready" with top 5 + link
- 2.11 Docker: python:3.11-slim, CPU torch, model baked in (offline), non-root user, HEALTHCHECK, gunicorn 1 worker × 4 threads
- 2.12 CI/CD: push → flake8 → pytest (20 tests, TF-IDF stand-in) → build (tag = commit SHA) → GitHub Container Registry (ghcr.io) → SSH deploy → health check
- 2.13 Infra & security: ap-southeast-2; EC2 t3.small AL2023, 20 GB gp3, 2 GB swap; RDS db.t4g.micro single-AZ, private;
  SG app: 80, 22; SG db: 3306 only from app SG; IAM least privilege (S3 Get/Put/List own bucket, SNS Publish own topic)

## Chapter 3: Results
- Local setup: Windows, Python 3.12.10 venv, torch 2.14.1+cpu, sentence-transformers 5.7.0
  (Python 3.8 was too old; this is the "environment issue" anecdote)
- load_db: 344 candidates, 28 jobs, 9,544 pairs in 8.0 s (SQLite)
- Evaluation (MiniLM):
  | config | mean Spearman | mean overlap@30 | random |
  | semantic only | 0.275 | 10.8 | 5.6 |
  | full scorer | 0.308 | 11.3 | 5.6 |
  - 27/28 jobs beat random (only Data Engineer: 1 vs 2.6)
  - best: Head of Internal Control & Compliance 0.676, Internal Audit 0.437, Trade Marketing 0.425
  - worst: Executive/Sr. Executive - IT 0.039 (no skills list), Project Coordinator (Civil) 0.116
  - jobs with skills list: Spearman 0.315 vs 0.278 without
  - Fig 3.1 fig3_spearman.png · Fig 3.2 fig3_overlap.png
- Dashboard: AI Engineer ranking, 18/30 in dataset top 30 (random ≈ 7.9; 90 tied candidates at cut-off 0.85);
  top candidate 73% (semantic 68%, skills 80%); "R or Java" matched via "R" → fig3_ranking_ai_engineer.png
- STILL NEEDED: dashboard + candidate page screenshots; S3 bucket, RDS, EC2, IAM role, SNS email, GitHub Actions run,
  GitHub Container Registry (ghcr.io) image, /health output, AWS cost/credits after deployment
- Budget: alerts at 30/60/90/100% of $100; AWS email-verification rule for alert recipients (since 30 Sep 2026)

## Chapter 4: Conclusion (points)
- Achieved: working cloud app, 2× better than random shortlist, full scorer > semantic-only
- Limitations: labels are dataset creator's score (unknown method, many ties); MiniLM truncates at 256 word pieces
  (18 resumes > 180 words); English only; dataset records, not PDF parsing; single EC2 (no autoscaling / HA);
  HTTP only (no TLS); SSH open to 0.0.0.0/0 for CI; no auth; fairness/bias not audited
- Future: PDF/DOCX upload + parsing; fine-tune on labelled pairs or cross-encoder re-ranking; ALB + Auto Scaling or ECS;
  HTTPS (ACM), Cognito login; CloudWatch monitoring/alarms; bias audit

## References (IEEE), to cite
Sentence-BERT (Reimers & Gurevych, EMNLP 2019); MiniLM (Wang et al., NeurIPS 2020); all-MiniLM-L6-v2 model card;
BERT (Devlin et al., NAACL 2019); Transformer (Vaswani et al., NeurIPS 2017); Kaggle resume dataset; NIST SP 800-145;
AWS docs: EC2, RDS, S3, SNS, IAM roles for EC2, Free Tier, Budgets email verification; Docker (Merkel 2014);
GitHub Actions docs; Flask docs; Spearman (1904)

## Cloud account finding (good for Ch. 3 "challenges" + viva)
- Account created via AWS's new sign-up experience = a "project" account inside an AWS-managed Organization
  (management account 545860874833); console role AccountFullAccessRole (AdministratorAccess)
- Service control policies: EC2/RDS/SNS denied in every region except the project's selected region, Sydney ap-southeast-2
  (tested 15 regions); notifications-contacts:* denied → budget email verification fails until "advanced features" activated
- Verified in ap-southeast-2: EC2, RDS, SNS ok; S3 bucket create/delete ok; Free-plan instance types incl. t3.small
- Free plan ACTIVE, $120 credits, expires 2027-04-08 → deployment region switched from Mumbai to Sydney

## Deployment evidence (20 Oct 2026, Sydney)
- RDS create 15:12 → available 15:24 IST (~12 min); endpoint resume-db.cf6qqmiempar.ap-southeast-2.rds.amazonaws.com
- EC2 i-0a27d4aef9cb8220e (t3.small, AL2023) public IP 54.66.145.64; user data: cloud-init done, Docker 25.0.14,
  1.9 GiB RAM + 2.0 GiB swap, 20 GB disk (16 GB free)
- Network isolation test: EC2 → RDS :3306 OPEN; CloudShell (outside VPC SG) → RDS :3306 BLOCKED
  → proves DB is private, only reachable from app security group (defence in depth)
- SNS email subscription: pending confirmation → confirmed (double opt-in)
- Approx. running cost ≈ $1.40/day (RDS ~$0.025/hr + EC2 ~$0.033/hr + storage/IP)
