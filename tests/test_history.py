"""P4's history rules H1-H4 inside the team pipeline (moved from demo/p4_standalone on 4 Nov). Written by P5;
P4 owns mel/writer/history.py."""
import copy
from datetime import timedelta

import pytest

from mel.data import load_insights, load_farmers
from mel.pipeline import run_insight, run_pipeline, clean
from mel.timing import parse_ist, fmt_ist
from mel.writer import FarmerMemory, build_context, check_survey, history_notes, write_surveys


def _surveyed(resolution=None):
    for i in load_insights():
        if resolution and i.get("resolution_type") != resolution:
            continue
        out = run_insight(i)
        if out["decision"].survey:
            return i, out
    pytest.skip(f"mock data has no surveyed {resolution or ''} insight")


def _earlier(i, days, **kw):
    e = copy.deepcopy(i)
    e.update(insight_id=i["insight_id"] + f"-E{days}", conversation_id=i["conversation_id"] + f"-E{days}",
             created_at=fmt_ist(parse_ist(i["created_at"]) - timedelta(days=days)), **kw)
    return e


def _answer(i, days, status="completed", answers=None):
    return {"farmer_id": i["farmer_id"], "status": status, "answers": answers or {},
            "recorded_at": fmt_ist(parse_ist(i["created_at"]) - timedelta(days=days)), "counts_toward_cap": True}


def test_no_memory_means_no_change():
    i, out = _surveyed()
    assert history_notes(i, None) == []
    assert [s["items"] for s in write_surveys(i, out["decision"].send_window).values()] == \
           [s["items"] for s in out["surveys"].values()]


def test_h1_repeat_problem_asks_same_problem_again():
    i, out = _surveyed("direct_action")
    mem = FarmerMemory([i, _earlier(i, 10)], {})
    rules = [r for r, _ in history_notes(i, mem)]
    assert "H1" in rules
    s = write_surveys(i, out["decision"].send_window, memory=mem)["en-IN"]
    assert any("same problem" in it["prompt"] for it in s["items"]) and "Personalised: H1" in s["rationale"]


def test_h5_low_turned_high_asks_if_earlier_advice_was_followed():
    i, out = _surveyed("direct_action")
    i = {**i, "severity": "high"}
    mem = FarmerMemory([i, _earlier(i, 4, severity="low")], {})
    assert [r for r, _ in history_notes(i, mem)] == ["H5"]  # replaces H1: more specific
    surveys = write_surveys(i, out["decision"].send_window, memory=mem)
    q = next(it for it in surveys["en-IN"]["items"] if "looked mild" in it["prompt"])
    assert {o["value"]: o.get("follow_up") for o in q["options"]}["followed_worse"] == "advice_did_not_work"
    assert all(not check_survey(clean(s)) for s in surveys.values())
    same_level = FarmerMemory([i, _earlier(i, 4, severity="high")], {})
    assert [r for r, _ in history_notes(i, same_level)] == ["H1"]


def test_only_earlier_conversations_count():
    i, _ = _surveyed("direct_action")
    later = _earlier(i, -10)  # 10 days AFTER the insight: must not be used
    assert history_notes(i, FarmerMemory([i, later], {})) == []


def test_h2_known_barrier_and_h3_fatigue_and_h4_light_user():
    i, _ = _surveyed("direct_action")
    mem = FarmerMemory([i], {})
    mem.record_response(_answer(i, 2, answers={"q1": "no", "q3": "not_nearby"}))
    assert [r for r, _ in history_notes(i, mem)] == ["H2"]

    tired = FarmerMemory([i], {})
    for d in (6, 4, 2):
        tired.record_response(_answer(i, d, status="expired"))
    assert "H3" in [r for r, _ in history_notes(i, tired)]

    light = FarmerMemory([i], {i["farmer_id"]: {"activity_level": "light"}})
    ctx = build_context(i, light)
    assert ctx["activity_level"] == "light"


def test_every_personalised_survey_passes_format_and_guards():
    """On the mock sample, with real farmer profiles plus a barrier answer and three ignored surveys for every
    farmer, every personalised survey in both languages still passes the schema and the safety guards."""
    ins, farmers = load_insights(), load_farmers()
    for case in ("plain", "barrier", "fatigue"):
        mem = FarmerMemory(ins, farmers)
        for i in ins:
            if case == "barrier":
                mem.record_response(_answer(i, 1, answers={"q3": "too_costly"}))
            if case == "fatigue":
                for d in (3, 2, 1):
                    mem.record_response(_answer(i, d, status="expired"))
        for i in ins:
            out = run_insight(i, memory=mem)
            if out["decision"].survey:
                for s in out["surveys"].values():
                    assert check_survey(clean(s)) == [], (case, i["insight_id"], check_survey(clean(s)))
                    assert 1 <= len(s["items"]) <= 3


def test_run_pipeline_history_switch():
    ins, farmers = load_insights(), load_farmers()
    off = run_pipeline(ins, farmers=farmers)
    on = run_pipeline(ins, farmers=farmers, history=True)
    assert [o["decision"].rule for o in off.outputs] == [o["decision"].rule for o in on.outputs]
    assert all(not s.get("_history") for o in off.outputs for s in o.get("surveys", {}).values())
