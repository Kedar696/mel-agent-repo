"""P3 completion: regression tests for the gaps found in the 4 Nov audit.

Each test names the behaviour it locks in. Grouped by requirement:
  1. batch safeguards (quality gate before the cap, opt-outs, cap metric, duplicates)
  2. cap policy (7-day boundary in both orders, high-priority exemption, move stays inside
     the window, merge keeps every ID within the schema limit, deterministic queue order)
  3. broadcaster (opt-out after queuing, simulated-app delivery, due / not due)
  4. channels and sheet (reachability, fallback in the batch, skipped middle answer, bad input)
  5. late answers (boundary, never `late: false`, valid once the optional field exists)
  6. frequency ranking in the real scheduling path, no look-ahead, neutral climate
  7. determinism and the reference grid
"""
import copy
import importlib
import json
from datetime import timedelta

import pytest

from mel.config import SCHEMAS
from mel.data import load_scenario, errors, load_insights
from mel.schedule import (
    build_handoff, CapLedger, OptOutList, run_batch, SeasonScheduler, Broadcaster, SimClock,
    FrequencyScheduler, FrequencyMonitor, ClimateContext,
)
from mel.schedule.batch import cap_violations
from mel.schedule.broadcast import SimulatedApp
from mel.schedule.handoff import max_source_insight_ids
from mel.channels import FarmerReachability
from mel.simulator import simulate, simulate_handoff, simulate_sheet
from mel.timing import parse_ist, fmt_ist, expires_at

sim = importlib.import_module("mel.simulator.simulate")
T = 0.5   # stand-in for P4's relevance threshold (P4 has not published one; see CLAUDE.md)


# ----------------------------------------------------------------------------- helpers
def _h(scenario="1-mustard-aphid-spray", score=0.9):
    s = load_scenario(scenario)
    h = build_handoff(s["insight"], s["surveys"]["hi-IN"])
    h["survey"]["self_eval"] = {"schema_valid": True, "relevance_score": score,
                                "gives_new_advice": False, "asks_personal_info": False}
    return h


def _copy(h, hid, ids, shift=timedelta(0), farmer=None):
    x = copy.deepcopy(h)
    x["handoff_id"] = hid
    x["survey"]["source_insight_ids"] = list(ids)
    for k in ("not_before", "not_after"):
        x["send_window"][k] = fmt_ist(parse_ist(h["send_window"][k]) + shift)
    x["survey"]["send_window"] = dict(x["send_window"])
    x["expires_at"] = fmt_ist(parse_ist(h["expires_at"]) + shift)
    if farmer:
        x["survey"]["farmer_id"] = farmer
        x["frequency_cap"]["key"] = f"mel:farmer:{farmer}"
    return x


def _nb(h):
    return parse_ist(h["send_window"]["not_before"])


def _pipeline_handoffs():
    from mel.pipeline import run_insight
    return [o["handoff"] for o in (run_insight(i) for i in load_insights()) if "handoff" in o]


# ===================================================== 1. batch safeguards
@pytest.mark.parametrize("break_it", ["schema_valid", "guard", "relevance_below", "no_self_eval"])
def test_batch_rejects_ineligible_survey_before_scheduling(break_it):
    h = _h()
    if break_it == "schema_valid":
        h["survey"]["self_eval"]["schema_valid"] = False
    elif break_it == "guard":
        q = h["survey"]["items"][0]
        q["options"][1]["value"] = q["options"][0]["value"]          # P4 guard: duplicate_option_value
    elif break_it == "relevance_below":
        h["survey"]["self_eval"]["relevance_score"] = 0.4999
    else:
        del h["survey"]["self_eval"]
    res = run_batch([h], relevance_threshold=T, simulate=True)
    assert res.counts["rejected"] == 1 and res.counts["sent"] == 0
    assert res.handoffs_to_send == [] and res.responses == []


def test_batch_relevance_exactly_at_threshold_is_scheduled():
    res = run_batch([_h(score=T)], relevance_threshold=T)
    assert res.counts["sent"] == 1 and res.counts["rejected"] == 0


def test_rejected_survey_does_not_take_the_weekly_slot():
    """Before the fix a rejected survey was admitted first, so a valid one the same week was
    merged into a survey that would never be sent."""
    bad = _h(score=0.1)
    good = _copy(_h(), "H-GOOD", ["I-GOOD"])
    res = run_batch([bad, good], relevance_threshold=T)
    d = {it.input_id: it.decision for it in res.items}
    assert d[bad["handoff_id"]] == "rejected" and d["H-GOOD"] == "sent"


def test_season_scheduler_rejects_before_cap_too():
    bad = _h(score=0.1)
    good = _copy(_h(), "H-GOOD", ["I-GOOD"])
    sched = SeasonScheduler(fmt_ist(_nb(bad)), relevance_threshold=T)
    decisions = [a.decision for a in sched.admit_all([bad, good])]
    assert sorted(decisions) == ["rejected", "sent"]
    assert sched.broadcaster.counts()["rejected"] == 1                  # P5's "blocked by quality check"
    assert [h["handoff_id"] for h in sched.pending] == ["H-GOOD"]


def test_cap_violation_metric_excludes_prevented_surveys():
    h1 = _h()
    same_week = [_copy(h1, f"H-{i}", [f"I-{i}"]) for i in range(3)]
    res = run_batch([h1, *same_week], relevance_threshold=T)
    assert res.counts["prevented"] == res.counts["skipped"] + res.counts["opted_out"] + res.counts["rejected"]
    assert res.counts["cap_violations"] == 0


def test_cap_violation_audit_detects_a_real_violation():
    """The metric is an audit of the output, not a hard-coded zero: two normal sends 3 days
    apart to one farmer are reported."""
    a = _h()
    b = _copy(a, "H-B", ["I-B"], shift=timedelta(days=3))
    assert cap_violations([a, b]) == [(a["handoff_id"], "H-B")]
    c = _copy(a, "H-C", ["I-C"], shift=timedelta(days=7))
    assert cap_violations([a, c]) == []                                 # exactly 7 days apart is fine


def test_duplicate_input_is_counted_once_and_not_sent_twice():
    h = _h()
    res = run_batch([h, copy.deepcopy(h)], relevance_threshold=T, simulate=True)
    assert res.counts["sent"] == 1 and res.counts["duplicates"] == 1
    assert len(res.items) == 1 and len(res.handoffs_to_send) == 1


def test_capledger_repeat_admission_is_a_no_op():
    led = CapLedger()
    h = _h()
    first = led.admit(h)
    again = led.admit(copy.deepcopy(h))
    assert first.decision == "sent" and again is first                  # was "merged into itself"


def test_batch_does_not_modify_the_callers_handoffs():
    h1 = _h()
    h2 = _copy(h1, "H-2", ["I-2"])
    before = copy.deepcopy([h1, h2])
    run_batch([h1, h2], relevance_threshold=T, simulate=True)
    assert [h1, h2] == before


def test_opted_out_farmer_gets_zero_surveys_including_high_priority():
    hi = _h("4-cow-vet-escalation")
    hi2 = _copy(hi, "H-HI2", ["I-HI2"], shift=timedelta(days=1))
    stop = OptOutList()
    stop.record(simulate(hi["survey"], "whatsapp", "farmer_opted_out"))
    res = run_batch([hi, hi2], relevance_threshold=T, opt_out=stop, simulate=True)
    assert res.counts["opted_out"] == 2 and res.handoffs_to_send == [] and res.responses == []


def test_opt_out_during_batch_simulation_blocks_later_exempt_survey():
    hi = _h("4-cow-vet-escalation")
    hi2 = _copy(hi, "H-HI2", ["I-HI2"], shift=timedelta(days=1))       # exempt: the cap would allow it
    res = run_batch([hi, hi2], relevance_threshold=T, simulate=True, persona="opts_out_first")
    d = {it.input_id: it.decision for it in res.items}
    assert d[hi["handoff_id"]] == "sent" and d["H-HI2"] == "opted_out"


# ===================================================== 2. cap policy
def test_weekly_boundary_6d_23h_59m_capped_exactly_7d_eligible():
    a = _h()
    near = _copy(a, "H-NEAR", ["I-N"], shift=timedelta(days=6, hours=23, minutes=59))
    exact = _copy(a, "H-EXACT", ["I-E"], shift=timedelta(days=7))
    led = CapLedger(); led.admit(a)
    assert led.admit(near).decision != "sent"
    led = CapLedger(); led.admit(a)
    assert led.admit(exact).decision == "sent"


def test_weekly_cap_holds_when_admitted_out_of_order():
    """The old check used timedelta.days, so a survey 6 d 23 h BEFORE an admitted one was 'sent'."""
    a = _h()
    earlier = _copy(a, "H-EARLIER", ["I-E"], shift=-timedelta(days=6, hours=23))
    led = CapLedger(); led.admit(a)
    assert led.admit(earlier).decision != "sent"


def test_high_priority_exempt_but_counts_toward_a_later_normal_survey():
    hi = _h("4-cow-vet-escalation")
    assert hi["frequency_cap"]["exempt"] is True
    normal = _copy(_h(), "H-NORMAL", ["I-NORMAL"])
    normal["survey"]["farmer_id"] = hi["survey"]["farmer_id"]
    normal["frequency_cap"]["key"] = hi["frequency_cap"]["key"]
    shift = _nb(hi) - _nb(normal) + timedelta(days=2)                   # 2 days after the high one
    normal = _copy(normal, "H-NORMAL", ["I-NORMAL"], shift=shift)
    hi2 = _copy(hi, "H-HI2", ["I-HI2"], shift=timedelta(days=1))
    res = run_batch([hi, hi2, normal], relevance_threshold=T)
    d = {it.input_id: it.decision for it in res.items}
    assert d[hi["handoff_id"]] == "sent" and d["H-HI2"] == "sent"       # both exempt
    assert d["H-NORMAL"] != "sent"                                      # blocked by the highs
    assert res.counts["cap_violations"] == 0


def test_moved_survey_stays_inside_its_own_window_and_expiry():
    a = _h()
    wide = _copy(a, "H-WIDE", ["I-W"])
    wide["send_window"]["not_after"] = fmt_ist(_nb(a) + timedelta(days=9))
    wide["survey"]["send_window"] = dict(wide["send_window"])
    wide["expires_at"] = expires_at(wide["send_window"])
    wide["handoff_id"] = "H-90002"                                      # schema pattern ^H-[0-9]{5,10}$
    led = CapLedger(); led.admit(a)
    m = led.admit(wide)
    assert m.decision == "moved"
    new_nb = parse_ist(m.handoff["send_window"]["not_before"])
    assert new_nb - _nb(a) >= timedelta(days=7)                         # clears the block
    assert m.handoff["send_window"]["not_after"] == wide["send_window"]["not_after"]   # not shifted
    assert m.handoff["expires_at"] == wide["expires_at"]                # expiry unchanged
    assert m.handoff["survey"]["send_window"] == m.handoff["send_window"]
    assert not errors("schedule_handoff", m.handoff)


def test_move_never_lands_less_than_7_days_after_a_later_clock_time():
    """A blocking send at 10:00 and a candidate at 07:00 seven days later is only 6 d 21 h:
    the move goes to the next day instead."""
    a = _h()
    a["send_window"]["not_before"] = fmt_ist(_nb(a).replace(hour=10))
    a["survey"]["send_window"] = dict(a["send_window"])
    wide = _copy(_h(), "H-WIDE", ["I-W"])
    wide["send_window"]["not_after"] = fmt_ist(_nb(wide) + timedelta(days=12))
    wide["survey"]["send_window"] = dict(wide["send_window"])
    led = CapLedger(); led.admit(a)
    m = led.admit(wide)
    assert m.decision == "moved"
    assert parse_ist(m.handoff["send_window"]["not_before"]) - _nb(a) >= timedelta(days=7)


def test_moved_survey_is_placed_after_a_high_priority_survey_that_opens_in_between():
    """Found on the full pack (9 cases): normal B is capped by A on day 0 and moved to day 7,
    but high-priority C opens on day 5. Placing B at day 7 straight away put a normal survey 2
    days after C. Now B waits in send order, sees C, and moves to C + 7 days."""
    a = _copy(_h(), "H-90010", ["I-A"], farmer="F-SAME")
    b = _copy(_h(), "H-90011", ["I-B"], shift=timedelta(days=1), farmer="F-SAME")
    b["send_window"]["not_after"] = fmt_ist(_nb(a) + timedelta(days=14))
    b["survey"]["send_window"] = dict(b["send_window"])
    b["expires_at"] = expires_at(b["send_window"])
    hi = _h("4-cow-vet-escalation")
    c = _copy(hi, "H-90012", ["I-C"], shift=_nb(a) - _nb(hi) + timedelta(days=5), farmer="F-SAME")
    res = run_batch([a, b, c], relevance_threshold=T)
    d = {it.input_id: it for it in res.items}
    assert d["H-90010"].decision == "sent" and d["H-90012"].decision == "sent"
    assert d["H-90011"].decision == "moved"
    assert parse_ist(d["H-90011"].handoff["send_window"]["not_before"]) >= _nb(c) + timedelta(days=7)
    assert res.counts["cap_violations"] == 0 and res.counts["moved"] == 1
    # The season scheduler uses the same send-order admission.
    sched = SeasonScheduler(relevance_threshold=T)
    sched.admit_all([copy.deepcopy(x) for x in (a, b, c)])
    assert sched.metrics()["admitted"] == {"sent": 2, "moved": 1}
    assert cap_violations(sched.pending) == []


def test_cannot_move_past_window_so_merges_or_skips():
    a = _h()
    same = _copy(a, "H-SAME", ["I-S"])                                  # window fully inside a's week
    led = CapLedger(); led.admit(a)
    assert led.admit(same).decision == "merged"


def test_merge_records_all_ids_without_duplicates_and_within_schema_limit():
    a = _h()
    limit = max_source_insight_ids()
    extras = [_copy(a, f"H-M{i}", [f"I-M{i}", a["survey"]["source_insight_ids"][0]]) for i in range(limit + 2)]
    res = run_batch([a, *extras], relevance_threshold=T)
    host = res.handoffs_to_send[0]
    ids = host["survey"]["source_insight_ids"]
    assert len(ids) == len(set(ids)) <= limit                           # no duplicates, schema limit
    assert ids[0] == a["survey"]["source_insight_ids"][0]               # host's own id first
    merged = [it for it in res.items if it.decision == "merged"]
    assert len(merged) == limit - 1                                     # room for limit-1 more ids
    for it in merged:
        assert extras[int(it.input_id[3:])]["survey"]["source_insight_ids"][0] in ids
    assert res.counts["skipped"] == len(extras) - len(merged)           # the rest cannot merge
    assert not errors("schedule_handoff", host)


def test_merged_ids_reach_the_hosts_simulated_record():
    a = _h()
    b = _copy(a, "H-B", ["I-B"])
    res = run_batch([a, b], relevance_threshold=T, simulate=True)
    rec = res.responses[0]
    assert rec["source_insight_ids"] == res.handoffs_to_send[0]["survey"]["source_insight_ids"]
    assert "I-B" in rec["source_insight_ids"] and not errors("response", rec)


def test_queue_order_is_send_window_start_then_deterministic_ties():
    a = _copy(_h(), "H-A", ["I-A"], farmer="F-AAA")
    b = _copy(_h(), "H-B", ["I-B"], farmer="F-BBB")
    early = _copy(_h(), "H-EARLY", ["I-EA"], shift=-timedelta(days=1), farmer="F-ZZZ")
    for order in ([a, b, early], [b, early, a], [early, b, a]):
        bc = Broadcaster(SimClock(fmt_ist(_nb(a))))
        bc.queue_all(order)
        assert [h["handoff_id"] for h in bc.pending] == ["H-EARLY", "H-A", "H-B"]
    # A rank breaks the tie at the same start, but never jumps an earlier window.
    bc = Broadcaster(SimClock(fmt_ist(_nb(a))))
    bc.queue(a, rank=1.0); bc.queue(b, rank=9.0); bc.queue(early, rank=0.0)
    assert [h["handoff_id"] for h in bc.pending] == ["H-EARLY", "H-B", "H-A"]


# ===================================================== 3. broadcaster
def test_broadcaster_drops_survey_whose_farmer_opted_out_after_queuing():
    """Before the fix, two queued surveys to one farmer both went out after the first opt-out."""
    hi = _h("4-cow-vet-escalation")
    hi2 = _copy(hi, "H-HI2", ["I-HI2"])
    sched = SeasonScheduler(fmt_ist(_nb(hi)), relevance_threshold=T, persona="opts_out_first")
    sched.admit_all([hi, hi2])
    sent = sched.run_due()
    assert [r.handoff_id for r in sent] == [hi["handoff_id"]]
    assert sched.broadcaster.counts()["opted_out"] == 1 and len(sched.broadcaster) == 0


def test_scheduler_and_broadcaster_share_clock_and_opt_out_list():
    sched = SeasonScheduler(relevance_threshold=T)
    assert sched.clock is sched.broadcaster.clock
    assert sched.opt_out is sched.broadcaster._opt_out


def test_broadcast_due_delivers_only_due_eligible_surveys_to_the_simulated_app():
    ok = _h()
    later = _copy(ok, "H-LATER", ["I-L"], shift=timedelta(days=5), farmer="F-L")
    low = _copy(ok, "H-LOW", ["I-LOW"], farmer="F-LOW"); low["survey"]["self_eval"]["relevance_score"] = 0.1
    gone = _copy(ok, "H-GONE", ["I-G"], shift=-timedelta(days=30), farmer="F-G")
    stopped = _copy(ok, "H-STOP", ["I-ST"], farmer="F-STOP")
    stop = OptOutList(); stop.record(simulate(stopped["survey"], "whatsapp", "farmer_opted_out"))
    app = SimulatedApp()
    bc = Broadcaster(SimClock(fmt_ist(_nb(ok))), opt_out=stop, app=app)
    bc.queue_all([ok, later, low, gone, stopped])
    actions = {b.handoff_id: b.action for b in bc.broadcast_due(relevance_threshold=T)}
    assert actions == {ok["handoff_id"]: "sent", "H-LATER": "pending", "H-LOW": "rejected",
                       "H-GONE": "expired", "H-STOP": "opted_out"}
    assert [m["handoff_id"] for m in app.inbox] == [ok["handoff_id"]]   # only the eligible, due one
    assert set(app.inbox[0]) == {"handoff_id", "survey_id", "farmer_id", "channel", "delivered_at"}


def test_broadcast_due_after_send_hours_waits_and_delivers_nothing():
    h = _h()
    app = SimulatedApp()
    bc = Broadcaster(SimClock(fmt_ist(_nb(h).replace(hour=21))), app=app)
    bc.queue(h)
    assert bc.broadcast_due(relevance_threshold=T)[0].action == "waiting"
    assert len(app) == 0 and len(bc) == 1


def test_season_step_delivers_to_the_simulated_app():
    h = _h()
    sched = SeasonScheduler(fmt_ist(_nb(h)), relevance_threshold=T)
    sched.admit_all([h])
    r = sched.step()
    assert r.kind == "sent"
    assert sched.broadcaster.app.inbox[-1]["handoff_id"] == h["handoff_id"]


def test_season_scheduler_repeat_admission_counts_once():
    h = _h()
    sched = SeasonScheduler(fmt_ist(_nb(h)), relevance_threshold=T)
    sched.admit(h); sched.admit(copy.deepcopy(h))
    assert sched.metrics()["admitted"] == {"sent": 1} and len(sched.broadcaster) == 1


# ===================================================== 4. channels and the sheet
def test_simulate_handoff_skips_explicitly_unreachable_channel_and_keeps_order():
    h = _h("3-potato-blight-wait")                                      # web -> app -> whatsapp
    fid = h["survey"]["farmer_id"]
    reach = FarmerReachability({}, unreachable_by_farmer={fid: {"app"}})
    recs = simulate_handoff(h, "never_answers", reachability=reach)
    assert [r["channel"] for r in recs] == ["web", "whatsapp"]


def test_no_reachability_data_skips_nothing():
    h = _h("3-potato-blight-wait")
    from mel.data import load_farmers
    with_data = simulate_handoff(h, "never_answers", reachability=FarmerReachability(load_farmers()))
    assert with_data == simulate_handoff(h, "never_answers")            # all-reachable fallback


def test_batch_simulation_walks_channel_fallback():
    h = _h()                                                            # app (24 h) -> whatsapp
    res = run_batch([h], relevance_threshold=T, simulate=True, persona="app_push_dead")
    assert [r["channel"] for r in res.responses] == ["app", "whatsapp"]
    assert res.items[0].response["status"] == "completed"


def test_sheet_keeps_answers_around_a_skipped_middle_question():
    s = load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]
    for closed in (True, False):
        r = simulate_sheet(s, "app", ["q1", "q3"], closed=closed)
        assert set(r["answers"]) == {"q1", "q3"}, closed
        assert [i["result"] for i in r["items"]] == ["answered", "skipped", "answered"]
        assert r["status"] == "partial" and r["complete"] is False
        assert r["sheet_outcome"] == ("closed_partway" if closed else "finished")
        assert not errors("response", r)


def test_sheet_partial_close_retains_answers_and_marks_shown_step_skipped():
    s = load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]
    r = simulate_sheet(s, "web", ["q1"], closed=True)
    assert r["answers"] == {"q1": "yes"}
    assert [i["result"] for i in r["items"]] == ["answered", "skipped", "not_reached"]
    assert r["raw_event"] == "Close tapped at step 2 of 3"
    assert r["farmerchat_reply"] == {"http_status": 201, "outcome": "accepted"}


def test_sheet_finished_matches_a_full_submission():
    s = load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]
    r = simulate_sheet(s, "app", ["q1", "q2", "q3"])
    assert r == simulate(s, "app", "completed")                         # one record, same as finishing


@pytest.mark.parametrize("ids,closed", [(["q1", "q9"], True), (["q1", "q1"], True),
                                        (["q1", "q2", "q3"], True)])
def test_sheet_rejects_ambiguous_input(ids, closed):
    s = load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]
    with pytest.raises(ValueError):
        simulate_sheet(s, "app", ids, closed=closed)


def test_sheet_tap_order_does_not_change_the_record():
    s = load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]
    assert simulate_sheet(s, "app", ["q3", "q1"], closed=True) == simulate_sheet(s, "app", ["q1", "q3"], closed=True)


def test_sheet_negative_answer_on_partial_close_flags_follow_up():
    s = load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]
    q2 = s["items"][1]                                                  # q2 has a follow-up option
    bad = next(o["value"] for o in q2["options"] if o.get("follow_up"))
    r = simulate_sheet(s, "app", ["q1", "q2"], closed=True, answers={"q2": bad})
    assert r["status"] == "negative_outcome" and r["needs_follow_up"] and r["follow_up_reasons"]
    assert not errors("response", r)


# ===================================================== 5. late answers
def _validate_with_late(record):
    """Validate against response.schema.json plus the optional boolean `late` P3 asked P1 for.
    Built in memory with P1's own $ref registry: the committed schema is P1's and must keep
    matching the organisers' pack, so this test does not edit it."""
    from jsonschema import Draft202012Validator
    from mel.data.validate import _registry
    s = json.loads((SCHEMAS / "response.schema.json").read_text(encoding="utf-8"))
    s["properties"]["late"] = {"type": "boolean"}
    return [e.message for e in Draft202012Validator(s, registry=_registry()).iter_errors(record)]


def test_late_answer_after_expiry_is_kept_and_marked(monkeypatch):
    monkeypatch.setattr(sim, "_EMIT_LATE", True)
    s = load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]
    after = fmt_ist(parse_ist(expires_at(s["send_window"])) + timedelta(seconds=1))
    r = simulate_sheet(s, "app", ["q1", "q2"], closed=True, submit_at=after)
    assert r["late"] is True and set(r["answers"]) == {"q1", "q2"}
    assert _validate_with_late(r) == []                                 # valid once P1 adds the field
    assert errors("response", r) == ["<root>: Additional properties are not allowed ('late' was unexpected)"]


def test_answer_exactly_at_expiry_is_not_late(monkeypatch):
    monkeypatch.setattr(sim, "_EMIT_LATE", True)
    s = load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]
    r = simulate_sheet(s, "app", ["q1"], closed=True, submit_at=expires_at(s["send_window"]))
    assert "late" not in r and not errors("response", r)


def test_simulate_never_writes_late_false(monkeypatch):
    monkeypatch.setattr(sim, "_EMIT_LATE", True)
    s = load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]
    for ch in ("app", "web", "whatsapp", "telegram", "voice"):
        for case in sim.cases_for(ch):
            assert sim.simulate(s, ch, case).get("late") is not False, (ch, case)


def test_late_flag_off_by_default_keeps_answer_and_today_schema():
    s = load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]
    after = fmt_ist(parse_ist(expires_at(s["send_window"])) + timedelta(days=1))
    r = simulate_sheet(s, "web", ["q1"], closed=True, submit_at=after)
    assert "late" not in r and r["answers"] == {"q1": "yes"} and not errors("response", r)


# ===================================================== 6. frequency ranking in the real path
def _ins(iid, fid, crop, ts, state="Bihar", district="Patna"):
    return {"insight_id": iid, "farmer_id": fid, "asset": {"name": crop}, "concern": "pest_disease",
            "created_at": ts, "location": {"country": "IN", "state": state, "district": district}}


def _tie_pair():
    """Two farmers' hand-offs opening at the same instant; F-BUSY asked about mustard 4 times
    in the fortnight before, F-QUIET once."""
    a = _copy(_h(), "H-QUIET", ["I-Q0"], farmer="F-QUIET")
    b = _copy(_h(), "H-BUSY", ["I-B0"], farmer="F-BUSY")
    nb = _nb(a)
    hist = [_ins("I-Q0", "F-QUIET", "mustard", fmt_ist(nb - timedelta(days=30)))]
    hist += [_ins(f"I-B{i}", "F-BUSY", "mustard", fmt_ist(nb - timedelta(days=d)))
             for i, d in enumerate((40, 5, 3, 1))]
    return a, b, hist


def test_ranker_breaks_same_start_ties_in_the_batch_and_explains_why():
    a, b, hist = _tie_pair()
    plain = run_batch([a, b], relevance_threshold=T)
    assert [it.input_id for it in plain.items] == ["H-BUSY", "H-QUIET"] or \
           [it.input_id for it in plain.items] == ["H-QUIET", "H-BUSY"]
    ranked = run_batch([a, b], relevance_threshold=T, ranker=FrequencyScheduler.from_insights(hist))
    assert [it.input_id for it in ranked.items] == ["H-BUSY", "H-QUIET"]
    sig = ranked.items[0].signals
    assert sig["frequency"]["is_peak"] is True and sig["frequency"]["topic"] == "mustard"
    assert sig["season_stage"] is not None                              # mustard is in a calendar stage
    assert sig["climate_context_missing"] is True and sig["climate_component"] == 0.0


def test_rank_never_moves_a_survey_ahead_of_an_earlier_window():
    a, b, hist = _tie_pair()
    a = _copy(a, "H-QUIET", ["I-Q0"], shift=-timedelta(days=1), farmer="F-QUIET")
    res = run_batch([a, b], relevance_threshold=T, ranker=FrequencyScheduler.from_insights(hist))
    assert [it.input_id for it in res.items] == ["H-QUIET", "H-BUSY"]


def test_season_scheduler_uses_the_ranker_for_ties():
    a, b, hist = _tie_pair()
    sched = SeasonScheduler(fmt_ist(_nb(a)), relevance_threshold=T, ranker=FrequencyScheduler.from_insights(hist))
    sched.admit_all([a, b])
    assert [h["handoff_id"] for h in sched.pending] == ["H-BUSY", "H-QUIET"]


def test_peak_never_bypasses_quality_or_cap():
    a, b, hist = _tie_pair()
    b["survey"]["self_eval"]["relevance_score"] = 0.1
    res = run_batch([a, b], relevance_threshold=T, ranker=FrequencyScheduler.from_insights(hist))
    assert {it.input_id: it.decision for it in res.items}["H-BUSY"] == "rejected"


def test_frequency_peak_has_no_look_ahead():
    hist = [_ins(f"I{i}", "F1", "mustard", f"2027-01-{d:02d}T09:00:00+05:30") for i, d in enumerate((2, 10, 12, 14))]
    mon = FrequencyMonitor(hist)
    early = mon.peak("F1", "mustard", as_of="2027-01-05T07:00:00+05:30")
    assert early.n_history == 1 and not early.is_peak                   # January 10-14 not visible yet


def test_climate_provider_gets_the_insights_own_region():
    seen = []
    clim = ClimateContext(provider=lambda st, dist, on: seen.append((st, dist)) or 0.5)
    a, _, hist = _tie_pair()
    hist[0]["location"] = {"country": "IN", "state": "Bihar", "district": "Gaya"}
    FrequencyScheduler.from_insights(hist, climate=clim).explain(a)
    assert seen == [("Bihar", "Gaya")]


def test_unknown_insight_gives_neutral_signals_not_invented_ones():
    h = _h()
    r = FrequencyScheduler.from_insights([]).explain(h)
    assert r.signals["frequency"]["is_peak"] is False
    assert r.signals["climate_context_missing"] is True and r.signals["climate_component"] == 0.0


# ===================================================== 7. real data, determinism, reference grid
def test_pipeline_batch_output_is_schema_valid_and_within_cap():
    hs = _pipeline_handoffs()
    res = run_batch(hs, relevance_threshold=T, simulate=True,
                    ranker=FrequencyScheduler.from_insights(load_insights()))
    assert sum(res.counts[k] for k in ("sent", "moved", "merged", "skipped", "opted_out", "rejected")) == len(hs)
    assert res.counts["cap_violations"] == 0
    for h in res.handoffs_to_send:
        assert not errors("schedule_handoff", h), h["handoff_id"]
    for r in res.responses:
        assert not errors("response", r), r["response_key"]
    assert len({r["response_key"] for r in res.responses}) == len(res.responses)   # nothing overwritten


def test_batch_and_season_runs_are_deterministic():
    hs = _pipeline_handoffs()
    a = run_batch(hs, relevance_threshold=T, simulate=True, seed=0)
    b = run_batch(hs, relevance_threshold=T, simulate=True, seed=0)
    assert a.counts == b.counts and a.responses == b.responses

    def walk():
        sched = SeasonScheduler(relevance_threshold=T, seed=0)
        sched.admit_all(copy.deepcopy(hs))
        out = []
        while not sched.is_season_over():
            out += [(r.handoff_id, r.channel, r.record["response_key"]) for r in sched.run_due()]
            sched.advance(1)
        return out, sched.metrics()
    assert walk() == walk()


def test_reference_grid_matches_all_183_records():
    from mel.simulator.reference_check import compare
    rep = compare()
    assert (rep["total"], rep["matched"], rep["mismatches"], rep["ignored_fields"]) == (183, 183, [], [])
