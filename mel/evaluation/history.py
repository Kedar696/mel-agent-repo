"""Eval run history, so the demo can show scores improving run by run ("hill-climb"). Owner: P5.

Each recorded run is one line in docs/results/eval_history.jsonl: when, which commit, a short label
saying what changed, and the headline numbers. The file is committed so the trend survives.
Record a run with:  python scripts/readme_numbers.py --record "R7 storage exception"
"""
import json
import subprocess
from datetime import datetime

from mel.config import ROOT, IST

HISTORY = ROOT / "docs" / "results" / "eval_history.jsonl"
KEYS = ("decision_acc", "rule_acc", "channel_acc", "window_acc", "item_similarity_avg",
        "format_pass", "safety_pass", "failed_but_scheduled", "ms_per_insight")


def _git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def load_history(path=HISTORY) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def record_run(label: str, golden: dict, card: dict, path=HISTORY) -> dict:
    """Append one run. `golden` = score_golden() result (full pack), `card` = run_scorecard() result."""
    row = {
        "run": len(load_history(path)) + 1,
        "at": datetime.now(IST).isoformat(timespec="seconds"),
        "commit": _git("rev-parse", "--short", "HEAD") or "unknown",
        "uncommitted_changes": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "label": label,
        "golden_rows": golden["n"], "insights": card["n_insights"],
        **{k: round(v, 4) if isinstance(v, float) else v
           for k, v in {**golden, **card}.items() if k in KEYS},
        "misses": len(golden["misses"]),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row
