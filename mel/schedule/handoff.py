"""Builds schedule_handoff.json from an insight + survey. Owner: P3."""

import json
import uuid
from datetime import timedelta
from functools import lru_cache

from mel.config import SCHEMAS, rules
from mel.timing import expires_at, parse_ist, fmt_ist

NS = uuid.UUID("6f1c2b8e-5d0a-4c1e-9f3a-2b7d8e9a0c11")  # project namespace for stable ids


@lru_cache
def max_source_insight_ids() -> int:
    """How many source_insight_ids one survey may carry (survey.schema.json maxItems, 5 today).
    A merge that would exceed it is not allowed, so a merged hand-off always stays schema-valid."""
    schema = json.loads((SCHEMAS / "survey.schema.json").read_text(encoding="utf-8"))
    return schema["properties"]["source_insight_ids"]["maxItems"]


def _within(a, b, window_days: int) -> bool:
    """True if two send starts are less than `window_days` apart, in either order. Uses the exact
    difference: 6 days 23:59 is inside a 7-day window, exactly 7 days is not."""
    return abs(a - b) < timedelta(days=window_days)


def priority(insight: dict) -> str:
    p = rules()["priority"]
    if (
        insight.get("resolution_type") in p["high_if_resolution"]
        or insight.get("severity") in p["high_if_severity"]
        or insight.get("behavioral_intent") in p["high_if_behavioral_intent"]
    ):
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
STEP_DOWN = {"high": "high", "normal": "low", "low": "low"}  # never demote a brief-high survey


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
        # handoff_id -> the Admit already returned, so admitting the same hand-off again is a no-op.
        self._decided: dict[str, "Admit"] = {}

    # -- original gate -------------------------------------------------------
    def allow(self, handoff: dict) -> bool:
        cap = handoff["frequency_cap"]
        start = parse_ist(handoff["send_window"]["not_before"])
        recent = [t for (t, _) in self._sent.get(cap["key"], []) if _within(start, t, cap["window_days"])]
        ok = cap["exempt"] or len(recent) < cap["max_surveys"]
        if ok:
            self._sent.setdefault(cap["key"], []).append((start, handoff))
        return ok

    # -- richer decision -----------------------------------------------------
    def admit(self, handoff: dict, opt_out=None, *, defer_move: bool = False):
        """Decide one hand-off (see the class docstring). With defer_move=True a `moved`
        decision is returned but NOT recorded: the caller re-admits the moved copy at its new
        send time, after everything that opens earlier (`schedule_in_send_order` does this), so
        a high-priority survey that lands in between is seen before the moved one is placed."""
        hid = handoff.get("handoff_id")
        if hid in self._decided:
            # The same hand-off again (duplicate input): return the first decision, count nothing.
            return self._decided[hid]
        a = self._admit(handoff, opt_out, defer_move=defer_move)
        if hid is not None and not (defer_move and a.decision == "moved"):
            self._decided[hid] = a
        return a

    def seen(self, handoff_id) -> bool:
        """True if this hand-off already has a decision (a repeat admission changes nothing)."""
        return handoff_id in self._decided

    def relabel(self, handoff_id, admit: "Admit") -> None:
        """Replace the stored decision for a hand-off (used when a deferred move is finally
        placed: the ledger saw it as `sent` at its new date, but the outcome is `moved`)."""
        self._decided[handoff_id] = admit

    def admit_checked(self, handoff: dict, opt_out=None, *, relevance_threshold: float, defer_move: bool = False):
        """The scheduling gate every P3 path uses, in this order:
          1. opt-out -> `opted_out` (always wins);
          2. P4 quality gate (schema_valid, guards, relevance >= the supplied threshold) ->
             `rejected`. A rejected survey never reaches the cap, so it cannot take the
             farmer's weekly slot or become a merge host;
          3. the weekly cap -> sent / moved / merged / skipped (see `admit`).
        Repeat calls for the same handoff_id return the first decision."""
        from .broadcast import quality_failures

        hid = handoff.get("handoff_id")
        if hid in self._decided:
            return self._decided[hid]
        if opt_out is not None and opt_out.blocks(handoff):
            a = Admit("opted_out", handoff, reason="farmer opted out of all surveys")
        else:
            fails = quality_failures(handoff["survey"], relevance_threshold)
            a = (
                Admit("rejected", handoff, reason="; ".join(fails))
                if fails
                else self._admit(handoff, opt_out, defer_move=defer_move)
            )
        if hid is not None and not (defer_move and a.decision == "moved"):
            self._decided[hid] = a
        return a

    def _admit(self, handoff: dict, opt_out=None, defer_move: bool = False):
        cap = handoff["frequency_cap"]
        key = cap["key"]
        window = handoff["send_window"]
        start = parse_ist(window["not_before"])

        if opt_out is not None and opt_out.blocks(handoff):
            return Admit("opted_out", handoff, reason="farmer opted out of all surveys")

        prior = self._sent.get(key, [])
        blocking = [(t, h) for (t, h) in prior if _within(start, t, cap["window_days"])]

        # High priority is exempt: it goes out and still counts toward the window.
        if cap["exempt"] or not blocking:
            self._sent.setdefault(key, []).append((start, handoff))
            return Admit("sent", handoff)

        # Over the cap. 1) Prefer to move to the next eligible date inside this window.
        moved_start = self._next_eligible(start, prior, cap["window_days"], window)
        if moved_start is not None:
            moved = _reschedule(handoff, moved_start)
            if not defer_move:
                self._sent.setdefault(key, []).append((moved_start, moved))
            return Admit("moved", moved, reason=f"moved to {moved['send_window']['not_before']}")

        # 2) Cannot move. If an earlier survey to this farmer is still open and asks the
        # same thing, merge so the farmer answers once; otherwise skip. We only merge when
        # the host survey's send window still contains this survey's open day (so the extra
        # questions can genuinely ride along) -- that keeps "merge" meaningful rather than a
        # silent drop in disguise.
        host = self._merge_host(blocking, start, handoff)
        if host is not None:
            _merge_into(host, handoff)
            return Admit("merged", host, reason=f"merged into {host['handoff_id']}")

        # 3) Neither move nor merge is possible: drop it (the farmer is already at the cap).
        return Admit("skipped", handoff, reason="capped; no eligible move date and no open survey to merge into")

    @staticmethod
    def _merge_host(blocking, start, extra):
        """The earliest still-open blocking survey whose send window still covers `start` and
        that can take `extra`'s source insight IDs without going over the schema limit, or None.
        Merging into it lets the capped survey's insight IDs ride along with the host."""
        limit = max_source_insight_ids()
        new = extra["survey"]["source_insight_ids"]
        for _, h in sorted(blocking, key=lambda tb: tb[0]):
            nb, na = parse_ist(h["send_window"]["not_before"]), parse_ist(h["send_window"]["not_after"])
            if not nb <= start <= na:
                continue
            ids = h["survey"]["source_insight_ids"]
            if len(ids) + len([i for i in dict.fromkeys(new) if i not in ids]) > limit:
                continue  # merging would break survey.schema.json maxItems: not an eligible host
            return h
        return None

    @staticmethod
    def _next_eligible(start, prior, window_days: int, window: dict):
        """The earliest send start (keeping the clock time) a full `window_days` away from EVERY prior send
        to this farmer, still inside [not_before, not_after]; None if none fits. Every prior send, not only
        the ones blocking the original start: a send admitted out of order can sit a week or more after
        the original start and still be less than a week from the moved date."""
        gap = timedelta(days=window_days)
        not_after = parse_ist(window["not_after"])
        candidate = start
        while candidate <= not_after:
            clash = [t for (t, _) in prior if abs(candidate - t) < gap]
            if not clash:
                return candidate
            earliest_ok = max(clash) + gap
            candidate = earliest_ok.replace(hour=start.hour, minute=start.minute, second=start.second)
            if candidate < earliest_ok:
                candidate += timedelta(days=1)  # same day but an earlier clock time: next day, same time
        return None


class Admit:
    """The outcome of CapLedger.admit(): a decision word plus the (possibly rescheduled or
    merged) hand-off it applies to, and a short human reason.

    `rejected` is never produced by CapLedger itself. The batch and season schedulers use it for
    a survey that failed the quality gate before it reached the cap, so it never takes a farmer's
    weekly slot."""

    DECISIONS = ("sent", "moved", "merged", "skipped", "opted_out", "rejected")

    def __init__(self, decision: str, handoff: dict, reason: str = ""):
        assert decision in self.DECISIONS, decision
        self.decision = decision
        self.handoff = handoff
        self.reason = reason

    def __repr__(self):
        return f"Admit({self.decision!r}, {self.handoff.get('handoff_id')!r}, {self.reason!r})"

    def __eq__(self, other):
        return (
            isinstance(other, Admit)
            and (self.decision, self.reason) == (other.decision, other.reason)
            and self.handoff.get("handoff_id") == other.handoff.get("handoff_id")
        )


def _reschedule(handoff: dict, new_start) -> dict:
    """A copy of the hand-off whose send window now opens at new_start. The end of the window
    and the expiry stay exactly as they were: a moved survey must still go out inside its own
    send window and before its own expiry, so the window is only shortened, never shifted
    later. Used when a capped survey is moved."""
    import copy

    h = copy.deepcopy(handoff)
    h["send_window"] = {"not_before": fmt_ist(new_start), "not_after": handoff["send_window"]["not_after"]}
    h["survey"]["send_window"] = dict(h["send_window"])
    h["expires_at"] = handoff["expires_at"]
    return h


def _merge_into(host: dict, extra: dict) -> None:
    """Fold `extra`'s source insight IDs into the host survey, preserving both sets and their
    order without duplicates. The host survey is what the farmer gets; the merged hand-off's
    insights are recorded on it so their provenance is not lost. The caller has already checked
    the result stays within survey.schema.json maxItems."""
    host_ids = host["survey"]["source_insight_ids"]
    for iid in extra["survey"]["source_insight_ids"]:
        if iid not in host_ids:
            host_ids.append(iid)
