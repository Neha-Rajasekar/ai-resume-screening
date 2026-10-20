from datetime import date

from app.extract import (normalize_skill, parse_experience_requirement, parse_list,
                         parse_skill_text, years_of_experience)

TODAY = date(2026, 10, 1)


def test_parse_list_handles_dataset_formats():
    assert parse_list("['Python', 'SQL']") == ["Python", "SQL"]
    assert parse_list("[['Big Data'], ['Spark', None]]") == ["Big Data", "Spark"]
    assert parse_list("['N/A', 'B.Tech']") == ["B.Tech"]
    assert parse_list(float("nan")) == []
    assert parse_list("Line one\nLine two") == ["Line one", "Line two"]


def test_parse_skill_text_strips_bullets_and_splits():
    assert parse_skill_text("•Administration\n•Health Safety") == ["Administration", "Health Safety"]
    assert parse_skill_text("Python\nR or Java\nScikit-learn.") == ["Python", "R or Java", "Scikit-learn"]
    assert parse_skill_text("AWS, Docker; aws") == ["AWS", "Docker"]


def test_normalize_skill():
    assert normalize_skill("Scikit-learn.") == "scikit learn"
    assert normalize_skill("C++") == "c++"


def test_experience_requirement():
    assert parse_experience_requirement("At least 5 year(s)") == (5, None)
    assert parse_experience_requirement("1 to 3 years") == (1, 3)
    assert parse_experience_requirement(None) == (None, None)


def test_years_of_experience_merges_overlaps_and_ongoing():
    years = years_of_experience("['Jan 2020', 'Jan 2018']", "['Ongoing', 'Jun 2020']", TODAY)
    assert 8.5 < years < 8.9  # Jan 2018 -> Oct 2026, overlap counted once
    assert years_of_experience("['02/2014']", "['06/2016']", TODAY) == 2.3
    assert years_of_experience(None, None, TODAY) == 0.0


def test_dataset_split(sample_data):
    candidates, jobs, labels = sample_data
    assert len(jobs) == 3
    assert len(candidates) == 20
    assert len(labels) == 60
    # The resume's 'responsibilities' column is the job's text, so it must not leak in.
    assert all("responsibilities" not in c for c in candidates)
    assert all(c["label"].startswith("Candidate ") for c in candidates)
