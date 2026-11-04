"""P3: the season driver -- scheduler and broadcaster share one SimClock, and every
scheduled step has a manual trigger.

Requirement under test:
  "The scheduler and broadcaster read time from a shared simulated clock so the demo can
   move through the November to March season in minutes. Every scheduled step also has a
   manual trigger."

These tests prove: (1) scheduler and broadcaster observe the SAME clock instance and the
system clock is never consulted; (2) advancing that clock changes which steps are due;
(3) each scheduled step can be fired by hand. Cases covered: not-yet-due, due, expired,
season-boundary, and repeated-trigger.
"""
import copy
from datetime import datetime, timedelta

import pytest

from mel.config import IST, rules
from mel.data import load_scenario, errors
from mel.schedule import SeasonScheduler, StepResult, build_handoff
from mel.timing import parse_ist, fmt_ist


THRESHOLD = 0.5


def _clear_handoff(scenario="1-mustard-aphid-spray"):
    s = load_scenario(scenario)
    h = build_handoff(s["insight"], s["surveys"]["hi-IN"])
    h["survey"]["self_eval"] = {
        "schema_valid": True, "relevance_score": 0.8,
        "gives_new_advice": False, "asks_personal_info": False,
    }
    return h


def _window_open_ist(h) -> str:
    return h["send_window"]["not_before"]


# ====================================================== shared clock (the core claim)
def test_scheduler_and_broadcaster_share_one_clock_instance():
    sched = SeasonScheduler("2026-11-01T07:00:00+05:30", relevance_threshold=THRESHOLD)
    # Same object, not just equal values.
    assert sched.clock is sched.broadcaster.clock
    # Advancing via the scheduler is seen by the broadcaster's clock immediately.
    sched.advance(10)
    assert sched.broadcaster.clock.now_ist() == sched.now_ist()
    assert sched.broadcaster.clock.now() is sched.clock.now()


def test_no_system_clock_used_for_due_decisions():
    """The due decision depends only on the SimClock, not wall-clock time: a hand-off whose
    window opened 'in the past' relative to the SimClock's start is due regardless of today's
    real date."""
    h = _clear_handoff()
    # Start the sim clock exactly at the window open; the real 'now' is irrelevant.
    sched = SeasonScheduler(_window_open_ist(h), relevance_threshold=THRESHOLD)
    sched.admit_all([h])
    r = sched.step()
    assert r.kind == "sent" and r.channel == h["channel_order"][0]["channel"]


# ====================================================== advancing changes the due set
def test_advancing_clock_changes_which_steps_are_due():
    h = _clear_handoff()
    sched = SeasonScheduler("2026-11-01T07:00:00+05:30", relevance_threshold=THRESHOLD)
    sched.admit_all([h])

    # Before the window opens: nothing due, hand-off stays queued.
    assert sched.broadcaster.due_now() == []
    assert sched.step().kind == "nothing"
    assert len(sched.broadcaster) == 1

    # Advance to the window open: now it is due and a step sends.
    opens = parse_ist(_window_open_ist(h))
    while sched.now() < opens:
        sched.advance(1)
    assert [x["handoff_id"] for x in sched.broadcaster.due_now()] == [h["handoff_id"]]
    assert sched.step().kind == "sent"


def test_two_handoffs_become_due_as_the_clock_moves():
    early = _clear_handoff()
    late = copy.deepcopy(early)
    late["handoff_id"] = "H-LATE"
    # Shift the late one's whole window (and expiry) two weeks later.
    shift = timedelta(days=14)
    nb = parse_ist(early["send_window"]["not_before"]) + shift
    na = parse_ist(early["send_window"]["not_after"]) + shift
    late["send_window"] = {"not_before": fmt_ist(nb), "not_after": fmt_ist(na)}
    late["survey"]["send_window"] = dict(late["send_window"])
    late["expires_at"] = fmt_ist(parse_ist(early["expires_at"]) + shift)
    late["survey"]["source_insight_ids"] = ["I-700000"]  # avoid cap-merge with early

    sched = SeasonScheduler("2026-11-01T07:00:00+05:30", relevance_threshold=THRESHOLD)
    sched.admit_all([early, late])

    # At the early window: only the early one is due.
    while sched.now() < parse_ist(early["send_window"]["not_before"]):
        sched.advance(1)
    due_ids = [x["handoff_id"] for x in sched.broadcaster.due_now()]
    assert early["handoff_id"] in due_ids and "H-LATE" not in due_ids

    # Fire the early step, then advance to the late window: now the late one is due.
    assert sched.step().kind == "sent"
    while sched.now() < parse_ist(late["send_window"]["not_before"]):
        sched.advance(1)
    assert [x["handoff_id"] for x in sched.broadcaster.due_now()] == ["H-LATE"]


# ====================================================== per-step manual trigger
def test_each_scheduled_step_is_manually_triggerable():
    """A hand-off whose first channel falls back (dead push) is walked channel by channel,
    one manual trigger per channel. Stepping matches what simulate_handoff() would do in a
    single call -- the per-step trigger is just that walk, paused between steps."""
    from mel.simulator import simulate_handoff
    h = _clear_handoff("1-mustard-aphid-spray")  # channel order starts with app, then whatsapp
    assert [c["channel"] for c in h["channel_order"]][:2] == ["app", "whatsapp"]
    # app_push_dead: app fails with fall_back_to_next_channel, then the next channel completes.
    sched = SeasonScheduler(_window_open_ist(h), relevance_threshold=THRESHOLD,
                            persona="app_push_dead")
    sched.admit_all([h])

    steps = []
    for _ in range(len(h["channel_order"]) + 2):
        r = sched.step()
        if r.kind == "nothing":
            break
        assert r.kind == "sent"
        steps.append(r.channel)

    expected = [rec["channel"] for rec in simulate_handoff(h, "app_push_dead")]
    assert steps == expected                 # same channel sequence as the one-shot walk
    assert len(steps) >= 2                    # genuinely more than one step
    assert len(sched.broadcaster) == 0        # finished after the fall-back completes


def test_each_step_is_a_distinct_channel_attempt():
    """Each manual trigger advances exactly one channel; the same channel is never stepped
    twice for one hand-off."""
    h = _clear_handoff("1-mustard-aphid-spray")
    sched = SeasonScheduler(_window_open_ist(h), relevance_threshold=THRESHOLD,
                            persona="app_push_dead")
    sched.admit_all([h])
    seen = []
    while True:
        r = sched.step()
        if r.kind == "nothing":
            break
        seen.append(r.channel)
    assert len(seen) == len(set(seen))        # no channel stepped twice


def test_run_due_fires_all_currently_due_steps():
    h = _clear_handoff()
    sched = SeasonScheduler(_window_open_ist(h), relevance_threshold=THRESHOLD)
    sched.admit_all([h])
    results = sched.run_due()
    assert results and all(isinstance(r, StepResult) for r in results)
    assert all(r.kind == "sent" for r in results)
    assert len(sched.broadcaster) == 0


def test_step_records_are_schema_valid_and_simulated():
    h = _clear_handoff()
    sched = SeasonScheduler(_window_open_ist(h), relevance_threshold=THRESHOLD)
    sched.admit_all([h])
    r = sched.step()
    assert r.kind == "sent"
    assert not errors("response", r.record)         # simulated response is schema-valid
    # Sent at the shared clock's instant (delivery stays simulated, no real send).
    assert r.record["timestamps"]["sent"] == sched.now_ist()


# ====================================================== not-yet-due / due / expired
def test_not_yet_due_then_due():
    h = _clear_handoff()
    sched = SeasonScheduler("2026-11-01T07:00:00+05:30", relevance_threshold=THRESHOLD)
    sched.admit_all([h])
    assert sched.step().kind == "nothing"            # not yet due
    while sched.now() < parse_ist(_window_open_ist(h)):
        sched.advance(1)
    assert sched.step().kind == "sent"               # due


def test_expired_step_is_dropped_never_sent():
    h = _clear_handoff()
    sched = SeasonScheduler("2026-11-01T07:00:00+05:30", relevance_threshold=THRESHOLD)
    sched.admit_all([h])
    # Jump well past expiry.
    while sched.now() <= parse_ist(h["expires_at"]):
        sched.advance(10)
    r = sched.step()
    assert r.kind == "nothing"
    assert len(sched.broadcaster) == 0               # expired work is swept, not sent


# ====================================================== season boundary (Nov -> March)
def test_season_boundary_handoff_near_march_end():
    """A hand-off whose window sits at the end of the rabi season (late March) is due when
    the clock reaches it and expired a few days later, within a single fast-forwarded walk."""
    h = _clear_handoff()
    season_end = rules()["window_rules"]["season_end"]  # 2027-03-31
    nb = f"{season_end}T07:00:00+05:30"
    na = f"{season_end}T19:00:00+05:30"
    h["send_window"] = {"not_before": nb, "not_after": na}
    h["survey"]["send_window"] = dict(h["send_window"])
    from mel.timing import expires_at
    h["expires_at"] = expires_at(h["send_window"])      # 2027-04-02T19:00

    # In November the boundary hand-off is not yet due.
    sched = SeasonScheduler("2026-11-01T07:00:00+05:30", relevance_threshold=THRESHOLD)
    sched.admit_all([h])
    assert sched.step().kind == "nothing"               # not due in November

    # Advancing a whole number of days from a 07:00 start keeps the clock at 07:00, so a
    # start exactly on the boundary morning lands in send hours and the step sends.
    at_boundary = SeasonScheduler(nb, relevance_threshold=THRESHOLD)
    at_boundary.admit_all([copy.deepcopy(h)])
    assert at_boundary.step().kind == "sent"            # due at the season boundary

    # A few days past expiry (early April), the same hand-off is swept, never sent.
    past = SeasonScheduler(nb, relevance_threshold=THRESHOLD)
    past.admit_all([copy.deepcopy(h)])
    past.advance(5)                                     # 2027-04-05, past the 04-02 expiry
    assert past.step().kind == "nothing"
    assert len(past.broadcaster) == 0


def test_season_walk_reaches_march_in_a_handful_of_advances():
    """Determinism + speed: a fixed sequence of day jumps moves from 1 Nov to past 31 Mar,
    and the same walk twice gives the same clock readings."""
    def walk():
        sched = SeasonScheduler("2026-11-01T07:00:00+05:30", relevance_threshold=THRESHOLD)
        readings = [sched.now_ist()]
        for _ in range(6):
            sched.advance(30)                            # month-sized jumps
            readings.append(sched.now_ist())
        return readings
    a, b = walk(), walk()
    assert a == b                                        # deterministic
    assert parse_ist(a[-1]) > parse_ist("2027-03-31T00:00:00+05:30")  # crossed the season


# ====================================================== repeated trigger
def test_repeated_trigger_before_window_is_idempotent():
    h = _clear_handoff()
    sched = SeasonScheduler("2026-11-01T07:00:00+05:30", relevance_threshold=THRESHOLD)
    sched.admit_all([h])
    for _ in range(5):
        assert sched.step().kind == "nothing"
    assert len(sched.broadcaster) == 1                   # never consumed, never double-sent


def test_repeated_trigger_after_send_does_not_resend():
    h = _clear_handoff()
    sched = SeasonScheduler(_window_open_ist(h), relevance_threshold=THRESHOLD)
    sched.admit_all([h])
    first = sched.step()
    assert first.kind == "sent"
    # The hand-off is done; further triggers find nothing and do not resend.
    assert sched.step().kind == "nothing"
    assert sched.step().kind == "nothing"
    assert len(sched.broadcaster) == 0


def test_full_season_walk_over_real_pipeline_handoffs():
    """End-to-end: admit the hand-offs the real pipeline built, then walk the whole rabi
    season by advancing the one shared clock in month-sized jumps and firing every due step
    by hand. All work reaches a terminal state (sent or expired/swept); every sent step's
    record is schema-valid; nothing is sent before its window or after expiry."""
    from mel.pipeline import run_insight
    from mel.data import load_insights

    handoffs = []
    for ins in load_insights()[:300]:
        out = run_insight(ins)
        if "handoff" in out:
            handoffs.append(out["handoff"])
    assert handoffs

    sched = SeasonScheduler("2026-11-01T07:00:00+05:30", relevance_threshold=THRESHOLD)
    sched.admit_all(handoffs)

    sent = 0
    for _ in range(12):                         # ~1 year in month jumps -> the season in a dozen steps
        for r in sched.run_due():
            if r.kind == "sent":
                sent += 1
                rec = r.record
                assert not errors("response", rec), r.handoff_id
                # Sent at the shared clock instant, inside the window and before expiry.
                sent_at = parse_ist(rec["timestamps"]["sent"])
                h = next(x for x in handoffs if x["handoff_id"] == r.handoff_id)
                assert parse_ist(h["send_window"]["not_before"]) <= sent_at <= parse_ist(h["expires_at"])
        if not sched.broadcaster:
            break
        sched.advance(30)

    assert sent > 0
    assert len(sched.broadcaster) == 0          # the whole queue is resolved by season end


def test_opt_out_during_a_step_blocks_a_later_handoff_to_same_farmer():
    """Opt-out behaviour is preserved through the season driver: if a farmer opts out on one
    step, a later hand-off to that same farmer is not admitted/sent."""
    h1 = _clear_handoff()
    farmer = h1["survey"]["farmer_id"]
    sched = SeasonScheduler(_window_open_ist(h1), relevance_threshold=THRESHOLD,
                            persona="opts_out_first")
    sched.admit_all([h1])
    r = sched.step()
    assert r.kind == "sent" and r.record["failure_code"] == "farmer_opted_out"
    # A new hand-off to the same farmer is now blocked by the opt-out list.
    h2 = _clear_handoff()
    h2["handoff_id"] = "H-LATER"
    h2["survey"]["farmer_id"] = farmer
    a = sched.admit(h2)
    assert a.decision == "opted_out"
    assert len(sched.broadcaster) == 0
