import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Tests run without PyTorch/MiniLM (fast CI): use the TF-IDF test embedder.
os.environ.setdefault("EMBEDDER", "tfidf")
for var in ("S3_BUCKET", "SNS_TOPIC_ARN"):
    os.environ.pop(var, None)

SAMPLE_CSV = os.path.join(ROOT, "tests", "fixtures", "sample_resume_data.csv")


@pytest.fixture(scope="session")
def sample_data():
    from app.dataset import load_dataset
    return load_dataset(SAMPLE_CSV)


@pytest.fixture()
def client(tmp_path, sample_data):
    from app import db
    from app.web import create_app

    url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = db.get_engine(url)
    db.init_db(engine)
    db.load_records(engine, *sample_data)
    app = create_app({"DATABASE_URL": url, "CACHE_DIR": str(tmp_path / "cache"), "TESTING": True})
    return app.test_client()
