"""P2: send time picks one moment inside the window, with a stated rule; downstream sends at it."""

from datetime import timedelta

import pytest

from mel.data import errors
from mel.data.loader import load_farmers, load_insights
from mel.decision import decide
from mel.pipeline import run_pipeline
from mel.simulator import simulate
from mel.timing import chat_hours, fmt_ist, parse_ist, pick_send_time
from mel.timing.calendar import harvest_period

WIN = {"not_before": "2026-11-20T07:00:00+05:30", "not_after": "2026-11-22T19:00:00+05:30"}


@pytest.fixture(autouse=True)
def brief_policy(monkeypatch):
    monkeypatch.setenv("MEL_TIMING_BASIS", "brief")


def ins(**kw):
    base = {
        "severity": "low",
        "preferred_channel": "app",
        "advice_summary": "Advised to weed the field.",
        "verification": {"method": "push"},
        "asset": {"name": "wheat", "category": "crop", "growth_stage": "vegetative"},
    }
    return {**base, **kw}


@pytest.mark.parametrize(
    "insight,farmer,hours,rule,send_at",
    [
        (ins(severity="high", preferred_channel="voice"), None, (), "high_severity", "2026-11-20T07:00:00+05:30"),
        (
            ins(advice_summary="Advised to spray in the evening.", preferred_channel="voice"),
            None,
            (),
            "advice_evening",
            "2026-11-20T07:00:00+05:30",
        ),
        (ins(preferred_channel="voice"), None, [14] * 6, "usual_time", "2026-11-20T13:00:00+05:30"),
        (ins(), {"activity_level": "light"}, [11] * 6, "usual_time", "2026-11-20T10:00:00+05:30"),
        (ins(), {"activity_level": "heavy"}, [11] * 6, "async_channel", "2026-11-20T07:00:00+05:30"),
        (
            ins(verification={"method": "ivr_callback"}),
            {"livestock": "cow"},
            (),
            "livestock_chores",
            "2026-11-20T13:00:00+05:30",
        ),
        (ins(preferred_channel="voice"), None, list(range(7, 19)), "call_default", "2026-11-20T16:00:00+05:30"),
    ],
)
def test_rules(insight, farmer, hours, rule, send_at):
    t = pick_send_time(insight, WIN, farmer, hours)
    assert (t["rule"], t["send_at"]) == (rule, send_at)
    assert t["assumption"] == (rule in {"harvest_busy", "livestock_chores", "call_default"})


def test_harvest_busy_calls_in_the_evening():
    start, _ = harvest_period("mustard")
    day = start.isoformat()
    win = {"not_before": f"{day}T07:00:00+05:30", "not_after": f"{day}T19:00:00+05:30"}
    t = pick_send_time(ins(preferred_channel="voice", asset={"name": "mustard", "category": "crop"}), win)
    assert (t["rule"], t["send_at"]) == ("harvest_busy", f"{day}T16:00:00+05:30")


def test_slot_outside_window_falls_back_to_opening():
    win = {"not_before": "2026-11-20T13:00:00+05:30", "not_after": "2026-11-20T15:00:00+05:30"}
    t = pick_send_time(ins(preferred_channel="voice"), win)
    assert (t["slot"], t["send_at"]) == (None, win["not_before"])


def test_chat_hours_ignores_other_farmers_and_the_future():
    rows = [
        {"farmer_id": "F-1", "created_at": "2026-11-01T09:00:00+05:30"},
        {"farmer_id": "F-1", "created_at": "2026-11-30T15:00:00+05:30"},
        {"farmer_id": "F-2", "created_at": "2026-11-01T18:00:00+05:30"},
        {"farmer_id": "F-1", "created_at": "not a date"},
        None,
    ]
    assert chat_hours(rows, "F-1", "2026-11-15T10:00:00+05:30") == [9]


def test_every_survey_time_is_inside_its_window_and_send_hours():
    insights, farmers = load_insights(), load_farmers()
    for i in insights:
        try:
            hist = chat_hours(insights, i.get("farmer_id"), i["created_at"])
        except (KeyError, TypeError, ValueError, OverflowError):
            hist = ()
        d = decide(i, farmers.get(i.get("farmer_id")), hist)
        if not d.survey:
            assert d.send_time is None
            continue
        at = parse_ist(d.send_time["send_at"])
        assert parse_ist(d.send_window["not_before"]) <= at <= parse_ist(d.send_window["not_after"]), i["insight_id"]
        assert 7 <= at.hour < 19, i["insight_id"]


def test_batch_run_sends_at_the_recommended_time():
    """The CLI's path: run_pipeline -> first channel -> simulate(send_at=decision.send_time)."""
    sent = 0
    for out in run_pipeline(load_insights(), farmers=load_farmers()).outputs:
        if "handoff" not in out:
            continue
        h, t = out["handoff"], out["decision"].send_time
        r = simulate(h["survey"], h["channel_order"][0]["channel"], "completed", send_at=t["send_at"])
        assert r["timestamps"]["sent"] == t["send_at"] and not errors("response", r)
        sent += 1
    assert sent


def test_pipeline_passes_chat_history_to_the_send_time():
    ins = next(i for i in load_insights() if decide(i).survey)
    ins = {
        **ins,
        "farmer_id": "F-999999",
        "preferred_channel": "voice",
        "severity": "low",
        "advice_summary": "Advised to weed the field.",
    }
    d0 = parse_ist(ins["created_at"])
    past = [
        {**ins, "insight_id": f"I-99999{n}", "created_at": fmt_ist((d0 - timedelta(days=n + 1)).replace(hour=14))}
        for n in range(6)
    ]
    t = run_pipeline(past + [ins]).outputs[-1]["decision"].send_time
    assert (t["rule"], t["slot"]) == ("usual_time", "afternoon")
