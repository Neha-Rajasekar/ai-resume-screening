import re


def first_job_id(client):
    html = client.get("/").get_data(as_text=True)
    return re.search(r'<option value="(j_[0-9a-f]+)"', html).group(1)


def test_health(client):
    body = client.get("/health").get_json()
    assert body["status"] == "ok" and body["candidates"] == 20 and body["jobs"] == 3


def test_dashboard_lists_jobs(client):
    html = client.get("/").get_data(as_text=True)
    assert "AI Engineer" in html and "HR Officer" in html


def test_rank_dataset_job_shows_top_candidates(client):
    resp = client.post("/rank", data={"mode": "preset", "job_id": first_job_id(client)})
    assert resp.status_code == 302
    page = client.get(resp.location).get_data(as_text=True)
    assert page.count("/candidates/c_") == 20  # sample has 20 candidates, all under top 30
    assert "in the dataset's own top" in page


def test_rank_custom_job_and_download_csv(client):
    resp = client.post("/rank", data={"mode": "custom", "title": "Data Analyst",
                                      "skills": "Python, SQL, Excel", "min_years": "1"})
    run_id = int(resp.location.rsplit("/", 1)[1])
    csv_text = client.get(f"/runs/{run_id}.csv").get_data(as_text=True)
    assert csv_text.splitlines()[1].startswith("rank,candidate")
    assert len(csv_text.splitlines()) == 2 + 20


def test_custom_job_validation(client):
    resp = client.post("/rank", data={"mode": "custom", "title": "", "skills": ""}, follow_redirects=True)
    assert "Give the job a title" in resp.get_data(as_text=True)
    resp = client.post("/api/rank", json={"title": "X", "skills": ["A"], "min_years": "abc"})
    assert resp.status_code == 400


def test_api_rank(client):
    body = client.post("/api/rank", json={"title": "HR", "skills": ["Recruitment"]}).get_json()
    assert body["results"][0]["rank"] == 1 and body["s3_key"] is None and body["notified"] is False


def test_candidate_page_and_404(client):
    resp = client.post("/rank", data={"mode": "preset", "job_id": first_job_id(client)})
    page = client.get(resp.location).get_data(as_text=True)
    cand = re.search(r'href="(/candidates/c_[0-9a-f]+\?run=\d+)"', page).group(1)
    assert client.get(cand).status_code == 200
    assert client.get("/runs/9999").status_code == 404
