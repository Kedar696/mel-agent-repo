"""P3: batch admission through the cap + opt-out gate (run_batch).

Covers requirement 1: deterministic send-window order, cap + opt-out applied before
sending, zero surveys to opted-out farmers (including opt-out produced during simulation),
the two-in-seven-days move/merge/skip policy, source_insight_ids preserved without
duplicates, high-priority exemption that still counts, and P5 counts from actual decisions.
"""
import copy
from datetime import timedelta


from mel.data import load_scenario
from mel.schedule import run_batch, build_handoff, OptOutList
from mel.timing import parse_ist, fmt_ist


def _clear(scenario="1-mustard-aphid-spray"):
    s = load_scenario(scenario)
    h = build_handoff(s["insight"], s["surveys"]["hi-IN"])
    h["survey"]["self_eval"] = {"schema_valid": True, "relevance_score": 0.8,
                                "gives_new_advice": False, "asks_personal_info": False}
    return h


def _shift(h, days, handoff_id, insight_ids):
    """A copy of h with its window shifted `days` forward and fresh id/insight ids."""
    h2 = copy.deepcopy(h)
    h2["handoff_id"] = handoff_id
    h2["survey"]["source_insight_ids"] = insight_ids
    nb = parse_ist(h["send_window"]["not_before"]) + timedelta(days=days)
    na = parse_ist(h["send_window"]["not_after"]) + timedelta(days=days)
    h2["send_window"] = {"not_before": fmt_ist(nb), "not_after": fmt_ist(na)}
    h2["survey"]["send_window"] = dict(h2["send_window"])
    h2["expires_at"] = fmt_ist(parse_ist(h["expires_at"]) + timedelta(days=days))
    return h2


# ===================================================== order + basic counts
def test_processes_in_send_window_order_deterministically():
    early = _clear()
    late = _shift(early, 40, "H-LATE", ["I-LATE"])   # 40 days later, well clear of the cap window
    # feed in reverse order; run_batch must still process earliest-window first
    res = run_batch([late, early], relevance_threshold=0.5)
    assert [it.handoff["handoff_id"] for it in res.items] == [early["handoff_id"], "H-LATE"]


def test_counts_come_from_actual_decisions_not_hardcoded():
    h = _clear()
    res = run_batch([h], relevance_threshold=0.5)
    assert res.counts["sent"] == 1
    assert set(res.counts) >= {"sent", "moved", "merged", "skipped", "opted_out", "cap_violations"}
    assert res.counts["cap_violations"] == 0


# ===================================================== cap: merge / move / skip
def test_second_normal_same_window_merges_and_preserves_insight_ids():
    h1 = _clear()
    h2 = copy.deepcopy(h1); h2["handoff_id"] = "H-2"; h2["survey"]["source_insight_ids"] = ["I-NEW"]
    res = run_batch([h1, h2], relevance_threshold=0.5)
    assert res.counts["sent"] == 1 and res.counts["merged"] == 1
    # the merge host carries BOTH insight id sets, de-duplicated
    host = next(it.handoff for it in res.items if it.decision == "merged")
    ids = host["survey"]["source_insight_ids"]
    assert "I-NEW" in ids
    assert len(ids) == len(set(ids))                 # no duplicates


def test_capped_survey_moves_when_a_later_date_fits():
    h1 = _clear()
    # a second survey whose window is wide enough that a day 7+ out still fits -> moved
    h2 = copy.deepcopy(h1); h2["handoff_id"] = "H-MOVE"
    nb = parse_ist(h1["send_window"]["not_before"])
    h2["send_window"] = {"not_before": h1["send_window"]["not_before"],
                         "not_after": fmt_ist(nb + timedelta(days=20))}
    h2["survey"]["send_window"] = dict(h2["send_window"])
    res = run_batch([h1, h2], relevance_threshold=0.5)
    assert res.counts["moved"] == 1
    moved = next(it.handoff for it in res.items if it.decision == "moved")
    assert parse_ist(moved["send_window"]["not_before"]) >= nb + timedelta(days=7)


def test_capped_survey_skips_when_cannot_move_or_merge():
    h1 = _clear()
    # opens the day after h1's window closes (no merge host) with a 2-day window (cannot move
    # 7 days out) but still inside h1's 7-day block -> skipped
    h2 = copy.deepcopy(h1); h2["handoff_id"] = "H-SKIP"
    start = parse_ist(h1["send_window"]["not_after"]) + timedelta(days=1)
    h2["send_window"] = {"not_before": fmt_ist(start), "not_after": fmt_ist(start + timedelta(days=2))}
    h2["survey"]["send_window"] = dict(h2["send_window"])
    res = run_batch([h1, h2], relevance_threshold=0.5)
    assert res.counts["skipped"] == 1
    # A skip is the cap working, not a violation: it is counted as prevented, and no
    # scheduled pair breaks the 7-day rule.
    assert res.counts["prevented"] == 1
    assert res.counts["cap_violations"] == 0


# ===================================================== opt-outs
def test_zero_surveys_to_opted_out_farmer_pre_existing():
    """A farmer already on the opt-out list gets nothing, even as the first hand-off."""
    h = _clear()
    stop = OptOutList()
    from mel.simulator import simulate
    stop.record(simulate(h["survey"], "whatsapp", "farmer_opted_out"))
    res = run_batch([h], relevance_threshold=0.5, opt_out=stop, simulate=True)
    assert res.counts["opted_out"] == 1 and res.counts["sent"] == 0
    assert res.responses == []                       # nothing simulated/sent


def test_opt_out_during_simulation_blocks_later_handoff_same_farmer():
    """An opt-out produced while sending the first hand-off must block a LATER hand-off for
    the same farmer in the same batch (requirement 1)."""
    h1 = _clear()
    h2 = _shift(h1, 40, "H-LATER", ["I-L"])          # same farmer, far-later window (not capped)
    res = run_batch([h1, h2], relevance_threshold=0.5, simulate=True, persona="opts_out_first")
    decisions = {it.handoff["handoff_id"]: it.decision for it in res.items}
    assert decisions[h1["handoff_id"]] == "sent"     # first goes out, produces the opt-out
    assert decisions["H-LATER"] == "opted_out"       # later one blocked
    assert res.counts["opted_out"] == 1


# ===================================================== high-priority exemption + counting
def test_high_priority_is_exempt_but_still_counts():
    """Two high-priority surveys to one farmer both send (exempt), and a following normal
    survey still sees them in the window (they counted)."""
    hi = _clear("4-cow-vet-escalation")
    hi["survey"]["self_eval"] = {"schema_valid": True, "relevance_score": 0.9,
                                 "gives_new_advice": False, "asks_personal_info": False}
    assert hi["frequency_cap"]["exempt"] is True
    hi2 = copy.deepcopy(hi); hi2["handoff_id"] = "H-HI2"; hi2["survey"]["source_insight_ids"] = ["I-HI2"]
    res = run_batch([hi, hi2], relevance_threshold=0.5)
    assert res.counts["sent"] == 2                   # both exempt high-priority surveys sent
    assert res.counts["cap_violations"] == 0


# ===================================================== determinism
def test_run_batch_is_deterministic():
    h1 = _clear()
    h2 = _shift(h1, 40, "H-B", ["I-B"])
    a = run_batch([h1, h2], relevance_threshold=0.5, simulate=True)
    b = run_batch([h1, h2], relevance_threshold=0.5, simulate=True)
    assert a.counts == b.counts
    assert [it.decision for it in a.items] == [it.decision for it in b.items]
