"""P3 blockers: wait intervals, distinct retries, and the full P4 guard gate.

1. Fallback across channel_order respects each channel's wait_hours, the send hours, the
   send window and expiry -- in the season scheduler's manual steps and in simulate_handoff.
2. Retry attempts are distinct and reproducible: a retry on the same channel gets its own
   delivery_attempt and response_key, so it never overwrites the first attempt.
3. The broadcaster's quality gate rejects every P4 guard failure, not only the three that
   self_eval summarises.
"""
import copy
import importlib
from datetime import datetime, timedelta

import pytest

from mel.config import IST, outcome_codes
from mel.data import load_scenario, errors
from mel.schedule import (
    SeasonScheduler, Broadcaster, SimClock, FrequencyMonitor, FrequencyScheduler,
    build_handoff, quality_failures,
)
from mel.simulator import simulate, simulate_handoff, earliest_send, next_step, PERSONAS
from mel.timing import parse_ist, fmt_ist
from mel.writer import check_survey
from mel.writer.guards import self_eval

sim = importlib.import_module("mel.simulator.simulate")
THRESHOLD = 0.5


def _handoff(scenario):
    s = load_scenario(scenario)
    h = build_handoff(s["insight"], s["surveys"]["hi-IN"])
    h["survey"]["self_eval"] = {"schema_valid": True, "relevance_score": 0.9,
                                "gives_new_advice": False, "asks_personal_info": False}
    return h


def _nb(h):
    return parse_ist(h["send_window"]["not_before"])


def _na(h):
    return parse_ist(h["send_window"]["not_after"])


def _in_send_hours(dt, h):
    f, t = (datetime.strptime(h["send_hours"][k], "%H:%M").time() for k in ("from", "to"))
    return f <= dt.time() <= t


# ======================================================================================
# 1. Wait intervals, send hours, send window, expiry
# ======================================================================================

# ---- the shared timing rules ----------------------------------------------------------
def test_earliest_send_keeps_an_in_hours_time():
    h = _handoff("1-mustard-aphid-spray")
    t = _nb(h) + timedelta(hours=3)                         # 10:00 on the first day
    assert earliest_send(h, t) == t


def test_earliest_send_moves_after_hours_to_next_morning():
    h = _handoff("1-mustard-aphid-spray")
    evening = _nb(h).replace(hour=21)                       # 21:00, after send hours
    assert earliest_send(h, evening) == (_nb(h) + timedelta(days=1)).replace(hour=7, minute=0)


def test_earliest_send_moves_before_hours_to_opening():
    h = _handoff("1-mustard-aphid-spray")
    early = (_nb(h) + timedelta(days=1)).replace(hour=5)    # 05:00 on day 2
    assert earliest_send(h, early) == early.replace(hour=7)


def test_earliest_send_waits_for_window_to_open():
    h = _handoff("1-mustard-aphid-spray")
    assert earliest_send(h, _nb(h) - timedelta(days=3)) == _nb(h)


def test_earliest_send_boundary_at_not_after():
    h = _handoff("1-mustard-aphid-spray")
    assert earliest_send(h, _na(h)) == _na(h)               # exactly the last allowed instant
    assert earliest_send(h, _na(h) + timedelta(minutes=1)) is None   # one minute later: closed


def test_next_step_rules_follow_outcome_codes():
    h = _handoff("1-mustard-aphid-spray")                   # app (24 h) -> whatsapp (last)
    s = h["survey"]
    # no answer on a channel that is not last -> fall back after that channel's wait_hours
    act, d = next_step(h, "app", 1, simulate(s, "app", "push_not_opened"))
    assert (act, d) == ("fallback", timedelta(hours=24))
    # no answer on the last channel (wait_hours null) -> stop
    assert next_step(h, "whatsapp", 1, simulate(s, "whatsapp", "window_expired"))[0] == "stop"
    # delivery failure -> fall back after retry_after_minutes (0)
    assert next_step(h, "app", 1, simulate(s, "app", "push_token_invalid")) == ("fallback", timedelta(0))
    # retry_same_channel -> retry once, then fall back
    rec = simulate(s, "whatsapp", "wa_session_window_closed")
    assert next_step(h, "whatsapp", 1, rec)[0] == "retry"
    assert next_step(h, "whatsapp", 2, rec)[0] == "fallback"
    # answered / declined / opted out -> stop
    for case in ("completed", "farmer_declined", "farmer_opted_out"):
        assert next_step(h, "whatsapp", 1, simulate(s, "whatsapp", case))[0] == "stop", case


def test_every_retry_case_waits_its_retry_after_minutes():
    """Each outcome code's retry_after_minutes is the delay next_step returns."""
    h = _handoff("4-cow-vet-escalation")
    oc = outcome_codes()["failures"]
    for code, v in oc.items():
        if v["retry_decision"] not in ("retry_same_channel", "fall_back_to_next_channel"):
            continue
        ch = v["channels"][0]
        _, delay = next_step(h, ch, 1, simulate(h["survey"], ch, code))
        assert delay == timedelta(minutes=v["retry_after_minutes"] or 0), code


# ---- the manual season trigger --------------------------------------------------------
def test_step_waits_wait_hours_before_falling_back():
    """No answer on app: whatsapp is NOT tried on the next trigger, only once the clock has
    passed app's 24-hour wait."""
    h = _handoff("1-mustard-aphid-spray")                   # app (24 h) -> whatsapp
    sched = SeasonScheduler(fmt_ist(_nb(h)), relevance_threshold=THRESHOLD, persona="never_answers")
    sched.admit_all([h])
    r1 = sched.step()
    assert (r1.kind, r1.channel, r1.record["failure_code"]) == ("sent", "app", "push_not_opened")
    assert sched.next_attempt_at(h["handoff_id"]) == _nb(h) + timedelta(hours=24)
    for _ in range(3):                                      # repeated triggers before the wait
        assert sched.step().kind == "nothing"
    assert len(sched.broadcaster) == 1                      # still queued, not dropped
    sched.advance(1)                                        # +24 h
    r2 = sched.step()
    assert (r2.kind, r2.channel) == ("sent", "whatsapp")
    assert parse_ist(r2.record["timestamps"]["sent"]) - parse_ist(r1.record["timestamps"]["sent"]) \
        == timedelta(hours=24)
    assert len(sched.broadcaster) == 0                      # last channel: done


def test_step_waits_six_hours_for_high_priority():
    h = _handoff("4-cow-vet-escalation")                    # voice (6 h) -> whatsapp
    sched = SeasonScheduler(fmt_ist(_nb(h)), relevance_threshold=THRESHOLD, persona="never_answers")
    sched.admit_all([h])
    assert sched.step().channel == "voice"                  # 07:00
    sched.clock.set(fmt_ist(_nb(h).replace(hour=12, minute=59)))
    assert sched.step().kind == "nothing"                   # 5 h 59 m: too early
    sched.clock.set(fmt_ist(_nb(h).replace(hour=13)))
    r = sched.step()
    assert (r.kind, r.channel) == ("sent", "whatsapp")      # exactly 6 h later


def test_step_wait_that_ends_after_hours_moves_to_next_morning():
    h = _handoff("4-cow-vet-escalation")                    # voice (6 h) -> whatsapp
    start = _nb(h).replace(hour=15)                          # 15:00 + 6 h = 21:00, after hours
    sched = SeasonScheduler(fmt_ist(start), relevance_threshold=THRESHOLD, persona="never_answers")
    sched.admit_all([h])
    assert sched.step().channel == "voice"
    nxt = sched.next_attempt_at(h["handoff_id"])
    assert nxt == (_nb(h) + timedelta(days=1)).replace(hour=7)   # next day 07:00
    assert _in_send_hours(nxt, h)


def test_step_ends_when_next_attempt_falls_after_send_window():
    """Low priority waits 48 h. Window 25 Dec 07:00 .. 27 Dec 19:00: telegram on the 25th,
    app on the 27th, and whatsapp would be the 29th -- outside the window, so never sent."""
    h = _handoff("5-wheat-variety-plan")                    # telegram (48) -> app (48) -> whatsapp
    sched = SeasonScheduler(fmt_ist(_nb(h)), relevance_threshold=THRESHOLD, persona="never_answers")
    sched.admit_all([h])
    channels = []
    for _ in range(10):
        for r in sched.run_due():
            channels.append(r.channel)
        if not sched.broadcaster:
            break
        sched.advance(1)
    assert channels == ["telegram", "app"]                  # whatsapp never sent
    assert sched.step_counts["window_closed_before_next_attempt"] == 1
    assert len(sched.broadcaster) == 0


def test_delivery_failure_falls_back_without_waiting():
    """A dead push address (retry_after 0) falls back on the very next trigger."""
    h = _handoff("1-mustard-aphid-spray")
    sched = SeasonScheduler(fmt_ist(_nb(h)), relevance_threshold=THRESHOLD, persona="app_push_dead")
    sched.admit_all([h])
    assert sched.step().record["failure_code"] == "push_token_invalid"
    r = sched.step()                                        # same instant
    assert (r.kind, r.channel, r.record["status"]) == ("sent", "whatsapp", "completed")


def test_every_step_send_is_inside_window_and_send_hours():
    """Walk every scenario and persona day by day: every simulated send lands inside the send
    window and the send hours, and every record is schema-valid."""
    scenarios = ["1-mustard-aphid-spray", "3-potato-blight-wait", "4-cow-vet-escalation",
                 "5-wheat-variety-plan"]
    for sc in scenarios:
        for persona in PERSONAS:
            h = _handoff(sc)
            sched = SeasonScheduler(fmt_ist(_nb(h) - timedelta(days=1)), relevance_threshold=THRESHOLD,
                                    persona=persona)
            sched.admit_all([h])
            for _ in range(12):
                for r in sched.run_due():
                    sent = parse_ist(r.record["timestamps"]["sent"])
                    assert _nb(h) <= sent <= _na(h), (sc, persona, r.channel, sent)
                    assert _in_send_hours(sent, h), (sc, persona, r.channel, sent)
                    assert not errors("response", r.record), (sc, persona)
                if not sched.broadcaster:
                    break
                sched.advance(1)
            assert len(sched.broadcaster) == 0, (sc, persona)  # always resolves


def test_broadcaster_never_sends_after_send_window_closes():
    """Between not_after and expires_at nothing may be sent: the hand-off is dropped."""
    h = _handoff("1-mustard-aphid-spray")                   # window ends 9 Dec 19:00, expires 11 Dec
    clock = SimClock(fmt_ist((_na(h) + timedelta(days=1)).replace(hour=7)))  # 10 Dec 07:00
    assert clock.now() < parse_ist(h["expires_at"])
    bc = Broadcaster(clock)
    bc.queue(h)
    res = bc.broadcast_due(relevance_threshold=THRESHOLD)
    assert res[0].action == "expired" and "send window closed" in res[0].reason
    assert bc.counts()["expired"] == 1


# ---- simulate_handoff uses the same timing ------------------------------------------------
def test_simulate_handoff_spaces_fallback_by_wait_hours():
    h = _handoff("1-mustard-aphid-spray")                   # app (24 h) -> whatsapp
    recs = simulate_handoff(h, "never_answers")
    assert [r["channel"] for r in recs] == ["app", "whatsapp"]
    t = [parse_ist(r["timestamps"]["sent"]) for r in recs]
    assert t[1] - t[0] == timedelta(hours=24)


def test_simulate_handoff_high_priority_six_hours():
    h = _handoff("4-cow-vet-escalation")                    # voice first send 10:00 (+3 h offset)
    recs = simulate_handoff(h, "never_answers")
    t = [parse_ist(r["timestamps"]["sent"]) for r in recs]
    assert [r["channel"] for r in recs] == ["voice", "whatsapp"]
    assert t[1] - t[0] == timedelta(hours=6)


def test_simulate_handoff_stops_when_window_closes():
    h = _handoff("5-wheat-variety-plan")
    recs = simulate_handoff(h, "never_answers")
    assert [r["channel"] for r in recs] == ["telegram", "app"]   # whatsapp would be outside


def test_simulate_handoff_all_sends_inside_window_and_hours():
    for sc in ("1-mustard-aphid-spray", "3-potato-blight-wait", "4-cow-vet-escalation",
               "5-wheat-variety-plan", "2-wheat-irrigation-timing"):
        h = _handoff(sc)
        for persona in PERSONAS:
            for r in simulate_handoff(h, persona):
                sent = parse_ist(r["timestamps"]["sent"])
                assert _nb(h) <= sent <= _na(h), (sc, persona, r["channel"])
                assert _in_send_hours(sent, h), (sc, persona, r["channel"])


def test_never_answers_persona_is_valid_per_outcome_codes():
    """Every channel case a persona produces must be allowed on that channel."""
    oc = outcome_codes()
    for name, p in PERSONAS.items():
        for ch in ("app", "web", "whatsapp", "telegram", "voice"):
            if ch in p["unreachable"]:
                continue
            case = p["per_channel"].get(ch, p["fallback_case"])
            f = oc["failures"].get(case)
            if f:
                assert ch in f["channels"], (name, ch, case)


# ======================================================================================
# 2. Distinct, reproducible retry attempts
# ======================================================================================
def _with_persona(monkeypatch, name, per_channel, fallback="completed"):
    monkeypatch.setitem(sim.PERSONAS, name, {"per_channel": per_channel, "fallback_case": fallback,
                                             "unreachable": set()})


def test_retry_gets_its_own_key_and_attempt():
    s = _handoff("1-mustard-aphid-spray")["survey"]
    a1 = simulate(s, "whatsapp", "wa_session_window_closed", attempt=1)
    a2 = simulate(s, "whatsapp", "wa_session_window_closed", attempt=2)
    assert a1["response_key"] != a2["response_key"]
    assert a2["response_key"] == a1["response_key"] + "-a2"
    assert (a1["delivery_attempt"], a2["delivery_attempt"]) == (1, 2)
    assert not errors("response", a1) and not errors("response", a2)


def test_first_attempt_key_is_unchanged():
    """Attempt 1 keeps the plain key the 183 reference records use."""
    s = _handoff("1-mustard-aphid-spray")["survey"]
    assert simulate(s, "app", "completed")["response_key"] == f"rk-{s['survey_id']}-app-completed"


def test_retry_key_stays_within_schema_length():
    s = _handoff("1-mustard-aphid-spray")["survey"]
    longest = max(outcome_codes()["failures"], key=len)
    r = simulate(s, "voice", longest, attempt=5)
    assert len(r["response_key"]) <= 64


def test_simulate_handoff_retry_records_are_distinct(monkeypatch):
    """app fails -> whatsapp session closed (retry) -> whatsapp again: three records, three
    keys, attempts 1/1/2. Writing them by response_key keeps all three."""
    _with_persona(monkeypatch, "wa_retry", {"app": "push_token_invalid",
                                            "whatsapp": "wa_session_window_closed"})
    h = _handoff("1-mustard-aphid-spray")
    recs = simulate_handoff(h, "wa_retry")
    assert [(r["channel"], r["delivery_attempt"]) for r in recs] == [("app", 1), ("whatsapp", 1), ("whatsapp", 2)]
    files = {r["response_key"]: r for r in recs}
    assert len(files) == 3                                  # nothing overwritten


def test_voice_busy_retry_waits_ten_minutes(monkeypatch):
    _with_persona(monkeypatch, "busy_line", {"voice": "voice_busy"})
    h = _handoff("4-cow-vet-escalation")                    # voice -> whatsapp
    recs = simulate_handoff(h, "busy_line")
    assert [(r["channel"], r["delivery_attempt"]) for r in recs] == [("voice", 1), ("voice", 2), ("whatsapp", 1)]
    t = [parse_ist(r["timestamps"]["sent"]) for r in recs]
    assert t[1] - t[0] == timedelta(minutes=10)             # retry_after_minutes for voice_busy
    assert t[2] - t[1] == timedelta(minutes=10)             # then falls back after the same delay
    assert recs[-1]["status"] == "completed"


def test_scheduler_step_retry_is_a_distinct_record(monkeypatch):
    _with_persona(monkeypatch, "busy_line", {"voice": "voice_busy"})
    h = _handoff("4-cow-vet-escalation")
    sched = SeasonScheduler(fmt_ist(_nb(h)), relevance_threshold=THRESHOLD, persona="busy_line")
    sched.admit_all([h])
    r1 = sched.step()
    assert sched.step().kind == "nothing"                   # waiting the 10 minutes
    sched.clock.set(fmt_ist(_nb(h) + timedelta(minutes=10)))
    r2 = sched.step()
    assert (r1.channel, r2.channel) == ("voice", "voice")
    assert (r1.record["delivery_attempt"], r2.record["delivery_attempt"]) == (1, 2)
    assert r1.record["response_key"] != r2.record["response_key"]
    sched.clock.set(fmt_ist(_nb(h) + timedelta(minutes=20)))
    r3 = sched.step()
    assert (r3.channel, r3.record["status"]) == ("whatsapp", "completed")


def test_retry_walk_is_reproducible(monkeypatch):
    _with_persona(monkeypatch, "busy_line", {"voice": "voice_busy"})
    h = _handoff("4-cow-vet-escalation")
    assert simulate_handoff(h, "busy_line", seed=0) == simulate_handoff(h, "busy_line", seed=0)


def test_reference_grid_still_matches_183():
    from mel.simulator.reference_check import compare
    rep = compare()
    assert (rep["total"], rep["matched"], rep["mismatches"]) == (183, 183, [])


# ======================================================================================
# 3. Quality gate rejects every P4 guard failure
# ======================================================================================
def _survey_with_guard_failure(kind):
    """A real survey broken in one way, with self_eval recomputed by P4 (so it reflects what
    P4 actually writes). Returns (survey, insight)."""
    sc = load_scenario("1-mustard-aphid-spray")
    s = copy.deepcopy(sc["surveys"]["hi-IN"])
    q = s["items"][0]
    if kind == "duplicate_option_value":
        q["options"][1]["value"] = q["options"][0]["value"]
    elif kind == "label_too_long":
        q["options"][0]["label"] = "क" * 25
    elif kind == "empty_text":
        q["prompt"] = "   "
    elif kind == "bad_item_count":
        s["items"] = []
    elif kind == "duplicate_item_id":
        s["items"][1]["item_id"] = s["items"][0]["item_id"]
    s["self_eval"] = self_eval(s, sc["insight"])
    s["self_eval"]["relevance_score"] = 0.9                 # keep relevance out of the picture
    return s


@pytest.mark.parametrize("kind", ["duplicate_option_value", "label_too_long", "empty_text",
                                  "bad_item_count", "duplicate_item_id"])
def test_gate_rejects_guard_failure(kind):
    s = _survey_with_guard_failure(kind)
    assert check_survey(s), kind                            # P4 flags it
    fails = quality_failures(s, THRESHOLD)
    assert any(f.startswith("guard:") for f in fails), (kind, fails)


def test_guard_failure_self_eval_misses_is_now_rejected():
    """The original gap: self_eval looks clean, but P4's guard fails."""
    s = _survey_with_guard_failure("duplicate_option_value")
    assert s["self_eval"]["schema_valid"] is True
    assert not s["self_eval"]["gives_new_advice"] and not s["self_eval"]["asks_personal_info"]
    assert quality_failures(s, THRESHOLD) == ["guard: q1: duplicate_option_value"]


def test_broadcaster_rejects_and_counts_guard_failure():
    h = _handoff("1-mustard-aphid-spray")
    h["survey"] = _survey_with_guard_failure("duplicate_option_value")
    bc = Broadcaster(SimClock(fmt_ist(_nb(h))))
    bc.queue(h)
    res = bc.broadcast_due(relevance_threshold=THRESHOLD)
    assert res[0].action == "rejected" and "duplicate_option_value" in res[0].reason
    assert bc.counts()["rejected"] == 1


def test_scheduler_never_sends_guard_failure():
    h = _handoff("1-mustard-aphid-spray")
    h["survey"] = _survey_with_guard_failure("duplicate_option_value")
    sched = SeasonScheduler(fmt_ist(_nb(h)), relevance_threshold=THRESHOLD)
    sched.admit_all([h])
    assert sched.step().kind == "nothing"
    assert len(sched.broadcaster) == 0
    assert sched.broadcaster.counts()["rejected"] == 1


def test_frequency_filter_excludes_guard_failure():
    h = _handoff("1-mustard-aphid-spray")
    h["survey"] = _survey_with_guard_failure("duplicate_option_value")
    assert FrequencyScheduler(FrequencyMonitor([])).filter_eligible([h], relevance_threshold=THRESHOLD) == []


def test_schema_and_relevance_rejections_still_apply():
    h = _handoff("1-mustard-aphid-spray")
    s = h["survey"]
    s["self_eval"]["schema_valid"] = False
    assert "self_eval.schema_valid is not true" in quality_failures(s, THRESHOLD)
    s["self_eval"]["schema_valid"] = True
    s["self_eval"]["relevance_score"] = 0.49
    assert any("below threshold" in f for f in quality_failures(s, THRESHOLD))
    s["self_eval"]["relevance_score"] = THRESHOLD           # equal is eligible
    assert quality_failures(s, THRESHOLD) == []


def test_clean_pipeline_surveys_have_no_guard_rejections():
    """No false rejects: every survey the pipeline writes passes P4's guards."""
    from mel.pipeline import run_insight
    from mel.data import load_insights
    for ins in load_insights():
        out = run_insight(ins)
        if "handoff" in out:
            assert not [f for f in quality_failures(out["handoff"]["survey"], 0.0)
                        if f.startswith("guard:")], out["handoff"]["handoff_id"]
