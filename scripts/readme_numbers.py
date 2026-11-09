#!/usr/bin/env python
"""Regenerate every published number from a fresh run. Owner: P5 (README results section).
The logic lives in mel/evaluation/report.py; this is the command-line wrapper.

  python scripts/readme_numbers.py                          print numbers for both send-time rules
  python scripts/readme_numbers.py --write                  also rewrite the README results block
                                                            and docs/results/scorecard.md
  python scripts/readme_numbers.py --write --record "what changed" [--basis brief|answer_key]
                                                            also append to docs/results/eval_history.jsonl

Numbers in the README and slides come from here, never typed by hand (team contract).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mel.config import ROOT
from mel.evaluation.report import BASES, run_eval, write_outputs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="rewrite README results + offline scorecard")
    ap.add_argument("--record", metavar="LABEL", help="append this run to the history, with a label")
    ap.add_argument(
        "--history",
        action="store_true",
        help="score with P4's history rules H1-H4 on (off by default; README always shows history off)",
    )
    ap.add_argument(
        "--basis",
        choices=[*BASES, "both"],
        default="both",
        help="which send-time rule(s) to score and record (default both)",
    )
    a = ap.parse_args()

    bases = BASES if a.basis == "both" else (a.basis,)
    results = run_eval(bases, record=a.record, history=a.history)
    for b, r in results.items():
        for label, g in (("full", r["full"]), ("mock", r["mock"])):
            if g:
                print(
                    f"[{b}] {label}: n={g['n']}  decision={g['decision_acc']:.1%}  rule={g['rule_acc']:.1%}  "
                    f"channel={g['channel_acc']:.1%}  window={g['window_acc']:.1%}  "
                    f"item_sim={g['item_similarity_avg']:.2f}  misses={len(g['misses'])}"
                )
        c = r["card"]
        print(
            f"[{b}] batch: insights={c['n_insights']}  surveyed={c['n_surveyed']}  format={c['format_pass']:.1%}  "
            f"safety={c['safety_pass']:.1%}  timeliness={c['timeliness_pass']:.1%}  "
            f"failed_but_scheduled={c['failed_but_scheduled']}  relevance={c['relevance_avg']:.2f}  "
            f"{c['s_per_survey'] * 1000:.1f} ms/survey ({c['batch_seconds']} s total)"
        )
    if a.record:
        print(f"Recorded: {a.record} ({', '.join(bases)})")
    if a.write:
        if a.basis != "both" or a.history:
            results = run_eval(BASES)  # published outputs: both send-time rules, history off
        for p in write_outputs(results):
            print("Wrote", p.relative_to(ROOT))


if __name__ == "__main__":
    main()
