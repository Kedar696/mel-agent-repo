"""Score our decisions against data/*/golden_set.jsonl. Owner: P8.

Metrics: decision accuracy (survey yes/no), rule match, channel match (expected.channel vs our
first channel), send-window exact match. TODO(P8): item similarity vs expected.items, per-rule confusion.
"""
from collections import Counter

from mel.data import load_golden
from mel.pipeline import run_insight


def score_golden(golden: list[dict] | None = None) -> dict:
    golden = golden or load_golden()
    n = len(golden)
    hits = Counter()
    misses = []
    for g in golden:
        exp, out = g["expected"], run_insight(g["insight"])
        d = out["decision"]
        ok_dec = d.survey == exp["survey"]
        hits["decision"] += ok_dec
        hits["rule"] += d.rule == exp.get("rule")
        if exp["survey"] and d.survey:
            hits["survey_rows"] += 1
            h = out["handoff"]
            hits["channel"] += h["channel_order"][0]["channel"] == exp.get("channel")
            ew = exp.get("send_window") or {}
            hits["window"] += (h["send_window"]["not_before"], h["send_window"]["not_after"]) == (ew.get("start"), ew.get("end"))
        if not ok_dec or d.rule != exp.get("rule"):
            misses.append({"golden_id": g["golden_id"], "insight_id": g["insight_id"],
                           "expected": exp.get("rule"), "got": d.rule, "reason": exp.get("reason_code")})
    sr = max(hits["survey_rows"], 1)
    return {"n": n, "decision_acc": hits["decision"] / n, "rule_acc": hits["rule"] / n,
            "channel_acc": hits["channel"] / sr, "window_acc": hits["window"] / sr, "misses": misses}
