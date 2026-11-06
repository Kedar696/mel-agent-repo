"""Custom context in Survey Studio: the form fields become a schema-valid insight the real pipeline accepts."""

import re

import pytest

from app import custom_context as cc
from mel.config import PACK_DATA
from mel.data import errors, load_insights
from mel.writer.compose import survey_id_for
from mel.pipeline import run_insight, clean
from mel.timing.window import parse_ist

BASE = {
    "question": "Small green insects on the mustard flowers, what should I do?",
    "advice": "Spray neem oil in the evening and check the plants after three days.",
    "asset": "mustard",
    "concern": "pest_disease",
    "severity": "medium",
    "resolution": "direct_action",
    "days": 3,
    "check": "yes",
    "channel": "app",
    "language": "en-IN",
    "district": "Patna",
}


def build(**over):
    return cc.build_insight({**BASE, **over}, cc.new_ids(1), "2026-11-04T16:20:00+05:30")


def test_form_becomes_a_schema_valid_insight_that_gets_a_survey():
    ins = build()
    assert errors("insight", ins) == []
    out = run_insight(ins)
    assert out["decision"].survey and out["decision"].rule == "R8"
    assert set(out["surveys"]) == {"hi-IN", "en-IN"}
    assert errors("schedule_handoff", out["handoff"]) == []
    assert out["handoff"]["channel_order"][0]["channel"] == "app"  # the farmer's usual channel goes first
    assert ins["query_summary"] == BASE["question"] and ins["advice_summary"] == BASE["advice"]  # as typed


def test_missing_advice_means_needs_more_context_and_no_survey():
    ins = build(advice="   ")
    assert ins["resolution_type"] == "needs_more_context" and ins["advice_summary"] == cc.NO_ADVICE_TEXT
    assert errors("insight", ins) == []  # an empty summary would fail the schema and count as junk (R1)
    assert cc.effective_resolution({**BASE, "advice": ""})[1] == cc.NO_ADVICE_NOTE
    out = run_insight(ins)
    assert not out["decision"].survey and out["decision"].rule == "R4"


def test_critical_severity_is_a_human_call_not_a_survey():
    out = run_insight(build(severity="critical"))
    assert not out["decision"].survey and out["decision"].rule == "R2"
    out = run_insight(build(severity="critical", advice=""))  # blank advice does not demote it to R4
    assert not out["decision"].survey and out["decision"].rule == "R2"


def test_language_and_district_come_from_the_form():
    assert build()["conversation_language"] == "en-IN"  # English unless the user picks Hindi
    assert build(language="hi-IN")["conversation_language"] == "hi-IN"
    assert build(district=" Gaya ")["location"] == {"country": "IN", "state": "Bihar", "district": "Gaya"}
    assert cc.validate({**BASE, "district": "  "}) == ["Give the district in Details (any Bihar district)."]
    assert cc.validate({**BASE, "district": "x" * 81})[0].startswith("Keep the district under 80")


def test_ids_never_collide_with_pack_surveys_or_handoffs():
    pack = load_insights(PACK_DATA / "insights.jsonl")
    pack_surveys = {survey_id_for(i) for i in pack}
    pack_max = max(int(re.sub(r"\D", "", i["insight_id"])) for i in pack)
    for n in (1, 2, 500):
        ins = cc.build_insight(BASE, cc.new_ids(n), "2026-11-04T16:20:00+05:30")
        assert survey_id_for(ins) not in pack_surveys
        out = run_insight(ins)
        for sid in (out["handoff"]["survey"]["survey_id"], out["handoff"]["handoff_id"]):
            assert int(re.sub(r"\D", "", sid)) > pack_max, (
                sid
            )  # so admits / weekly-limit lookups cannot match a pack row


def test_no_check_back_means_no_survey():
    out = run_insight(build(check="no"))
    assert not out["decision"].survey and out["decision"].rule == "R5"


def test_whitespace_only_question_is_rejected_before_anything_runs():
    assert cc.validate({**BASE, "question": " \n\t "}) == ["Type what the farmer asked. The box is empty."]
    assert cc.validate({**BASE, "question": "x" * 401})[0].startswith("Keep what the farmer asked under 400")
    assert cc.validate({**BASE, "advice": "x" * 601})[0].startswith("Keep the advice under 600")
    assert cc.validate(BASE) == []


def test_ids_are_unique_per_submission_and_created_at_is_real_ist():
    assert cc.new_ids(1) != cc.new_ids(2)
    assert cc.new_ids(7)["insight_id"] == "I-900007"
    stamp = cc.now_ist()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+05:30", stamp)
    assert parse_ist(stamp).utcoffset().total_seconds() == 5.5 * 3600
    sub = cc.submission(BASE, 3)
    assert sub["insight"]["insight_id"] == "I-900003" and sub["note"] is None
    assert errors("insight", sub["insight"]) == []


@pytest.mark.parametrize("resolution", list(cc.ADVICE_TYPES))
def test_every_asset_problem_and_advice_type_runs_cleanly(resolution):
    """No combination the form allows may crash the pipeline, and every survey it writes must be valid."""
    for asset in cc.ASSETS:
        for concern in cc.CONCERNS:
            ins = build(asset=asset, concern=concern, resolution=resolution)
            assert errors("insight", ins) == [], (asset, concern, resolution)
            out = run_insight(ins)
            if out["decision"].survey:
                for s in out["surveys"].values():
                    assert errors("survey", clean(s)) == [], (asset, concern, resolution)


def test_model_reading_fills_the_details_and_the_timing():
    read = {
        "asset": "goat",
        "concern": "livestock_health",
        "severity": "high",
        "advice_type": "escalate_to_expert",
        "act_within_days": 1,
        "check_back": "next_day",
        "questions": 2,
        "nonsense": "x",
    }
    f = cc.apply_reading(BASE, read)
    assert (f["asset"], f["concern"], f["severity"], f["resolution"], f["days"], f["timing"], f["questions"]) == (
        "goat",
        "livestock_health",
        "high",
        "escalate_to_expert",
        1,
        "next_day",
        2,
    )
    ins = cc.build_insight(f, cc.new_ids(2), "2026-11-05T09:00:00+05:30")
    assert errors("insight", ins) == [] and ins["verification"]["timing"] == "next_day"
    out = run_insight(ins)
    assert out["decision"].survey and out["decision"].send_window["not_before"] == "2026-11-06T07:00:00+05:30"
    assert cc.submission(f, 2)["questions"] == 2 and cc.submission(BASE, 3)["questions"] is None
    assert cc.apply_reading(BASE, {"asset": "dragonfruit", "questions": 9})["asset"] == "mustard"  # unknown: as typed
    assert cc.apply_reading(BASE, {"advice_type": "generic_information"})["check"] == "no"
    note = cc.reading_note(f)
    assert (
        note.startswith("Bedrock read the conversation as: Goat") and "2 questions" in note and "the next day" in note
    )
    assert build()["verification"]["timing"] == "none"  # the form's default
