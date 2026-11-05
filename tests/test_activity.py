"""Activity attention (mel.data.activity) + its pipeline wiring. Owner: P1.

Covers spec R-12 with hand-built, schema-valid farmers so the thresholds are exercised directly, plus the
cross-cutting guarantees: the 7-day high-promotion budget, opt-out/fatigue still win over a surge, filtered and
full runs agree, robustness to broken rows, and the full-pack on/off invariants.
"""
import datetime

import pytest

from mel.config import PACK
from mel.data import load_insights
from mel.data.activity import ActivityHistory, Attention, settings, with_high_budget_spent, _poisson_tail
from mel.pipeline import run_pipeline
from mel.schedule.handoff import adjust_priority, build_handoff

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
BASE = datetime.datetime(2027, 1, 1, 9, 0, tzinfo=IST)
FULL_DATA = PACK / "data"
has_pack = (FULL_DATA / "insights.jsonl").exists()


def D(n: int) -> datetime.datetime:
    return BASE + datetime.timedelta(days=n)


def ins(iid, fid, cid, day, **kw):
    """A schema-valid insight on dataset-day `day` (int, days after BASE). why_junk() must accept it,
    otherwise the activity module treats it as junk and ignores it."""
    d = {
        "insight_id": iid, "farmer_id": fid, "conversation_id": cid,
        "created_at": D(day).isoformat(), "conversation_language": "en-IN",
        "location": {"country": "IN", "state": "Bihar", "district": "Patna"},
        "asset": {"name": "wheat", "category": "crop", "growth_stage": "vegetative"},
        "concern": "pest_disease", "behavioral_intent": "diagnosing",
        "decision_episode_type": "problem_resolution", "severity": "low",
        "query_summary": "farmer asks about a pest problem in the wheat crop field and needs help",
        "advice_summary": "advised to spray a recommended fungicide as per the product label on the field",
        "resolution_type": "direct_action", "action_window_days": 10,
        "verification": {"needed": True, "timing": "three_to_ten_days", "method": "push"},
        "preferred_channel": "app", "quality_flag": "clean",
    }
    d.update(kw)
    return d


def high(iid, fid, cid, day, **kw):
    """A high-weight (urgent) insight: escalate_to_expert + high severity."""
    return ins(iid, fid, cid, day, resolution_type="escalate_to_expert", severity="high", **kw)


def tier_of(rows, target):
    return ActivityHistory(rows).attention_for(target)


# --------------------------------------------------------------------------- the module

def test_quiet_then_high_weight_is_surge():
    rows = [ins("Q0", "F", "C0", 0), high("QX", "F", "CX", 40)]
    a = tier_of(rows, rows[1])
    assert (a.tier, a.reason) == ("surge", "quiet_then_high_weight")
    assert a.weight == settings()["weights"]["surge"] == 1.5
    assert a.explanation and isinstance(a.explanation, str)


def test_same_high_question_from_steady_heavy_is_steady_high():
    heavy = [ins(f"H{d}", "F", f"C{d}", d) for d in range(0, 40, 3)]
    heavy.append(high("HX", "F", "CX", 40))
    a = tier_of(heavy, heavy[-1])
    assert (a.tier, a.reason) == ("steady_high", "none")
    assert a.baseline_per_week >= settings()["steady_high_baseline"]


def test_steady_high_priority_stays_high_for_a_brief_high_survey():
    # The safety rule: a steady heavy user's urgent question is never demoted.
    heavy = [ins(f"H{d}", "F", f"C{d}", d) for d in range(0, 40, 3)]
    heavy.append(high("HX", "F", "CX", 40))
    att = tier_of(heavy, heavy[-1]).as_dict()
    assert att["tier"] == "steady_high"
    # brief priority of an escalate+high insight is "high"; steady_high must leave it high
    h = build_handoff(heavy[-1], {"survey_id": "S-1", "farmer_id": "F", "source_insight_ids": ["HX"],
                                  "language": "en-IN", "send_window": {"not_before": D(45).isoformat(),
                                  "not_after": D(50).isoformat()}, "items": []}, att)
    assert h["priority"] == "high" and h["frequency_cap"]["exempt"] is True


def test_heavy_farmer_going_quiet_is_neutral_unchanged():
    # busy early, then silent; the insight itself is a normal (non-urgent) question.
    rows = [ins(f"H{d}", "F", f"C{d}", d) for d in range(0, 30, 3)]
    rows.append(ins("QX", "F", "CX", 55))   # 25 days after the last chat: recent rate well below baseline
    a = tier_of(rows, rows[-1])
    assert a.tier == "neutral"
    assert a.reason in ("declining", "none")


def test_heavy_then_quiet_then_returns_still_neutral():
    # Another farmer anchors the dataset start early; F is heavy early, then silent long enough that the heavy
    # chats fall out of the returning insight's 70->14 baseline window, so F is not "steady" any more.
    other = [ins("O", "G", "CO", 0)]
    rows = other + [ins(f"H{d}", "F", f"C{d}", d) for d in range(0, 30, 3)]
    rows.append(ins("BACK", "F", "CBACK", 110))   # 80+ days after the last heavy chat: baseline ~0, recent low
    a = tier_of(rows, rows[-1])
    assert a.tier == "neutral"


def test_gradual_growth_is_not_a_surge():
    rows = [ins(f"G{d}", "F", f"C{d}", d) for d in (0, 7, 14, 21, 28, 33, 36)]
    rows.append(ins("GX", "F", "CGX", 40))
    a = tier_of(rows, rows[-1])
    assert a.tier != "surge"


def test_insight_in_first_28_days_is_insufficient_history():
    rows = [ins("E0", "F", "C0", 0), high("E1", "F", "C1", 20)]  # 20 < 28 days after dataset start
    assert tier_of(rows, rows[1]).reason == "insufficient_history"


def test_new_farmer_late_in_season_can_surge():
    # dataset starts day 0 (another farmer), this farmer's first ever chat is day 50 and is urgent.
    rows = [ins("OTHER", "G", "CO", 0), high("NEW", "F", "CN", 50)]
    a = tier_of(rows, rows[1])
    assert a.tier == "surge" and a.reason == "quiet_then_high_weight"


def test_adding_later_insights_never_changes_an_earlier_result():
    early = [ins("A", "F", "CA", 0), high("B", "F", "CB", 40)]
    before = tier_of(early, early[1])
    later = early + [ins("C", "F", "CC", 45), high("E", "F", "CE", 60)]
    after = tier_of(later, later[1])     # same insight B, now with future rows present
    assert before == after


def test_junk_and_extra_insights_in_one_conversation_do_not_raise_counts():
    rows = [ins("K0", "F", "C0", 0)]
    # three extra insights all in ONE conversation C1 in the baseline window -> counts as 1 conversation
    rows += [ins(f"K1_{n}", "F", "C1", 30 + n) for n in range(3)]
    # a junk row (quality_flag) in its own conversation -> must not count
    rows.append(ins("JUNK", "F", "CJUNK", 31, quality_flag="junk"))
    rows.append(high("KX", "F", "CX", 40))
    baseline_with = tier_of(rows, rows[-1]).baseline_per_week
    # Remove the duplicates/junk, keep one real conversation: baseline must match.
    lean = [ins("K0", "F", "C0", 0), ins("K1", "F", "C1", 30), high("KX", "F", "CX", 40)]
    assert tier_of(rows, rows[-1]).baseline_per_week == pytest.approx(tier_of(lean, lean[-1]).baseline_per_week)
    assert baseline_with > 0


def test_broken_rows_do_not_crash_or_count():
    rows = [
        ins("OK", "F", "C0", 0),
        {"insight_id": "NOTS", "farmer_id": "F", "conversation_id": "CB", "created_at": "not-a-date"},
        {"insight_id": "NOFID", "conversation_id": "CC", "created_at": D(5).isoformat()},
        "this is not even a dict",
        high("GOOD", "F", "CX", 40),
    ]
    h = ActivityHistory(rows)              # must not raise
    assert h.dataset_start == D(0)         # computed only from the one usable, non-junk row
    a = h.attention_for(rows[-1])
    assert a.tier in ("surge", "neutral", "steady_high")


def test_poisson_tail_edge_cases():
    assert _poisson_tail(0, 0.0) == 1.0
    assert _poisson_tail(3, 0.0) == 0.0          # silent baseline, a 3-burst is a clear jump
    assert 0.0 < _poisson_tail(5, 1.0) < 1.0


def test_activity_jump_fires_on_a_real_burst():
    # Dataset start is anchored early by another farmer. F has an (essentially) silent baseline window and then
    # a burst of 3 conversations in the last 14 days -> Poisson tail ~0 -> activity_jump.
    other = [ins("O", "G", "CO", 0)]
    rows = other + [ins(f"J{d}", "F", f"CJ{d}", d) for d in (90, 94, 98)]
    rows.append(ins("JX", "F", "CX", 100))
    a = tier_of(rows, rows[-1])
    assert a.tier == "surge" and a.reason == "activity_jump", (a.baseline_per_week, a.recent_count)


# --------------------------------------------------------------------------- 7-day high budget (in run_pipeline)

def test_burst_promotes_to_high_only_once_in_7_days():
    # A farmer with several activity_jump surges a few days apart. Each would promote normal->high, but only the
    # first within any 7-day window may; the budget is applied in run_pipeline over the unfiltered set.
    # Dataset start anchored early by another farmer; F is silent through the baseline window, then a dense run
    # of conversations in days 84-96. Each urgent insight (medium severity -> brief priority normal) on days
    # 90/93/96 sees >=3 recent conversations against a ~0 baseline, so each is an activity_jump surge. The 7-day
    # budget must let at most one of them become high.
    rows = [ins("O", "G", "CO", 0)]
    rows += [ins(f"F{d}", "F", f"CF{d}", d) for d in (47, 49, 51)]
    jumps = [ins(f"J{d}", "F", f"CJ{d}", d, severity="medium") for d in (55, 58, 61)]
    rows += jumps
    res = run_pipeline(rows, attention=True)
    prio, reason = {}, {}
    for ins_row, out in zip(res.insights, res.outputs):
        reason[ins_row["insight_id"]] = (getattr(out["decision"], "attention", None) or {}).get("reason")
        if "handoff" in out:
            prio[ins_row["insight_id"]] = out["handoff"]["priority"]
    jumps = [iid for iid in ("J55", "J58", "J61") if reason.get(iid) == "activity_jump"]
    assert len(jumps) >= 2, reason    # need at least two jump surges to prove the budget caps them
    promoted = [iid for iid in jumps if prio.get(iid) == "high"]
    assert len(promoted) <= 1, prio   # at most one high within the rolling 7-day window


def no_survey(iid, fid, cid, day, **kw):
    """A schema-valid insight that gets NO survey (verification not needed -> R5), brief priority normal."""
    return ins(iid, fid, cid, day, severity="medium",
               verification={"needed": False, "timing": "none", "method": "none"}, **kw)


def test_no_survey_chat_does_not_spend_the_high_budget():
    # Only a row that actually becomes a survey may use the 7-day high slot. Here every activity-building chat
    # and the day-55 chat are no-survey (R5); the only real survey is on day 58. Before the fix, a no-survey
    # activity_jump chat consumed the slot and left the later real survey at normal; after the fix it does not,
    # so the real survey is still promoted to high.
    rows = [ins("O", "G", "CO", 0)]
    rows += [no_survey(f"F{d}", "F", f"CF{d}", d) for d in (47, 49, 51)]   # build recent activity, no surveys
    rows.append(no_survey("NOSURV", "F", "CNS", 55))                        # would-be activity_jump, but no survey
    rows.append(ins("SURV", "F", "CSV", 58, severity="medium"))            # the only real survey (R8), normal brief prio
    res = run_pipeline(rows, attention=True)
    out = {i["insight_id"]: o for i, o in zip(res.insights, res.outputs)}

    # The no-survey chat produced no hand-off, and in the attention map it was an activity_jump surge that did
    # NOT spend the budget (no high_budget flag), so it never blocks the later real survey.
    amap = __import__("mel.pipeline", fromlist=["_attention_by_insight_id"])._attention_by_insight_id(rows)
    assert "handoff" not in out["NOSURV"]
    assert amap["NOSURV"]["reason"] == "activity_jump"
    assert amap["NOSURV"].get("high_budget") is None
    assert amap["SURV"]["reason"] == "activity_jump"
    assert amap["SURV"].get("high_budget") is None

    # End to end: the real survey is an activity_jump surge and got the high slot.
    assert out["SURV"]["handoff"]["priority"] == "high"


def test_adjust_priority_honours_the_spent_budget():
    surge = Attention("surge", "activity_jump", 0.1, 4, 1.5, "x").as_dict()
    spent = with_high_budget_spent(Attention("surge", "activity_jump", 0.1, 4, 1.5, "x")).as_dict()
    i = ins("I", "F", "C", 40, severity="medium")   # brief priority normal
    assert adjust_priority("normal", i, surge) == "high"
    assert adjust_priority("normal", i, spent) == "normal"
    assert adjust_priority("low", i, surge) == "normal"            # one step up, not to high
    steady = Attention("steady_high", "none", 2.0, 1, 0.5, "x").as_dict()
    assert adjust_priority("normal", i, steady) == "low"
    assert adjust_priority("high", i, steady) == "high"            # never demote a brief-high


# --------------------------------------------------------------------------- opt-out / fatigue still win

def test_surge_farmer_still_shortened_by_fatigue():
    from mel.writer import FarmerMemory
    from mel.writer.compose import compose_survey
    # A light-user surge normally keeps up to 3 (H4 skipped), but H3 fatigue still shortens.
    mem = FarmerMemory([], {"F": {"activity_level": "light", "crops": "wheat"}})
    # three unanswered prior surveys -> H3 cuts to 1
    for n in range(3):
        mem.record_response({"farmer_id": "F", "recorded_at": D(n).isoformat(),
                             "status": "expired", "counts_toward_cap": True, "answers": {}})
    i = ins("I", "F", "C", 40, resolution_type="direct_action", severity="medium")
    s = compose_survey({"send_window": {"not_before": D(45).isoformat(), "not_after": D(50).isoformat()}},
                       i, "en-IN", memory=mem, attention={"tier": "surge"})
    assert len(s["items"]) == 1        # H3 fatigue wins even for a surge
    assert not any(rule == "H4" for rule, _ in s["_history"])   # and no H4 note was emitted


def test_steady_high_trim_drops_the_personalised_note_it_cut():
    from mel.writer import FarmerMemory
    from mel.writer.history import personalize
    from mel.writer.templates import build_items
    from mel.writer.compose import compose_survey
    # A repeat problem (same crop + concern earlier) triggers H1, which adds a personalised question as the 3rd
    # item of a direct_action survey. steady_high caps the survey at 2, cutting that H1 question -> its note
    # must be dropped so the rationale never claims a question the survey does not ask.
    prior = ins("P", "F", "CP", 40, resolution_type="direct_action", severity="medium")
    cur = ins("I", "F", "CI", 50, resolution_type="direct_action", severity="medium")
    mem = FarmerMemory([prior, cur], {"F": {"activity_level": "regular", "crops": "wheat"}})

    # With no attention: H1 fires, the survey keeps 3 items and the H1 note is present.
    items_plain, notes_plain = personalize(build_items(cur, "golden"), cur, mem)
    assert any(rule == "H1" for rule, _ in notes_plain)
    assert len(items_plain) == 3

    # With steady_high: the survey is trimmed to 2 and the H1 note is gone.
    items_sh, notes_sh = personalize(build_items(cur, "golden", {"tier": "steady_high"}), cur, mem,
                                     {"tier": "steady_high"})
    assert len(items_sh) == 2
    assert not any(rule in ("H1", "H2") for rule, _ in notes_sh), notes_sh

    # End to end: the composed survey's rationale and _history carry no H1/H2 claim.
    s = compose_survey({"send_window": {"not_before": D(55).isoformat(), "not_after": D(60).isoformat()}},
                       cur, "en-IN", memory=mem, attention={"tier": "steady_high"})
    assert len(s["items"]) == 2
    assert not any(rule in ("H1", "H2") for rule, _ in s["_history"])
    assert "H1" not in s["rationale"] and "H2" not in s["rationale"]


# --------------------------------------------------------------------------- filtered == full

def test_filtered_and_full_runs_agree_for_the_same_farmer():
    rows = [ins("O0", "G", "CO0", 0)] + [ins(f"H{d}", "F", f"C{d}", d) for d in range(0, 30, 3)]
    rows.append(high("FX", "F", "CFX", 50))
    full = run_pipeline(rows, attention=True)
    only_f = run_pipeline(rows, farmer="F", attention=True)
    full_att = {i["insight_id"]: o["decision"].attention
                for i, o in zip(full.insights, full.outputs) if i["farmer_id"] == "F"}
    filt_att = {i["insight_id"]: o["decision"].attention
                for i, o in zip(only_f.insights, only_f.outputs)}
    assert full_att == filt_att and full_att
    # limit must not change a kept farmer's result either
    lim = run_pipeline(rows, limit=len(rows), attention=True)
    lim_att = {i["insight_id"]: o["decision"].attention for i, o in zip(lim.insights, lim.outputs)}
    assert all(lim_att[k] == full_att.get(k, lim_att[k]) for k in lim_att if k in full_att)


def test_input_order_does_not_change_the_result():
    rows = [ins("O0", "G", "CO0", 0)] + [ins(f"H{d}", "F", f"C{d}", d) for d in range(0, 30, 3)]
    rows.append(high("FX", "F", "CFX", 50))
    a = run_pipeline(rows, attention=True)
    b = run_pipeline(list(reversed(rows)), attention=True)
    amap = {i["insight_id"]: o["decision"].attention for i, o in zip(a.insights, a.outputs)}
    bmap = {i["insight_id"]: o["decision"].attention for i, o in zip(b.insights, b.outputs)}
    assert amap == bmap


# --------------------------------------------------------------------------- off == today, on is valid (full pack)

def test_attention_off_leaves_decisions_untouched():
    rows = load_insights()
    off = run_pipeline(rows)
    assert all(getattr(o["decision"], "attention", None) is None for o in off.outputs)


@pytest.mark.skipif(not has_pack, reason="full participant pack not present")
def test_full_pack_decision_and_rule_identical_on_off():
    rows = load_insights(FULL_DATA / "insights.jsonl")
    off = run_pipeline(rows)
    on = run_pipeline(rows, attention=True)
    assert len(off.outputs) == len(on.outputs) == len(rows)
    for a, b in zip(off.outputs, on.outputs):
        assert a["decision"].survey == b["decision"].survey
        assert a["decision"].rule == b["decision"].rule
        if a["decision"].survey:
            assert a["decision"].send_window == b["decision"].send_window


@pytest.mark.skipif(not has_pack, reason="full participant pack not present")
def test_full_pack_handoffs_valid_with_attention_on():
    from mel.data import errors
    rows = load_insights(FULL_DATA / "insights.jsonl")
    on = run_pipeline(rows, attention=True)
    bad = 0
    for o in on.outputs:
        if "handoff" in o:
            bad += bool(errors("schedule_handoff", o["handoff"]))
            assert o["handoff"]["priority"] in ("high", "normal", "low")
    assert bad == 0
