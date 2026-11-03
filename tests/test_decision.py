"""P2: decision cascade."""
from mel.data import load_scenario, list_scenarios, load_golden
from mel.decision import decide


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
