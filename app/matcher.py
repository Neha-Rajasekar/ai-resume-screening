"""AI/NLP matching and ranking (synopsis modules 3 and 4).

Score for one candidate against one job, every part in [0, 1]:

  semantic   = cosine similarity of MiniLM sentence embeddings of the
               whole resume text and the whole job description.
               Catches meaning even when different words are used.
  skills     = how many required skills the candidate has. A required
               skill counts as matched if the candidate lists it exactly,
               OR lists a skill whose MiniLM embedding is close enough
               (e.g. "Scikit-learn" ~ "sklearn", "AutoCAD" ~ "Auto CAD 2D").
  experience = years of experience compared with the job's requirement.

  final = weighted average of the parts that the job actually specifies
          (a job with no skills list is scored on semantic + experience).

Candidates are sorted by final score and the top 30 are returned.
"""

import hashlib
import logging
import os
import re

import numpy as np

from .extract import normalize_skill

log = logging.getLogger(__name__)

MODEL_NAME = os.getenv("MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")

DEFAULT_WEIGHTS = {
    "semantic": float(os.getenv("W_SEMANTIC", 0.55)),
    "skills": float(os.getenv("W_SKILLS", 0.30)),
    "experience": float(os.getenv("W_EXPERIENCE", 0.15)),
}


# ---------------------------------------------------------------- embedders

class MiniLMEmbedder:
    """Sentence embeddings from Hugging Face MiniLM (384 numbers per text)."""

    name = "minilm"
    skill_threshold = 0.70  # cosine above which two skill names mean the same thing

    def __init__(self, model_name: str = MODEL_NAME):
        from sentence_transformers import SentenceTransformer
        self.model_name = model_name
        self.model = SentenceTransformer(model_name, device="cpu")

    def fit(self, corpus):  # pre-trained, nothing to fit
        return self

    def encode(self, texts) -> np.ndarray:
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        emb = self.model.encode(list(texts), batch_size=64, normalize_embeddings=True,
                                show_progress_bar=False, convert_to_numpy=True)
        return emb.astype(np.float32)


class TfidfEmbedder:
    """Lightweight fallback (no PyTorch, no download) used by CI tests.

    Character n-gram TF-IDF vectors. Not semantic like MiniLM, so it is
    only for testing the pipeline, not for the real deployment.
    """

    name = "tfidf"
    skill_threshold = 0.55

    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.model_name = "tfidf-char-3-5"
        self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5),
                                          sublinear_tf=True, min_df=1)
        self.fitted = False

    def fit(self, corpus):
        self.vectorizer.fit([t.lower() for t in corpus if t])
        self.fitted = True
        return self

    def encode(self, texts) -> np.ndarray:
        if not texts:
            return np.zeros((0, 1), dtype=np.float32)
        mat = self.vectorizer.transform([t.lower() for t in texts]).toarray().astype(np.float32)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return mat / norms


def get_embedder(kind: str = None):
    """EMBEDDER=minilm (default, real NLP), tfidf (tests), or auto (minilm, else tfidf)."""
    kind = (kind or os.getenv("EMBEDDER", "minilm")).lower()
    if kind == "tfidf":
        return TfidfEmbedder()
    try:
        return MiniLMEmbedder()
    except Exception as exc:  # ImportError or model download failure
        if kind == "auto":
            log.warning("MiniLM unavailable (%s); falling back to TF-IDF.", exc)
            return TfidfEmbedder()
        raise


# ---------------------------------------------------------------- ranker

def alternatives(skill: str) -> list:
    """'R or Java' -> ['R or Java', 'R', 'Java']; 'Python' -> ['Python']."""
    parts = [p.strip() for p in re.split(r"\s+or\s+", skill, flags=re.IGNORECASE) if p.strip()]
    return [skill] + parts if len(parts) > 1 else [skill]


def experience_fit(years: float, min_years, max_years):
    """1.0 inside the required range, partial credit below, gentle decay above."""
    if min_years is None and max_years is None:
        return None
    lo = min_years or 0.0
    if years < lo:
        return round(years / lo, 4) if lo > 0 else 0.0
    if max_years is not None and years > max_years:
        return round(max(0.5, 1.0 - (years - max_years) / 10.0), 4)
    return 1.0


class Ranker:
    def __init__(self, candidates, embedder=None, cache_dir: str = None, weights: dict = None):
        self.candidates = list(candidates)
        self.embedder = embedder or get_embedder()
        self.weights = dict(weights or DEFAULT_WEIGHTS)
        self.cache_dir = cache_dir

        texts = [c["text"] for c in self.candidates]

        # Vocabulary of every distinct skill any candidate lists.
        self.skill_names, self.skill_keys = [], {}
        self.cand_skill_idx = []
        for cand in self.candidates:
            idx = []
            for skill in cand["skills"]:
                key = normalize_skill(skill)
                if not key:
                    continue
                if key not in self.skill_keys:
                    self.skill_keys[key] = len(self.skill_names)
                    self.skill_names.append(skill)
                idx.append(self.skill_keys[key])
            self.cand_skill_idx.append(np.array(sorted(set(idx)), dtype=np.int64))

        self.embedder.fit(texts + self.skill_names)
        self.cand_emb = self._cached_encode("candidates", texts)
        self.skill_emb = self._cached_encode("skills", self.skill_names)
        log.info("Ranker ready: %d candidates, %d distinct skills, embedder=%s",
                 len(self.candidates), len(self.skill_names), self.embedder.name)

    # Embeddings are cached on disk so a container restart takes seconds, not a minute.
    def _cached_encode(self, label, texts):
        if not self.cache_dir or self.embedder.name == "tfidf":
            return self.embedder.encode(texts)
        digest = hashlib.sha1(("\n".join(texts) + self.embedder.model_name).encode("utf-8")).hexdigest()[:16]
        path = os.path.join(self.cache_dir, f"{label}_{self.embedder.name}_{digest}.npy")
        if os.path.exists(path):
            return np.load(path)
        emb = self.embedder.encode(texts)
        os.makedirs(self.cache_dir, exist_ok=True)
        np.save(path, emb)
        return emb

    def score_all(self, job: dict):
        """Score every candidate for `job`. Returns a list of result dicts (unsorted)."""
        query = self.embedder.encode([job["text"]])[0]
        semantic = np.clip(self.cand_emb @ query, 0.0, 1.0)

        required = [s for s in job.get("skills", []) if normalize_skill(s)]
        if required:
            # "R or Java" is satisfied by either option: score each alternative, keep the best.
            options = [alternatives(s) for s in required]
            flat = [o for opts in options for o in opts]
            flat_emb = self.embedder.encode(flat)
            flat_sim = flat_emb @ self.skill_emb.T if len(self.skill_names) else np.zeros((len(flat), 0))
            for r, opt in enumerate(flat):
                col = self.skill_keys.get(normalize_skill(opt))
                if col is not None:
                    flat_sim[r, col] = 1.0
            sim, start = np.zeros((len(required), flat_sim.shape[1]), dtype=np.float32), 0
            for r, opts in enumerate(options):
                sim[r] = flat_sim[start:start + len(opts)].max(axis=0)
                start += len(opts)
        threshold = self.embedder.skill_threshold

        results = []
        for i, cand in enumerate(self.candidates):
            parts = {"semantic": float(semantic[i]), "skills": None, "experience": None}
            matched, missing = [], []
            if required:
                cols = self.cand_skill_idx[i]
                credit = []
                for r, req in enumerate(required):
                    if cols.size:
                        j = int(cols[np.argmax(sim[r, cols])])
                        best = float(sim[r, j])
                    else:
                        j, best = -1, 0.0
                    if best >= threshold:
                        credit.append(best)
                        matched.append({"required": req, "candidate_skill": self.skill_names[j],
                                        "similarity": round(min(best, 1.0), 3)})
                    else:
                        credit.append(0.0)
                        missing.append(req)
                parts["skills"] = float(np.mean(credit))
            parts["experience"] = experience_fit(cand["years_experience"], job.get("min_years"), job.get("max_years"))

            used = {k: v for k, v in parts.items() if v is not None and self.weights.get(k, 0) > 0}
            total_w = sum(self.weights[k] for k in used)
            final = sum(self.weights[k] * v for k, v in used.items()) / total_w if total_w else 0.0

            results.append({
                "candidate_id": cand["id"],
                "final": round(final, 4),
                "semantic": round(parts["semantic"], 4),
                "skills": None if parts["skills"] is None else round(parts["skills"], 4),
                "experience": parts["experience"],
                "matched_skills": matched,
                "missing_skills": missing,
            })
        return results

    def rank(self, job: dict, top_k: int = 30):
        results = self.score_all(job)
        results.sort(key=lambda r: (-r["final"], -r["semantic"], r["candidate_id"]))
        for n, r in enumerate(results, start=1):
            r["rank"] = n
        return results[:top_k] if top_k else results
