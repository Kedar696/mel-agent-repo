"""P1 - REST API: a thin FastAPI front over the existing pipeline and scheduler.

`POST /surveys` runs one insight through `mel.pipeline.run_insight` and, when it produces a
survey, admits it to one shared in-memory `SeasonScheduler` (weekly cap + opt-outs + the P4
quality gate). `GET /surveys/due` reports, read-only, which queued hand-offs that scheduler
would send at a given instant. No decision, cap or quality logic lives here: the API reuses
mel.pipeline and mel.schedule unchanged.

Run it with:  uvicorn mel.api.app:app
Build the app in code with `create_app()` (tests make a fresh one per test).
"""
from .app import create_app, app

__all__ = ["create_app", "app"]
