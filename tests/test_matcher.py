from app.matcher import Ranker, TfidfEmbedder, alternatives, experience_fit


def make_candidate(cid, skills, years, text):
    return {"id": cid, "skills": skills, "years_experience": years, "text": text}


CANDIDATES = [
    make_candidate("c1", ["Python", "TensorFlow", "Scikit-learn"], 4,
                   "Machine learning engineer building deep learning models in Python and TensorFlow."),
    make_candidate("c2", ["Recruitment", "Payroll processing", "Onboarding"], 6,
                   "HR officer handling recruitment, payroll and employee onboarding."),
    make_candidate("c3", ["AutoCAD", "SolidWorks"], 1,
                   "Mechanical designer creating drawings in AutoCAD and SolidWorks."),
]

ML_JOB = {"id": "j1", "title": "ML Engineer", "skills": ["Python", "TensorFlow", "PyTorch"],
          "min_years": 3, "max_years": None,
          "text": "Job: ML Engineer. Required skills: Python, TensorFlow, PyTorch. Build machine learning models."}


def ranker():
    return Ranker(CANDIDATES, embedder=TfidfEmbedder())


def test_relevant_candidate_ranks_first():
    top = ranker().rank(ML_JOB, top_k=3)
    assert top[0]["candidate_id"] == "c1"
    assert [r["rank"] for r in top] == [1, 2, 3]
    assert all(0.0 <= r["final"] <= 1.0 for r in top)


def test_matched_and_missing_skills_reported():
    best = ranker().rank(ML_JOB, top_k=1)[0]
    matched = {m["required"] for m in best["matched_skills"]}
    assert {"Python", "TensorFlow"} <= matched
    assert "PyTorch" in best["missing_skills"]
    assert abs(best["skills"] - 2 / 3) < 1e-3  # scores are rounded to 4 decimals


def test_similar_skill_names_match():
    job = dict(ML_JOB, skills=["Payroll"], text="Job: HR. Payroll.")
    hr = next(r for r in ranker().score_all(job) if r["candidate_id"] == "c2")
    assert hr["matched_skills"][0]["candidate_skill"] == "Payroll processing"


def test_job_without_skills_uses_semantic_and_experience_only():
    job = dict(ML_JOB, skills=[])
    result = ranker().rank(job, top_k=1)[0]
    assert result["skills"] is None and result["matched_skills"] == []


def test_top_k_limits_results():
    assert len(ranker().rank(ML_JOB, top_k=2)) == 2


def test_experience_fit():
    assert experience_fit(5, 3, None) == 1.0
    assert experience_fit(1, 4, None) == 0.25
    assert experience_fit(12, 1, 3) == 0.5
    assert experience_fit(5, None, None) is None


def test_or_requirement_accepts_either_option():
    assert alternatives("R or Java") == ["R or Java", "R", "Java"]
    job = dict(ML_JOB, skills=["Julia or Python"])
    best = ranker().rank(job, top_k=1)[0]
    assert best["candidate_id"] == "c1" and best["matched_skills"][0]["candidate_skill"] == "Python"
