"""The Dashboard's cost section (app/dashboard.py) draws P5's Bedrock cost ledger (mel.evaluation.costs) without
errors, before and after a full run is recorded, and shows nothing while the ledger is empty."""
from streamlit.testing.v1 import AppTest

LEDGER = [
    {"run": 1, "at": "2026-11-05T09:00:00+05:30", "kind": "pilot", "label": "pilot, 20 insights", "writer": "haiku",
     "surveys": 20, "calls": 60, "cached_calls": 0, "spent_usd": 0.05, "by_purpose": {"write": {"usd": 0.04}},
     "usd_per_survey": 0.0025, "usd_per_1000_surveys": 2.5, "projected_full_usd": 6.54, "revisions": 2, "fallbacks": {}},
    {"run": 2, "at": "2026-11-05T10:00:00+05:30", "kind": "single", "label": "app: I-001996", "writer": "haiku",
     "surveys": 1, "calls": 3, "spent_usd": 0.003, "usd_per_survey": None, "usd_per_1000_surveys": None,
     "projected_full_usd": None},
    {"run": 3, "at": "2026-11-05T11:00:00+05:30", "kind": "batch", "label": "full pack", "writer": "haiku",
     "surveys": 2616, "calls": 7900, "spent_usd": 5.9, "usd_per_survey": 0.0023, "usd_per_1000_surveys": 2.26,
     "projected_full_usd": 5.9, "revisions": 40, "fallbacks": {"guard": 3}},
]
FULL = {"surveys": 2616, "seconds": 900, "cost": {"spent_usd": 5.9}, "revisions": 40, "surveys_revised": 30,
        "fallbacks": {"guard": 3}, "schema_invalid_files": 0, "judge_relevance": 4.6}


def _costs_app():
    import streamlit as st
    from app import dashboard
    dashboard._costs(st.session_state["ledger"], st.session_state.get("full"), 6999, 0.374)


def _run(ledger, full=None):
    at = AppTest.from_function(_costs_app, default_timeout=60)
    at.session_state["ledger"], at.session_state["full"] = ledger, full
    at.run()
    assert not at.exception, at.exception
    return " ".join(m.value for m in at.markdown)


def test_cost_calculator_with_and_without_a_full_run():
    screen = _run(LEDGER)
    assert "$0.0023" in screen and "$2.26" in screen and "not run yet" in screen  # priced from the latest batch run
    assert "2,590" in screen and "$5.96" in screen       # 37% of 6,999 conversations = 2,590 surveys x $0.0023
    screen = _run(LEDGER, FULL)
    assert "$5.90" in screen and "2,616 surveys in 15 min" in screen
    assert _run([]) == ""
