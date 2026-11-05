"""Cost tracking and the batch runner (owner: P5), with a stand-in Bedrock: nothing calls AWS."""
import json

import pytest

from mel.agent.batch import run_batch, summarise, stratified_sample
from mel.agent.inputs import Pack
from mel.data import load_insights
from mel.evaluation import costs as C
from mel.pipeline import run_pipeline
from mel.writer import llm
from mel.writer.templates import template_items


class Runtime:
    """bedrock-runtime stand-in: answers every writing request with that insight's template items."""
    def __init__(self, insights):
        self.by_advice = {i["advice_summary"]: i for i in insights}
        self.calls = 0

    def converse(self, **kw):
        self.calls += 1
        text = kw["messages"][0]["content"][0]["text"]
        lang = "hi-IN" if "Language: hi-IN" in text else "en-IN"
        ins = next(i for a, i in self.by_advice.items() if a and a in text)
        return {"output": {"message": {"content": [{"text": json.dumps({"items": template_items(ins, lang)}, ensure_ascii=False)}]}},
                "usage": {"inputTokens": 1000, "outputTokens": 100}}


@pytest.fixture
def mock():
    return load_insights(None)


@pytest.fixture
def bedrock(tmp_path, monkeypatch, mock):
    monkeypatch.setenv("MEL_USE_LLM", "1")
    monkeypatch.setenv("MEL_BEDROCK_WRITE_MODEL", "test-write")
    monkeypatch.delenv("MEL_BEDROCK_CHECK_MODEL", raising=False)
    monkeypatch.setenv("MEL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MEL_LLM_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setenv("MEL_BEDROCK_PRICES", json.dumps({"test-write": {"in": 0.001, "out": 0.005}}))  # USD per 1K
    rt = Runtime(mock)
    llm.set_client(llm.ModelClient(runtime=rt, sleep=lambda s: None))
    yield rt
    llm.set_client(None)


def test_projection_maths():
    p = C.projection(1.30, 100, full_surveys=2616)
    assert p["usd_per_survey"] == 0.013 and p["usd_per_1000_surveys"] == 13.0 and p["projected_full_usd"] == 34.01
    assert C.projection(0, 0)["projected_full_usd"] is None


def test_ledger_appends_and_reads_back(tmp_path):
    path = tmp_path / "ledger.jsonl"
    a = C.record_cost({"kind": "pilot", "spent_usd": 0.5}, path=path)
    b = C.record_cost({"kind": "batch", "spent_usd": 9.0}, path=path)
    assert (a["run"], b["run"]) == (1, 2) and a["at"] and a["commit"]
    assert [r["kind"] for r in C.load_costs(path)] == ["pilot", "batch"]


def test_meter_reads_only_what_was_logged_after_it_started(tmp_path, monkeypatch):
    log = tmp_path / "calls.jsonl"
    log.write_text(json.dumps({"purpose": "write", "cost_usd": 5.0, "ok": True, "cached": False}) + "\n")
    monkeypatch.setenv("MEL_LLM_LOG", str(log))
    m = C.CostMeter()
    with log.open("a") as f:
        f.write(json.dumps({"purpose": "write", "model": "w", "tag": "I-1", "input_tokens": 10, "output_tokens": 2,
                            "cost_usd": 0.25, "ok": True, "cached": False}) + "\n")
        f.write(json.dumps({"purpose": "judge", "model": "j", "input_tokens": 5, "output_tokens": 1,
                            "cost_usd": 0.01, "ok": True, "cached": False}) + "\n")
        f.write(json.dumps({"purpose": "write", "cost_usd": 0.0, "ok": True, "cached": True}) + "\n")
    s = m.summary()
    assert s["spent_usd"] == 0.26 and s["calls"] == 2 and s["cached_calls"] == 1
    assert s["by_purpose"]["judge"]["usd"] == 0.01 and s["fresh_tags"] == ["I-1"]


def test_batch_writes_every_survey_and_prices_them(bedrock, mock):
    pack = Pack(mock, {})
    results, meter, stopped = run_batch(mock, pack, workers=2, progress=None)
    assert not stopped and all(r is not None for r in results)
    ref = {i["insight_id"]: o for i, o in zip(mock, run_pipeline(mock).outputs)}
    surveyed = [r for r in results if r["surveys"]]
    assert len(surveyed) == sum(1 for o in ref.values() if "handoff" in o)
    assert all(s["_source"] == "bedrock" for r in surveyed for s in r["surveys"].values())
    row = C.row_from_results("batch", "test", meter, results)
    # 2 languages x 1 call each, 1,000 tokens in at $0.001/1K + 100 out at $0.005/1K = $0.0015 per call
    assert row["calls"] == 2 * len(surveyed) and row["spent_usd"] == pytest.approx(0.003 * len(surveyed))
    assert row["usd_per_survey"] == pytest.approx(0.003) and row["projected_full_usd"] == pytest.approx(0.003 * 2616, abs=0.01)
    assert row["sources"]["en-IN:bedrock"] == len(surveyed)
    sm = summarise(results, mock)
    assert sm["schema_invalid_files"] == 0 and sm["surveys"] == len(surveyed) and sm["no_survey"] == len(mock) - len(surveyed)


def test_resume_is_free(bedrock, mock):
    pack = Pack(mock, {})
    run_batch(mock, pack, workers=2, progress=None)
    calls = bedrock.calls
    results, meter, _ = run_batch(mock, pack, workers=2, progress=None)
    assert bedrock.calls == calls                           # all from the cache
    row = C.row_from_results("batch", "again", meter, results)
    assert row["spent_usd"] == 0 and row["calls"] == 0 and row["usd_per_survey"] is None


def test_budget_cap_stops_new_work(bedrock, mock):
    pack = Pack(mock, {})
    results, meter, stopped = run_batch(mock, pack, workers=1, max_usd=0.004, progress=None)
    assert stopped and any(r is None for r in results)
    assert meter.spent() < 0.004 + 2 * 0.003                # at most the in-flight work past the cap


def test_without_bedrock_the_batch_matches_the_pipeline(mock, monkeypatch):
    monkeypatch.delenv("MEL_USE_LLM", raising=False)
    results, _, _ = run_batch(mock, Pack(mock, {}), workers=2, progress=None)
    ref = run_pipeline(mock).outputs
    for r, o in zip(results, ref):
        if "handoff" in o:
            assert {k: v["items"] for k, v in r["surveys"].items()} == {k: v["items"] for k, v in o["surveys"].items()}


def test_pilot_sample_is_spread_across_advice_types(mock):
    s = stratified_sample(mock, 10)
    assert len(s) == 10 and len({i["resolution_type"] for i in s}) >= 4
