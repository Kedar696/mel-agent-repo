"""Score our decisions against data/*/golden_set.jsonl. Owner: P5.

Metrics: decision accuracy (survey yes/no), rule match, channel match (expected.channel vs our
first channel), send-window exact match, per-rule confusion matrix, item similarity vs expected.items.
"""
import re
from collections import Counter

from mel.data import load_golden
from mel.pipeline import run_insight, clean

RULES = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]


def item_similarity(survey: dict, golden_items: list[dict]) -> float:
    """How close our survey items are to the golden set's expected items (0..1).

    For each expected item, checks whether any of our items shares a keyword (4+ letters)
    in the prompt.  Returns the fraction of expected items that found a match.
    Baseline only; a Claude judge or embedding similarity would be stronger.
    """
    if not golden_items or not survey.get("items"):
        return 0.0
    our_items = survey["items"]
    matched = 0
    for g in golden_items:
        g_words = set(re.findall(r"[a-z]{4,}", (g.get("text") or "").lower()))
        for o in our_items:
            o_words = set(re.findall(r"[a-z]{4,}", (o.get("prompt") or "").lower()))
            if g_words & o_words:
                matched += 1
                break
    return round(matched / len(golden_items), 2)


def score_golden(golden: list[dict] | None = None) -> dict:
    golden = golden or load_golden()
    n = len(golden)
    hits = Counter()
    misses = []
    confusion = {e: {g: 0 for g in RULES} for e in RULES}
    item_sims = []
    for g in golden:
        exp, out = g["expected"], run_insight(g["insight"])
        d = out["decision"]
        ok_dec = d.survey == exp["survey"]
        hits["decision"] += ok_dec
        hits["rule"] += d.rule == exp.get("rule")
        exp_rule = exp.get("rule", "?")
        if exp_rule in confusion:
            confusion[exp_rule][d.rule] += 1
        if exp["survey"] and d.survey:
            hits["survey_rows"] += 1
            h = out["handoff"]
            hits["channel"] += h["channel_order"][0]["channel"] == exp.get("channel")
            ew = exp.get("send_window") or {}
            hits["window"] += (h["send_window"]["not_before"], h["send_window"]["not_after"]) == (ew.get("start"), ew.get("end"))
            if exp.get("items"):
                our = clean(out.get("surveys", {}).get("en-IN") or out.get("surveys", {}).get("hi-IN", {}))
                if our.get("items"):
                    item_sims.append({"golden_id": g["golden_id"], "score": item_similarity(our, exp["items"])})
        if not ok_dec or d.rule != exp.get("rule"):
            misses.append({"golden_id": g["golden_id"], "insight_id": g["insight_id"],
                           "expected": exp.get("rule"), "got": d.rule, "reason": exp.get("reason_code")})
    sr = max(hits["survey_rows"], 1)
    sim_avg = round(sum(s["score"] for s in item_sims) / len(item_sims), 2) if item_sims else 0.0
    return {"n": n, "decision_acc": hits["decision"] / n, "rule_acc": hits["rule"] / n,
            "channel_acc": hits["channel"] / sr, "window_acc": hits["window"] / sr,
            "confusion": confusion, "item_similarities": item_sims,
            "item_similarity_avg": sim_avg, "misses": misses}
