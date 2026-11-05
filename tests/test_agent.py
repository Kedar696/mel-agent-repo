"""The Fasal Pulse agent (owner: P5): Evidence Extractor -> Analyst -> Verifier -> Synthesizer, bounded revision.
Bedrock is a stand-in here; nothing calls AWS."""
import json

import pytest

from mel.agent import run_agent_to_end, MAX_REVISIONS
from mel.data import load_insights
from mel.pipeline import run_insight, clean
from mel.writer import llm
from mel.writer.templates import template_items, question_count


@pytest.fixture
def insights():
    return load_insights(None)


@pytest.fixture
def one(insights):
    return next(i for i in insights if run_insight(i)["decision"].survey and question_count(i) == 2)


def test_without_bedrock_the_agent_matches_the_pipeline(insights):
    for i in insights:
        ref = run_insight(i)
        evs, res = run_agent_to_end(i)
        assert [e["step"] for e in evs][0] == "evidence" and res["step"] == "result"
        json.dumps(res)                                            # streamable as JSON
        if not ref["decision"].survey:
            assert res["no_survey"] == ref["no_survey"] and res["surveys"] is None
            continue
        for lang, s in ref["surveys"].items():
            assert res["surveys"][lang]["items"] == s["items"]
        assert res["handoff"] == ref["handoff"]
        assert all(e["status"] == "ok" for e in evs)


class Runtime:
    """bedrock-runtime stand-in: returns the drafts in `replies` in order (the last one repeats)."""
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def converse(self, **kw):
        self.calls.append(kw)
        text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return {"output": {"message": {"content": [{"text": text}]}}, "usage": {"inputTokens": 100, "outputTokens": 50}}


@pytest.fixture
def bedrock(tmp_path, monkeypatch):
    monkeypatch.setenv("MEL_USE_LLM", "1")
    monkeypatch.setenv("MEL_BEDROCK_WRITE_MODEL", "test-write-model")
    monkeypatch.delenv("MEL_BEDROCK_CHECK_MODEL", raising=False)
    monkeypatch.setenv("MEL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MEL_LLM_LOG", str(tmp_path / "calls.jsonl"))

    def install(replies):
        rt = Runtime(replies)
        llm.set_client(llm.ModelClient(runtime=rt, sleep=lambda s: None))
        return rt
    yield install
    llm.set_client(None)


def _good(insight, lang="en-IN"):
    return json.dumps({"items": template_items(insight, lang)}, ensure_ascii=False)


def _too_long(insight, lang="en-IN"):
    items = template_items(insight, lang)
    items[0] = dict(items[0], prompt="You were advised to do exactly what the expert said about your crop last week. " * 2
                    + items[0]["prompt"])
    return json.dumps({"items": items}, ensure_ascii=False)


def test_model_draft_that_passes_is_used(bedrock, one):
    bedrock([_good(one)])
    evs, res = run_agent_to_end(one, langs=("en-IN",))
    assert res["surveys"]["en-IN"]["_source"] == "bedrock" and res["surveys"]["en-IN"]["_revisions"] == 0
    assert res["metrics"]["calls"] == 1 and res["metrics"]["input_tokens"] == 100


def test_rejected_draft_is_revised_with_the_reasons(bedrock, one):
    rt = bedrock([_too_long(one), _good(one)])
    evs, res = run_agent_to_end(one, langs=("en-IN",))
    s = res["surveys"]["en-IN"]
    assert s["_source"] == "bedrock" and s["_revisions"] == 1
    fails = [e for e in evs if e["step"] == "verifier" and e["status"] == "fail"]
    assert len(fails) == 1 and "longer than" in fails[0]["detail"]
    second = rt.calls[1]["messages"][0]["content"][0]["text"]
    assert "previous draft was rejected" in second and "longer than" in second   # the Analyst got the reasons
    assert any("revises (round 1" in e["title"] for e in evs)


def test_revision_is_bounded_then_falls_back_to_the_template(bedrock, one):
    rt = bedrock([_too_long(one)])
    evs, res = run_agent_to_end(one, langs=("en-IN",))
    s = res["surveys"]["en-IN"]
    assert s["_source"] == "template" and "after 2 revisions" in s["_fallback_reason"]
    assert len(rt.calls) == 1 + MAX_REVISIONS
    assert s["items"] == template_items(one, "en-IN") and s["self_eval"]["schema_valid"]
    assert [e["status"] for e in evs if e["step"] == "verifier"][-1] == "ok"


def test_guardrail_and_judge_in_the_verifier(bedrock, one, tmp_path, monkeypatch):
    bedrock([_good(one)])
    seen = []

    def guardrail(text):
        seen.append(text)
        return "Denied topic: pesticide brands" if len(seen) == 1 else None   # blocks the first draft only

    class Judge:
        model_id = "judge-x"
        def complete(self, system, user):
            return '{"score": 4, "reason": "ok"}', {"input_tokens": 1, "output_tokens": 1}
    import mel.evaluation.judge as J
    monkeypatch.setattr(J, "CACHE", tmp_path / "jc")
    evs, res = run_agent_to_end(one, langs=("en-IN",), guardrail=guardrail, judge=Judge())
    v = [e for e in evs if e["step"] == "verifier"]
    assert v[0]["status"] == "fail" and "Bedrock Guardrails blocked it" in v[0]["detail"]
    assert v[1]["status"] == "ok" and v[1]["data"]["judge"] == 4
    assert res["surveys"]["en-IN"]["_revisions"] == 1


def test_no_survey_stops_after_the_analyst(insights):
    i = next(i for i in insights if not run_insight(i)["decision"].survey)
    evs, res = run_agent_to_end(i)
    assert [e["step"] for e in evs] == ["evidence", "analyst", "synthesizer"]
    assert res["no_survey"]["decision"] == "no_survey" and res["surveys"] is None and res["handoff"] is None


# ---------------------------------------------------------------- AWS side, with stand-in clients
def test_cloudwatch_metrics_and_s3_results(one, monkeypatch):
    from mel.agent import aws
    _, res = run_agent_to_end(one)
    pts = {p["MetricName"]: p["Value"] for p in aws.metric_data(res)}
    assert pts["Runs"] == 1 and pts["Surveys"] == 1 and pts["Revisions"] == 0 and pts["ModelCalls"] == 0

    class CW:
        def put_metric_data(self, Namespace, MetricData):
            self.ns, self.n = Namespace, len(MetricData)
    cw = CW()
    assert aws.put_metrics(res, client=cw) and cw.ns == "FasalPulse/Agent" and cw.n == len(pts)
    monkeypatch.setenv("MEL_METRICS", "0")
    assert aws.put_metrics(res, client=cw) is False

    class S3:
        def put_object(self, Bucket, Key, Body, ContentType):
            self.where, self.body = (Bucket, Key), json.loads(Body)
    s3 = S3()
    monkeypatch.delenv("MEL_S3_RESULTS", raising=False)
    assert aws.save_result(res, client=s3) is None                       # off unless configured
    monkeypatch.setenv("MEL_S3_RESULTS", "s3://fasal-results/runs")
    url = aws.save_result(res, client=s3)
    assert url.startswith(f"s3://fasal-results/runs/{one['insight_id']}/") and s3.body["insight_id"] == one["insight_id"]


def test_agentcore_stream_is_read_event_by_event(one):
    from mel.agent.remote import invoke, parse_stream
    evs, res = run_agent_to_end(one)
    lines = [f"data: {json.dumps(e)}".encode() for e in evs + [res]] + [b"", b": keep-alive"]

    class Body:
        def iter_lines(self):
            return iter(lines)

    class Client:
        def invoke_agent_runtime(self, **kw):
            assert len(kw["runtimeSessionId"]) >= 33 and json.loads(kw["payload"])["insight"]["insight_id"]
            return {"contentType": "text/event-stream", "response": Body()}
    got = list(invoke("arn:aws:bedrock-agentcore:us-east-1:1:runtime/x", {"insight": one}, client=Client()))
    assert [e["step"] for e in got] == [e["step"] for e in evs] + ["result"]
    assert list(parse_stream(['data: "{\\"step\\": \\"evidence\\"}"']))[0]["step"] == "evidence"   # double-encoded
