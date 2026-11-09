"""P1: loaders, schema validation, Excel parity, junk reasons."""

from pathlib import Path

import pytest

from mel.data import (
    list_scenarios,
    load_scenario,
    load_insights,
    errors,
    why_junk,
    load_insights_xlsx,
    check_insights_parity,
)
from mel.data.excel import _coerce, _unflatten

PACK = Path(__file__).resolve().parents[1] / "mel-survey-agent-participant-pack" / "participant-pack"
PACK_XLSX = PACK / "spreadsheets" / "insights.xlsx"
PACK_JSONL = PACK / "data" / "insights.jsonl"
has_pack = PACK_XLSX.exists() and PACK_JSONL.exists()


def test_scenarios_are_schema_valid():
    for n in list_scenarios():
        s = load_scenario(n)
        assert not errors("insight", s["insight"])
        for sv in s["surveys"].values():
            assert not errors("survey", sv)
        if s["handoff"]:
            assert not errors("schedule_handoff", s["handoff"])


def test_mock_insights_load():
    assert len(load_insights()) > 20


def test_why_junk_flags_labelled_and_broken_rows():
    clean = load_insights()[0]
    assert not errors("insight", clean) or clean.get("quality_flag") == "junk"
    # A labelled-junk row reports the label.
    labelled = {**clean, "quality_flag": "junk"}
    assert any("junk" in r for r in why_junk(labelled))
    # A schema-breaking row reports the schema problem.
    broken = {**clean, "behavioral_intent": None}
    reasons = why_junk(broken)
    assert any("schema" in r for r in reasons)


def test_why_junk_clean_row_has_no_reasons():
    clean_rows = [i for i in load_insights() if i.get("quality_flag") == "clean" and not errors("insight", i)]
    assert clean_rows, "the mock data must contain clean, schema-valid insights"
    for ins in clean_rows:
        assert why_junk(ins) == [], ins["insight_id"]


def test_coerce_types():
    assert _coerce("verification.needed", "true") is True
    assert _coerce("verification.needed", "false") is False
    assert _coerce("action_window_days", "5") == 5
    assert _coerce("action_window_days", None) is None
    assert _coerce("asset.name", "") is None
    assert _coerce("asset.name", "wheat") == "wheat"


def test_unflatten_nests_dotted_columns():
    flat = {
        "insight_id": "I-1",
        "location.country": "IN",
        "location.state": "Bihar",
        "verification.needed": "true",
    }
    out = _unflatten(flat)
    assert out["insight_id"] == "I-1"
    assert out["location"] == {"country": "IN", "state": "Bihar"}
    assert out["verification"] == {"needed": True}


@pytest.mark.skipif(not has_pack, reason="full participant pack not present")
def test_excel_matches_jsonl():
    rows = load_insights_xlsx(PACK_XLSX)
    assert len(rows) > 20
    assert check_insights_parity(PACK_XLSX, PACK_JSONL) == []
