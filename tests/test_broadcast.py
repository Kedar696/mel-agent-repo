"""P3: the simulated clock (SimClock) and the broadcaster (Broadcaster / broadcast_due).

These are the "alarm clock" pieces the demo's Season screen drives (docs/TEAM.md). They
are deterministic: time only moves when advance() is called, and broadcast_due() acts only
when called. The checklist (item 2) pins the behaviour these tests lock in.
"""
import copy
from datetime import datetime, timedelta, timezone

import pytest

from mel.data import load_scenario, errors
from mel.schedule import (
    SimClock, Broadcaster, Broadcast,
    build_handoff, quality_failures, passes_quality, within_send_hours,
)


# --------------------------------------------------------------------------- helpers
def _clear_handoff(scenario="1-mustard-aphid-spray"):
    """A hand-off whose survey has a passing self_eval, so the quality gate is not the thing
    under test unless a test deliberately spoils it."""
    s = load_scenario(scenario)
    h = build_handoff(s["insight"], s["surveys"]["hi-IN"])
    h["survey"]["self_eval"] = {
        "schema_valid": True, "relevance_score": 0.8,
        "gives_new_advice": False, "asks_personal_info": False,
    }
    return h


def _at(ts: str) -> SimClock:
    return SimClock(ts)


# =========================================================================== SimClock
def test_clock_now_is_deterministic_and_ist():
    c = _at("2026-11-04T07:00:00+05:30")
    assert c.now() == c.now()  # no wall-clock drift between calls
    assert c.now_ist() == "2026-11-04T07:00:00+05:30"
    assert c.now().utcoffset() == timedelta(hours=5, minutes=30)


def test_clock_advance_moves_forward_whole_days():
    c = _at("2026-11-04T07:00:00+05:30")
    after = c.advance(7)
    assert c.now_ist() == "2026-11-11T07:00:00+05:30"
    assert after == c.now()
    c.advance(0)  # zero days is allowed (a no-op step)
    assert c.now_ist() == "2026-11-11T07:00:00+05:30"


def test_clock_advance_sequence_is_reproducible():
    a = _at("2026-11-04T07:00:00+05:30")
    b = _at("2026-11-04T07:00:00+05:30")
    for d in (1, 2, 3, 7):
        a.advance(d)
        b.advance(d)
    assert a.now_ist() == b.now_ist()


def test_clock_rejects_negative_advance():
    c = _at("2026-11-04T07:00:00+05:30")
    with pytest.raises(ValueError):
        c.advance(-1)
    assert c.now_ist() == "2026-11-04T07:00:00+05:30"  # unchanged after a rejected move


def test_clock_rejects_non_integer_advance():
    c = _at("2026-11-04T07:00:00+05:30")
    for bad in (1.5, "3", None):
        with pytest.raises(TypeError):
            c.advance(bad)
    # bool is an int subclass; it must not quietly mean 1
    with pytest.raises(TypeError):
        c.advance(True)


def test_clock_rejects_naive_start():
    with pytest.raises(ValueError):
        SimClock(datetime(2026, 11, 4, 7, 0, 0))  # no tzinfo -> ambiguous
    with pytest.raises(ValueError):
        SimClock("2026-11-04T07:00:00")  # no offset in the string


def test_clock_accepts_tzaware_datetime_and_normalises_to_ist():
    utc = datetime(2026, 11, 4, 1, 30, 0, tzinfo=timezone.utc)  # 07:00 IST
    c = SimClock(utc)
    assert c.now_ist() == "2026-11-04T07:00:00+05:30"


# ============================================================ quality gate (P4 threshold)
def _survey_with(**self_eval):
    """A real, guard-clean survey with the given self_eval. (The gate also runs P4's
    check_survey, so a bare {"self_eval": ...} dict with no items is correctly rejected.)"""
    s = copy.deepcopy(load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"])
    base = {"schema_valid": True, "relevance_score": 0.8,
            "gives_new_advice": False, "asks_personal_info": False}
    base.update(self_eval)
    s["self_eval"] = base
    return s


def test_quality_gate_passes_a_clean_survey():
    assert quality_failures(_survey_with(), relevance_threshold=0.5) == []
    assert passes_quality(_survey_with(), relevance_threshold=0.5)


def test_quality_gate_threshold_is_inclusive():
    # equal to the threshold is eligible; just below is not
    assert quality_failures(_survey_with(relevance_score=0.5), relevance_threshold=0.5) == []
    assert quality_failures(_survey_with(relevance_score=0.49), relevance_threshold=0.5)


def test_quality_gate_rejects_bad_self_eval_flags():
    assert quality_failures(_survey_with(schema_valid=False), relevance_threshold=0.5)
    assert quality_failures(_survey_with(gives_new_advice=True), relevance_threshold=0.5)
    assert quality_failures(_survey_with(asks_personal_info=True), relevance_threshold=0.5)


def test_quality_gate_rejects_missing_or_out_of_range_score():
    assert quality_failures(_survey_with(relevance_score=None), relevance_threshold=0.5)
    assert quality_failures({"self_eval": {"schema_valid": True, "gives_new_advice": False,
                                           "asks_personal_info": False}}, relevance_threshold=0.5)
    assert quality_failures(_survey_with(relevance_score=1.5), relevance_threshold=0.5)


def test_quality_gate_rejects_survey_without_self_eval():
    assert quality_failures({}, relevance_threshold=0.5)


def test_quality_gate_threshold_must_be_explicit_and_valid():
    # the caller must supply a real threshold; P3 invents none
    with pytest.raises(TypeError):
        quality_failures(_survey_with(), relevance_threshold="high")
    with pytest.raises(ValueError):
        quality_failures(_survey_with(), relevance_threshold=1.5)


# ===================================================================== send hours
def test_within_send_hours_is_inclusive_of_bounds():
    sh = {"from": "07:00", "to": "19:00"}
    assert within_send_hours(SimClock("2026-12-06T07:00:00+05:30").now(), sh)
    assert within_send_hours(SimClock("2026-12-06T19:00:00+05:30").now(), sh)
    assert not within_send_hours(SimClock("2026-12-06T06:59:00+05:30").now(), sh)
    assert not within_send_hours(SimClock("2026-12-06T19:01:00+05:30").now(), sh)


# ===================================================================== Broadcaster
def test_queue_orders_by_window_start_not_insertion():
    late = _clear_handoff()
    early = copy.deepcopy(late)
    early["handoff_id"] = "H-EARLY"
    early["send_window"]["not_before"] = "2026-11-01T07:00:00+05:30"
    bc = Broadcaster()
    bc.queue(late)   # inserted first, but opens later
    bc.queue(early)  # inserted second, but opens earlier
    assert [h["handoff_id"] for h in bc.pending] == ["H-EARLY", late["handoff_id"]]


def test_queue_is_idempotent_on_handoff_id():
    h = _clear_handoff()
    bc = Broadcaster()
    bc.queue(h)
    bc.queue(copy.deepcopy(h))  # same id again -> not a second copy
    assert len(bc) == 1


def test_broadcast_due_holds_before_window_opens():
    h = _clear_handoff()
    bc = Broadcaster(); bc.queue(h)
    res = bc.broadcast_due(_at("2026-12-01T07:00:00+05:30"), relevance_threshold=0.5)
    assert [b.action for b in res] == ["pending"]
    assert len(bc) == 1  # stays queued


def test_broadcast_due_sends_when_due_and_in_hours():
    h = _clear_handoff()  # window opens 2026-12-06T07:00
    bc = Broadcaster(); bc.queue(h)
    res = bc.broadcast_due(_at("2026-12-06T07:00:00+05:30"), relevance_threshold=0.5)
    assert res == [Broadcast("sent", h)]
    assert len(bc) == 0  # sent work leaves the queue


def test_broadcast_due_waits_outside_send_hours():
    h = _clear_handoff()
    bc = Broadcaster(); bc.queue(h)
    res = bc.broadcast_due(_at("2026-12-06T22:00:00+05:30"), relevance_threshold=0.5)
    assert res[0].action == "waiting"
    assert len(bc) == 1  # held for a later trigger


def test_broadcast_due_drops_expired_work():
    h = _clear_handoff()  # expires 2026-12-11T19:00
    bc = Broadcaster(); bc.queue(h)
    res = bc.broadcast_due(_at("2026-12-20T07:00:00+05:30"), relevance_threshold=0.5)
    assert res[0].action == "expired"
    assert len(bc) == 0  # dropped, never sent


def test_broadcast_due_rejects_survey_below_threshold():
    h = _clear_handoff()
    h["survey"]["self_eval"]["relevance_score"] = 0.3
    bc = Broadcaster(); bc.queue(h)
    res = bc.broadcast_due(_at("2026-12-06T07:00:00+05:30"), relevance_threshold=0.5)
    assert res[0].action == "rejected"
    assert len(bc) == 0  # a failing survey is not held, it is dropped


def test_broadcast_due_sends_at_exact_threshold():
    h = _clear_handoff()
    h["survey"]["self_eval"]["relevance_score"] = 0.5
    bc = Broadcaster(); bc.queue(h)
    res = bc.broadcast_due(_at("2026-12-06T07:00:00+05:30"), relevance_threshold=0.5)
    assert res[0].action == "sent"


def test_broadcast_due_requires_explicit_threshold():
    h = _clear_handoff()
    bc = Broadcaster(); bc.queue(h)
    with pytest.raises(TypeError):
        bc.broadcast_due(_at("2026-12-06T07:00:00+05:30"))  # threshold is keyword-only, required


def test_season_walk_is_deterministic_and_eventually_sends():
    """Advancing the clock day by day: the hand-off is pending until its window opens, then
    sent. Two independent walks produce the same action sequence (determinism)."""
    def walk():
        h = _clear_handoff()
        bc = Broadcaster(); bc.queue(h)
        clock = _at("2026-12-01T07:00:00+05:30")
        actions = []
        for _ in range(10):
            res = bc.broadcast_due(clock, relevance_threshold=0.5)
            actions.append(res[0].action if res else "empty")
            if not bc:  # nothing left to send
                break
            clock.advance(1)
        return actions

    a, b = walk(), walk()
    assert a == b
    assert a[-1] == "sent" and "pending" in a


def test_broadcaster_drives_real_pipeline_handoffs():
    """End-to-end: feed the broadcaster hand-offs the real pipeline built (surveys carry the
    self_eval P4 writes) and walk the season. Every hand-off ends sent, expired or rejected
    -- nothing is stuck pending forever -- and every 'sent' survey is schema-valid."""
    from mel.pipeline import run_insight
    from mel.data import load_insights

    handoffs = []
    for ins in load_insights()[:300]:
        out = run_insight(ins)
        if "handoff" in out:
            handoffs.append(out["handoff"])
    assert handoffs, "expected the pipeline to produce at least one hand-off"

    bc = Broadcaster()
    bc.queue_all(handoffs)
    # Start before any window opens and walk a generous span of the season.
    clock = _at("2026-11-01T07:00:00+05:30")
    sent = []
    terminal = {"sent": 0, "expired": 0, "rejected": 0}
    for _ in range(220):  # ~7 months of daily steps covers the rabi season
        for b in bc.broadcast_due(clock, relevance_threshold=0.5):
            if b.action in terminal:
                terminal[b.action] += 1
            if b.action == "sent":
                sent.append(b.handoff)
        if not bc:
            break
        clock.advance(1)

    assert len(bc) == 0, "every queued hand-off should reach a terminal state in the walk"
    assert sum(terminal.values()) == len(handoffs)
    assert sent, "at least one hand-off should have been sent during the season"
    for h in sent:
        assert not errors("survey", h["survey"]), h["handoff_id"]


def test_due_now_is_readonly_view():
    h = _clear_handoff()
    bc = Broadcaster(); bc.queue(h)
    before = _at("2026-12-01T07:00:00+05:30")
    assert bc.due_now(before) == []        # window not open
    opened = _at("2026-12-06T07:00:00+05:30")
    assert [x["handoff_id"] for x in bc.due_now(opened)] == [h["handoff_id"]]
    assert len(bc) == 1  # due_now does not remove anything


def test_quality_cache_rechecks_a_changed_survey():
    """P5's cache in quality_failures must never hide a change: same content -> same answer, edited -> re-checked."""
    import copy
    from mel.schedule.broadcast import quality_failures
    from mel.data import load_insights
    from mel.pipeline import run_pipeline
    h = next(o["handoff"] for o in run_pipeline(load_insights(None)).outputs if "handoff" in o)
    s = copy.deepcopy(h["survey"])
    assert quality_failures(s, 0.0) == quality_failures(copy.deepcopy(s), 0.0) == []
    s["items"][0]["options"][0]["label"] = "x" * 40          # now too long for a tap label
    assert any("label_too_long" in f for f in quality_failures(s, 0.0))
    s["self_eval"]["relevance_score"] = 0.1
    assert quality_failures(s, 0.5) != quality_failures(s, 0.0)   # threshold is part of the key
