"""P2: decision cascade."""
import json
from pathlib import Path

import pytest

from mel.data import load_scenario, list_scenarios, load_golden
from mel.data.validate import errors
from mel.decision import decide


@pytest.fixture(autouse=True)
def brief_policy(monkeypatch):
    monkeypatch.setenv("MEL_TIMING_BASIS", "brief")


def insight():
    return load_scenario("1-mustard-aphid-spray")["insight"]


def test_worked_scenarios():
    for n in list_scenarios():
        s = load_scenario(n)
        assert decide(s["insight"]).survey == (s["no_survey"] is None), n


def test_golden_mock_accuracy_floor():
    g = load_golden()
    acc = sum(decide(x["insight"]).survey == x["expected"]["survey"] for x in g) / len(g)
    assert acc >= 0.9  # raise this as R7 improves


def test_junk_never_surveyed():
    for x in load_golden():
        if x["insight"].get("quality_flag") == "junk":
            assert decide(x["insight"]).rule == "R1"


@pytest.mark.parametrize("changes,rule", [
    ({"quality_flag": "junk", "severity": "critical"}, "R1"),
    ({"severity": "critical", "resolution_type": "needs_more_context"}, "R2"),
    ({"resolution_type": "generic_information"}, "R3"),
    ({"resolution_type": "needs_more_context"}, "R4"),
    ({"verification": {"needed": False, "timing": "none", "method": "none"}}, "R5"),
    ({"created_at": "2027-03-31T09:00:00+05:30"}, "R6"),
    ({"created_at": "2027-03-22T09:00:00+05:30"}, "R7"),
    ({}, "R8"),
])
def test_every_rule_and_precedence(changes, rule):
    i = insight()
    i.update(changes)
    d = decide(i)
    assert d.rule == rule
    assert d.survey is (rule == "R8")
    if not d.survey:
        record = d.no_survey_record(i)
        assert errors("no_survey", record) == []
        assert d.reason_code in record["reason"]


@pytest.mark.parametrize("bad", [
    {"created_at": "2027-02-30T09:00:00+05:30"},
    {"created_at": "2026-13-01T09:00:00+05:30"},
    {"created_at": "2026-12-01T25:00:00+05:30"},
    {"farmer_id": None}, {"insight_id": 123},
    {"verification": {}}, {"action_window_days": -1},
])
def test_invalid_inputs_are_rejected_without_crashing(bad):
    i = insight()
    i.update(bad)
    d = decide(i)
    assert d.rule == "R1"
    assert errors("no_survey", d.no_survey_record(i)) == []


@pytest.mark.parametrize("asset,concern", [
    ({"name": "potato", "category": "crop", "growth_stage": "post_harvest"}, "pest_disease"),
    ({"name": "potato", "category": "crop", "growth_stage": None}, "storage_post_harvest"),
    ({"name": "cow", "category": "livestock", "growth_stage": None}, "livestock_health"),
])
def test_storage_and_livestock_are_not_blocked_by_crop_harvest(asset, concern):
    i = insight()
    i.update(created_at="2027-03-17T09:00:00+05:30", asset=asset, concern=concern)
    assert decide(i).rule == "R8"


def test_harvest_blocks_standing_crop_advice():
    i = insight()
    i.update(created_at="2027-03-17T09:00:00+05:30",
             asset={"name": "potato", "category": "crop", "growth_stage": "vegetative"})
    assert decide(i).rule == "R7"


def test_full_golden_answer_key_policy(monkeypatch):
    """Integration regression: all R1-R8 and 95 expected windows, no ID lookups."""
    monkeypatch.setenv("MEL_TIMING_BASIS", "answer_key")
    path = Path(__file__).resolve().parents[1] / "mel-survey-agent-participant-pack/participant-pack/data/golden_set.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        d, expected = decide(row["insight"]), row["expected"]
        assert (d.survey, d.rule) == (expected["survey"], expected["rule"]), row["golden_id"]
        if d.survey:
            assert d.send_window == {
                "not_before": expected["send_window"]["start"],
                "not_after": expected["send_window"]["end"],
            }, row["golden_id"]
