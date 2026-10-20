"""Entry point for gunicorn (production) and `python wsgi.py` (local development)."""

import logging
import os
import threading

from app.web import create_app

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = create_app()

# Load MiniLM and embed all resumes in the background at startup,
# so the first recruiter request doesn't wait for it.
if os.getenv("WARMUP", "1") == "1":
    threading.Thread(target=app.extensions["ranker"].get, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
