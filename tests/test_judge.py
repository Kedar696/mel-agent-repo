"""P5: AI relevance judge, tested with a stand-in model (no network, no AWS)."""
import csv

import pytest

from mel.evaluation import judge as J


class FakeClient:
    model_id = "fake-small-model"

    def __init__(self, reply='{"score": 4, "reason": "Asks about the advice."}'):
        self.reply, self.calls = reply, 0

    def complete(self, system, user):
        self.calls += 1
        assert "RUBRIC" in user and "Advice given" in user and "Q1." in user
        return self.reply, {"input_tokens": 300, "output_tokens": 20}


@pytest.fixture(scope="module")
def pairs():
    p = J.golden_pairs()
    assert p, "mock answer key has no survey rows"
    return p


def test_parse_score_handles_json_noise_and_garbage():
    assert J.parse_score('Sure! {"score": 5, "reason": "ok"}') == (5, "ok")
    assert J.parse_score('{"score": 9}')[0] is None
    assert J.parse_score("I'd give it a 3.")[0] == 3
    assert J.parse_score("no idea")[0] is None


def test_judge_caches_so_reruns_are_free(pairs, tmp_path):
    g, ins, s = pairs[0]
    c = FakeClient()
    first = J.judge_survey(s, ins, c, cache_dir=tmp_path)
    again = J.judge_survey(s, ins, c, cache_dir=tmp_path)
    assert first["score"] == again["score"] == 4 and c.calls == 1 and again["cached"]


def test_batch_reports_average_tokens_and_cost(pairs, tmp_path, monkeypatch):
    monkeypatch.setenv("MEL_BEDROCK_PRICES", '{"fake-small-model": {"in": 0.001, "out": 0.005}}')   # USD per 1,000
    r = J.judge_batch(pairs[:3], FakeClient(), cache_dir=tmp_path)
    assert r["n"] == r["n_scored"] == len(pairs[:3]) and r["judge_relevance"] == 4.0
    assert r["input_tokens"] == 300 * r["n"] and r["cost_usd"] == pytest.approx(r["n"] * 400 / 1e6)


def test_unparseable_reply_is_not_counted(pairs, tmp_path):
    r = J.judge_batch(pairs[:2], FakeClient("cannot grade"), cache_dir=tmp_path)
    assert r["n_scored"] == 0 and r["judge_relevance"] is None


def test_hand_sheet_is_balanced_and_protects_scores(pairs, tmp_path):
    path = tmp_path / "hand.csv"
    n = J.make_sheet(pairs, path=path, n=5)
    rows = J.read_sheet(path)
    assert n == len(rows) == min(5, len(pairs)) and all(r["questions"].startswith("Q1.") for r in rows)
    rows[0]["score_1_to_5"] = "4"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=J.SHEET_FIELDS)
        w.writeheader()
        w.writerows(rows)
    with pytest.raises(FileExistsError):
        J.make_sheet(pairs, path=path, n=5)


def test_calibration_compares_judge_with_people(pairs, tmp_path):
    path = tmp_path / "hand.csv"
    J.make_sheet(pairs, path=path, n=3)
    rows = J.read_sheet(path)
    for r, h in zip(rows, ["4", "3", "1"]):
        r["score_1_to_5"] = h
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=J.SHEET_FIELDS)
        w.writeheader()
        w.writerows(rows)
    a = J.calibrate(pairs, FakeClient(), path=path, cache_dir=tmp_path / "c")
    expected = J.agreement(list(zip([int(r["score_1_to_5"]) for r in rows], [4] * len(rows))))
    assert {k: a[k] for k in expected} == expected and a["n"] == len(rows)
    assert a["always_5"] == J.agreement([(h, 5) for h in (4, 3, 1)][:len(rows)])
    assert a["people_vs_people"]["n"] == 0 and sum(a["judge_scores"].values()) == len(rows)
    assert J.agreement([(4, 4), (3, 4), (1, 4)]) == {"n": 3, "exact": 1 / 3, "within_1": 2 / 3, "mean_abs_diff": 1.33}


def test_bedrock_client_needs_a_model_id(monkeypatch):
    monkeypatch.delenv("MEL_JUDGE_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="MEL_JUDGE_MODEL"):
        J.BedrockClient()


def test_summary_file_round_trips_and_ranks(pairs, tmp_path):
    path = tmp_path / "summary.json"
    rows = [{"golden_id": g["golden_id"], "score": 5 - (i % 2), "cached": True, "seconds": 0,
             "input_tokens": 0, "output_tokens": 0, "cost_usd": None} for i, (g, _, _) in enumerate(pairs)]
    run = J.run_summary({"n": len(rows), "judge_relevance": 4.5, "rows": rows}, pairs, "m")
    J.write_summary(path, run=run)
    J.write_summary(path, calibration={"within_1": 0.9})
    got = J.load_summary(path)
    assert got["run"]["n"] == len(rows) and "rows" not in got["run"] and got["calibration"]["within_1"] == 0.9
    assert sum(got["run"]["score_counts"].values()) == len(rows)
    assert J.load_summary(tmp_path / "missing.json") == {}
    assert J._corr([1, 2, 3], [2, 4, 6]) == 1.0 and J._corr([5, 5], [1, 2]) is None


def test_survey_from_text_round_trips(pairs):
    for _, _, s in pairs:
        t = J.survey_text(s)
        assert J.survey_text(J.survey_from_text(t)) == t


def test_bedrock_client_goes_through_p4_model_client(monkeypatch, tmp_path):
    monkeypatch.setenv("MEL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MEL_LLM_LOG", str(tmp_path / "calls.jsonl"))

    class FakeRuntime:
        calls = 0

        def converse(self, **kw):
            FakeRuntime.calls += 1
            assert kw["modelId"] == "judge-model" and kw["inferenceConfig"]["temperature"] == 0
            return {"output": {"message": {"content": [{"text": '{"score": 4, "reason": "ok"}'}]}},
                    "usage": {"inputTokens": 120, "outputTokens": 15}}

    c = J.BedrockClient("judge-model", runtime=FakeRuntime())
    assert c.complete("sys", "user") == ('{"score": 4, "reason": "ok"}', {"input_tokens": 120, "output_tokens": 15})
    assert c.complete("sys", "user")[1] == {"input_tokens": 120, "output_tokens": 15, "cached": True}   # cache hit
    assert FakeRuntime.calls == 1
    import json
    rows = [json.loads(l) for l in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert rows[0]["purpose"] == "judge" and rows[0]["input_tokens"] == 120
