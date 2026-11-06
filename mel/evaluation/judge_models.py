"""Which Bedrock model makes the best relevance judge? Owner: P5.

Every text model the account can call judges the same 20 hand-scored surveys (docs/results/hand_scores.csv), and
we measure how well each one agrees with the 5 people who scored them: the same calibration as the main judge
(`judge.calibrate`). The result goes to docs/results/judge_models.json (committed), which the app's Dashboard
shows, so the app never calls Bedrock itself.

    python -m mel.evaluation.judge_models --list                  every text model we could call, and how
    python -m mel.evaluation.judge_models --run                   judge the 20 surveys with every model
    python -m mel.evaluation.judge_models --run --only nova,llama only models whose id contains one of these
    python -m mel.evaluation.judge_models --run --full            also score all 94 answer-key surveys per model
    python -m mel.evaluation.judge_models --prices                fetch token prices into docs/results/bedrock_prices.json

Cost counts too. Each model's price per token comes from docs/results/bedrock_prices.json (fetched from the AWS
Price List API by --prices, then checked by a person; edit any line that looks wrong), and its cost per survey is
that price times the tokens it actually used. The pick is the CHEAPEST model whose quality is close to the best one
(ranking match within QUALITY_MARGIN_R and gap within QUALITY_MARGIN_GAP of the most accurate model). A model with
no known price can still be the most accurate, but is never the "best value" pick.

Credentials come from the AWS account (paste the event's temporary keys into the terminal, never into git).
Region: MEL_BEDROCK_REGION, else AWS_REGION / AWS_DEFAULT_REGION, else us-east-1. A model the account cannot use
(not enabled, provisioned-only, no Converse support) is listed with its error and skipped; nothing is guessed.
"""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

from mel.config import ROOT, bedrock_region
from mel.writer import llm

from . import judge as J

RESULTS = ROOT / "docs" / "results" / "judge_models.json"
PRICES = (
    ROOT / "docs" / "results" / "bedrock_prices.json"
)  # {model id: {"in": USD per 1M tokens, "out": ..., "source"}}
QUALITY_MARGIN_R = 0.10  # "close to the best": ranking match at most this much below the most accurate model
QUALITY_MARGIN_GAP = 0.15  # ... and an average gap at most this much larger
SEASON_SURVEYS = 2616  # surveys in the full 6,999-insight run, for the "whole season" cost
MAX_TOKENS = 1000  # room for models that think before answering; the judge's own default is 200


def region() -> str:
    return bedrock_region() or "us-east-1"


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
        out.append(
            {
                "model_id": mid,
                "call_id": call,
                "provider": m.get("providerName", ""),
                "name": m.get("modelName", mid),
                "via": via,
            }
        )
    return sorted(out, key=lambda r: (r["provider"].lower(), r["name"].lower()))


# ---------------------------------------------------------------- prices
def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _tokens_per_unit(unit: str) -> float | None:
    u = (unit or "").lower().replace(" ", "")
    if "1k" in u or "thousand" in u or u.startswith("k"):
        return 1_000.0
    if "1m" in u or "million" in u or u.startswith("m"):
        return 1_000_000.0
    return None


def fetch_prices(pricing, region_code: str, models: list[dict]) -> dict:
    """Best effort: standard on-demand input/output token prices from the AWS Price List API, matched to our models
    by name. Returns {model id: {"in", "out" (USD per 1M tokens), "source"}}. Batch, cached, provisioned, long-context
    and other special prices are skipped. Anything it cannot match is simply missing: a person fills it in."""
    by_name = {_norm(m["name"]): m["model_id"] for m in models}
    found: dict = {}
    skip = ("batch", "cache", "provisioned", "longcontext", "long-context", "flex", "priority", "customiz", "train")
    for code in ("AmazonBedrock", "AmazonBedrockFoundationModels"):
        try:
            pages = pricing.get_paginator("get_products").paginate(
                ServiceCode=code, Filters=[{"Type": "TERM_MATCH", "Field": "regionCode", "Value": region_code}]
            )
            for page in pages:
                for raw in page.get("PriceList", []):
                    p = json.loads(raw) if isinstance(raw, str) else raw
                    a = (p.get("product") or {}).get("attributes") or {}
                    what = " ".join(
                        str(a.get(k, "")) for k in ("usagetype", "inferenceType", "feature", "operation")
                    ).lower()
                    if "token" not in what or any(x in what.replace(" ", "") for x in skip):
                        continue
                    side = "in" if "input" in what else "out" if "output" in what else None
                    name = _norm(a.get("model") or a.get("modelName") or a.get("titanModel") or "")
                    mid = by_name.get(name) or next(
                        (v for k, v in by_name.items() if name and (name in k or k in name)), None
                    )
                    if not (side and mid):
                        continue
                    for term in ((p.get("terms") or {}).get("OnDemand") or {}).values():
                        for dim in (term.get("priceDimensions") or {}).values():
                            usd, per = dim.get("pricePerUnit", {}).get("USD"), _tokens_per_unit(dim.get("unit", ""))
                            if usd is None or per is None:
                                continue
                            v = round(float(usd) * 1_000_000 / per, 4)
                            cur = found.setdefault(mid, {"source": f"AWS Price List ({code}, {region_code})"})
                            cur[side] = min(v, cur.get(side, v))
        except Exception:
            continue
    return {k: v for k, v in found.items() if "in" in v and "out" in v}


def load_prices(path=PRICES) -> dict:
    try:
        return {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if isinstance(v, dict)}
    except (OSError, ValueError):
        return {}


def price_for(model: dict, prices: dict) -> dict | None:
    for k in (model.get("model_id"), model.get("call_id")):
        p = prices.get(k or "")
        if p and p.get("in") is not None and p.get("out") is not None:
            return p
    return None


def add_costs(rows: list[dict], prices: dict) -> None:
    """Cost per survey from the tokens each model really used and its price; None when the price is unknown."""
    for r in rows:
        p = price_for(r, prices)
        calls = r.get("calls") or 0
        if p and calls:
            usd = (r.get("input_tokens", 0) * p["in"] + r.get("output_tokens", 0) * p["out"]) / 1_000_000 / calls
            r["usd_per_1000_surveys"] = round(usd * 1000, 4)
            r["usd_per_season"] = round(usd * SEASON_SURVEYS, 2)
            r["price_source"] = p.get("source", "prices file")
        else:
            r["usd_per_1000_surveys"] = r["usd_per_season"] = None
            r["price_source"] = None


def choose(rows: list[dict]) -> dict:
    """Most accurate = rank 1. Best value = the cheapest priced model whose quality is close to rank 1's."""
    ranked = [r for r in rows if r.get("rank")]
    if not ranked:
        return {"most_accurate": None, "best_value": None}
    top = ranked[0]
    tr, tg = top.get("rank_r"), top.get("mean_abs_diff")
    close = [
        r
        for r in ranked
        if (tr is None or (r.get("rank_r") is not None and r["rank_r"] >= tr - QUALITY_MARGIN_R))
        and (tg is None or (r.get("mean_abs_diff") is not None and r["mean_abs_diff"] <= tg + QUALITY_MARGIN_GAP))
    ]
    priced = [r for r in close if r.get("usd_per_1000_surveys") is not None]
    pick = min(priced, key=lambda r: (r["usd_per_1000_surveys"], r["rank"])) if priced else None
    for r in rows:
        r["close_to_best"] = any(r is c for c in close)
        r["pick"] = "best value" if r is pick else ("most accurate" if r is top else "")
    if pick is top:
        top["pick"] = "best value and most accurate"
    return {"most_accurate": top["model_id"], "best_value": pick["model_id"] if pick else None}


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
    """BedrockClient with more room to answer. Some models refuse a system prompt, and newer ones refuse a temperature
    setting; each refusal is remembered and the call is retried without it."""

    def __init__(self, call_id, runtime):
        self.model_id = call_id
        self._inner = J.BedrockClient(call_id, runtime=runtime)
        self._no_system = self._no_temperature = False

    def complete(self, system, user):
        c = self._inner._client
        for _ in range(3):
            sys_, usr = (None, system + "\n\n" + user) if self._no_system else (system, user)
            try:
                text = c.converse(
                    self.model_id,
                    sys_,
                    usr,
                    purpose="judge",
                    max_tokens=MAX_TOKENS,
                    temperature=None if self._no_temperature else 0,
                )
                return text, dict(c.last_usage)
            except Exception as e:  # ModelUnavailable from P4's client
                msg = str(e).lower()
                if "temperature" in msg and not self._no_temperature:
                    self._no_temperature = True
                elif "system" in msg and not self._no_system:
                    self._no_system = True
                else:
                    raise
        raise RuntimeError("model refused both the system prompt and the temperature setting")


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
        return {**row, "status": "error", "error": f"{type(e).__name__}: {e}"[:300], "calls": client.calls}
    n_surveys = sum(v for k, v in cal["judge_scores"].items() if k is not None)  # None = answer we could not read
    use = _usage(pairs, client, cache_dir)
    avg = (sum(int(k) * v for k, v in cal["judge_scores"].items() if k is not None) / n_surveys) if n_surveys else None
    return {
        **row,
        "status": "ok" if n_surveys else "no usable answers",
        "surveys_scored": n_surveys,
        "within_1": cal["within_1"],
        "exact": cal["exact"],
        "mean_abs_diff": cal["mean_abs_diff"],
        "rank_r": cal["rank_r"],
        "avg_score": round(avg, 2) if avg is not None else None,
        "score_counts": {str(k): v for k, v in cal["judge_scores"].items()},
        "new_calls": client.calls,
        **use,
    }


def _usage(pairs, client, cache_dir) -> dict:
    """Tokens and time per survey from the judge's saved answers (each keeps what it took when it was made), so a
    re-run that is all cache hits still prices every model correctly. Makes no model call: everything is cached."""
    by_gid = {g["golden_id"]: ins for g, ins, _ in pairs}
    rows, seen = [], set()
    for r in J.read_sheet():
        gid = r["golden_id"]
        if gid in seen or gid not in by_gid or not r.get("score_1_to_5", "").strip():
            continue
        seen.add(gid)
        shown = J.survey_from_text(r.get("questions", ""))
        if shown["items"]:
            rows.append(J.judge_survey(shown, by_gid[gid], client, cache_dir))
    n = len(rows)
    return {
        "calls": n,
        "input_tokens": sum(x.get("input_tokens", 0) for x in rows),
        "output_tokens": sum(x.get("output_tokens", 0) for x in rows),
        "seconds_per_call": round(sum(x.get("seconds", 0) for x in rows) / n, 2) if n else None,
    }


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


def sweep(
    models,
    runtime_factory,
    pairs=None,
    workers: int = 6,
    full: bool = False,
    cache_dir=J.CACHE,
    prices: dict | None = None,
) -> dict:
    pairs = pairs if pairs is not None else J.golden_pairs()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        rows = list(ex.map(lambda m: evaluate_model(m, pairs, runtime_factory, full, cache_dir), models))
    people = J.calibrate(pairs, _NoModel(), cache_dir=None) if pairs else {}
    rows = rank(rows)
    add_costs(rows, prices if prices is not None else load_prices())
    return {
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "region": region(),
        "rubric": J.RUBRIC_VERSION,
        "surveys": 20,
        "people_vs_people": people.get("people_vs_people"),
        "people_rank_r": people.get("people_rank_r"),
        **choose(rows),
        "quality_margin": {"rank_r": QUALITY_MARGIN_R, "mean_abs_diff": QUALITY_MARGIN_GAP},
        "season_surveys": SEASON_SURVEYS,
        "models": rows,
    }


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
    g.add_argument("--prices", action="store_true")
    ap.add_argument("--only", default="", help="comma-separated parts of model ids to keep, e.g. nova,llama")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--full", action="store_true")
    a = ap.parse_args()
    import boto3

    models = discover(boto3.client("bedrock", region_name=region()))
    if a.only:
        keep = [s.strip().lower() for s in a.only.split(",") if s.strip()]
        models = [m for m in models if any(k in m["model_id"].lower() for k in keep)]
    if a.prices:
        got = fetch_prices(boto3.client("pricing", region_name="us-east-1"), region(), models)
        merged = {**got, **load_prices()}  # anything already in the file (checked by a person) wins
        PRICES.write_text(json.dumps(dict(sorted(merged.items())), indent=2) + "\n", encoding="utf-8")
        print(
            f"Prices for {len(merged)} of {len(models)} models -> {PRICES.relative_to(ROOT)} "
            f"({len(got)} from the AWS Price List API). Check them against the Bedrock pricing page; "
            'add any missing model as  "<model id>": {"in": <USD per 1M input tokens>, "out": <...>, "source": "..."}.'
        )
        missing = [m["model_id"] for m in models if m["call_id"] and not price_for(m, merged)]
        if missing:
            print("No price yet:", ", ".join(missing))
        return
    if a.list:
        pr = load_prices()
        for m in models:
            p = price_for(m, pr)
            m["usd_per_1M_in/out"] = f"{p['in']} / {p['out']}" if p else ""
        _print(models, ["provider", "name", "model_id", "call_id", "via", "usd_per_1M_in/out"])
        print(
            f"\n{len(models)} text models in {region()}; {sum(1 for m in models if m['call_id'])} callable; "
            f"{sum(1 for m in models if price_for(m, pr))} priced (run --prices to fetch prices)."
        )
        return
    t0 = time.perf_counter()
    res = sweep(models, lambda: llm.client().runtime(), workers=a.workers, full=a.full)
    RESULTS.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    cols = [
        "rank",
        "pick",
        "provider",
        "name",
        "within_1",
        "mean_abs_diff",
        "rank_r",
        "avg_score",
        "surveys_scored",
        "usd_per_1000_surveys",
        "seconds_per_call",
        "status",
    ] + (["judge_relevance_all"] if a.full else [])
    _print(res["models"], cols)
    errs = [r for r in res["models"] if r.get("status") in ("error", "no usable answers")]
    for r in errs:
        print(f"  {r['model_id']}: {r.get('error', r['status'])}")
    print(
        f"\nMost accurate: {res['most_accurate']}. Best value (cheapest within the quality margin): "
        f"{res['best_value'] or 'none: no priced model is close enough; run --prices'}."
    )
    print(
        f"People vs people: {res['people_vs_people']}. Wrote {RESULTS.relative_to(ROOT)} "
        f"in {time.perf_counter() - t0:.0f} s."
    )


if __name__ == "__main__":
    main()
