"""P5: end-to-end and eval smoke test."""
from mel.evaluation import score_golden


def test_eval_runs():
    r = score_golden()
    assert r["n"] > 0 and 0 <= r["decision_acc"] <= 1
