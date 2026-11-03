"""P1: loaders and schema validation."""
from mel.data import list_scenarios, load_scenario, load_insights, errors


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
