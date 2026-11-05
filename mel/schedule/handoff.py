"""Builds schedule_handoff.json from an insight + survey. Owner: P3."""
import uuid
from datetime import timedelta

from mel.config import rules
from mel.timing import expires_at, parse_ist, fmt_ist

NS = uuid.UUID("6f1c2b8e-5d0a-4c1e-9f3a-2b7d8e9a0c11")  # project namespace for stable ids


def priority(insight: dict) -> str:
    p = rules()["priority"]
    if (insight.get("resolution_type") in p["high_if_resolution"]
            or insight.get("severity") in p["high_if_severity"]
            or insight.get("behavioral_intent") in p["high_if_behavioral_intent"]):
        return "high"
    if insight.get("resolution_type") in p["low_if_resolution"]:
        return "low"
    return "normal"


def channel_order(insight: dict, prio: str) -> list[dict]:
    order: list[str] = []
    add = lambda c: c and c not in order and order.append(c)
    add(insight.get("preferred_channel"))
    add(rules()["channel_by_method"].get((insight.get("verification") or {}).get("method") or "none"))
    add("whatsapp")
    if prio == "high":
        add("voice")
    wait = rules()["wait_hours_by_priority"][prio]
    return [{"channel": c, "wait_hours": wait if i < len(order) - 1 else None} for i, c in enumerate(order)]


STEP_UP = {"low": "normal", "normal": "high", "high": "high"}
STEP_DOWN = {"high": "high", "normal": "low", "low": "low"}   # never demote a brief-high survey


def adjust_priority(brief_prio: str, insight: dict, attention: dict | None) -> str:
    """Nudge the brief's priority by the activity-attention tier. Pure per-insight (no rolling-window state).

      surge       one step up (low->normal, normal->high), BUT stop at normal when attention["high_budget"]
                  == "spent" (the once-per-7-days high-promotion budget, decided upstream in run_pipeline).
      steady_high one step down, only normal->low: a survey the brief makes high stays high (safety: an urgent
                  question from a steady heavy user is never demoted).
      neutral     unchanged.
    """
    if not attention:
        return brief_prio
    tier = attention.get("tier")
    if tier == "surge":
        up = STEP_UP[brief_prio]
        if up == "high" and attention.get("high_budget") == "spent":
            return "normal"
        return up
    if tier == "steady_high":
        return STEP_DOWN[brief_prio]
    return brief_prio


def build_handoff(insight: dict, survey: dict, attention: dict | None = None) -> dict:
    r = rules()
    prio = priority(insight)
    if attention is not None:
        prio = adjust_priority(prio, insight, attention)
    sid = survey["survey_id"]
    flow_key = r["farmerchat_flow"]["flow_key"].format(survey_id_lower=sid.lower().replace("-", "_"))
    created = parse_ist(insight["created_at"]).replace(hour=23, minute=0, second=0)
    return {
        "handoff_id": "H-" + sid.split("-", 1)[1],
        "created_at": fmt_ist(created),
        "survey": survey,
        "send_window": survey["send_window"],
        "send_hours": dict(r["send_hours"]),
        "channel_order": channel_order(insight, prio),
        "frequency_cap": {
            "key": r["frequency_cap"]["key"].format(farmer_id=insight["farmer_id"]),
            "max_surveys": r["frequency_cap"]["max_surveys"],
            "window_days": r["frequency_cap"]["window_days"],
            "exempt": prio in r["frequency_cap"]["exempt_priority"],
        },
        "priority": prio,
        "expires_at": expires_at(survey["send_window"]),
        "farmerchat_flow": {
            "org_id": r["farmerchat_flow"]["org_id"],
            "flow_key": flow_key,
            "version": r["farmerchat_flow"]["version"],
            "campaign_id": str(uuid.uuid5(NS, r["farmerchat_flow"]["campaign_name"])),
            "flow_id": str(uuid.uuid5(NS, flow_key)),
        },
    }


class OptOutList:
    """Farmers who asked for no more surveys (Do not ask me again, STOP, /stop, or 9 on a call). Owner: P3.
    The brief: 'Stop all future surveys to this farmer.' Feed it every answer record; check it before sending.
    TODO(P3): persist across runs (a file now; a database such as DynamoDB if this ever goes to AWS)."""

    def __init__(self):
        self._farmers: set[str] = set()

    def record(self, response: dict) -> None:
        if response.get("failure_code") == "farmer_opted_out":
            self._farmers.add(response["farmer_id"])

    def blocks(self, handoff_or_farmer) -> bool:
        fid = handoff_or_farmer if isinstance(handoff_or_farmer, str) else handoff_or_farmer["survey"]["farmer_id"]
        return fid in self._farmers


class CapLedger:
    """Per-farmer 1-survey-per-7-days cap across all surveys and channels. Owner: P3.

    The brief: at most 1 non-high-priority survey per farmer per 7 days, counted across
    every survey and channel. A high-priority survey is exempt (it goes out even when the
    cap is full) but still counts toward the window for later surveys.

    Two entry points:
      allow(handoff) -> bool
          The original yes/no gate. Records the send and returns whether it was allowed.
          Kept so existing callers and the Streamlit replay keep working.
      admit(handoff, opt_out=None) -> Admit
          The richer decision the H+4 contract asked for
          (docs/h4_interface_decisions.md row 12). Returns one of:
            sent      - within the cap (or exempt); scheduled as-is.
            opted_out - the farmer has opted out; nothing is sent, ever.
            moved     - capped, but moved to the next eligible date that still falls inside
                        its send window and before expiry; scheduled then.
            merged    - capped, and an earlier survey to the same farmer is still open in
                        the same 7-day window; this survey's questions ride along with it
                        and its source insight IDs are preserved on that earlier survey.
            skipped   - capped, and it can neither move inside its window nor merge; dropped.

    Policy for two-in-a-week (deterministic, documented in docs/cap_policy.md):
      1. High priority -> always `sent` (exempt), and it still counts.
      2. Opted out -> `opted_out`.
      3. Within the cap -> `sent`.
      4. Over the cap -> try to MOVE: find the earliest day, at or after the blocking
         survey's 7-day window clears, that is still within this survey's own
         [not_before, expires_at]. Keep the clock time (07:00). If such a day exists, the
         survey is `moved` to it. Preference order is move-before-skip per the task.
      5. If it cannot move but an earlier open survey to the same farmer sits in the same
         window, MERGE into it (preserve both surveys' source_insight_ids), -> `merged`.
      6. Otherwise `skipped`.
    """

    def __init__(self):
        # cap key -> list of (send_start_datetime, handoff) already admitted and counted.
        self._sent: dict[str, list] = {}

    # -- original gate -------------------------------------------------------
    def allow(self, handoff: dict) -> bool:
        cap = handoff["frequency_cap"]
        start = parse_ist(handoff["send_window"]["not_before"])
        recent = [t for (t, _) in self._sent.get(cap["key"], []) if abs((start - t).days) < cap["window_days"]]
        ok = cap["exempt"] or len(recent) < cap["max_surveys"]
        if ok:
            self._sent.setdefault(cap["key"], []).append((start, handoff))
        return ok

    # -- richer decision -----------------------------------------------------
    def admit(self, handoff: dict, opt_out=None):
        cap = handoff["frequency_cap"]
        key = cap["key"]
        window = handoff["send_window"]
        start = parse_ist(window["not_before"])

        if opt_out is not None and opt_out.blocks(handoff):
            return Admit("opted_out", handoff, reason="farmer opted out of all surveys")

        prior = self._sent.get(key, [])
        blocking = [(t, h) for (t, h) in prior if abs((start - t).days) < cap["window_days"]]

        # High priority is exempt: it goes out and still counts toward the window.
        if cap["exempt"] or not blocking:
            self._sent.setdefault(key, []).append((start, handoff))
            return Admit("sent", handoff)

        # Over the cap. 1) Prefer to move to the next eligible date inside this window.
        moved_start = self._next_eligible(start, blocking, cap["window_days"], window)
        if moved_start is not None:
            moved = _reschedule(handoff, moved_start)
            self._sent.setdefault(key, []).append((moved_start, moved))
            return Admit("moved", moved, reason=f"moved to {moved['send_window']['not_before']}")

        # 2) Cannot move. If an earlier survey to this farmer is still open and asks the
        # same thing, merge so the farmer answers once; otherwise skip. We only merge when
        # the host survey's send window still contains this survey's open day (so the extra
        # questions can genuinely ride along) -- that keeps "merge" meaningful rather than a
        # silent drop in disguise.
        host = self._merge_host(blocking, start)
        if host is not None:
            _merge_into(host, handoff)
            return Admit("merged", host, reason=f"merged into {host['handoff_id']}")

        # 3) Neither move nor merge is possible: drop it (the farmer is already at the cap).
        return Admit("skipped", handoff, reason="capped; no eligible move date and no open survey to merge into")

    @staticmethod
    def _merge_host(blocking, start):
        """The earliest still-open blocking survey whose send window still covers `start`,
        or None. Merging into it lets the capped survey's questions ride along."""
        hosts = [h for (_, h) in sorted(blocking, key=lambda tb: tb[0])
                 if parse_ist(h["send_window"]["not_before"]) <= start <= parse_ist(h["send_window"]["not_after"])]
        return hosts[0] if hosts else None

    @staticmethod
    def _next_eligible(start, blocking, window_days: int, window: dict):
        """The earliest send start (keeping 07:00) at least `window_days` after the latest
        blocking send, that is still inside [not_before, not_after]. None if none fits."""
        latest_block = max(t for (t, _) in blocking)
        earliest_ok = latest_block + timedelta(days=window_days)
        candidate = start if start >= earliest_ok else earliest_ok.replace(
            hour=start.hour, minute=start.minute, second=start.second)
        not_after = parse_ist(window["not_after"])
        return candidate if candidate <= not_after else None


class Admit:
    """The outcome of CapLedger.admit(): a decision word plus the (possibly rescheduled or
    merged) hand-off it applies to, and a short human reason."""
    DECISIONS = ("sent", "moved", "merged", "skipped", "opted_out")

    def __init__(self, decision: str, handoff: dict, reason: str = ""):
        assert decision in self.DECISIONS, decision
        self.decision = decision
        self.handoff = handoff
        self.reason = reason

    def __repr__(self):
        return f"Admit({self.decision!r}, {self.handoff.get('handoff_id')!r}, {self.reason!r})"

    def __eq__(self, other):
        return isinstance(other, Admit) and (self.decision, self.reason) == (other.decision, other.reason) \
            and self.handoff.get("handoff_id") == other.handoff.get("handoff_id")


def _reschedule(handoff: dict, new_start) -> dict:
    """A copy of the hand-off whose send window starts at new_start (same window width and
    clock), with expiry recomputed. Used when a capped survey is moved."""
    import copy
    h = copy.deepcopy(handoff)
    old_start = parse_ist(handoff["send_window"]["not_before"])
    old_end = parse_ist(handoff["send_window"]["not_after"])
    shift = new_start - old_start
    new_end = old_end + shift
    h["send_window"] = {"not_before": fmt_ist(new_start), "not_after": fmt_ist(new_end)}
    h["survey"]["send_window"] = dict(h["send_window"])
    h["expires_at"] = expires_at(h["send_window"])
    return h


def _merge_into(host: dict, extra: dict) -> None:
    """Fold `extra`'s source insight IDs into the host survey, preserving both sets and
    their order without duplicates. Questions ride along with the host survey."""
    host_ids = host["survey"]["source_insight_ids"]
    for iid in extra["survey"]["source_insight_ids"]:
        if iid not in host_ids:
            host_ids.append(iid)
