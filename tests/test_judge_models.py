"""The model sweep for the AI judge (owner: P5), with stand-in Bedrock clients: no AWS needed."""

import pytest

from mel.evaluation import judge as J
from mel.evaluation import judge_models as M


class FakeBedrock:
    def list_foundation_models(self, byOutputModality):
        assert byOutputModality == "TEXT"
        return {
            "modelSummaries": [
                {
                    "modelId": "amazon.nova-lite-v1:0",
                    "providerName": "Amazon",
                    "modelName": "Nova Lite",
                    "inputModalities": ["TEXT", "IMAGE"],
                    "inferenceTypesSupported": ["ON_DEMAND"],
                    "modelLifecycle": {"status": "ACTIVE"},
                },
                {
                    "modelId": "anthropic.claude-haiku-4-5-20251001-v1:0",
                    "providerName": "Anthropic",
                    "modelName": "Claude Haiku 4.5",
                    "inputModalities": ["TEXT"],
                    "inferenceTypesSupported": ["INFERENCE_PROFILE"],
                    "modelLifecycle": {"status": "ACTIVE"},
                },
                {
                    "modelId": "meta.llama-old",
                    "providerName": "Meta",
                    "modelName": "Old Llama",
                    "inputModalities": ["TEXT"],
                    "inferenceTypesSupported": ["ON_DEMAND"],
                    "modelLifecycle": {"status": "LEGACY"},
                },
                {
                    "modelId": "cohere.big:128k",
                    "providerName": "Cohere",
                    "modelName": "Big",
                    "inputModalities": ["TEXT"],
                    "inferenceTypesSupported": ["PROVISIONED"],
                    "modelLifecycle": {"status": "ACTIVE"},
                },
                {
                    "modelId": "stability.image",
                    "providerName": "Stability",
                    "modelName": "Image",
                    "inputModalities": ["IMAGE"],
                    "inferenceTypesSupported": ["ON_DEMAND"],
                },
            ]
        }

    def list_inference_profiles(self, **kw):
        arn = "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0"
        return {
            "inferenceProfileSummaries": [
                {"inferenceProfileId": "eu.anthropic.claude-haiku-4-5-20251001-v1:0", "models": [{"modelArn": arn}]},
                {"inferenceProfileId": "us.anthropic.claude-haiku-4-5-20251001-v1:0", "models": [{"modelArn": arn}]},
            ]
        }


def test_discover_finds_callable_text_models():
    ms = {m["model_id"]: m for m in M.discover(FakeBedrock())}
    assert set(ms) == {"amazon.nova-lite-v1:0", "anthropic.claude-haiku-4-5-20251001-v1:0", "cohere.big:128k"}
    assert ms["amazon.nova-lite-v1:0"]["call_id"] == "amazon.nova-lite-v1:0"
    assert ms["anthropic.claude-haiku-4-5-20251001-v1:0"]["call_id"].startswith("us.")  # us. profile preferred
    assert ms["cohere.big:128k"]["call_id"] is None  # provisioned only


class Runtime:
    """Answers like a model: 'good' says 5 for every survey, 'denied' is not enabled, 'nosys' refuses system prompts."""

    def __init__(self, kind):
        self.kind = kind

    def converse(self, **kw):
        if self.kind == "denied":
            raise RuntimeError("AccessDeniedException: You don't have access to the model")
        if self.kind == "nosys" and "system" in kw:
            raise RuntimeError("ValidationException: This model doesn't support system messages")
        if self.kind == "notemp" and "temperature" in kw["inferenceConfig"]:
            raise RuntimeError("ValidationException: This model doesn't support the temperature field.")
        return {
            "output": {"message": {"content": [{"text": '{"score": 5, "reason": "ok"}'}]}},
            "usage": {"inputTokens": 100, "outputTokens": 10},
        }


@pytest.fixture
def pairs():
    return J.golden_pairs()


def test_sweep_scores_ranks_and_reports_failures(pairs, tmp_path, monkeypatch):
    monkeypatch.setenv("MEL_CACHE_DIR", str(tmp_path / "mc"))
    monkeypatch.setenv("MEL_LLM_LOG", str(tmp_path / "log.jsonl"))
    models = [
        {"model_id": k, "call_id": k, "provider": "P", "name": k, "via": "on-demand"}
        for k in ("good", "denied", "nosys", "notemp")
    ]
    models.append(
        {
            "model_id": "prov",
            "call_id": None,
            "provider": "P",
            "name": "prov",
            "via": "provisioned throughput only (skipped)",
        }
    )
    kinds = iter(["good", "denied", "nosys", "notemp", "unused"])
    import threading

    lock = threading.Lock()

    def factory():
        with lock:
            return Runtime(next(kinds))

    res = M.sweep(
        models,
        factory,
        pairs=pairs,
        workers=1,
        cache_dir=tmp_path / "jc",
        prices={"good": {"in": 1.0, "out": 5.0}, "nosys": {"in": 0.1, "out": 0.4}},
    )
    by = {r["model_id"]: r for r in res["models"]}
    n = len({r["golden_id"] for r in J.read_sheet()})
    assert by["good"]["status"] == "ok" and by["good"]["surveys_scored"] == n and by["good"]["avg_score"] == 5
    assert by["nosys"]["status"] == "ok"  # retried without a system prompt
    assert by["notemp"]["status"] == "ok"  # retried without a temperature
    assert by["denied"]["status"] == "error" and "AccessDenied" in by["denied"]["error"]
    assert by["prov"]["status"] == "skipped"
    assert res["models"][0]["rank"] == 1 and by["denied"]["rank"] is None
    assert res["people_vs_people"]["within_1"] == pytest.approx(0.83, abs=0.01)
    assert res["best_value"] == "nosys" and by["nosys"]["usd_per_1000_surveys"] < by["good"]["usd_per_1000_surveys"]


def _row(mid, rank, r, gap, usd_in=None, usd_out=None):
    return {
        "model_id": mid,
        "call_id": mid,
        "provider": "P",
        "name": mid,
        "status": "ok",
        "surveys_scored": 20,
        "rank": rank,
        "rank_r": r,
        "mean_abs_diff": gap,
        "calls": 20,
        "input_tokens": 20_000,
        "output_tokens": 2_000,
    }


def test_best_value_is_the_cheapest_model_close_to_the_best():
    rows = [
        _row("big", 1, 0.60, 0.60),
        _row("mid", 2, 0.55, 0.70),
        _row("small", 3, 0.30, 0.65),
        _row("free?", 4, 0.58, 0.62),
    ]
    prices = {"big": {"in": 15.0, "out": 75.0}, "mid": {"in": 0.8, "out": 4.0}, "small": {"in": 0.05, "out": 0.2}}
    M.add_costs(rows, prices)
    by = {r["model_id"]: r for r in rows}
    # 1,000 tokens in + 100 out per survey: big = (1000*15 + 100*75)/1e6 = $0.0225 per survey
    assert by["big"]["usd_per_1000_surveys"] == 22.5 and by["free?"]["usd_per_1000_surveys"] is None
    pick = M.choose(rows)
    assert pick == {"most_accurate": "big", "best_value": "mid"}  # small is cheapest but too far below on r
    assert by["mid"]["pick"] == "best value" and by["big"]["pick"] == "most accurate"
    assert by["small"]["close_to_best"] is False and by["free?"]["close_to_best"] is True  # close, but no price


def test_no_priced_model_means_no_best_value_pick():
    rows = [_row("a", 1, 0.5, 0.6)]
    M.add_costs(rows, {})
    assert M.choose(rows) == {"most_accurate": "a", "best_value": None}


class FakePricing:
    def get_paginator(self, name):
        assert name == "get_products"
        return self

    def paginate(self, ServiceCode, Filters):
        import json

        def prod(model, usage, usd, unit="1K tokens"):
            return json.dumps(
                {
                    "product": {"attributes": {"model": model, "usagetype": usage}},
                    "terms": {
                        "OnDemand": {"t": {"priceDimensions": {"d": {"unit": unit, "pricePerUnit": {"USD": usd}}}}}
                    },
                }
            )

        if ServiceCode != "AmazonBedrock":
            raise RuntimeError("no such service code")
        return [
            {
                "PriceList": [
                    prod("Nova Lite", "USE1-NovaLite-input-tokens", "0.00006"),
                    prod("Nova Lite", "USE1-NovaLite-output-tokens", "0.00024"),
                    prod("Nova Lite", "USE1-NovaLite-batch-input-tokens", "0.00003"),  # batch: skipped
                    prod("Claude Haiku 4.5", "USE1-input-tokens", "1.0", unit="1M tokens"),
                ]
            }
        ]  # no output price


def test_fetch_prices_reads_the_price_list_per_million_tokens():
    models = [
        {"model_id": "amazon.nova-lite-v1:0", "name": "Nova Lite"},
        {"model_id": "anthropic.claude-haiku-4-5-20251001-v1:0", "name": "Claude Haiku 4.5"},
    ]
    got = M.fetch_prices(FakePricing(), "us-east-1", models)
    assert set(got) == {"amazon.nova-lite-v1:0"}  # Haiku has no output price: left for a person
    assert got["amazon.nova-lite-v1:0"]["in"] == 0.06 and got["amazon.nova-lite-v1:0"]["out"] == 0.24


def test_rerun_from_cache_keeps_costs(pairs, tmp_path, monkeypatch):
    """A second sweep is all cache hits (no model calls) but must price each model exactly as the first did."""
    monkeypatch.setenv("MEL_CACHE_DIR", str(tmp_path / "mc"))
    monkeypatch.setenv("MEL_LLM_LOG", str(tmp_path / "log.jsonl"))
    models = [{"model_id": "good", "call_id": "good", "provider": "P", "name": "good", "via": "on-demand"}]
    prices = {"good": {"in": 1.0, "out": 5.0}}
    first = M.sweep(models, lambda: Runtime("good"), pairs=pairs, workers=1, cache_dir=tmp_path / "jc", prices=prices)
    again = M.sweep(models, lambda: Runtime("denied"), pairs=pairs, workers=1, cache_dir=tmp_path / "jc", prices=prices)
    a, b = first["models"][0], again["models"][0]
    assert a["usd_per_1000_surveys"] == b["usd_per_1000_surveys"] > 0 and b["new_calls"] == 0
