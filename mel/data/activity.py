"""Activity attention: label each insight by whether the farmer's activity is *changing*. Owner: P1.

The beneficiary's representative asked us to focus survey attention on positive CHANGE in a farmer's
activity, not on high activity itself:
  surge        quiet, then a jump in activity or a sudden high-weight (urgent) question -> highlight.
  steady_high  constantly busy -> no top treatment by default.
  neutral      everyone else, including a farmer whose activity drops or stops (no boost, no penalty).

This is a deliberate change to the brief and is OFF by default (see mel.pipeline.run_pipeline(attention=...)).
With it off, nothing here runs and every output is identical to today.

Design notes (full spec: .kiro/specs/activity-attention/):
  * Pure and deterministic: arithmetic plus the existing high-priority test. No model calls, no randomness.
  * No leakage: only the farmer's rows strictly BEFORE the insight's created_at are counted.
  * Counts DISTINCT conversation_ids, never insights, so extra insights in one conversation add nothing.
  * Junk rows (mel.data.why_junk) and rows with an unusable created_at / missing farmer_id are dropped: they
    never crash the run, never count as activity, and never affect the dataset start.
  * activity_level in farmers.csv is a STATIC label and is deliberately not used to detect change.
"""
import json
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from math import exp, factorial

from mel.config import CONFIG
from mel.timing import parse_ist

SETTINGS_PATH = CONFIG / "activity_attention.json"

TIERS = ("surge", "neutral", "steady_high")
REASONS = ("insufficient_history", "quiet_then_high_weight", "activity_jump", "declining", "none")


@lru_cache
def settings() -> dict:
    """Thresholds/windows/weights. Lives outside config/rules and config/schemas so parity ignores it."""
    return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Attention:
    """What attention thinks about one insight. `as_dict()` is exactly what rides on Decision.attention."""
    tier: str
    reason: str
    baseline_per_week: float
    recent_count: int
    weight: float
    explanation: str
    high_budget: str | None = None   # "spent" when run_pipeline used up this farmer's 7-day high promotion

    def as_dict(self) -> dict:
        d = {
            "tier": self.tier, "reason": self.reason,
            "baseline_per_week": self.baseline_per_week, "recent_count": self.recent_count,
            "weight": self.weight, "explanation": self.explanation,
        }
        if self.high_budget is not None:
            d["high_budget"] = self.high_budget
        return d


def _usable_time(row):
    """parse_ist(created_at) for a usable row, else None. A usable row is a dict with a farmer_id and a
    created_at that parses. Junk rows (why_junk) are excluded here too, so they never count or move the start."""
    from .validate import why_junk
    if not isinstance(row, dict) or not row.get("farmer_id"):
        return None
    if why_junk(row):
        return None
    try:
        return parse_ist(row["created_at"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _poisson_tail(k: int, lam: float) -> float:
    """P(X >= k) for X ~ Poisson(lam). k is small (conversation counts), so the direct sum is exact and cheap.
    lam == 0: the farmer was silent, so any k >= 1 is 'impossible' under the baseline -> tail 0 (k == 0 -> 1)."""
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    below = sum(exp(-lam) * lam**j / factorial(j) for j in range(k))
    return max(0.0, 1.0 - below)


def _high_weight(insight: dict) -> bool:
    """The existing high-priority test, reused (not copied): escalate_to_expert, severity high/critical,
    or emergency intent. Imported locally so mel.data does not import mel.schedule at module load."""
    from mel.schedule.handoff import priority
    return priority(insight) == "high"


class ActivityHistory:
    """Per-farmer conversation history, built once per run from the UNFILTERED insight set.

    `attention_for(insight)` returns an Attention for that insight using only earlier, usable, non-junk rows.
    Because this is built from the whole set, a farmer's result is the same in a filtered (--farmer/--limit)
    run as in a full run.
    """

    def __init__(self, insights, cfg: dict | None = None):
        self.cfg = cfg or settings()
        # farmer_id -> list of (created_at_datetime, conversation_id), usable rows only.
        self.by_farmer: dict[str, list] = {}
        self.dataset_start = None
        for row in insights:
            t = _usable_time(row)
            if t is None:
                continue
            fid = row["farmer_id"]
            self.by_farmer.setdefault(fid, []).append((t, row.get("conversation_id")))
            if self.dataset_start is None or t < self.dataset_start:
                self.dataset_start = t
        for rows in self.by_farmer.values():
            rows.sort(key=lambda tc: tc[0])

    # -- metrics -------------------------------------------------------------
    def _distinct_conversations_in(self, rows, lo, hi) -> int:
        """Distinct conversation_ids whose EARLIEST row falls in [lo, hi). Rows are the farmer's usable rows
        already filtered to strictly before the insight and with the insight's own conversation dropped."""
        first_seen: dict = {}
        for t, cid in rows:
            key = cid if cid is not None else ("_anon", t)   # a row with no conversation_id counts once on its own
            if key not in first_seen or t < first_seen[key]:
                first_seen[key] = t
        return sum(1 for t in first_seen.values() if lo <= t < hi)

    def attention_for(self, insight: dict) -> Attention:
        c = self.cfg
        t0 = _usable_time(insight)
        if t0 is None:
            # An unusable insight should never reach here (it would be R1 junk), but be safe: treat as neutral.
            return _make("neutral", "none", 0.0, 0, c)

        own_cid = insight.get("conversation_id")
        prior = [(t, cid) for (t, cid) in self.by_farmer.get(insight["farmer_id"], [])
                 if t < t0 and cid != own_cid]

        bw = c["baseline_window"]
        base_lo = t0 - timedelta(days=bw["from_days"])
        base_hi = t0 - timedelta(days=bw["to_days"])
        baseline_count = self._distinct_conversations_in(prior, base_lo, base_hi)

        # Covered span starts at the dataset start, never the farmer's first chat (so a quiet farmer is not
        # rewarded with a tiny divisor). Clamp to the window and to a positive span.
        span_lo = base_lo if self.dataset_start is None else max(base_lo, self.dataset_start)
        covered_days = (base_hi - span_lo).total_seconds() / 86400.0
        max_days = bw["from_days"] - bw["to_days"]
        covered_days = min(max(covered_days, 0.0), float(max_days))
        baseline_per_week = round(baseline_count / (covered_days / 7.0), 4) if covered_days > 0 else 0.0

        recent_lo = t0 - timedelta(days=c["recent_days"])
        # recent_count includes the current conversation, so it is always >= 1.
        recent_count = self._distinct_conversations_in(prior, recent_lo, t0) + 1

        high_weight = _high_weight(insight)
        age_days = None if self.dataset_start is None else (t0 - self.dataset_start).days

        tier, reason = self._tier(age_days, baseline_per_week, recent_count, high_weight, c)
        return _make(tier, reason, baseline_per_week, recent_count, c)

    @staticmethod
    def _tier(age_days, baseline_per_week, recent_count, high_weight, c):
        """First match wins (spec R-3)."""
        if age_days is not None and age_days < c["min_dataset_age_days"]:
            return "neutral", "insufficient_history"
        if baseline_per_week <= c["quiet_baseline_max"] and high_weight:
            return "surge", "quiet_then_high_weight"
        if recent_count >= c["jump_min_recent"]:
            lam = baseline_per_week * c["jump_poisson_factor"]
            if _poisson_tail(recent_count, lam) < c["jump_poisson_p"]:
                return "surge", "activity_jump"
        recent_rate = recent_count / (c["recent_days"] / 7.0)
        if baseline_per_week > 0 and recent_rate < c["declining_ratio"] * baseline_per_week:
            return "neutral", "declining"
        if baseline_per_week >= c["steady_high_baseline"]:
            return "steady_high", "none"
        return "neutral", "none"


_EXPLAIN = {
    "insufficient_history": "Too early in the season to tell if this farmer's activity is changing.",
    "quiet_then_high_weight": "This farmer was quiet, then raised an urgent question: worth extra attention.",
    "activity_jump": "This farmer's activity jumped well above their usual rate: worth extra attention.",
    "declining": "This farmer's activity has dropped below their usual rate: treated normally.",
    "none": None,  # filled per tier below
}
_TIER_NONE_EXPLAIN = {
    "steady_high": "This farmer is consistently busy, so no extra priority by default.",
    "neutral": "This farmer's activity is steady, so no change.",
}


def _make(tier: str, reason: str, baseline_per_week: float, recent_count: int, c: dict,
          high_budget: str | None = None) -> Attention:
    weight = c["weights"][tier]
    explanation = _EXPLAIN.get(reason) or _TIER_NONE_EXPLAIN[tier]
    return Attention(tier, reason, baseline_per_week, recent_count, weight, explanation, high_budget)


def with_high_budget_spent(att: Attention) -> Attention:
    """A copy of `att` marked so adjust_priority stops a normal->high promotion at normal (7-day budget)."""
    return _make(att.tier, att.reason, att.baseline_per_week, att.recent_count, settings(), high_budget="spent")
