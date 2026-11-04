"""AI judge for survey relevance (Digital Green: "LLM-as-judge for relevance"). Owner: P5.

A small model on Amazon Bedrock reads one insight (what the farmer asked, the advice given) and the survey
we wrote for it, and scores relevance 1-5 against RUBRIC. English is the evaluation baseline, so the judge
reads the en-IN survey. Off by default: nothing calls Bedrock unless you ask.

    python -m mel.evaluation.judge --make-sheet     write docs/results/hand_scores.csv (20 surveys to score by hand)
    python -m mel.evaluation.judge --run            judge the answer key's survey rows (needs Bedrock)
    python -m mel.evaluation.judge --calibrate      compare the judge with the team's hand scores (needs Bedrock)

Bedrock settings (credentials come from the AWS account's IAM role, never a key in code):
    MEL_JUDGE_MODEL      Bedrock model id or inference profile, e.g. a small Claude model enabled in our region
    AWS_REGION           the region event staff enabled the models in
    MEL_JUDGE_PRICE_IN / MEL_JUDGE_PRICE_OUT   optional USD per million input / output tokens, for cost logs

When P4's ModelClient lands, pass it as `client` (anything with .complete(system, user) -> (text, usage)).
"""
import argparse
import csv
import hashlib
import json
import os
import random
import re
import time
from collections import defaultdict

from mel.config import OUT, PACK_DATA, ROOT
from mel.data import load_golden
from mel.pipeline import run_insight, clean

RUBRIC_VERSION = "v1"
RUBRIC = """Score how relevant this follow-up survey is to the advice this farmer actually received.

5 = Asks directly whether the farmer acted on this specific advice and whether it worked. Every question
    is about this farmer's crop or animal and problem. Short, tap-to-answer.
4 = Clearly about this advice, but one question is generic or slightly off the main action.
3 = About the right crop or problem, but does not check the specific action that was advised.
2 = Mostly generic: could be sent to any farmer; only loosely tied to this conversation.
1 = Irrelevant, gives new advice, contradicts the advice, or asks for personal information.

Built from Digital Green's design principles: one farmer, one context; ask about the advice given; never give
new advice; short and tappable. Replace with Digital Green's MEL rubric if they share one."""

SYSTEM = ("You are a monitoring-and-evaluation reviewer for Digital Green's FarmerChat. You grade follow-up "
          "surveys against a rubric. Reply with JSON only: {\"score\": <1-5>, \"reason\": \"<one sentence>\"}.")

SHEET = ROOT / "docs" / "results" / "hand_scores.csv"
CACHE = OUT / "judge_cache"
RESULTS = OUT / "judge_results.jsonl"
SHEET_FIELDS = ["sample", "golden_id", "insight_id", "crop_or_animal", "resolution", "farmer_asked",
                "advice_given", "questions", "score_1_to_5", "scorer", "notes"]


# ---------------------------------------------------------------- what the judge sees

def survey_text(survey: dict) -> str:
    lines = []
    for i, it in enumerate(survey.get("items", []), 1):
        if it.get("type") == "survey-scale":
            opts = f"scale {it.get('scale_min')}-{it.get('scale_max')}"
        else:
            opts = " / ".join(str(o.get("label")) for o in it.get("options", []))
        lines.append(f"Q{i}. {it.get('prompt')}  [{opts}]")
    return "\n".join(lines)


def insight_text(insight: dict) -> str:
    a = insight.get("asset") or {}
    return (f"Crop or animal: {a.get('name') or 'unknown'} ({a.get('growth_stage') or 'stage unknown'})\n"
            f"Problem: {(insight.get('concern') or 'unknown').replace('_', ' ')}\n"
            f"Farmer asked: {insight.get('query_summary') or '-'}\n"
            f"Advice given: {insight.get('advice_summary') or '-'}\n"
            f"Resolution: {(insight.get('resolution_type') or '-').replace('_', ' ')}")


def prompt_for(survey: dict, insight: dict) -> str:
    return (f"RUBRIC\n{RUBRIC}\n\nCONVERSATION SUMMARY\n{insight_text(insight)}\n\n"
            f"SURVEY SENT TO THE FARMER\n{survey_text(survey)}\n\nReturn JSON only.")


def parse_score(text: str) -> tuple[int | None, str]:
    """Pull {"score", "reason"} out of the model's reply. None if it isn't a 1-5 score."""
    try:
        obj = json.loads(text[text.index("{"): text.rindex("}") + 1])
        score = int(obj.get("score"))
        return (score if 1 <= score <= 5 else None), str(obj.get("reason", ""))[:300]
    except (ValueError, TypeError, AttributeError):
        m = re.search(r"\b([1-5])\b", text or "")
        return (int(m.group(1)) if m else None), (text or "")[:300]


# ---------------------------------------------------------------- model access

class BedrockClient:
    """Minimal Bedrock Converse adapter. Swap for P4's ModelClient once it exists."""

    def __init__(self, model_id: str | None = None, region: str | None = None):
        self.model_id = model_id or os.environ.get("MEL_JUDGE_MODEL")
        if not self.model_id:
            raise RuntimeError("Set MEL_JUDGE_MODEL to a Bedrock model id enabled in our account (ask P1/P4).")
        import boto3  # only needed when the judge actually runs
        self._rt = boto3.client("bedrock-runtime", region_name=region or os.environ.get("AWS_REGION"))

    def complete(self, system: str, user: str) -> tuple[str, dict]:
        r = self._rt.converse(modelId=self.model_id, system=[{"text": system}],
                              messages=[{"role": "user", "content": [{"text": user}]}],
                              inferenceConfig={"maxTokens": 200, "temperature": 0})
        text = "".join(c.get("text", "") for c in r["output"]["message"]["content"])
        u = r.get("usage", {})
        return text, {"input_tokens": u.get("inputTokens", 0), "output_tokens": u.get("outputTokens", 0)}


def _cost(usage: dict) -> float | None:
    pin, pout = os.environ.get("MEL_JUDGE_PRICE_IN"), os.environ.get("MEL_JUDGE_PRICE_OUT")
    if not (pin and pout):
        return None
    return (usage.get("input_tokens", 0) * float(pin) + usage.get("output_tokens", 0) * float(pout)) / 1e6


def judge_survey(survey: dict, insight: dict, client, cache_dir=CACHE) -> dict:
    """Score one survey. Cached on disk by (rubric version, model, prompt), so reruns are free and repeatable."""
    user = prompt_for(survey, insight)
    model = getattr(client, "model_id", type(client).__name__)
    key = hashlib.sha256(f"{RUBRIC_VERSION}|{model}|{user}".encode()).hexdigest()[:24]
    path = cache_dir / f"{key}.json" if cache_dir else None
    if path and path.exists():
        return {**json.loads(path.read_text(encoding="utf-8")), "cached": True}
    t0 = time.perf_counter()
    text, usage = client.complete(SYSTEM, user)
    score, reason = parse_score(text)
    row = {"insight_id": insight.get("insight_id"), "score": score, "reason": reason, "model": model,
           "rubric": RUBRIC_VERSION, "input_tokens": usage.get("input_tokens", 0),
           "output_tokens": usage.get("output_tokens", 0), "cost_usd": _cost(usage),
           "seconds": round(time.perf_counter() - t0, 3)}
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    return {**row, "cached": False}


# ---------------------------------------------------------------- which surveys

def golden_pairs(golden: list[dict] | None = None) -> list[tuple[dict, dict, dict]]:
    """(golden row, insight, our en-IN survey) for every answer-key row where both we and the key survey."""
    if golden is None:
        path = PACK_DATA / "golden_set.jsonl"
        golden = load_golden(path if path.exists() else None)
    out = []
    for g in golden:
        if not g["expected"].get("survey"):
            continue
        res = run_insight(g["insight"])
        if res["decision"].survey:
            out.append((g, g["insight"], clean(res["surveys"]["en-IN"])))
    return out


def judge_batch(pairs, client, cache_dir=CACHE) -> dict:
    rows = [{"golden_id": g["golden_id"], **judge_survey(s, ins, client, cache_dir)} for g, ins, s in pairs]
    scored = [r["score"] for r in rows if r["score"] is not None]
    costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    return {"n": len(rows), "n_scored": len(scored),
            "judge_relevance": round(sum(scored) / len(scored), 2) if scored else None,
            "input_tokens": sum(r["input_tokens"] for r in rows),
            "output_tokens": sum(r["output_tokens"] for r in rows),
            "cost_usd": round(sum(costs), 4) if costs else None,
            "seconds": round(sum(r["seconds"] for r in rows if not r["cached"]), 2),
            "rows": rows}


# ---------------------------------------------------------------- hand-scoring sheet and calibration

def sample_for_hand_scoring(pairs, n: int = 20, seed: int = 7):
    """n surveys spread across resolution types (direct action, wait and monitor, ...), same every time."""
    by_res = defaultdict(list)
    for p in sorted(pairs, key=lambda p: p[0]["golden_id"]):
        by_res[p[1].get("resolution_type")].append(p)
    rnd = random.Random(seed)
    for v in by_res.values():
        rnd.shuffle(v)
    picked, keys = [], sorted(by_res, key=str)
    while len(picked) < n and any(by_res.values()):
        for k in keys:
            if by_res[k] and len(picked) < n:
                picked.append(by_res[k].pop())
    return sorted(picked, key=lambda p: p[0]["golden_id"])


def make_sheet(pairs, path=SHEET, n: int = 20) -> int:
    """Write the hand-scoring sheet. Never overwrites a sheet that already has scores in it."""
    if path.exists() and any(r.get("score_1_to_5", "").strip() for r in read_sheet(path)):
        raise FileExistsError(f"{path} already has hand scores; move it aside before regenerating.")
    sample = sample_for_hand_scoring(pairs, n)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SHEET_FIELDS)
        w.writeheader()
        for i, (g, ins, s) in enumerate(sample, 1):
            a = ins.get("asset") or {}
            w.writerow({"sample": i, "golden_id": g["golden_id"], "insight_id": ins.get("insight_id"),
                        "crop_or_animal": a.get("name"), "resolution": ins.get("resolution_type"),
                        "farmer_asked": ins.get("query_summary"), "advice_given": ins.get("advice_summary"),
                        "questions": survey_text(s), "score_1_to_5": "", "scorer": "", "notes": ""})
    return len(sample)


def read_sheet(path=SHEET) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def agreement(pairs_of_scores: list[tuple[int, int]]) -> dict:
    """How often the judge agrees with people: exact, within one point, and average gap."""
    n = len(pairs_of_scores)
    if not n:
        return {"n": 0, "exact": None, "within_1": None, "mean_abs_diff": None}
    diffs = [abs(h - j) for h, j in pairs_of_scores]
    return {"n": n, "exact": sum(d == 0 for d in diffs) / n, "within_1": sum(d <= 1 for d in diffs) / n,
            "mean_abs_diff": round(sum(diffs) / n, 2)}


def calibrate(pairs, client, path=SHEET, cache_dir=CACHE) -> dict:
    by_gid = {g["golden_id"]: (g, ins, s) for g, ins, s in pairs}
    both = []
    for r in read_sheet(path):
        h = r.get("score_1_to_5", "").strip()
        if not h or r["golden_id"] not in by_gid:
            continue
        g, ins, s = by_gid[r["golden_id"]]
        j = judge_survey(s, ins, client, cache_dir)["score"]
        if j is not None:
            both.append((int(h), j))
    return agreement(both)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--make-sheet", action="store_true")
    g.add_argument("--run", action="store_true")
    g.add_argument("--calibrate", action="store_true")
    a = ap.parse_args()
    pairs = golden_pairs()
    if a.make_sheet:
        print(f"Wrote {make_sheet(pairs)} surveys to {SHEET.relative_to(ROOT)}")
        return
    client = BedrockClient()
    if a.run:
        r = judge_batch(pairs, client)
        RESULTS.parent.mkdir(parents=True, exist_ok=True)
        RESULTS.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in r["rows"]) + "\n", encoding="utf-8")
        print({k: v for k, v in r.items() if k != "rows"}, "->", RESULTS)
    else:
        print(calibrate(pairs, client))


if __name__ == "__main__":
    main()
