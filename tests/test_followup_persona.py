"""P3: a persona that sometimes reports the advice failed, feeding the follow-up queue, plus
late-answer counting with today's schema.

Covers: failed-advice answer -> follow-up ticket; success -> no ticket; same seed -> same
answers; explicit scenario; existing personas unchanged; late boundary and counting.
"""
import importlib
from datetime import timedelta

import pytest

from mel.data import load_scenario, load_insights, errors
from mel.pipeline import run_insight
from mel.schedule import build_handoff, run_batch
from mel.simulator import (
    simulate, simulate_handoff, simulate_sheet, PERSONAS, reports_advice_failure,
    advice_failure_answer, follow_up_tickets, is_late, cases_for,
)
from mel.timing import parse_ist, fmt_ist, expires_at

sim = importlib.import_module("mel.simulator.simulate")
EXISTING = ("default", "app_push_dead", "never_answers", "opts_out_first", "no_voice")


def _handoffs():
    return [o["handoff"] for o in (run_insight(i) for i in load_insights()) if "handoff" in o]


def _surveys(hs):
    return {h["survey"]["survey_id"]: h["survey"] for h in hs}


def _h(scenario="1-mustard-aphid-spray"):
    s = load_scenario(scenario)
    h = build_handoff(s["insight"], s["surveys"]["hi-IN"])
    h["survey"]["self_eval"] = {"schema_valid": True, "relevance_score": 0.9,
                                "gives_new_advice": False, "asks_personal_info": False}
    return h


# ===================================================== the persona
def test_failed_advice_answer_creates_a_follow_up_ticket():
    hs = _handoffs()
    failing = [h for h in hs if reports_advice_failure("sometimes_fails", h["survey"]["survey_id"], 0)]
    assert failing, "seed 0 should make the persona fail on some mock surveys"
    h = failing[0]
    recs = simulate_handoff(h, "sometimes_fails", seed=0)
    rec = recs[-1]
    assert rec["status"] == "negative_outcome" and rec["needs_follow_up"]
    assert "advice_did_not_work" in rec["follow_up_reasons"]
    k, value = advice_failure_answer(h["survey"]["items"])
    assert rec["answers"][h["survey"]["items"][k]["item_id"]] == value
    tickets = follow_up_tickets(recs, _surveys([h]))
    assert len(tickets) == 1
    t = tickets[0]
    assert (t["reason"], t["survey_id"], t["response_key"]) == \
           ("advice_did_not_work", h["survey"]["survey_id"], rec["response_key"])
    assert not errors("response", rec)


def test_successful_answer_creates_no_follow_up():
    hs = _handoffs()
    ok = [h for h in hs if not reports_advice_failure("sometimes_fails", h["survey"]["survey_id"], 0)]
    assert ok
    recs = [r for h in ok for r in simulate_handoff(h, "sometimes_fails", seed=0)]
    assert all(r["status"] == "completed" and not r["needs_follow_up"] for r in recs)
    assert follow_up_tickets(recs, _surveys(ok)) == []


def test_every_failure_becomes_exactly_one_ticket():
    hs = _handoffs()
    recs = [r for h in hs for r in simulate_handoff(h, "sometimes_fails", seed=0)]
    failed = [r for r in recs if "advice_did_not_work" in r["follow_up_reasons"]]
    tickets = follow_up_tickets(recs, _surveys(hs))
    assert len(tickets) == len(failed) > 0
    assert {t["response_key"] for t in tickets} == {r["response_key"] for r in failed}
    assert all(t["reason"] == "advice_did_not_work" for t in tickets)


def test_persona_is_repeatable_with_the_same_seed():
    hs = _handoffs()
    a = [r for h in hs for r in simulate_handoff(h, "sometimes_fails", seed=0)]
    b = [r for h in hs for r in simulate_handoff(h, "sometimes_fails", seed=0)]
    assert a == b
    pick = lambda seed: [h["survey"]["survey_id"] for h in hs
                         if reports_advice_failure("sometimes_fails", h["survey"]["survey_id"], seed)]
    assert pick(0) == pick(0) and pick(7) == pick(7)


def test_seed_changes_which_surveys_fail_deterministically():
    ids = [f"S-{n:05d}" for n in range(10000, 10400)]
    s0 = {i for i in ids if reports_advice_failure("sometimes_fails", i, 0)}
    s1 = {i for i in ids if reports_advice_failure("sometimes_fails", i, 1)}
    assert s0 != s1
    rate = PERSONAS["sometimes_fails"]["advice_fails"]
    assert abs(len(s0) / len(ids) - rate) < 0.08                 # "sometimes": close to the rate


def test_explicit_scenario_always_fails(monkeypatch):
    h = _h()
    sid = h["survey"]["survey_id"]
    p = dict(PERSONAS["sometimes_fails"], advice_fails=0.0, advice_fails_for=frozenset({sid}))
    monkeypatch.setitem(sim.PERSONAS, "fails_on_this_one", p)
    rec = simulate_handoff(h, "fails_on_this_one")[-1]
    assert rec["needs_follow_up"] and "advice_did_not_work" in rec["follow_up_reasons"]
    other = _h("4-cow-vet-escalation")
    assert not simulate_handoff(other, "fails_on_this_one")[-1]["needs_follow_up"]


def test_survey_without_a_failure_answer_is_left_alone(monkeypatch):
    h = _h()
    for it in h["survey"]["items"]:
        for o in it.get("options", []):
            if o.get("follow_up") == "advice_did_not_work":
                o.pop("follow_up")
    monkeypatch.setitem(sim.PERSONAS, "always_fails",
                        dict(PERSONAS["sometimes_fails"], advice_fails=1.0))
    assert advice_failure_answer(h["survey"]["items"]) is None
    rec = simulate_handoff(h, "always_fails")[-1]
    assert "advice_did_not_work" not in rec["follow_up_reasons"]


def test_batch_with_the_persona_feeds_the_queue():
    hs = _handoffs()
    res = run_batch(hs, relevance_threshold=0.5, simulate=True, persona="sometimes_fails")
    tickets = follow_up_tickets(res.responses, _surveys(hs))
    sent_failing = [it for it in res.items if it.decision in ("sent", "moved")
                    and reports_advice_failure("sometimes_fails", it.handoff["survey"]["survey_id"], 0)]
    assert len(tickets) == len(sent_failing)


# ===================================================== existing personas unchanged
@pytest.mark.parametrize("persona", EXISTING)
def test_existing_personas_never_report_failure(persona):
    for h in _handoffs():
        assert not reports_advice_failure(persona, h["survey"]["survey_id"], 0)


@pytest.mark.parametrize("persona", EXISTING)
def test_existing_personas_records_identical_to_before(persona):
    """simulate() with an existing persona is byte-identical to the persona-free record, for
    every channel and case: the new answer rule never touches them."""
    s = load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]
    for ch in ("app", "web", "whatsapp", "telegram", "voice"):
        for case in cases_for(ch):
            assert simulate(s, ch, case, persona=persona) == simulate(s, ch, case), (persona, ch, case)


def test_existing_persona_definitions_unchanged():
    assert PERSONAS["default"] == {"per_channel": {}, "fallback_case": "completed", "unreachable": set()}
    assert PERSONAS["no_voice"]["unreachable"] == {"voice"}
    assert PERSONAS["app_push_dead"]["per_channel"] == {"app": "push_token_invalid"}
    assert PERSONAS["opts_out_first"]["fallback_case"] == "farmer_opted_out"


# ===================================================== late answers (today's schema)
def test_is_late_boundary():
    s = load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]
    exp = expires_at(s["send_window"])
    at = simulate_sheet(s, "web", ["q1"], closed=True, submit_at=exp)
    after = simulate_sheet(s, "web", ["q1"], closed=True,
                           submit_at=fmt_ist(parse_ist(exp) + timedelta(seconds=1)))
    assert not is_late(at, exp) and is_late(after, exp)


def test_late_answer_is_kept_counted_and_valid_by_default():
    """Flag off (today's schema): the late answer is stored, not dropped, the record validates,
    and is_late() still counts it."""
    s = load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]
    exp = expires_at(s["send_window"])
    recs = [simulate_sheet(s, "app", ["q1", "q2"], closed=True,
                           submit_at=fmt_ist(parse_ist(exp) + timedelta(days=d))) for d in (-1, 0, 1, 2)]
    late = [r for r in recs if is_late(r, exp)]
    assert len(late) == 2
    assert all(r["answers"] == {"q1": "yes", "q2": recs[0]["answers"]["q2"]} for r in late)
    assert all("late" not in r and not errors("response", r) for r in recs)


def test_late_flag_matches_is_late_when_enabled(monkeypatch):
    monkeypatch.setattr(sim, "_EMIT_LATE", True)
    s = load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]
    exp = expires_at(s["send_window"])
    for d in (-1, 0, 1):
        r = simulate_sheet(s, "app", ["q1"], closed=True, submit_at=fmt_ist(parse_ist(exp) + timedelta(days=d)))
        assert r.get("late", False) == is_late(r, exp)


def test_on_time_answers_are_never_late():
    hs = _handoffs()
    recs = [r for h in hs for r in simulate_handoff(h, "sometimes_fails", seed=0)]
    exp = {h["survey"]["survey_id"]: h["expires_at"] for h in hs}
    assert sum(is_late(r, exp[r["survey_id"]]) for r in recs) == 0
