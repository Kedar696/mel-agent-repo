"""FastAPI app for the MEL survey agent. Owner: P1 (Data, Contracts & Integration).

Thin by design: it reuses mel.pipeline (decide + write + hand-off) and mel.schedule
(weekly cap, opt-outs, quality gate, broadcaster) without copying any of their logic.

Endpoints
---------
POST /surveys        run one insight; if it yields a survey, admit it to the scheduler.
GET  /surveys/due    read-only list of hand-offs the scheduler would send at an instant.
GET  /healthz        liveness for the container.

Shared state
------------
One in-memory ``SeasonScheduler(relevance_threshold=RELEVANCE_THRESHOLD)`` per process,
created by ``create_app()`` (so each test gets a fresh one) and guarded by a lock. The
scheduler holds the weekly-cap ledger, the opt-out list and the broadcaster queue. **This
state lives only in memory and is lost when the process restarts** -- there is no database.
Delivery stays simulated; no real messaging and no AWS calls are made here.

Run it:  uvicorn mel.api.app:app
"""
import json
import threading

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from mel.data import load_farmers
from mel.pipeline import clean, run_insight
from mel.schedule import SeasonScheduler
from mel.schedule.broadcast import passes_quality, within_send_hours
from mel.timing import fmt_ist, parse_ist
from mel.writer import RELEVANCE_THRESHOLD


class UTF8JSONResponse(JSONResponse):
    """JSON responses that keep Hindi unescaped (`ensure_ascii=False`), as the rest of the
    project writes JSON. FastAPI's default JSONResponse escapes non-ASCII; we override it so
    `survey`/`no_survey` text comes back as real Devanagari, not \\uXXXX."""

    def render(self, content) -> bytes:
        return json.dumps(content, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")


# --------------------------------------------------------------- serialisation helpers
def _decision_dict(d) -> dict:
    """The Decision fields the contract names, as plain JSON. No schema covers the Decision,
    so we emit exactly: survey, rule, reason_code, send_window, send_time (plus notes and
    attention, which are already part of the dataclass)."""
    return {
        "survey": d.survey,
        "rule": d.rule,
        "reason_code": d.reason_code,
        "send_window": d.send_window,
        "send_time": d.send_time,
        "notes": list(d.notes),
        "attention": d.attention,
    }


def create_app(farmers: dict | None = None) -> FastAPI:
    """Build a fresh app with its own scheduler. `farmers` defaults to `load_farmers()`; pass
    an explicit dict (even `{}`) in tests to avoid touching the data folder."""
    app = FastAPI(title="Fasal Pulse - MEL Survey Agent API", version="1.0.0",
                  default_response_class=UTF8JSONResponse)

    app.state.scheduler = SeasonScheduler(relevance_threshold=RELEVANCE_THRESHOLD)
    app.state.lock = threading.Lock()
    try:
        app.state.farmers = load_farmers() if farmers is None else farmers
    except FileNotFoundError:
        app.state.farmers = {}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/surveys")
    async def post_survey(request: Request):
        # A body that is not a JSON object is a client error (422), not a server crash.
        try:
            insight = await request.json()
        except Exception:
            return UTF8JSONResponse(status_code=422, content={"detail": "body must be a JSON object"})
        if not isinstance(insight, dict):
            return UTF8JSONResponse(status_code=422, content={"detail": "body must be a JSON object"})

        # Attention and history stay off, matching the CLI default. Junk input is NOT an error:
        # the pipeline returns the R1 no-survey result, which we report as a 200 no_survey.
        farmer = app.state.farmers.get(insight.get("farmer_id"))  # None if unknown
        with app.state.lock:
            result = run_insight(insight, farmer)
            decision = _decision_dict(result["decision"])

            if "no_survey" in result:
                return UTF8JSONResponse(
                    status_code=200,
                    content={"status": "no_survey", "decision": decision,
                             "no_survey": result["no_survey"]},
                )

            # A survey. Admit it to the one shared scheduler (weekly cap + opt-outs + quality
            # gate). Admitting the same insight again returns the first decision and takes no
            # second weekly slot (CapLedger de-dupes by handoff_id).
            handoff = result["handoff"]
            admit = app.state.scheduler.admit(handoff)
            # The resulting hand-off: a moved copy or a merge host when the cap changed it.
            out_handoff = admit.handoff

            # surveys and handoff must pass the existing schemas; strip _-prefixed keys.
            surveys = {lang: clean(s) for lang, s in result["surveys"].items()}
            return UTF8JSONResponse(
                status_code=201,
                content={"status": "survey", "decision": decision, "surveys": surveys,
                         "handoff": out_handoff,
                         "admission": {"decision": admit.decision, "reason": admit.reason}},
            )

    @app.get("/surveys/due")
    def surveys_due(at: str | None = None, limit: int | None = None):
        """Read-only: the hand-offs the broadcaster would send at `at` (default: the
        scheduler's simulated clock). Never advances the clock, sends, or dequeues anything.

        `at` is ISO 8601 with a timezone offset. In a query string a literal `+` decodes to a
        space, so `at=...+05:30` arrives as `... 05:30`; we restore that single space to `+`
        so the raw form works as well as the percent-encoded `%2B05:30`."""
        scheduler = app.state.scheduler
        if at is None:
            clock = scheduler.clock
        else:
            fixed = at.replace(" ", "+", 1) if " " in at else at   # query-string '+'-as-space
            try:
                clock = _FixedClock(parse_ist(fixed))
            except (ValueError, TypeError):
                return UTF8JSONResponse(status_code=422,
                                    content={"detail": "`at` must be ISO 8601 with a timezone offset"})
        if limit is not None and limit < 0:
            return UTF8JSONResponse(status_code=422, content={"detail": "`limit` must be 0 or more"})

        now = clock.now()
        opt_out = scheduler.opt_out
        rt = scheduler.relevance_threshold
        due = []
        # due_now gives window-opened hand-offs in send-window order (read-only view). Then we
        # keep only what the broadcaster would really SEND now, matching Broadcaster._decide_one:
        # not opted out, not past not_after, not past expires_at, passes the P4 quality gate,
        # and inside the day's send hours.
        for h in scheduler.broadcaster.due_now(clock):
            if opt_out is not None and opt_out.blocks(h):
                continue
            if now > parse_ist(h["send_window"]["not_after"]):
                continue
            if now > parse_ist(h["expires_at"]):
                continue
            if not passes_quality(h["survey"], rt):
                continue
            if not within_send_hours(now, h.get("send_hours")):
                continue
            due.append(h)
        if limit is not None:
            due = due[:limit]
        # Return each stored hand-off unchanged, so every entry in `handoffs` is a full,
        # schema-valid schedule_handoff (same object the scheduler holds and would send).
        return {"as_of": fmt_ist(now), "count": len(due), "handoffs": due}

    return app


class _FixedClock:
    """A minimal read-only clock holding one instant, for a `GET /surveys/due?at=...` call.
    It only needs `now()`; the broadcaster's `due_now` reads nothing else."""

    def __init__(self, now):
        self._now = now

    def now(self):
        return self._now


# Module-level app for `uvicorn mel.api.app:app`.
app = create_app()
