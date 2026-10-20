"""Resume information extraction (synopsis module 2).

Turns one row of the Kaggle resume dataset into two clean records:
  * a candidate profile (skills, education, experience, roles, ...)
  * a job description (title, required skills, experience, education)

The dataset stores most resume fields as Python-list strings, e.g.
    "['Python', 'SQL']"   or   "[['Big Data'], ['Spark', 'Hive']]"
so `parse_list` safely turns those into flat Python lists.

Dataset quirk (important for the report/viva):
    The resume column `responsibilities` is identical to the job column
    `responsibilities.1` in every row, i.e. it holds the JOB's
    responsibilities, not the candidate's. Using it as resume text would
    leak the job description into the resume, so it is ignored here.
"""

import ast
import hashlib
import json
import re
from datetime import date

# Values the dataset uses to mean "nothing here".
_EMPTY = {"", "n/a", "na", "none", "nan", "null", "-", "--"}

# Words the dataset uses for a job that has not ended.
_ONGOING = {"ongoing", "current", "present", "till date", "till now", "now", "to date", "continuing"}

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


# ---------------------------------------------------------------- helpers

def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and value != value:  # NaN
        return True
    return str(value).strip().lower() in _EMPTY


def _flatten(value):
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _flatten(item)
    else:
        yield value


def parse_list(raw) -> list:
    """Parse a list-looking string from the dataset into a flat list of strings.

    "['A', 'B']"          -> ['A', 'B']
    "[['A'], ['B', None]]" -> ['A', 'B']
    "A\\nB"                -> ['A', 'B']     (newline-separated text)
    NaN / "N/A"           -> []
    """
    if _is_empty(raw):
        return []
    text = str(raw).strip()
    items = None
    if text.startswith("["):
        try:
            items = list(_flatten(ast.literal_eval(text)))
        except (ValueError, SyntaxError):
            items = None
    if items is None:
        items = re.split(r"[\n\r]+", text)
    out = []
    for item in items:
        if _is_empty(item):
            continue
        cleaned = clean_skill(str(item))
        if cleaned:
            out.append(cleaned)
    return out


def clean_skill(text: str) -> str:
    """Strip bullets, stray punctuation and extra spaces from one skill/phrase."""
    text = re.sub(r"^[\s•\-\*·▪●◦–]+", "", text)
    text = text.strip().strip(".,;:")
    return re.sub(r"\s+", " ", text)


def normalize_skill(text: str) -> str:
    """Lower-case canonical form used for exact skill comparison.

    'Scikit-learn.' -> 'scikit learn', 'AutoCAD' -> 'autocad', 'Auto CAD' -> 'auto cad'
    """
    text = clean_skill(text).lower()
    text = re.sub(r"[^a-z0-9+#]+", " ", text)
    return text.strip()


def unique(items):
    """Keep the first occurrence of each item (case-insensitive), preserving order."""
    seen, out = set(), []
    for item in items:
        key = normalize_skill(item)
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def parse_skill_text(raw) -> list:
    """Split a free-text skills field (newlines, commas, semicolons, bullets) into skills."""
    if _is_empty(raw):
        return []
    parts = re.split(r"[\n\r,;•]+", str(raw))
    return unique([clean_skill(p) for p in parts if clean_skill(p) and not _is_empty(p)])


# ------------------------------------------------------------- experience

def _parse_date(text: str, today: date):
    """Parse 'Jul 2019', '07/2019', '2019', 'Ongoing' -> (year, month) or None."""
    if _is_empty(text):
        return None
    t = str(text).strip().lower()
    if any(word in t for word in _ONGOING):
        return today.year, today.month
    m = re.search(r"([a-z]{3})[a-z]*\.?\s*[,\-]?\s*(\d{4})", t)          # Jul 2019 / July, 2019
    if m and m.group(1) in _MONTHS:
        return int(m.group(2)), _MONTHS[m.group(1)]
    m = re.search(r"(\d{1,2})\s*[/\-.]\s*(\d{4})", t)                  # 07/2019
    if m and 1 <= int(m.group(1)) <= 12:
        return int(m.group(2)), int(m.group(1))
    m = re.search(r"(\d{4})", t)                                       # 2019
    if m:
        return int(m.group(1)), 6
    return None


def years_of_experience(start_raw, end_raw, today: date = None) -> float:
    """Total years across all jobs, from the parallel start/end date lists.

    Overlapping jobs are merged so they are not counted twice.
    """
    today = today or date.today()
    starts = _raw_list(start_raw)
    ends = _raw_list(end_raw)
    spans = []
    for i, start in enumerate(starts):
        s = _parse_date(start, today)
        e = _parse_date(ends[i], today) if i < len(ends) else None
        if s is None:
            continue
        if e is None:
            e = s
        s_m, e_m = s[0] * 12 + s[1], e[0] * 12 + e[1]
        if e_m < s_m or s[0] < 1950 or e[0] > today.year + 1:
            continue
        spans.append((s_m, e_m))
    if not spans:
        return 0.0
    spans.sort()
    total, (cur_s, cur_e) = 0, spans[0]
    for s, e in spans[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s
            cur_s, cur_e = s, e
    total += cur_e - cur_s
    return round(min(total / 12.0, 45.0), 1)


def _raw_list(raw) -> list:
    """Like parse_list but keeps 'N/A'/None placeholders so indices stay aligned."""
    if _is_empty(raw):
        return []
    try:
        value = ast.literal_eval(str(raw))
        return [str(v) if v is not None else "" for v in _flatten(value)]
    except (ValueError, SyntaxError):
        return [str(raw)]


def parse_experience_requirement(raw):
    """'At least 5 year(s)' -> (5, None); '1 to 3 years' -> (1, 3); NaN -> (None, None)."""
    if _is_empty(raw):
        return None, None
    text = str(raw).lower()
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
    if not nums:
        return None, None
    if len(nums) >= 2 and ("to" in text or "-" in text):
        return nums[0], nums[1]
    if "max" in text or "at most" in text or "up to" in text:
        return 0.0, nums[0]
    return nums[0], None


# ---------------------------------------------------------- record builders

RESUME_KEY_COLUMNS = [
    "career_objective", "skills", "educational_institution_name", "degree_names",
    "passing_years", "major_field_of_studies", "professional_company_names",
    "start_dates", "end_dates", "positions", "related_skils_in_job",
]

JOB_KEY_COLUMNS = [
    "job_position_name", "educationaL_requirements", "experiencere_requirement",
    "skills_required", "age_requirement",
]


def stable_id(row, columns, prefix: str) -> str:
    """Deterministic short id from the given columns, so re-loading gives the same ids."""
    payload = json.dumps([str(row.get(c, "")) for c in columns], ensure_ascii=False)
    return prefix + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def build_candidate(row: dict, today: date = None) -> dict:
    skills = unique(parse_list(row.get("skills")))
    job_skills = unique(parse_list(row.get("related_skils_in_job")))
    cert_skills = unique(parse_list(row.get("certification_skills")))
    all_skills = unique(skills + job_skills + cert_skills)

    degrees = parse_list(row.get("degree_names"))
    majors = parse_list(row.get("major_field_of_studies"))
    institutions = parse_list(row.get("educational_institution_name"))
    positions = unique(parse_list(row.get("positions")))
    companies = unique(parse_list(row.get("professional_company_names")))
    languages = parse_list(row.get("languages"))
    certifications = unique(parse_list(row.get("certification_providers")))
    objective = "" if _is_empty(row.get("career_objective")) else str(row["career_objective"]).strip()
    years = years_of_experience(row.get("start_dates"), row.get("end_dates"), today)

    # Text the NLP model reads. Order: who they are -> what they did -> what they know.
    parts = []
    if positions:
        parts.append("Roles: " + ", ".join(positions) + ".")
    if objective:
        parts.append(objective)
    if all_skills:
        parts.append("Skills: " + ", ".join(all_skills) + ".")
    if degrees or majors:
        parts.append("Education: " + ", ".join(degrees + majors) + ".")
    if years:
        parts.append(f"{years:g} years of experience.")

    return {
        "id": stable_id(row, RESUME_KEY_COLUMNS, "c_"),
        "objective": objective,
        "skills": all_skills,
        "degrees": degrees,
        "majors": majors,
        "institutions": institutions,
        "positions": positions,
        "companies": companies,
        "languages": languages,
        "certifications": certifications,
        "years_experience": years,
        "text": " ".join(parts),
    }


def build_job(row: dict) -> dict:
    title = str(row.get("job_position_name") or "").strip()
    # Column names are spelled exactly as in the Kaggle CSV (including its typos).
    education = _text(row.get("educationaL_requirements"))
    experience_raw = _text(row.get("experiencere_requirement"))
    age = _text(row.get("age_requirement"))
    skills = parse_skill_text(row.get("skills_required"))
    min_years, max_years = parse_experience_requirement(experience_raw)
    return {
        "id": stable_id(row, JOB_KEY_COLUMNS, "j_"),
        "title": title,
        "education": education,
        "experience": experience_raw,
        "min_years": min_years,
        "max_years": max_years,
        "age": age,
        "skills": skills,
        "text": job_text(title, skills, education, experience_raw),
    }


def _text(value) -> str:
    return "" if _is_empty(value) else clean_skill(str(value))


def job_text(title: str, skills: list, education: str = "", experience: str = "", description: str = "") -> str:
    parts = [f"Job: {title}." if title else ""]
    if description:
        parts.append(description.strip())
    if skills:
        parts.append("Required skills: " + ", ".join(skills) + ".")
    if education:
        parts.append("Education: " + education.rstrip(".") + ".")
    if experience:
        parts.append("Experience: " + experience + ".")
    return " ".join(p for p in parts if p)
