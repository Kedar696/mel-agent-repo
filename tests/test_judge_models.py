"""The model sweep for the AI judge (owner: P5), with stand-in Bedrock clients: no AWS needed."""
import pytest

from mel.evaluation import judge as J
from mel.evaluation import judge_models as M


class FakeBedrock:
    def list_foundation_models(self, byOutputModality):
        assert byOutputModality == "TEXT"
        return {"modelSummaries": [
            {"modelId": "amazon.nova-lite-v1:0", "providerName": "Amazon", "modelName": "Nova Lite",
             "inputModalities": ["TEXT", "IMAGE"], "inferenceTypesSupported": ["ON_DEMAND"], "modelLifecycle": {"status": "ACTIVE"}},
            {"modelId": "anthropic.claude-haiku-4-5-20251001-v1:0", "providerName": "Anthropic", "modelName": "Claude Haiku 4.5",
             "inputModalities": ["TEXT"], "inferenceTypesSupported": ["INFERENCE_PROFILE"], "modelLifecycle": {"status": "ACTIVE"}},
            {"modelId": "meta.llama-old", "providerName": "Meta", "modelName": "Old Llama",
             "inputModalities": ["TEXT"], "inferenceTypesSupported": ["ON_DEMAND"], "modelLifecycle": {"status": "LEGACY"}},
            {"modelId": "cohere.big:128k", "providerName": "Cohere", "modelName": "Big",
             "inputModalities": ["TEXT"], "inferenceTypesSupported": ["PROVISIONED"], "modelLifecycle": {"status": "ACTIVE"}},
            {"modelId": "stability.image", "providerName": "Stability", "modelName": "Image",
             "inputModalities": ["IMAGE"], "inferenceTypesSupported": ["ON_DEMAND"]},
        ]}

    def list_inference_profiles(self, **kw):
        arn = "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0"
        return {"inferenceProfileSummaries": [
            {"inferenceProfileId": "eu.anthropic.claude-haiku-4-5-20251001-v1:0", "models": [{"modelArn": arn}]},
            {"inferenceProfileId": "us.anthropic.claude-haiku-4-5-20251001-v1:0", "models": [{"modelArn": arn}]}]}


def test_discover_finds_callable_text_models():
    ms = {m["model_id"]: m for m in M.discover(FakeBedrock())}
    assert set(ms) == {"amazon.nova-lite-v1:0", "anthropic.claude-haiku-4-5-20251001-v1:0", "cohere.big:128k"}
    assert ms["amazon.nova-lite-v1:0"]["call_id"] == "amazon.nova-lite-v1:0"
    assert ms["anthropic.claude-haiku-4-5-20251001-v1:0"]["call_id"].startswith("us.")   # us. profile preferred
    assert ms["cohere.big:128k"]["call_id"] is None                                       # provisioned only


class Runtime:
    """Answers like a model: 'good' says 5 for every survey, 'denied' is not enabled, 'nosys' refuses system prompts."""
    def __init__(self, kind):
        self.kind = kind

    def converse(self, **kw):
        if self.kind == "denied":
            raise RuntimeError("AccessDeniedException: You don't have access to the model")
        if self.kind == "nosys" and "system" in kw:
            raise RuntimeError("ValidationException: This model doesn't support system messages")
        return {"output": {"message": {"content": [{"text": '{"score": 5, "reason": "ok"}'}]}},
                "usage": {"inputTokens": 100, "outputTokens": 10}}


@pytest.fixture
def pairs():
    return J.golden_pairs()


def test_sweep_scores_ranks_and_reports_failures(pairs, tmp_path, monkeypatch):
    monkeypatch.setenv("MEL_CACHE_DIR", str(tmp_path / "mc"))
    monkeypatch.setenv("MEL_LLM_LOG", str(tmp_path / "log.jsonl"))
    models = [{"model_id": k, "call_id": k, "provider": "P", "name": k, "via": "on-demand"} for k in ("good", "denied", "nosys")]
    models.append({"model_id": "prov", "call_id": None, "provider": "P", "name": "prov", "via": "provisioned throughput only (skipped)"})
    kinds = iter(["good", "denied", "nosys", "unused"])
    import threading
    lock = threading.Lock()

    def factory():
        with lock:
            return Runtime(next(kinds))
    res = M.sweep(models, factory, pairs=pairs, workers=1, cache_dir=tmp_path / "jc")
    by = {r["model_id"]: r for r in res["models"]}
    n = len({r["golden_id"] for r in J.read_sheet()})
    assert by["good"]["status"] == "ok" and by["good"]["surveys_scored"] == n and by["good"]["avg_score"] == 5
    assert by["nosys"]["status"] == "ok"                      # retried without a system prompt
    assert by["denied"]["status"] == "error" and "AccessDenied" in by["denied"]["error"]
    assert by["prov"]["status"] == "skipped"
    assert res["models"][0]["rank"] == 1 and by["denied"]["rank"] is None
    assert res["people_vs_people"]["within_1"] == pytest.approx(0.83, abs=0.01)
