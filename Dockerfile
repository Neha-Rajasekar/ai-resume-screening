# Resume screening app image: Flask + MiniLM, served by gunicorn on port 5000.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf

WORKDIR /app

# 1. CPU-only PyTorch (the default PyPI wheel bundles CUDA and is ~2 GB larger).
ARG WITH_ML=1
RUN if [ "$WITH_ML" = "1" ]; then \
      pip install torch --index-url https://download.pytorch.org/whl/cpu; \
    fi

# 2. Python dependencies (cached as a layer until the requirements change).
COPY requirements.txt requirements-ml.txt ./
RUN pip install -r requirements.txt && \
    if [ "$WITH_ML" = "1" ]; then pip install -r requirements-ml.txt; fi

# 3. Bake the MiniLM model into the image so the server never downloads at runtime.
RUN if [ "$WITH_ML" = "1" ]; then \
      python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"; \
    fi
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

# 4. Application code, run as a non-root user.
COPY app ./app
COPY scripts ./scripts
COPY sql ./sql
COPY wsgi.py ./
RUN useradd --create-home appuser && mkdir -p /app/data/cache && chown -R appuser /app
USER appuser

EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health', timeout=4)" || exit 1

# One worker keeps a single copy of the model in RAM; threads handle concurrent requests.
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--timeout", "180", "--bind", "0.0.0.0:5000", "--access-logfile", "-", "wsgi:app"]
