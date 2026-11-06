"""The AWS side of the agent: S3 input and results, CloudWatch metrics. Owner: P5.

Every function is a no-op (or a local fallback) when its setting is missing, so the agent runs the same on a laptop.
"""
import json
import time
from functools import lru_cache

from mel.config import PACK_DATA, env


def _s3_split(url: str) -> tuple[str, str]:
    assert url.startswith("s3://"), url
    bucket, _, key = url[5:].partition("/")
    return bucket, key


@lru_cache(maxsize=1)
def _insights_by_id(source: str) -> dict:
    if source.startswith("s3://"):
        import boto3
        b, k = _s3_split(source)
        text = boto3.client("s3").get_object(Bucket=b, Key=k)["Body"].read().decode("utf-8")
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        from mel.data import load_insights
        from pathlib import Path
        rows = load_insights(Path(source) if source else None)
    return {r.get("insight_id"): r for r in rows if isinstance(r, dict)}


def load_insight(insight_id: str | None) -> dict | None:
    """From MEL_S3_INPUT (s3://bucket/key.jsonl) when set, else the participant pack in the image (or the mock)."""
    if not insight_id:
        return None
    src = env("MEL_S3_INPUT") or (str(PACK_DATA / "insights.jsonl") if (PACK_DATA / "insights.jsonl").exists() else "")
    return _insights_by_id(src).get(insight_id)


def save_result(result: dict, client=None) -> str | None:
    """Write the result JSON to MEL_S3_RESULTS (s3://bucket/prefix). Returns the s3:// URL, or None when off."""
    dest = env("MEL_S3_RESULTS")
    if not dest:
        return None
    b, prefix = _s3_split(dest)
    key = f"{prefix.rstrip('/')}/{result.get('insight_id', 'unknown')}/{time.strftime('%Y%m%dT%H%M%S')}.json".lstrip("/")
    c = client
    if c is None:
        import boto3
        c = boto3.client("s3")
    c.put_object(Bucket=b, Key=key, Body=json.dumps(result, ensure_ascii=False).encode("utf-8"),
                 ContentType="application/json")
    return f"s3://{b}/{key}"


def metric_data(result: dict) -> list[dict]:
    """The CloudWatch data points for one run (pure, so it is tested without AWS)."""
    m = result.get("metrics") or {}
    surveys = result.get("surveys") or {}
    writer = next((s.get("_model") for s in surveys.values() if s.get("_model")), "templates")
    dims = [{"Name": "Writer", "Value": str(writer)[:250]}]
    pts = [("Runs", 1, "Count"), ("Seconds", m.get("seconds", 0), "Seconds"),
           ("ModelCalls", m.get("calls", 0), "Count"), ("InputTokens", m.get("input_tokens", 0), "Count"),
           ("OutputTokens", m.get("output_tokens", 0), "Count"), ("CostUSD", m.get("cost_usd") or 0, "None")]
    if surveys:
        pts += [("Revisions", m.get("revisions", 0), "Count"),
                ("TemplateFallbacks", sum(1 for s in surveys.values() if s.get("_fallback_reason")), "Count"),
                ("Surveys", 1, "Count")]
    else:
        pts += [("NoSurvey", 1, "Count")]
    return [{"MetricName": n, "Value": float(v), "Unit": u, "Dimensions": dims} for n, v, u in pts]


def put_metrics(result: dict, client=None) -> bool:
    """Send the run's metrics to CloudWatch (namespace MEL_METRICS_NAMESPACE, default FasalPulse/Agent).
    Off when MEL_METRICS=0. Never raises: metrics must not break a run."""
    if env("MEL_METRICS", "1") == "0":
        return False
    try:
        c = client
        if c is None:
            import boto3
            c = boto3.client("cloudwatch")
        c.put_metric_data(Namespace=env("MEL_METRICS_NAMESPACE", "FasalPulse/Agent"),
                          MetricData=metric_data(result))
        return True
    except Exception:
        return False
