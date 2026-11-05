"""Blind side-by-side sheet: today's Bedrock writer vs the templates, scored by people. Owner: P5.

Why: the AI judge gives Bedrock 4.9 and templates 4.5, but it may just reward longer questions. People
decide here, without knowing which writer made which survey, and the score step checks whether the
longer survey simply wins.

Make the sheet ($0: the Bedrock surveys come from the committed replay file docs/results/bedrock_cache.jsonl):
    python scripts/blind_sheet.py make
Each scorer copies docs/results/blind_sheet.csv to docs/results/blind_sheet_<name>.csv and fills
score_A, score_B (1-5, rubric in README "Relevance rubric") and better (A, B or same). Then:
    python scripts/blind_sheet.py score docs/results/blind_sheet_*.csv
which writes docs/results/blind_comparison.md and .json. The key (which survey is Bedrock) is in
docs/results/blind_sheet_key.json: don't open it before scoring.
"""
import csv
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RESULTS = ROOT / "docs" / "results"
SHEET, KEY = RESULTS / "blind_sheet.csv", RESULTS / "blind_sheet_key.json"
WRITE_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

# Pairs per advice type: every type that gets surveys, so the sample isn't all direct action.
# (generic_information and needs_more_context never get a survey under R1-R8, so they have no pairs.)
QUOTA = {"direct_action": 8, "plan_created": 5, "wait_and_monitor": 3, "escalate_to_expert": 2, "do_not_act": 2}
FIELDS = ["pair", "insight_id", "crop_or_animal", "advice_type", "farmer_asked", "advice_given",
          "survey_A", "survey_B", "score_A", "score_B", "better", "scorer", "notes"]


def show(items: list[dict]) -> str:
    """One survey as plain text, the way a farmer would see it (questions and tap answers)."""
    out = []
    for n, q in enumerate(items, 1):
        if q.get("options"):
            answers = " / ".join(o["label"] for o in q["options"])
        else:
            lo, hi = q.get("scale_min", 1), q.get("scale_max", 5)
            ends = [q.get("scale_min_label"), q.get("scale_max_label")]
            answers = f"scale {lo}-{hi}" + (f" ({ends[0]} ... {ends[1]})" if all(ends) else "")
        out.append(f"Q{n}. {q['prompt']}  [{answers}]")
    return "\n".join(out)


def chars(items: list[dict]) -> int:
    return sum(len(q["prompt"]) for q in items)


def make(seed: int = 7) -> None:
    os.environ.setdefault("MEL_DATA_DIR", str(ROOT / "mel-survey-agent-participant-pack/participant-pack/data"))
    os.environ.setdefault("MEL_BEDROCK_WRITE_MODEL", WRITE_MODEL)
    os.environ.setdefault("MEL_BEDROCK_REGION", "us-west-2")
    from mel.agent.orchestrator import run_agent_to_end
    from mel.data.loader import load_insights
    from mel.decision import decide
    from mel.pipeline import clean
    from mel.writer import llm

    insights = load_insights()
    random.Random(seed).shuffle(insights)
    need, rows, key, skipped = dict(QUOTA), [], {}, Counter()
    for ins in insights:
        t = ins.get("resolution_type")
        if not need.get(t):
            continue
        try:
            if not decide(clean(ins)).survey:
                continue
        except Exception:
            continue
        with llm.writer(False):
            tpl = run_agent_to_end(ins, langs=("en-IN",))[1]["surveys"]["en-IN"]
        with llm.writer(True):
            res = run_agent_to_end(ins, langs=("en-IN",))[1]
        bed = res["surveys"]["en-IN"]
        if res["metrics"]["input_tokens"] or res["metrics"]["output_tokens"]:
            raise SystemExit("A Bedrock call was paid for: this script must only replay saved answers.")
        if bed.get("_source") != "bedrock":
            skipped["bedrock fell back to the template or had no saved answer"] += 1
            continue
        need[t] -= 1
        pair = len(rows) + 1
        a_is_bedrock = random.Random(seed * 1000 + pair).random() < 0.5
        a, b = (bed, tpl) if a_is_bedrock else (tpl, bed)
        rows.append({"pair": pair, "insight_id": ins["insight_id"],
                     "crop_or_animal": (ins.get("asset") or {}).get("name"), "advice_type": t,
                     "farmer_asked": ins.get("query_summary"), "advice_given": ins.get("advice_summary"),
                     "survey_A": show(a["items"]), "survey_B": show(b["items"]),
                     "score_A": "", "score_B": "", "better": "", "scorer": "", "notes": ""})
        key[str(pair)] = {"A": "bedrock" if a_is_bedrock else "template", "B": "template" if a_is_bedrock else "bedrock",
                          "chars_A": chars(a["items"]), "chars_B": chars(b["items"]),
                          "items_A": len(a["items"]), "items_B": len(b["items"])}
        if not any(need.values()):
            break
    with SHEET.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)
    KEY.write_text(json.dumps({"note": "Which writer made A and B in each pair. Don't open until scoring is done.",
                               "writer_model": WRITE_MODEL, "seed": seed, "short_of_quota": {k: v for k, v in need.items() if v},
                               "skipped": dict(skipped), "pairs": key}, indent=2) + "\n", encoding="utf-8")
    print(f"{len(rows)} pairs -> {SHEET.relative_to(ROOT)} (key {KEY.relative_to(ROOT)}); skipped {dict(skipped)}")


def sign_test(wins: int, losses: int) -> float:
    """Two-sided p-value: how often a coin would split at least this unevenly."""
    n = wins + losses
    if not n:
        return 1.0
    k = max(wins, losses)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n)


def score(paths: list[str]) -> dict:
    key = json.loads(KEY.read_text(encoding="utf-8"))["pairs"]
    marks, prefs, longer = defaultdict(list), Counter(), Counter()
    by_type = defaultdict(Counter)
    scorers, rows_used = set(), 0
    for p in paths:
        for r in csv.DictReader(open(p, encoding="utf-8")):
            k = key.get(str(r["pair"]))
            if not k:
                continue
            got = False
            for side in "AB":
                v = (r.get(f"score_{side}") or "").strip()
                if v.isdigit() and 1 <= int(v) <= 5:
                    marks[k[side]].append(int(v))
                    got = True
            better = (r.get("better") or "").strip().upper()
            if better in ("A", "B"):
                winner = k[better]
                prefs[winner] += 1
                by_type[r["advice_type"]][winner] += 1
                if k["chars_A"] != k["chars_B"]:
                    long_side = "A" if k["chars_A"] > k["chars_B"] else "B"
                    longer["longer won" if better == long_side else "shorter won"] += 1
                got = True
            elif better in ("SAME", "="):
                prefs["same"] += 1
                by_type[r["advice_type"]]["same"] += 1
                got = True
            if got:
                rows_used += 1
                scorers.add((r.get("scorer") or Path(p).stem).strip())
    mean = {w: round(sum(v) / len(v), 2) if v else None for w, v in marks.items()}
    out = {"files": [str(Path(p).name) for p in paths], "scorers": sorted(scorers), "rows_scored": rows_used,
           "mean_score": mean, "n_scores": {w: len(v) for w, v in marks.items()},
           "preferred": dict(prefs), "p_value_sign_test": round(sign_test(prefs["bedrock"], prefs["template"]), 3),
           "longer_survey": dict(longer), "by_advice_type": {t: dict(c) for t, c in sorted(by_type.items())},
           "avg_survey_chars": {w: round(sum(k["chars_A"] if k["A"] == w else k["chars_B"] for k in key.values())
                                         / max(1, len(key)), 1) for w in ("bedrock", "template")}}
    decided = prefs["bedrock"] + prefs["template"]
    verdict = ("not enough answers yet" if decided < 10 else
               "people prefer Bedrock" if prefs["bedrock"] > prefs["template"] and out["p_value_sign_test"] < 0.05 else
               "people prefer the templates" if prefs["template"] > prefs["bedrock"] and out["p_value_sign_test"] < 0.05 else
               "no clear winner")
    out["verdict"] = verdict
    lw, sw = longer["longer won"], longer["shorter won"]
    lines = ["# Blind comparison: Bedrock writer vs templates (people's scores)", "",
             f"Scorers: {', '.join(out['scorers']) or 'none yet'} · rows scored: {rows_used} · sheet: `docs/results/blind_sheet.csv`", "",
             f"**Verdict: {verdict}.**", "",
             "| | Bedrock (Claude Haiku 4.5) | Templates |", "|---|---|---|",
             f"| Mean score (1-5) | {mean.get('bedrock')} ({len(marks['bedrock'])} scores) | {mean.get('template')} ({len(marks['template'])} scores) |",
             f"| Picked as better | {prefs['bedrock']} | {prefs['template']} |",
             f"| Survey length (characters of question text) | {out['avg_survey_chars']['bedrock']} | {out['avg_survey_chars']['template']} |", "",
             f"\"Same\": {prefs['same']}. Sign test on better/worse picks: p = {out['p_value_sign_test']} "
             "(below 0.05 means the split is unlikely to be chance).", "",
             f"**Does the longer survey just win?** Longer won {lw}, shorter won {sw}"
             + (f" ({round(100 * lw / (lw + sw))}% longer)." if lw + sw else "."), "",
             "By advice type (picks): " + "; ".join(f"{t} {dict(c)}" for t, c in out["by_advice_type"].items())]
    (RESULTS / "blind_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (RESULTS / "blind_comparison.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return out


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "make":
        make()
    elif len(sys.argv) >= 3 and sys.argv[1] == "score":
        score(sys.argv[2:])
    else:
        raise SystemExit(__doc__)
