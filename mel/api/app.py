"""FastAPI app for the MEL survey agent. Owner: P1.

Thin by design: one generator (mel.agent.run_agent: decide, write with Bedrock or the templates, verify, hand off),
P3's opt-out, quality and weekly-cap rules unchanged, and one database (mel.store) for everything that must outlive
a process. No rule lives here.

Endpoints (every one but /healthz needs `Authorization: Bearer <MEL_API_TOKEN>`)
  POST /surveys                          run one insight; a survey is admitted (opt-out, quality gate, weekly cap) and stored
  GET  /surveys/due                      the hand-offs a sender should send at an instant (read-only)
  GET  /v1/surveys/{flow_id}             the survey registered under a FarmerChat flow id (static registration)
  POST /v1/surveys/{flow_id}/responses   FarmerChat's answer path: one answer record in; opt-outs and follow-ups come out
  GET  /follow-ups                       answer records that need a person (needs_follow_up)
  GET  /healthz                          liveness

State lives in the SQLite database MEL_DATABASE_URL names, so a restart loses nothing. The weekly cap is decided
per request from that farmer's stored hand-offs; the same hand-off again returns its first decision and takes no
second slot.

Run it:  MEL_API_TOKEN=... uvicorn --factory mel.api.app:create_app
"""
import json
import secrets
import threading
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from mel.agent import run_agent_to_end
from mel.config import IST, env
from mel.data import errors, load_farmers
from mel.pipeline import clean
from mel.schedule import Admit, CapLedger, OptOutList
from mel.schedule.broadcast import passes_quality, queue_key, within_send_hours
from mel.store import Store
from mel.timing import fmt_ist, parse_ist
from mel.writer import RELEVANCE_THRESHOLD


class UTF8JSONResponse(JSONResponse):
    """JSON responses that keep Hindi unescaped (`ensure_ascii=False`), as the rest of the project writes JSON."""

    def render(self, content) -> bytes:
        return json.dumps(content, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _bad(status: int, detail) -> UTF8JSONResponse:
    return UTF8JSONResponse(status_code=status, content={"detail": detail})


async def _json_object(request: Request) -> dict | None:
    """The body as a dict, or None when it is not JSON or not an object (a client error, never a crash)."""
    try:
        body = await request.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


def admit(store: Store, handoff: dict) -> Admit:
    """P3's gate (opt-out, quality, weekly cap) against this farmer's stored hand-offs, then the outcome is stored.
    The ledger is rebuilt from the farmer's rows on every call, so every replica decides from the same facts.
    ponytail: two requests for the same farmer in the same instant could both pass the cap; a row lock per farmer
    if that ever shows up."""
    stored = store.handoff(handoff["handoff_id"])
    if stored:
        body, decision, reason = stored
        return Admit(decision, body, reason)
    fid = handoff["survey"]["farmer_id"]
    opt_out = OptOutList()
    if store.opted_out(fid):
        opt_out.record({"failure_code": "farmer_opted_out", "farmer_id": fid})
    ledger = CapLedger()
    for prior in store.farmer_handoffs(fid):
        ledger.allow(prior)
    a = ledger.admit_checked(handoff, opt_out=opt_out, relevance_threshold=RELEVANCE_THRESHOLD)
    if a.decision == "merged":
        host = store.handoff(a.handoff["handoff_id"])       # the host now carries this survey's insight ids too
        store.put_handoff(a.handoff, host[1], host[2])
        store.put_handoff(handoff, "merged", a.reason)
    else:
        store.put_handoff(a.handoff, a.decision, a.reason)
    return a


def create_app(farmers: dict | None = None, store: Store | None = None, token: str | None = None) -> FastAPI:
    """`farmers` defaults to `load_farmers()`; `store` to `Store()` (MEL_DATABASE_URL); `token` to MEL_API_TOKEN.
    Tests pass an in-memory store and a token so nothing touches the environment."""
    token = token or env("MEL_API_TOKEN")
    if not token:
        raise RuntimeError("MEL_API_TOKEN is not set; the API does not start without a bearer token")
    store = store or Store()
    app = FastAPI(title="Fasal Pulse - MEL Survey Agent API", version="2.0.0", default_response_class=UTF8JSONResponse)
    app.state.store = store
    app.state.lock = threading.Lock()
    try:
        app.state.farmers = load_farmers() if farmers is None else farmers
    except FileNotFoundError:
        app.state.farmers = {}

    def auth(request: Request):
        scheme, _, given = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(given.strip(), token):
            raise HTTPException(401, "a valid bearer token is required", headers={"WWW-Authenticate": "Bearer"})
    guarded = [Depends(auth)]

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/surveys", dependencies=guarded)
    async def post_survey(request: Request):
        insight = await _json_object(request)
        if insight is None:
            return _bad(422, "body must be a JSON object")
        # History and attention stay off, matching the CLI default. Junk input is not an error: the agent
        # returns the R1 no-survey result, reported as a 200 no_survey.
        farmer = app.state.farmers.get(insight.get("farmer_id"))
        # Off the event loop: with Bedrock on, one run takes seconds, and /healthz must keep answering meanwhile.
        _, res = await run_in_threadpool(run_agent_to_end, insight, farmer=farmer)
        decision = res["decision"]
        if not decision["survey"]:
            store.put_no_survey(res["no_survey"])
            return UTF8JSONResponse(status_code=200, content={"status": "no_survey", "decision": decision,
                                                              "no_survey": res["no_survey"]})
        surveys = {lang: clean(s) for lang, s in res["surveys"].items()}     # schema-valid: _-keys stripped
        for s in surveys.values():
            store.put_survey(s)
        with app.state.lock:
            a = admit(store, res["handoff"])
        return UTF8JSONResponse(status_code=201, content={
            "status": "survey", "decision": decision, "surveys": surveys, "handoff": a.handoff,
            "admission": {"decision": a.decision, "reason": a.reason}})

    @app.get("/surveys/due", dependencies=guarded)
    def surveys_due(at: str | None = None, limit: int | None = None):
        """Read-only: what a sender should send at `at` (ISO 8601 with offset; default: now). In a query string
        a literal `+` decodes to a space, so `...+05:30` arrives as `... 05:30`; that one space is restored."""
        if at is None:
            now = datetime.now(IST)
        else:
            try:
                now = parse_ist(at.replace(" ", "+", 1) if " " in at else at)
            except (ValueError, TypeError):
                return _bad(422, "`at` must be ISO 8601 with a timezone offset")
        if limit is not None and limit < 0:
            return _bad(422, "`limit` must be 0 or more")
        # Window opened and not expired come from the database; the rest matches Broadcaster._decide_one.
        due = []
        for h in sorted(store.due(fmt_ist(now.astimezone(IST))), key=queue_key):
            if store.opted_out(h["survey"]["farmer_id"]):
                continue
            if now > parse_ist(h["send_window"]["not_after"]):
                continue
            if not passes_quality(h["survey"], RELEVANCE_THRESHOLD):
                continue
            if not within_send_hours(now, h.get("send_hours")):
                continue
            due.append(h)
        if limit is not None:
            due = due[:limit]
        return {"as_of": fmt_ist(now), "count": len(due), "handoffs": due}

    @app.get("/v1/surveys/{flow_id}", dependencies=guarded)
    def get_flow(flow_id: str):
        """Static registration: the flow id is derived when the hand-off is built (rules.json farmerchat_flow), and
        this is what FarmerChat reads back under it. A real registration call replaces the derivation, not this."""
        found = store.handoff_by_flow(flow_id)
        if not found:
            return _bad(404, "unknown flow_id")
        body, decision, reason = found
        return {"flow": body["farmerchat_flow"], "admission": {"decision": decision, "reason": reason}, "handoff": body}

    @app.post("/v1/surveys/{flow_id}/responses", dependencies=guarded)
    async def post_response(flow_id: str, request: Request):
        record = await _json_object(request)
        if record is None:
            return _bad(422, "body must be a JSON object")
        found = store.handoff_by_flow(flow_id)
        if not found:
            return _bad(404, "unknown flow_id")
        problems = errors("response", record)
        if problems:
            return _bad(422, problems)
        survey = found[0]["survey"]
        if record["survey_id"] != survey["survey_id"] or record["farmer_id"] != survey["farmer_id"]:
            return _bad(422, "survey_id and farmer_id must match the flow's survey")
        new = store.put_response(record, flow_id)
        if record.get("failure_code") == "farmer_opted_out":
            store.opt_out(record["farmer_id"], record["response_key"], record["recorded_at"])
        return UTF8JSONResponse(status_code=201 if new else 200, content={
            "response_key": record["response_key"], "status": record["status"], "stored": new,
            "needs_follow_up": bool(record.get("needs_follow_up")),
            "follow_up_reasons": list(record.get("follow_up_reasons") or []),
            "opted_out": store.opted_out(record["farmer_id"])})

    @app.get("/follow-ups", dependencies=guarded)
    def follow_ups(limit: int | None = None):
        if limit is not None and limit < 0:
            return _bad(422, "`limit` must be 0 or more")
        rows = store.follow_ups(limit)
        return {"count": len(rows), "responses": rows}

    return app
