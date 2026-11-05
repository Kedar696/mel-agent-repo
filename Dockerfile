# REST API image for the Fasal Pulse - MEL Survey Agent. Owner: P1.
# Serves mel/api (FastAPI) with uvicorn. Runtime deps only (requirements-api.txt); no dev,
# app or Bedrock packages, and no secrets baked in. Runs as a non-root user.
FROM python:3.12-slim

# Keep Python lean and predictable in a container.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MEL_OUT_DIR=/tmp/mel_out

WORKDIR /app

# Install only the API's runtime dependencies first, so this layer caches across code changes.
COPY requirements-api.txt .
RUN pip install -r requirements-api.txt

# Copy only what the API imports at runtime: the package, the schemas it validates against,
# the rules/config it reads, and the mock data it loads farmers/insights from. No tests, docs,
# .git, participant pack, app/ or demo/ (see .dockerignore).
COPY mel/ ./mel/
COPY config/ ./config/
COPY data/mock/ ./data/mock/

# A writable output dir owned by the non-root user, and the non-root user itself.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p ${MEL_OUT_DIR} \
    && chown -R appuser:appuser /app ${MEL_OUT_DIR}
USER appuser

EXPOSE 8000

# Liveness: the container is healthy once /healthz answers. Uses stdlib only (no curl needed).
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"

CMD ["uvicorn", "mel.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
