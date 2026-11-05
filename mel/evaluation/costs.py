"""What generating surveys costs, run by run, and what the whole dataset would cost. Owner: P5.

Every run that writes surveys with Bedrock adds one line to docs/results/cost_history.jsonl (committed, so the trend
survives): when, which commit, which models, how many surveys, tokens and dollars split by purpose (write / check /
judge), revisions and template fallbacks, cost per survey, and the projected cost of the full synthetic dataset.

The numbers come from P4's call log (out/bedrock_calls.jsonl, one row per model call, priced by llm.cost_usd from
docs/results/bedrock_prices.json). A CostMeter remembers where the log ended when the run started and reads only what
was added after, so it stays right with parallel workers. A cached answer costs $0: the ledger shows real spend.
"""
import json
from collections import defaultdict
from datetime import datetime

from mel.config import ROOT, IST
from mel.writer import llm

from .history import _git

LEDGER = ROOT / "docs" / "results" / "cost_history.jsonl"
FULL_SET_SURVEYS = 2616          # surveys in the full 6,999-insight run (brief rules), each in hi-IN and en-IN
LANGS_PER_SURVEY = 2


class CostMeter:
    """Spend since construction, read from the model-call log."""

    def __init__(self, path=None):
        self.path = path or llm.log_path()
        self.start = self.path.stat().st_size if self.path.exists() else 0

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open("rb") as f:
            f.seek(self.start)
            out = []
            for line in f.read().decode("utf-8", "replace").splitlines():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
            return out

    def spent(self) -> float:
        return round(sum(r.get("cost_usd") or 0 for r in self.rows()), 6)

    def summary(self) -> dict:
        rows = self.rows()
        by = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0})
        models = defaultdict(set)
        for r in rows:
            if r.get("cached") or not r.get("ok", True):
                continue
            p = r.get("purpose") or "write"
            b = by[p]
            b["calls"] += 1
            b["input_tokens"] += r.get("input_tokens", 0)
            b["output_tokens"] += r.get("output_tokens", 0)
            b["usd"] = round(b["usd"] + (r.get("cost_usd") or 0), 6)
            models[p].add(r.get("model"))
        unpriced = sum(1 for r in rows if r.get("ok", True) and not r.get("cached") and r.get("cost_usd") is None)
        return {"calls": sum(b["calls"] for b in by.values()), "cached_calls": sum(1 for r in rows if r.get("cached")),
                "failed_calls": sum(1 for r in rows if not r.get("ok", True)), "unpriced_calls": unpriced,
                "input_tokens": sum(b["input_tokens"] for b in by.values()),
                "output_tokens": sum(b["output_tokens"] for b in by.values()),
                "spent_usd": round(sum(b["usd"] for b in by.values()), 6),
                "by_purpose": {k: dict(v) for k, v in sorted(by.items())},
                "models": {k: sorted(m for m in v if m) for k, v in sorted(models.items())},
                "fresh_tags": sorted({r.get("tag") for r in rows if not r.get("cached") and r.get("ok", True)
                                      and (r.get("purpose") or "write") == "write" and r.get("tag")})}


def projection(spent_usd: float, surveys_written: int, full_surveys: int = FULL_SET_SURVEYS) -> dict:
    """Cost per survey (both languages, revisions and checks included) and what the full dataset would cost."""
    if not surveys_written:
        return {"usd_per_survey": None, "usd_per_1000_surveys": None, "projected_full_usd": None}
    per = spent_usd / surveys_written
    return {"usd_per_survey": round(per, 6), "usd_per_1000_surveys": round(per * 1000, 4),
            "projected_full_usd": round(per * full_surveys, 2), "full_surveys": full_surveys}


def record_cost(row: dict, path=LEDGER) -> dict:
    """Append one run to the ledger (adds run number, time and commit)."""
    full = {"run": len(load_costs(path)) + 1, "at": datetime.now(IST).isoformat(timespec="seconds"),
            "commit": _git("rev-parse", "--short", "HEAD") or "unknown", **row}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(full, ensure_ascii=False) + "\n")
    return full


def load_costs(path=LEDGER) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def row_from_results(kind: str, label: str, meter: CostMeter, results: list[dict], **extra) -> dict:
    """One ledger row from a CostMeter and the agent results (step 'result' events) of the run."""
    s = meter.summary()
    surveyed = [r for r in results if r.get("surveys")]
    fresh = set(s.pop("fresh_tags"))
    written = sum(1 for r in surveyed if r.get("insight_id") in fresh)   # surveys that made a new writing call
    fallbacks = defaultdict(int)
    sources = defaultdict(int)
    for r in surveyed:
        for lang, sv in r["surveys"].items():
            sources[f"{lang}:{sv.get('_source')}"] += 1
            if sv.get("_fallback_reason"):
                fallbacks[sv["_fallback_reason"]] += 1
    return {"kind": kind, "label": label, "insights": len(results), "surveys": len(surveyed),
            "files": sum(len(r["surveys"]) for r in surveyed), "surveys_written_fresh": written,
            "revisions": sum((r.get("metrics") or {}).get("revisions", 0) for r in surveyed),
            "sources": dict(sorted(sources.items())), "fallbacks": dict(sorted(fallbacks.items())),
            **s, **projection(s["spent_usd"], written), **extra}
