"""Eval run history, so the demo can show scores improving run by run ("hill-climb"). Owner: P5.

Each recorded run is one line in docs/results/eval_history.jsonl: when, which commit, a short label
saying what changed, and the headline numbers. The file is committed so the trend survives.
Record a run with:  python scripts/readme_numbers.py --write --record "what changed" [--basis brief|answer_key]
"""
import json
import subprocess
from datetime import datetime

from mel.config import ROOT, IST

HISTORY = ROOT / "docs" / "results" / "eval_history.jsonl"
KEYS = ("decision_acc", "rule_acc", "channel_acc", "window_acc", "item_similarity_avg",
        "format_pass", "safety_pass", "timeliness_pass", "relevance_avg", "judge_relevance",
        "failed_but_scheduled", "ms_per_insight", "s_per_survey")


def _git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def load_history(path=HISTORY) -> list[dict]:
    if not path.exists():
        return []
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    for r in rows:
        r.setdefault("timing_basis", "brief")  # rows recorded before the timing setting existed
        r.setdefault("history", False)          # rows recorded before P4's history rules joined the pipeline
    return rows


def record_run(label: str, golden: dict, card: dict, path=HISTORY, timing_basis: str = "brief",
               history: bool = False) -> dict:
    """Append one run. `golden` = score_golden() result (full pack), `card` = run_scorecard() result,
    `timing_basis` = which send-window rule was active (MEL_TIMING_BASIS)."""
    row = {
        "run": len(load_history(path)) + 1,
        "at": datetime.now(IST).isoformat(timespec="seconds"),
        "commit": _git("rev-parse", "--short", "HEAD") or "unknown",
        "uncommitted_changes": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "label": label, "timing_basis": timing_basis, "history": history,
        "golden_rows": golden["n"], "insights": card["n_insights"],
        **{k: round(v, 4) if isinstance(v, float) else v
           for k, v in {**golden, **card}.items() if k in KEYS},
        "misses": len(golden["misses"]),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row
