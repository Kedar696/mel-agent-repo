"""Which Bedrock model makes the best relevance judge? Owner: P5.

Every text model the account can call judges the same 20 hand-scored surveys (docs/results/hand_scores.csv), and
we measure how well each one agrees with the 5 people who scored them: the same calibration as the main judge
(`judge.calibrate`). The result goes to docs/results/judge_models.json (committed), which the app's Dashboard
shows, so the app never calls Bedrock itself.

    python -m mel.evaluation.judge_models --list                  every text model we could call, and how
    python -m mel.evaluation.judge_models --run                   judge the 20 surveys with every model
    python -m mel.evaluation.judge_models --run --only nova,llama only models whose id contains one of these
    python -m mel.evaluation.judge_models --run --full            also score all 94 answer-key surveys per model

Credentials come from the AWS account (paste the event's temporary keys into the terminal, never into git).
Region: MEL_BEDROCK_REGION, else AWS_REGION / AWS_DEFAULT_REGION, else us-east-1. A model the account cannot use
(not enabled, provisioned-only, no Converse support) is listed with its error and skipped; nothing is guessed.
"""
import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

from mel.config import ROOT

from . import judge as J

RESULTS = ROOT / "docs" / "results" / "judge_models.json"
MAX_TOKENS = 1000      # room for models that think before answering; the judge's own default is 200


def region() -> str:
    return (os.environ.get("MEL_BEDROCK_REGION") or os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1")


# ---------------------------------------------------------------- which models can we call?
def _profiles(bedrock) -> dict:
    """base model id -> inference profile id (a us. or global. profile, for models without on-demand access)."""
    out, token = {}, None
    while True:
        kw = {"nextToken": token} if token else {}
        try:
            page = bedrock.list_inference_profiles(**kw)
        except Exception:
            return out
        for p in page.get("inferenceProfileSummaries", []):
            pid = p.get("inferenceProfileId", "")
            for m in p.get("models", []):
                base = m.get("modelArn", "").rsplit("/", 1)[-1]
                # prefer a profile for this region's geography (us.), then global., then any
                rank = 0 if pid.startswith("us.") else 1 if pid.startswith("global.") else 2
                if base and (base not in out or rank < out[base][0]):
                    out[base] = (rank, pid)
        token = page.get("nextToken")
        if not token:
            return {k: v[1] for k, v in out.items()}


def discover(bedrock) -> list[dict]:
    """Every active text-in, text-out foundation model, with the id to call it by (its own id when on-demand works,
    else an inference profile). Models that are provisioned-only are listed with `call_id` None and a reason."""
    profiles = _profiles(bedrock)
    out = []
    for m in bedrock.list_foundation_models(byOutputModality="TEXT").get("modelSummaries", []):
        if "TEXT" not in (m.get("inputModalities") or []):
            continue
        if (m.get("modelLifecycle") or {}).get("status", "ACTIVE") != "ACTIVE":
            continue
        mid, types = m["modelId"], m.get("inferenceTypesSupported") or []
        if "ON_DEMAND" in types:
            call, via = mid, "on-demand"
        elif mid in profiles:
            call, via = profiles[mid], "inference profile"
        else:
            call, via = None, "provisioned throughput only (skipped)"
        out.append({"model_id": mid, "call_id": call, "provider": m.get("providerName", ""),
                    "name": m.get("modelName", mid), "via": via})
    return sorted(out, key=lambda r: (r["provider"].lower(), r["name"].lower()))


# ---------------------------------------------------------------- one model's calibration
class _Metered:
    """Wraps a judge client: same cache key (model id), plus calls, seconds and tokens for the report."""

    def __init__(self, inner):
        self.inner, self.model_id = inner, inner.model_id
        self.calls = self.input_tokens = self.output_tokens = 0
        self.seconds = 0.0

    def complete(self, system, user):
        t0 = time.perf_counter()
        text, use = self.inner.complete(system, user)
        self.seconds += time.perf_counter() - t0
        self.calls += 1
        self.input_tokens += use.get("input_tokens", 0)
        self.output_tokens += use.get("output_tokens", 0)
        return text, use


class _SweepClient:
    """BedrockClient with more room to answer, and a retry without a system prompt for models that refuse one."""

    def __init__(self, call_id, runtime):
        self.model_id = call_id
        self._inner = J.BedrockClient(call_id, runtime=runtime)
        self._no_system = False

    def complete(self, system, user):
        c = self._inner._client
        if not self._no_system:
            try:
                text = c.converse(self.model_id, system, user, purpose="judge", max_tokens=MAX_TOKENS, temperature=0)
                return text, dict(c.last_usage)
            except Exception as e:      # ModelUnavailable from P4's client
                if "system" not in str(e).lower():
                    raise
                self._no_system = True
        text = c.converse(self.model_id, None, system + "\n\n" + user, purpose="judge", max_tokens=MAX_TOKENS, temperature=0)
        return text, dict(c.last_usage)


def evaluate_model(model: dict, pairs, runtime_factory, full: bool = False, cache_dir=J.CACHE) -> dict:
    """Calibrate one model against the hand scores. Never raises: an unusable model comes back with `status`."""
    row = {k: model[k] for k in ("model_id", "call_id", "provider", "name", "via")}
    if not model.get("call_id"):
        return {**row, "status": "skipped", "error": model["via"]}
    client = _Metered(_SweepClient(model["call_id"], runtime_factory()))
    try:
        cal = J.calibrate(pairs, client, cache_dir=cache_dir)
        if full:
            row["judge_relevance_all"] = J.judge_batch(pairs, client, cache_dir=cache_dir)["judge_relevance"]
    except Exception as e:
        return {**row, "status": "error", "error": f"{type(e).__name__}: {e}"[:300],
                "calls": client.calls}
    n_surveys = sum(v for k, v in cal["judge_scores"].items() if k is not None)   # None = answer we could not read
    avg = (sum(int(k) * v for k, v in cal["judge_scores"].items() if k is not None) / n_surveys) if n_surveys else None
    return {**row, "status": "ok" if n_surveys else "no usable answers",
            "surveys_scored": n_surveys, "within_1": cal["within_1"], "exact": cal["exact"],
            "mean_abs_diff": cal["mean_abs_diff"], "rank_r": cal["rank_r"],
            "avg_score": round(avg, 2) if avg is not None else None,
            "score_counts": {str(k): v for k, v in cal["judge_scores"].items()},
            "calls": client.calls, "input_tokens": client.input_tokens, "output_tokens": client.output_tokens,
            "seconds_per_call": round(client.seconds / client.calls, 2) if client.calls else None}


def rank(rows: list[dict], n_surveys: int = 20) -> list[dict]:
    """Best judge first: the ones that answered (almost) every survey, by how closely they follow people's
    ranking (r), then by the smallest average gap. Models that failed go last, in name order."""
    def key(r):
        good = r.get("status") == "ok" and (r.get("surveys_scored") or 0) >= n_surveys - 2
        rr = r.get("rank_r")
        return (0 if good else 1, -(rr if rr is not None else -9), r.get("mean_abs_diff") or 9, r["name"].lower())
    out = sorted(rows, key=key)
    pos = 0
    for r in out:
        if r.get("status") == "ok" and (r.get("surveys_scored") or 0) >= n_surveys - 2:
            pos += 1
            r["rank"] = pos
        else:
            r["rank"] = None
    return out


def sweep(models, runtime_factory, pairs=None, workers: int = 6, full: bool = False, cache_dir=J.CACHE) -> dict:
    pairs = pairs if pairs is not None else J.golden_pairs()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        rows = list(ex.map(lambda m: evaluate_model(m, pairs, runtime_factory, full, cache_dir), models))
    people = J.calibrate(pairs, _NoModel(), cache_dir=None) if pairs else {}
    return {"date": time.strftime("%Y-%m-%d %H:%M"), "region": region(), "rubric": J.RUBRIC_VERSION,
            "surveys": 20, "people_vs_people": people.get("people_vs_people"),
            "people_rank_r": people.get("people_rank_r"), "models": rank(rows)}


class _NoModel:
    """Lets calibrate() compute the people-only numbers without a model (every judge score comes back None)."""
    model_id = "none"

    def complete(self, system, user):
        return "", {}


def load(path=RESULTS) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _print(rows, cols):
    widths = [max(len(c), *(len(str(r.get(c, "") if r.get(c) is not None else "")) for r in rows)) for c in cols]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    for r in rows:
        print("  ".join(str(r.get(c, "") if r.get(c) is not None else "").ljust(w) for c, w in zip(cols, widths)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--run", action="store_true")
    ap.add_argument("--only", default="", help="comma-separated parts of model ids to keep, e.g. nova,llama")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--full", action="store_true")
    a = ap.parse_args()
    import boto3
    models = discover(boto3.client("bedrock", region_name=region()))
    if a.only:
        keep = [s.strip().lower() for s in a.only.split(",") if s.strip()]
        models = [m for m in models if any(k in m["model_id"].lower() for k in keep)]
    if a.list:
        _print(models, ["provider", "name", "model_id", "call_id", "via"])
        print(f"\n{len(models)} text models in {region()}; {sum(1 for m in models if m['call_id'])} callable.")
        return
    t0 = time.perf_counter()
    res = sweep(models, lambda: boto3.client("bedrock-runtime", region_name=region()), workers=a.workers, full=a.full)
    RESULTS.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    cols = ["rank", "provider", "name", "within_1", "mean_abs_diff", "rank_r", "avg_score", "surveys_scored",
            "seconds_per_call", "status"] + (["judge_relevance_all"] if a.full else [])
    _print(res["models"], cols)
    errs = [r for r in res["models"] if r.get("status") in ("error", "no usable answers")]
    for r in errs:
        print(f"  {r['model_id']}: {r.get('error', r['status'])}")
    print(f"\nPeople vs people: {res['people_vs_people']}. Wrote {RESULTS.relative_to(ROOT)} "
          f"in {time.perf_counter() - t0:.0f} s.")


if __name__ == "__main__":
    main()
