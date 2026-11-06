# Streamlit UI image for the Fasal Pulse - MEL Survey Agent (app/streamlit_app.py). Owner: P2 (Will).
# Built on AWS by the CodeBuild project in infra/terraform/ui.tf and run by its ECS Express Mode
# service (see infra/README.md). The build context is the repo root; ui.Dockerfile.dockerignore next
# to this file decides what is copied in (.dockerignore belongs to the REST API image, Dockerfile).
# No keys are baked in: on AWS the task role grants the app what it may call.
FROM public.ecr.aws/docker/library/python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd --create-home app
WORKDIR /srv
RUN chown app /srv
COPY requirements.txt requirements-api.txt ./
RUN pip install -r requirements.txt
COPY --chown=app . .
USER app
EXPOSE 8501
CMD ["streamlit", "run", "app/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
