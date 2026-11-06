"""P1: mel.store, the API's database (SQLite here; the same SQL runs on RDS Postgres)."""
from datetime import timedelta

import pytest

from mel.data import load_insights
from mel.pipeline import run_insight
from mel.simulator import simulate
from mel.store import Store
from mel.timing import fmt_ist, parse_ist


def _handoff():
    for i in load_insights():
        r = run_insight(i)
        if "handoff" in r:
            return r["handoff"]
    raise AssertionError("no survey in the mock data")


def test_handoff_round_trip_and_flow_lookup():
    s, h = Store("sqlite://"), _handoff()
    assert s.handoff(h["handoff_id"]) is None
    s.put_handoff(h, "sent")
    assert s.handoff(h["handoff_id"]) == (h, "sent", "")
    assert s.handoff_by_flow(h["farmerchat_flow"]["flow_id"])[0] == h
    assert s.farmer_handoffs(h["survey"]["farmer_id"]) == [h]
    s.put_handoff(h, "skipped", "over the cap")                     # an upsert replaces the decision
    assert s.handoff(h["handoff_id"])[1:] == ("skipped", "over the cap")
    assert s.farmer_handoffs(h["survey"]["farmer_id"]) == []        # skipped holds no weekly slot
    assert s.counts()["handoffs"] == 1


def test_due_filters_on_window_and_expiry():
    s, h = Store("sqlite://"), _handoff()
    s.put_handoff(h, "moved", "moved to a free day")
    opens = parse_ist(h["send_window"]["not_before"])
    assert s.due(fmt_ist(opens - timedelta(days=1))) == []
    assert s.due(fmt_ist(opens)) == [h]
    assert s.due(fmt_ist(parse_ist(h["expires_at"]) + timedelta(days=1))) == []


def test_responses_are_stored_once_and_feed_follow_ups_and_opt_outs():
    s, h = Store("sqlite://"), _handoff()
    flow = h["farmerchat_flow"]["flow_id"]
    rec = simulate(h["survey"], h["channel_order"][0]["channel"], "completed", seed=0)
    assert s.put_response(rec, flow) is True
    assert s.put_response(rec, flow) is False                      # a retry changes nothing
    assert s.response(rec["response_key"]) == rec
    assert s.follow_ups() == []
    flagged = dict(rec, response_key="rk-flagged", needs_follow_up=True)
    assert s.put_response(flagged, flow) is True
    assert [r["response_key"] for r in s.follow_ups()] == ["rk-flagged"]
    assert s.follow_ups(limit=0) == []
    fid = h["survey"]["farmer_id"]
    assert s.opted_out(fid) is False
    s.opt_out(fid, rec["response_key"], rec["recorded_at"])
    s.opt_out(fid, "rk-later", rec["recorded_at"])                   # the first opt-out stands
    assert s.opted_out(fid) is True and s.counts()["opt_outs"] == 1


def test_postgres_gets_its_own_placeholder():
    s = Store.__new__(Store)
    s._param = "%s"
    assert s._sql("a = ? AND b IN (?, ?)") == "a = %s AND b IN (%s, %s)"


def test_unknown_engine_is_refused():
    with pytest.raises(ValueError):
        Store("mysql://nope")
