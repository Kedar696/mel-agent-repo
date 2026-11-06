"""P1 - the REST API over the agent, the scheduler rules and the database (mel.store).

Run:  MEL_API_TOKEN=... uvicorn --factory mel.api.app:create_app
Build the app in code with `create_app()` (tests make a fresh one per test, on an in-memory database)."""

from .app import create_app

__all__ = ["create_app"]
