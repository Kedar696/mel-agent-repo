"""P1: the REST API (mel/api). A fresh app on an in-memory database per test.

Covers the bearer token, POST /surveys (survey / no-survey / junk / non-object body / schema validity /
repeated POST / a second non-high survey within 7 days / state that survives a restart), GET /surveys/due
(window timing, send hours, expiry, read-only, the raw vs percent-encoded `+` in `at`, a comparison with what
the broadcaster would really send), the FarmerChat answer path (POST /v1/surveys/{flow_id}/responses: stored once,
opt-outs, follow-ups, 404 / 422), GET /v1/surveys/{flow_id}, GET /follow-ups, /healthz and Hindi unescaped.
"""

import copy
import urllib.parse
from datetime import timedelta

import pytest

from mel.data import errors, is_valid, load_insights
from mel.pipeline import run_insight
from mel.schedule.broadcast import Broadcaster
from mel.schedule.clock import SimClock
from mel.simulator import simulate
from mel.store import Store
from mel.timing import fmt_ist, parse_ist

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from mel.api.app import create_app  # noqa: E402

MOCK = load_insights()
TOKEN = "test-token"


def client(store: Store | None = None) -> TestClient:
    """A fresh app on an in-memory database (empty cap, opt-outs and queue), sending the token."""
    return TestClient(
        create_app(store=store or Store("sqlite://"), token=TOKEN), headers={"Authorization": f"Bearer {TOKEN}"}
    )


def _first_survey_insight(predicate=None):
    for i in MOCK:
        r = run_insight(i)
        if "handoff" in r and (predicate is None or predicate(i, r)):
            return i, r
    raise AssertionError("no survey insight matched")


def _first_no_survey_insight():
    for i in MOCK:
        r = run_insight(i)
        if "no_survey" in r:
            return i, r
    raise AssertionError("no no-survey insight in mock")


def _non_high(i, r):
    return r["handoff"]["priority"] != "high"


# --- /healthz and the token ---------------------------------------------------------------


def test_healthz_needs_no_token():
    c = TestClient(create_app(store=Store("sqlite://"), token=TOKEN))
    r = c.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_every_other_call_needs_the_token():
    c = TestClient(create_app(store=Store("sqlite://"), token=TOKEN))
    insight, _ = _first_survey_insight()
    assert c.post("/surveys", json=insight).status_code == 401
    assert c.get("/surveys/due").status_code == 401
    assert c.get("/follow-ups").status_code == 401
    assert c.get("/v1/surveys/x").status_code == 401
    wrong = {"Authorization": "Bearer not-the-token"}
    assert c.get("/surveys/due", headers=wrong).status_code == 401
    assert c.get("/surveys/due", headers={"Authorization": f"Basic {TOKEN}"}).status_code == 401
    assert c.get("/surveys/due", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


def test_app_refuses_to_start_without_a_token(monkeypatch):
    monkeypatch.delenv("MEL_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        create_app(store=Store("sqlite://"))


# --- POST /surveys: the three input shapes ----------------------------------------------


def test_post_survey_returns_201_with_the_contracted_shape():
    insight, _ = _first_survey_insight()
    r = client().post("/surveys", json=insight)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "survey"
    assert set(body) == {"status", "decision", "surveys", "handoff", "admission"}
    d = body["decision"]
    for k in ("survey", "rule", "reason_code", "send_window", "send_time"):
        assert k in d
    assert d["survey"] is True and d["rule"] == "R8"
    assert set(body["admission"]) == {"decision", "reason"}
    assert body["admission"]["decision"] in ("sent", "moved", "merged", "skipped")


def test_post_no_survey_returns_200():
    insight, _ = _first_no_survey_insight()
    r = client().post("/surveys", json=insight)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "no_survey"
    assert "no_survey" in body and body["decision"]["survey"] is False
    assert is_valid("no_survey", body["no_survey"])


def test_post_junk_is_a_no_survey_not_an_error():
    # Input the agent treats as junk -> the R1 no-survey result, 200 (not an error).
    r = client().post("/surveys", json={"insight_id": "I-9", "farmer_id": "F-1", "quality_flag": "junk"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "no_survey" and body["decision"]["rule"] == "R1"


def test_post_non_object_body_is_422():
    c = client()
    for content in ("[1,2,3]", '"hello"', "not json"):
        assert c.post("/surveys", content=content, headers={"content-type": "application/json"}).status_code == 422


# --- schema validity of what comes back -------------------------------------------------


def test_returned_survey_and_handoff_pass_the_schemas():
    insight, _ = _first_survey_insight()
    body = client().post("/surveys", json=insight).json()
    for lang, s in body["surveys"].items():
        assert is_valid("survey", s), (lang, s)
        assert not any(k.startswith("_") for k in s)  # _-prefixed keys stripped
    assert is_valid("schedule_handoff", body["handoff"])


# --- repeated POST / the weekly cap / a restart -----------------------------------------


def test_repeated_post_takes_no_second_weekly_slot():
    insight, _ = _first_survey_insight()
    c = client()
    first = c.post("/surveys", json=insight).json()["admission"]
    second = c.post("/surveys", json=insight).json()["admission"]
    assert first == second  # same decision, idempotent
    counts = c.app.state.store.counts()
    assert counts["handoffs"] == 1 and counts["surveys"] == 2  # one hand-off (two language files), counted once


def _collision_pair():
    """A base non-high, non-exempt survey insight plus a near-copy for the same farmer a day
    later, so the second one hits the weekly cap."""
    base, _ = _first_survey_insight(
        lambda i, r: r["handoff"]["priority"] != "high" and not r["handoff"]["frequency_cap"]["exempt"]
    )
    second = copy.deepcopy(base)
    second["insight_id"] = "I-999001"
    second["created_at"] = fmt_ist(parse_ist(base["created_at"]) + timedelta(days=1))
    return base, second


def test_second_non_high_survey_within_seven_days_is_capped():
    base, second = _collision_pair()
    c = client()
    first = c.post("/surveys", json=base).json()
    assert first["admission"]["decision"] == "sent"
    r2 = c.post("/surveys", json=second).json()
    # Capped: moved, merged or skipped (not a second plain send).
    assert r2["admission"]["decision"] in ("moved", "merged", "skipped")


def test_state_survives_a_restart(tmp_path):
    # Two apps on the same database file stand in for a restart (or a second replica).
    url = f"sqlite:///{tmp_path / 'mel.sqlite3'}"
    base, second = _collision_pair()
    first = client(Store(url)).post("/surveys", json=base).json()["admission"]
    assert first["decision"] == "sent"
    c2 = client(Store(url))
    assert c2.post("/surveys", json=base).json()["admission"] == first
    assert c2.post("/surveys", json=second).json()["admission"]["decision"] in ("moved", "merged", "skipped")


# --- GET /surveys/due: timing ------------------------------------------------------------


def _post_and_window(c, insight):
    return c.post("/surveys", json=insight).json()["handoff"]


def test_due_is_empty_before_the_window_opens():
    insight, _ = _first_survey_insight(_non_high)
    c = client()
    h = _post_and_window(c, insight)
    before = parse_ist(h["send_window"]["not_before"]) - timedelta(days=1)
    r = c.get("/surveys/due", params={"at": fmt_ist(before)})
    assert r.status_code == 200 and r.json()["count"] == 0


def test_due_lists_the_survey_inside_its_window_and_send_hours():
    insight, _ = _first_survey_insight(_non_high)
    c = client()
    h = _post_and_window(c, insight)
    at = parse_ist(h["send_window"]["not_before"]).replace(hour=9, minute=0, second=0)
    r = c.get("/surveys/due", params={"at": fmt_ist(at)})
    body = r.json()
    assert r.status_code == 200 and body["count"] >= 1
    assert h["handoff_id"] in [d["handoff_id"] for d in body["handoffs"]]
    assert body["as_of"] == fmt_ist(at)


def test_due_returns_full_schema_valid_handoffs():
    insight, _ = _first_survey_insight(_non_high)
    c = client()
    h = _post_and_window(c, insight)
    at = parse_ist(h["send_window"]["not_before"]).replace(hour=9, minute=0, second=0)
    body = c.get("/surveys/due", params={"at": fmt_ist(at)}).json()
    assert body["count"] >= 1
    for entry in body["handoffs"]:
        assert is_valid("schedule_handoff", entry), errors("schedule_handoff", entry)
    # The returned object is the stored hand-off itself, unchanged.
    returned = next(e for e in body["handoffs"] if e["handoff_id"] == h["handoff_id"])
    assert returned == h


def test_due_excludes_outside_send_hours():
    insight, _ = _first_survey_insight(_non_high)
    c = client()
    h = _post_and_window(c, insight)
    # 05:00 is before the 07:00 send-hours start: window is open but it is not sendable.
    at = parse_ist(h["send_window"]["not_before"]).replace(hour=5, minute=0, second=0)
    r = c.get("/surveys/due", params={"at": fmt_ist(at)})
    assert r.status_code == 200 and r.json()["count"] == 0


def test_due_excludes_after_expiry():
    insight, _ = _first_survey_insight(_non_high)
    c = client()
    h = _post_and_window(c, insight)
    after = parse_ist(h["expires_at"]) + timedelta(days=1)
    r = c.get("/surveys/due", params={"at": fmt_ist(after)})
    assert r.status_code == 200 and r.json()["count"] == 0


def test_due_bad_or_missing_offset_is_422():
    c = client()
    assert c.get("/surveys/due", params={"at": "not-a-date"}).status_code == 422
    assert c.get("/surveys/due", params={"at": "2026-12-06T07:00:00"}).status_code == 422  # no offset
    assert c.get("/surveys/due", params={"limit": -1}).status_code == 422


def test_due_accepts_both_raw_and_percent_encoded_plus():
    insight, _ = _first_survey_insight(_non_high)
    c = client()
    h = _post_and_window(c, insight)
    at = fmt_ist(parse_ist(h["send_window"]["not_before"]).replace(hour=9, minute=0, second=0))
    raw = c.get(f"/surveys/due?at={at}")  # literal + (decodes to space)
    enc = c.get("/surveys/due?at=" + urllib.parse.quote(at, safe=""))  # %2B05:30
    assert raw.status_code == enc.status_code == 200
    assert raw.json() == enc.json()


def test_due_limit_caps_the_list():
    c = client()
    posted = []
    for i in MOCK:
        r = run_insight(i)
        if "handoff" in r and r["handoff"]["priority"] != "high":
            c.post("/surveys", json=i)
            posted.append(r["handoff"])
        if len(posted) >= 3:
            break
    at = max(parse_ist(h["send_window"]["not_before"]) for h in posted).replace(hour=9)
    full = c.get("/surveys/due", params={"at": fmt_ist(at)}).json()
    if full["count"] >= 2:
        one = c.get("/surveys/due", params={"at": fmt_ist(at), "limit": 1}).json()
        assert one["count"] == 1


# --- GET /surveys/due: read-only, and matches the broadcaster ----------------------------


def test_due_is_read_only():
    insight, _ = _first_survey_insight(_non_high)
    c = client()
    h = _post_and_window(c, insight)
    at = fmt_ist(parse_ist(h["send_window"]["not_before"]).replace(hour=9, minute=0, second=0))
    before = c.app.state.store.counts()
    a = c.get("/surveys/due", params={"at": at}).json()
    b = c.get("/surveys/due", params={"at": at}).json()
    assert a == b  # two GETs are identical
    assert c.app.state.store.counts() == before  # nothing was written


def test_due_matches_what_the_broadcaster_would_send():
    c = client()
    posted = []
    for i in MOCK:
        r = run_insight(i)
        if "handoff" in r:
            c.post("/surveys", json=i)
            posted.append(r["handoff"])
        if len(posted) >= 8:
            break
    at = max(parse_ist(h["send_window"]["not_before"]) for h in posted).replace(hour=9)
    at_str = fmt_ist(at)
    due_ids = sorted(d["handoff_id"] for d in c.get("/surveys/due", params={"at": at_str}).json()["handoffs"])
    # What the broadcaster would really SEND now, on a copy of the stored queue.
    bc = Broadcaster(SimClock(at_str))
    bc.queue_all(copy.deepcopy(c.app.state.store.due(at_str)))
    from mel.writer import RELEVANCE_THRESHOLD

    sent_ids = sorted(
        b.handoff["handoff_id"] for b in bc.broadcast_due(relevance_threshold=RELEVANCE_THRESHOLD) if b.action == "sent"
    )
    assert due_ids == sent_ids


# --- the FarmerChat answer path ---------------------------------------------------------


def _post_survey(c, predicate=None):
    insight, _ = _first_survey_insight(predicate)
    h = c.post("/surveys", json=insight).json()["handoff"]
    return insight, h, h["farmerchat_flow"]["flow_id"]


def _answer(h, case="completed", channel=None):
    """A schema-valid answer record for this hand-off, from P3's simulator."""
    return simulate(h["survey"], channel or h["channel_order"][0]["channel"], case, seed=0)


def test_get_flow_returns_the_registered_survey():
    c = client()
    _, h, flow_id = _post_survey(c)
    r = c.get(f"/v1/surveys/{flow_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["flow"] == h["farmerchat_flow"]
    assert body["handoff"]["survey"]["survey_id"] == h["survey"]["survey_id"]
    assert body["admission"]["decision"] in ("sent", "moved", "merged")
    assert c.get("/v1/surveys/no-such-flow").status_code == 404


def test_response_is_stored_once_and_a_retry_is_200():
    c = client()
    _, h, flow_id = _post_survey(c)
    rec = _answer(h)
    assert is_valid("response", rec)
    r = c.post(f"/v1/surveys/{flow_id}/responses", json=rec)
    assert r.status_code == 201
    body = r.json()
    assert body["response_key"] == rec["response_key"] and body["stored"] is True
    assert body["status"] == "completed" and body["opted_out"] is False
    again = c.post(f"/v1/surveys/{flow_id}/responses", json=rec)
    assert again.status_code == 200 and again.json()["stored"] is False
    assert c.app.state.store.counts()["responses"] == 1


def test_opt_out_answer_blocks_the_farmer_from_then_on():
    base, second = _collision_pair()
    c = client()
    h = c.post("/surveys", json=base).json()["handoff"]
    flow_id = h["farmerchat_flow"]["flow_id"]
    rec = _answer(h, "farmer_opted_out")
    assert rec["failure_code"] == "farmer_opted_out"
    r = c.post(f"/v1/surveys/{flow_id}/responses", json=rec)
    assert r.status_code == 201 and r.json()["opted_out"] is True
    # The queued survey is no longer due, and the farmer's next survey is admitted as opted_out.
    at = parse_ist(h["send_window"]["not_before"]).replace(hour=9, minute=0, second=0)
    assert h["handoff_id"] not in [
        d["handoff_id"] for d in c.get("/surveys/due", params={"at": fmt_ist(at)}).json()["handoffs"]
    ]
    assert c.post("/surveys", json=second).json()["admission"]["decision"] == "opted_out"


def test_negative_outcome_lands_in_the_follow_up_queue():
    def has_follow_up(i, r):
        return any(o.get("follow_up") for s in r["surveys"].values() for q in s["items"] for o in q.get("options", []))

    c = client()
    _, h, flow_id = _post_survey(c, has_follow_up)
    rec = _answer(h, "negative_outcome")
    assert rec["needs_follow_up"] is True
    r = c.post(f"/v1/surveys/{flow_id}/responses", json=rec)
    assert r.status_code == 201 and r.json()["needs_follow_up"] is True
    assert r.json()["follow_up_reasons"] == rec["follow_up_reasons"]
    q = c.get("/follow-ups").json()
    assert q["count"] == 1 and q["responses"][0]["response_key"] == rec["response_key"]
    assert c.get("/follow-ups", params={"limit": 0}).json()["count"] == 0
    assert c.get("/follow-ups", params={"limit": -1}).status_code == 422


def test_response_errors():
    c = client()
    _, h, flow_id = _post_survey(c)
    rec = _answer(h)
    assert c.post("/v1/surveys/no-such-flow/responses", json=rec).status_code == 404
    assert c.post(f"/v1/surveys/{flow_id}/responses", json={"response_key": "x"}).status_code == 422
    assert c.post(f"/v1/surveys/{flow_id}/responses", json=[rec]).status_code == 422
    wrong = dict(rec, survey_id="S-00000")
    r = c.post(f"/v1/surveys/{flow_id}/responses", json=wrong)
    assert r.status_code == 422 and "survey_id" in r.json()["detail"]
    assert c.app.state.store.counts()["responses"] == 0


# --- Hindi returned unescaped -----------------------------------------------------------


def test_hindi_text_is_returned_unescaped():
    insight, _ = _first_survey_insight(lambda i, r: "hi-IN" in r["surveys"])
    r = client().post("/surveys", json=insight)
    assert r.status_code == 201
    assert "\\u0900" not in r.text and "\\u09" not in r.text
    assert any("ऀ" <= ch <= "ॿ" for ch in r.text)
