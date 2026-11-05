"""P1: the REST API (mel/api). A fresh app (and so a fresh in-memory scheduler) per test.

Covers POST /surveys (survey / no-survey / junk / non-object body / schema validity /
repeated POST / a second non-high survey within 7 days) and GET /surveys/due (window timing,
send hours, expiry, read-only, the raw vs percent-encoded `+` in `at`, and a comparison with
what the broadcaster would really send). Plus /healthz and Hindi returned unescaped.
"""
import copy
import urllib.parse
from datetime import timedelta

import pytest

from mel.data import is_valid, load_insights
from mel.pipeline import run_insight
from mel.schedule.broadcast import Broadcaster
from mel.schedule.clock import SimClock
from mel.timing import fmt_ist, parse_ist

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from mel.api.app import create_app  # noqa: E402

MOCK = load_insights()


def client():
    """A fresh app -> a fresh SeasonScheduler -> empty cap/opt-out/queue, per test."""
    return TestClient(create_app())


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


# --- /healthz ---------------------------------------------------------------------------

def test_healthz():
    r = client().get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


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
    # Input the pipeline treats as junk -> the R1 no-survey result, 200 (not an error).
    r = client().post("/surveys", json={"insight_id": "I-9", "farmer_id": "F-1",
                                        "quality_flag": "junk"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "no_survey" and body["decision"]["rule"] == "R1"


def test_post_non_object_body_is_422():
    c = client()
    assert c.post("/surveys", content="[1,2,3]",
                  headers={"content-type": "application/json"}).status_code == 422
    assert c.post("/surveys", content="\"hello\"",
                  headers={"content-type": "application/json"}).status_code == 422
    assert c.post("/surveys", content="not json",
                  headers={"content-type": "application/json"}).status_code == 422


# --- schema validity of what comes back -------------------------------------------------

def test_returned_survey_and_handoff_pass_the_schemas():
    insight, _ = _first_survey_insight()
    body = client().post("/surveys", json=insight).json()
    for lang, s in body["surveys"].items():
        assert is_valid("survey", s), (lang, s)
        assert not any(k.startswith("_") for k in s)   # _-prefixed keys stripped
    assert is_valid("schedule_handoff", body["handoff"])


# --- repeated POST / the weekly cap -----------------------------------------------------

def test_repeated_post_takes_no_second_weekly_slot():
    insight, _ = _first_survey_insight()
    c = client()
    first = c.post("/surveys", json=insight).json()["admission"]
    second = c.post("/surveys", json=insight).json()["admission"]
    assert first == second                               # same decision, idempotent
    sched = c.app.state.scheduler
    # One survey queued, counted once: the repeat added no slot.
    assert len(sched.broadcaster) == 1
    assert sum(sched.admit_counts.values()) == 1


def _collision_pair():
    """A base non-high, non-exempt survey insight plus a near-copy for the same farmer a day
    later, so the second one hits the weekly cap."""
    base, _ = _first_survey_insight(
        lambda i, r: r["handoff"]["priority"] != "high"
        and not r["handoff"]["frequency_cap"]["exempt"])
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


# --- GET /surveys/due: timing ------------------------------------------------------------

def _post_and_window(c, insight):
    body = c.post("/surveys", json=insight).json()
    return body["handoff"]


def test_due_is_empty_before_the_window_opens():
    insight, _ = _first_survey_insight(
        lambda i, r: r["handoff"]["priority"] != "high")
    c = client()
    h = _post_and_window(c, insight)
    before = parse_ist(h["send_window"]["not_before"]) - timedelta(days=1)
    r = c.get("/surveys/due", params={"at": fmt_ist(before)})
    assert r.status_code == 200 and r.json()["count"] == 0


def test_due_lists_the_survey_inside_its_window_and_send_hours():
    insight, _ = _first_survey_insight(
        lambda i, r: r["handoff"]["priority"] != "high")
    c = client()
    h = _post_and_window(c, insight)
    at = parse_ist(h["send_window"]["not_before"]).replace(hour=9, minute=0, second=0)
    r = c.get("/surveys/due", params={"at": fmt_ist(at)})
    body = r.json()
    assert r.status_code == 200 and body["count"] >= 1
    assert h["handoff_id"] in [d["handoff_id"] for d in body["handoffs"]]
    assert body["as_of"] == fmt_ist(at)


def test_due_excludes_outside_send_hours():
    insight, _ = _first_survey_insight(
        lambda i, r: r["handoff"]["priority"] != "high")
    c = client()
    h = _post_and_window(c, insight)
    # 05:00 is before the 07:00 send-hours start: window is open but it is not sendable.
    at = parse_ist(h["send_window"]["not_before"]).replace(hour=5, minute=0, second=0)
    r = c.get("/surveys/due", params={"at": fmt_ist(at)})
    assert r.status_code == 200 and r.json()["count"] == 0


def test_due_excludes_after_expiry():
    insight, _ = _first_survey_insight(
        lambda i, r: r["handoff"]["priority"] != "high")
    c = client()
    h = _post_and_window(c, insight)
    after = parse_ist(h["expires_at"]) + timedelta(days=1)
    r = c.get("/surveys/due", params={"at": fmt_ist(after)})
    assert r.status_code == 200 and r.json()["count"] == 0


def test_due_bad_or_missing_offset_is_422():
    c = client()
    assert c.get("/surveys/due", params={"at": "not-a-date"}).status_code == 422
    # No timezone offset -> parse_ist raises -> 422.
    assert c.get("/surveys/due", params={"at": "2026-12-06T07:00:00"}).status_code == 422
    assert c.get("/surveys/due", params={"limit": -1}).status_code == 422


def test_due_accepts_both_raw_and_percent_encoded_plus():
    insight, _ = _first_survey_insight(
        lambda i, r: r["handoff"]["priority"] != "high")
    c = client()
    h = _post_and_window(c, insight)
    at = fmt_ist(parse_ist(h["send_window"]["not_before"]).replace(hour=9, minute=0, second=0))
    raw = c.get(f"/surveys/due?at={at}")                               # literal + (decodes to space)
    enc = c.get("/surveys/due?at=" + urllib.parse.quote(at, safe=""))  # %2B05:30
    assert raw.status_code == enc.status_code == 200
    assert raw.json() == enc.json()


def test_due_limit_caps_the_list():
    c = client()
    # Post several non-high surveys for different farmers so more than one is due at a time.
    posted = []
    for i in MOCK:
        r = run_insight(i)
        if "handoff" in r and r["handoff"]["priority"] != "high":
            c.post("/surveys", json=i)
            posted.append(r["handoff"])
        if len(posted) >= 3:
            break
    # Pick an instant where at least two windows are open (late in the season at 09:00).
    at = max(parse_ist(h["send_window"]["not_before"]) for h in posted).replace(hour=9)
    full = c.get("/surveys/due", params={"at": fmt_ist(at)}).json()
    if full["count"] >= 2:
        one = c.get("/surveys/due", params={"at": fmt_ist(at), "limit": 1}).json()
        assert one["count"] == 1


# --- GET /surveys/due: read-only, and matches the broadcaster ----------------------------

def test_due_is_read_only():
    insight, _ = _first_survey_insight(
        lambda i, r: r["handoff"]["priority"] != "high")
    c = client()
    h = _post_and_window(c, insight)
    at = fmt_ist(parse_ist(h["send_window"]["not_before"]).replace(hour=9, minute=0, second=0))
    sched = c.app.state.scheduler
    before = len(sched.broadcaster)
    a = c.get("/surveys/due", params={"at": at}).json()
    b = c.get("/surveys/due", params={"at": at}).json()
    assert a == b                                   # two GETs are identical
    assert len(sched.broadcaster) == before         # the queue did not change


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
    sched = c.app.state.scheduler
    at = max(parse_ist(h["send_window"]["not_before"]) for h in posted).replace(hour=9)
    at_str = fmt_ist(at)
    due_ids = sorted(d["handoff_id"] for d in
                     c.get("/surveys/due", params={"at": at_str}).json()["handoffs"])
    # What the broadcaster would really SEND now, on a copy of the live queue.
    bc = Broadcaster(SimClock(at_str))
    bc.queue_all([copy.deepcopy(h) for h in sched.broadcaster.pending])
    sent_ids = sorted(b.handoff["handoff_id"] for b in
                      bc.broadcast_due(relevance_threshold=sched.relevance_threshold)
                      if b.action == "sent")
    assert due_ids == sent_ids


# --- Hindi returned unescaped -----------------------------------------------------------

def test_hindi_text_is_returned_unescaped():
    # A Hindi-language insight yields a hi-IN survey; the raw bytes must carry Devanagari,
    # not \uXXXX escapes.
    insight, result = _first_survey_insight(
        lambda i, r: "hi-IN" in r["surveys"])
    r = client().post("/surveys", json=insight)
    assert r.status_code == 201
    assert "\\u0900" not in r.text and "\\u09" not in r.text
    # At least one Devanagari character is present in the raw response text.
    assert any("\u0900" <= ch <= "\u097f" for ch in r.text)
