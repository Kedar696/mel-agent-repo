"""Build a small, reproducible mock dataset from the participant pack.

Usage: python scripts/make_mock_data.py [--pack mel-survey-agent-participant-pack/participant-pack] [--n 60]
(--pack defaults to the committed pack folder in this repo.)
Writes data/mock/{insights.jsonl,golden_set.jsonl,farmers.csv}.
Stratified: every resolution_type, both languages, junk rows, and every golden rule R1-R8.
"""

import argparse, csv, json, random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "mock"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--pack",
        default=str(ROOT / "mel-survey-agent-participant-pack" / "participant-pack"),
        help="participant-pack folder (default: the committed pack)",
    )
    ap.add_argument("--n", type=int, default=60, help="insights to sample")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    pack = Path(a.pack).expanduser()

    rows = [json.loads(l) for l in open(pack / "data/insights.jsonl", encoding="utf-8")]
    buckets = defaultdict(list)
    for r in rows:
        buckets[(r.get("resolution_type"), r.get("quality_flag"), r.get("conversation_language"))].append(r)
    picked, per = [], max(1, a.n // len(buckets))
    for k in sorted(buckets, key=str):
        picked += rnd.sample(buckets[k], min(per, len(buckets[k])))
    picked = picked[: a.n]

    golden = [json.loads(l) for l in open(pack / "data/golden_set.jsonl", encoding="utf-8")]
    by_rule = defaultdict(list)
    for g in golden:
        by_rule[g["expected"]["rule"]].append(g)
    gpick = []
    for rule, gs in sorted(by_rule.items()):
        gpick += rnd.sample(gs, min(4 if rule != "R8" else 12, len(gs)))

    farmer_ids = {r["farmer_id"] for r in picked} | {g["insight"]["farmer_id"] for g in gpick}
    with open(pack / "data/farmers.csv", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        frows = [r for r in rd if r["farmer_id"] in farmer_ids]
        fields = rd.fieldnames

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "insights.jsonl", "w", encoding="utf-8") as f:
        for r in picked:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(OUT / "golden_set.jsonl", "w", encoding="utf-8") as f:
        for g in gpick:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    with open(OUT / "farmers.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(frows)
    print(f"insights={len(picked)} golden={len(gpick)} farmers={len(frows)} -> {OUT}")


if __name__ == "__main__":
    main()
