# One image recipe, three targets: `docker build --target api|ui|agent .` Owner: P1.
# No secrets baked in; every target runs as a non-root user and writes only under MEL_OUT_DIR.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MEL_OUT_DIR=/tmp/mel_out
WORKDIR /app
RUN useradd --create-home --uid 10001 appuser && mkdir -p /tmp/mel_out && chown appuser /tmp/mel_out /app

# --- api: the REST service (mel/api). Only the package, its config and the mock data; no pack, docs or app.
FROM base AS api
COPY pyproject.toml ./
COPY mel/ ./mel/
COPY config/ ./config/
COPY data/mock/ ./data/mock/
RUN pip install -e ".[api]" && chown -R appuser /app
USER appuser
EXPOSE 8000
# Liveness: healthy once /healthz answers. Stdlib only (no curl in the image).
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
CMD ["uvicorn", "--factory", "mel.api.app:create_app", "--host", "0.0.0.0", "--port", "8000"]

# --- ui: the Streamlit demo with the participant pack and the recorded runs (.dockerignore trims the context).
FROM base AS ui
COPY . .
RUN pip install -e ".[ui]" && chown -R appuser /app
USER appuser
EXPOSE 8501
CMD ["streamlit", "run", "app/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]

# --- agent: agentcore_app.py as a plain container (EKS). `agentcore launch` builds its own image from the same file.
FROM base AS agent
COPY pyproject.toml agentcore_app.py ./
COPY mel/ ./mel/
COPY config/ ./config/
COPY data/mock/ ./data/mock/
COPY mel-survey-agent-participant-pack/participant-pack/data/ ./mel-survey-agent-participant-pack/participant-pack/data/
RUN pip install -e ".[agent]" && chown -R appuser /app
USER appuser
ENV DOCKER_CONTAINER=1
EXPOSE 8080
CMD ["python", "-m", "agentcore_app"]
