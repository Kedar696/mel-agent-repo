#!/usr/bin/env python
"""Print baseline numbers for the README. Owner: P5.

  python scripts/readme_numbers.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mel.config import PACK_DATA
from mel.data import load_golden
from mel.evaluation import score_golden


def _print(label, r):
    print(f"{label}: n={r['n']}  decision={r['decision_acc']:.1%}  rule={r['rule_acc']:.1%}  "
          f"channel={r['channel_acc']:.1%}  window={r['window_acc']:.1%}  "
          f"item_sim={r['item_similarity_avg']:.2f}  misses={len(r['misses'])}")


def main():
    _print("Mock", score_golden())
    path = PACK_DATA / "golden_set.jsonl"
    if path.exists():
        _print("Full", score_golden(load_golden(path)))
    else:
        print("Full pack not found at", PACK_DATA)


if __name__ == "__main__":
    main()
