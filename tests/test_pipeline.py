"""P5: end-to-end and eval tests."""
import copy

from mel.data import load_insights
from mel.evaluation import (score_golden, run_scorecard, format_problems, safety_problems,
                            load_history, record_run)
from mel.pipeline import run_insight, clean


def _a_survey():
    for ins in load_insights():
        out = run_insight(ins)
        if out["decision"].survey:
            return {lang: clean(s) for lang, s in out["surveys"].items()}
    raise AssertionError("mock data has no surveyed insight")


def test_eval_runs():
    r = score_golden()
    assert r["n"] > 0 and 0 <= r["decision_acc"] <= 1


def test_scorecard_mock_batch_is_clean():
    c = run_scorecard(load_insights())
    assert c["n_surveyed"] > 0 and c["n_survey_files"] == 2 * c["n_surveyed"]
    assert c["format_pass"] == 1.0 and c["safety_pass"] == 1.0
    assert c["failed_but_scheduled"] == 0 and c["ms_per_insight"] > 0


def test_format_checks_catch_bad_surveys():
    s = _a_survey()
    assert format_problems(s["en-IN"], "en-IN") == [] and format_problems(s["hi-IN"], "hi-IN") == []
    four = copy.deepcopy(s["en-IN"])
    four["items"] = (four["items"] * 4)[:4]
    assert any("item count" in p for p in format_problems(four, "en-IN"))
    # English text where Hindi is expected
    assert any("no Hindi text" in p for p in format_problems({**s["en-IN"], "language": "hi-IN"}, "hi-IN"))


def test_safety_checks_catch_advice_and_personal_info():
    s = copy.deepcopy(_a_survey()["en-IN"])
    s["items"][0]["prompt"] = "You should spray neem oil now."
    assert any("advice" in p for p in safety_problems(s))
    s["items"][0]["prompt"] = "What is your phone number?"
    assert any("personal" in p for p in safety_problems(s))


def test_history_records_runs(tmp_path):
    path = tmp_path / "h.jsonl"
    g = score_golden()
    c = run_scorecard(load_insights()[:5])
    record_run("first", g, c, path=path)
    row = record_run("second", g, c, path=path)
    hist = load_history(path)
    assert [h["run"] for h in hist] == [1, 2] and row["label"] == "second"
    assert hist[0]["decision_acc"] == round(g["decision_acc"], 4)


def _a_surveyed_insight():
    for ins in load_insights():
        out = run_insight(ins)
        if out["decision"].survey:
            return ins, out["handoff"]["send_window"]
    raise AssertionError("mock data has no surveyed insight")


def test_timeliness_passes_our_windows_and_catches_bad_ones():
    from mel.evaluation import timeliness_problems
    ins, win = _a_surveyed_insight()
    assert timeliness_problems(ins, win) == []
    created = ins["created_at"][:10]
    too_early = {"not_before": f"{created}T09:00:00+05:30", "not_after": win["not_after"]}
    assert any("before the action window ends" in p for p in timeliness_problems(ins, too_early))
    at_night = {"not_before": win["not_before"].replace("T07:00", "T05:00"),
                "not_after": win["not_after"].replace("T19:00", "T22:00")}
    probs = timeliness_problems(ins, at_night)
    assert any("opens at 05:00" in p for p in probs) and any("closes at 22:00" in p for p in probs)
    late = {"not_before": "2027-04-02T07:00:00+05:30", "not_after": "2027-04-05T19:00:00+05:30"}
    assert any("after the season ends" in p for p in timeliness_problems(ins, late))


def test_timing_basis_switches_and_restores(monkeypatch):
    import os
    from mel.evaluation import timing_basis
    monkeypatch.delenv("MEL_TIMING_BASIS", raising=False)
    with timing_basis("answer_key"):
        assert os.environ["MEL_TIMING_BASIS"] == "answer_key"
    assert "MEL_TIMING_BASIS" not in os.environ


def test_rules_changed_compares_each_run_with_the_previous(tmp_path):
    from mel.evaluation import rules_changed
    g = score_golden()
    c = run_scorecard(load_insights()[:5])
    path = tmp_path / "h.jsonl"
    record_run("baseline", {**g, "decision_acc": 0.9}, c, path=path)
    record_run("fix", g, c, path=path, timing_basis="answer_key")
    (row,) = rules_changed(load_history(path))
    assert row["change"] == "fix" and row["timing_basis"] == "answer_key"
    assert row["decision_acc"] == (0.9, round(g["decision_acc"], 4))
