"""The broadcaster: given a simulated clock, decide which hand-offs go out now. Owner: P3.

This is the piece the demo's "Season" screen drives. It holds a queue of hand-offs and,
each time it is asked (never on a timer of its own), reports which ones are due to send at
the clock's current instant. In production this maps to EventBridge/Step Functions waking
up a sender; here it is a plain, deterministic function so the walk-through is reproducible
(see docs/TEAM.md, "Alarm clock and retry").

What the checklist asks of it:
  * Queue hand-offs by their send-window start, not the order they were added. Two surveys
    added in any order come out of the queue earliest-window-first.
  * `broadcast_due(clock, ...)` is an explicit manual trigger. It sends only work that is
    (a) due -- the window has opened -- and (b) inside the day's send hours, and it drops
    work whose expiry has already passed. It never advances the clock itself.
  * Before anything is sent it passes the survey's P4 quality gate: a survey with a failed
    self-evaluation (schema invalid, gives new advice, asks for personal info), a missing or
    out-of-range relevance score, or a score below the threshold the caller supplies, is
    rejected (never sent). A score exactly equal to the threshold is eligible. The threshold
    is always passed in explicitly -- there is no shared default invented here, because the
    "right" relevance bar is a P4/P5 decision, not P3's to hard-code.
"""

import json
from datetime import datetime, time

from mel.config import rules

from mel.timing import parse_ist, fmt_ist


# -------------------------------------------------------------- P4 quality gate
_QUALITY_CACHE: dict = {}
_QUALITY_CACHE_MAX = 50_000


def quality_failures(survey: dict, relevance_threshold: float) -> list[str]:
    """Cached front for `_quality_failures` (same contract). The broadcaster re-checks every queued survey on every
    step, and the check (P4's guards plus a JSON Schema validation) is the slow part of a season walk. The result
    depends only on the survey's content and the threshold, so it is cached on exactly those: a survey that is
    changed in any way is checked again. Added by P5 for the Season tab's speed; P3 to review."""
    try:
        key = (json.dumps(survey, sort_keys=True, ensure_ascii=False, default=str), relevance_threshold)
    except (TypeError, ValueError):
        return _quality_failures(survey, relevance_threshold)
    hit = _QUALITY_CACHE.get(key)
    if hit is None:
        hit = tuple(_quality_failures(survey, relevance_threshold))  # raises for a bad threshold, like before
        if len(_QUALITY_CACHE) >= _QUALITY_CACHE_MAX:
            _QUALITY_CACHE.clear()
        _QUALITY_CACHE[key] = hit
    return list(hit)


def _quality_failures(survey: dict, relevance_threshold: float) -> list[str]:
    """Why this survey must not be sent, or [] if it is clear to send.

    Reads only the survey's own `self_eval` block (the shape P4 writes, defined in
    config/schemas/survey.schema.json): `schema_valid`, `relevance_score`,
    `gives_new_advice`, `asks_personal_info`. `relevance_threshold` is supplied by the
    caller -- P3 does not invent a shared bar. A score equal to the threshold passes.

    A survey with no `self_eval` at all is treated as not-yet-evaluated and rejected: the
    broadcaster will not send something the writer never cleared.

    Guard failures: `self_eval` only summarises three of P4's guards (schema, new advice,
    personal info). Other guard failures -- label_too_long, bad_option_count,
    duplicate_option_value, confirm_needs_two and the rest -- leave `self_eval` looking clean.
    So the gate also runs P4's public `mel.writer.check_survey()` on the survey and rejects on
    any failure it reports. P3 calls P4's function; it does not re-implement or change it.
    """
    if not isinstance(relevance_threshold, (int, float)) or isinstance(relevance_threshold, bool):
        raise TypeError("relevance_threshold must be a number supplied by the caller")
    if not 0.0 <= float(relevance_threshold) <= 1.0:
        raise ValueError("relevance_threshold must be between 0 and 1")

    se = survey.get("self_eval")
    if not isinstance(se, dict):
        return ["no self_eval: survey has not been quality-checked"]

    out: list[str] = []
    if se.get("schema_valid") is not True:
        out.append("self_eval.schema_valid is not true")
    if se.get("gives_new_advice") is True:
        out.append("survey gives new advice")
    if se.get("asks_personal_info") is True:
        out.append("survey asks for personal information")

    score = se.get("relevance_score")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        out.append("relevance_score is missing or not a number")
    elif not 0.0 <= float(score) <= 1.0:
        out.append(f"relevance_score {score} is outside 0..1")
    elif float(score) < float(relevance_threshold):
        out.append(f"relevance_score {score} is below threshold {relevance_threshold}")

    # Every P4 guard, not just the three self_eval summarises.
    from mel.writer import check_survey

    out += [f"guard: {g}" for g in check_survey(survey)]
    return out


def passes_quality(survey: dict, relevance_threshold: float) -> bool:
    return not quality_failures(survey, relevance_threshold)


# ------------------------------------------------------------------ send hours
def _hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def within_send_hours(when: datetime, send_hours: dict | None = None) -> bool:
    """True if `when`'s time-of-day is inside [from, to] (inclusive) of the send hours.

    `send_hours` defaults to the project rules ({"from": "07:00", "to": "19:00"}). A
    hand-off carries its own `send_hours`, so callers normally pass handoff["send_hours"].
    """
    sh = send_hours or rules()["send_hours"]
    t = when.time()
    return _hm(sh["from"]) <= t <= _hm(sh["to"])


# ------------------------------------------------------------------ queue order
def queue_key(handoff: dict, rank: float | None = None):
    """Deterministic send order for hand-offs: send-window start first (always), then, only to
    break ties between hand-offs opening at the same instant, a higher frequency rank, then the
    contract's order (created time, then farmer), then handoff_id. A rank never moves a
    hand-off ahead of one whose window opens earlier."""
    return (
        parse_ist(handoff["send_window"]["not_before"]),
        -(rank if rank is not None else 0.0),
        handoff.get("created_at") or "",
        handoff.get("frequency_cap", {}).get("key", ""),
        handoff.get("handoff_id") or "",
    )


# ---------------------------------------------------------------- simulated app
class SimulatedApp:
    """The stand-in for the farmer's app: the broadcaster's only delivery target. Real delivery
    (FarmerChat push, WhatsApp, Telegram, voice) is outside P3, so a "send" here only appends
    to `inbox`. Each entry holds ids and the time only, no farmer contact details."""

    def __init__(self):
        self.inbox: list[dict] = []

    def deliver(self, handoff: dict, at, channel: str | None = None) -> None:
        self.inbox.append(
            {
                "handoff_id": handoff.get("handoff_id"),
                "survey_id": handoff["survey"]["survey_id"],
                "farmer_id": handoff["survey"]["farmer_id"],
                "channel": channel or handoff["channel_order"][0]["channel"],
                "delivered_at": fmt_ist(at),
            }
        )

    def __len__(self) -> int:
        return len(self.inbox)


# -------------------------------------------------------------- the broadcaster
class Broadcast:
    """One broadcaster decision for one hand-off at the clock's current instant.

    `action` is one of:
      sent     -- due, inside send hours, and quality-clear: it goes out now.
      waiting  -- due (window open) but outside the day's send hours: hold for later today
                  or a later day; stays in the queue.
      pending  -- the send window has not opened yet; stays in the queue.
      expired  -- past expires_at, or its send window has closed: dropped, never sent.
      rejected -- failed the P4 quality gate: dropped, never sent.
      opted_out -- the farmer is on the opt-out list (possibly since it was queued): dropped,
                  never sent.
    """

    ACTIONS = ("sent", "waiting", "pending", "expired", "rejected", "opted_out")

    def __init__(self, action: str, handoff: dict, reason: str = ""):
        assert action in self.ACTIONS, action
        self.action = action
        self.handoff = handoff
        self.reason = reason

    @property
    def handoff_id(self) -> str:
        return self.handoff.get("handoff_id")

    def __repr__(self) -> str:
        return f"Broadcast({self.action!r}, {self.handoff_id!r}, {self.reason!r})"

    def __eq__(self, other):
        return (
            isinstance(other, Broadcast)
            and (self.action, self.reason) == (other.action, other.reason)
            and self.handoff_id == other.handoff_id
        )


class Broadcaster:
    """A hand-off queue the simulated clock drives.

        clock = SimClock("2026-11-01T07:00:00+05:30")
        bc = Broadcaster(clock)            # bound to a shared clock
        bc.queue(handoff_a)
        bc.queue(handoff_b)
        results = bc.broadcast_due(relevance_threshold=0.5)   # reads the bound clock

    The queue is always kept in send-window-start order, so `broadcast_due` considers the
    earliest-opening survey first regardless of the order things were queued. `broadcast_due`
    is the only thing that acts, and only when you call it: it is the manual trigger.

    Clock sharing: pass a `SimClock` to the constructor and the broadcaster reads time from
    that one instance every call. `SeasonScheduler` constructs the broadcaster with the same
    clock it schedules against, so scheduler and broadcaster never disagree about "now" and
    neither ever touches the system clock. For backward compatibility `broadcast_due` and
    `due_now` still accept a clock argument; when given, it overrides the bound clock for
    that call (older callers passed one positionally).
    """

    def __init__(self, clock=None, opt_out=None, app=None):
        self._queue: list[dict] = []
        self._rank: dict[str, float] = {}  # optional frequency rank per handoff_id (tie-break only)
        self._clock = clock
        # The opt-out list is checked on every decision, not only at admission: a farmer who opts
        # out while one of their surveys is still queued must not get it. SeasonScheduler passes
        # the same OptOutList its steps feed.
        self._opt_out = opt_out
        # Where sent surveys are delivered: the simulated app (no real messaging in P3).
        self.app = app if app is not None else SimulatedApp()
        # P5 metrics: running totals of rejected (quality-gate), expired and opted-out hand-offs
        # the broadcaster has dropped over this object's life. Counted from actual decisions in
        # broadcast_due / drop_expired_and_rejected, never hard-coded.
        self.rejected_count = 0
        self.expired_count = 0
        self.opted_out_count = 0

    @property
    def clock(self):
        return self._clock

    def counts(self) -> dict:
        """P5: cumulative rejected/expired/opted-out totals from actual broadcaster decisions."""
        return {"rejected": self.rejected_count, "expired": self.expired_count, "opted_out": self.opted_out_count}

    def _resolve_clock(self, clock):
        c = clock if clock is not None else self._clock
        if c is None:
            raise ValueError("no clock: construct Broadcaster(clock) or pass a clock to this call")
        return c

    # -- queue management ----------------------------------------------------
    def queue(self, handoff: dict, rank: float | None = None) -> None:
        """Add one hand-off. Idempotent on handoff_id: re-queuing the same hand-off replaces
        the earlier copy rather than sending twice. The queue stays window-start ordered;
        `rank` (optional, e.g. a frequency score) only breaks ties at the same start."""
        hid = handoff.get("handoff_id")
        self._queue = [h for h in self._queue if h.get("handoff_id") != hid]
        self._queue.append(handoff)
        if rank is not None:
            self._rank[hid] = float(rank)
        self._resort()

    def queue_all(self, handoffs) -> None:
        for h in handoffs:
            self.queue(h)

    def _resort(self) -> None:
        self._queue.sort(key=lambda h: queue_key(h, self._rank.get(h.get("handoff_id"))))

    @property
    def pending(self) -> list[dict]:
        """Hand-offs still waiting, in send-window-start order."""
        return list(self._queue)

    def remove(self, handoff_id: str) -> bool:
        """Drop one hand-off from the queue by id. Returns True if it was present. Used by a
        per-step trigger once a step has been run for that hand-off."""
        before = len(self._queue)
        self._queue = [h for h in self._queue if h.get("handoff_id") != handoff_id]
        return len(self._queue) != before

    def __len__(self) -> int:
        return len(self._queue)

    # -- the manual trigger --------------------------------------------------
    def due_now(self, clock=None) -> list[dict]:
        """Hand-offs whose send window has opened at the clock's instant, window-start order.
        A read-only view; it does not send or remove anything. Uses the bound shared clock
        unless a clock is passed for this call."""
        now = self._resolve_clock(clock).now()
        return [h for h in self._queue if parse_ist(h["send_window"]["not_before"]) <= now]

    def drop_expired_and_rejected(self, clock=None, *, relevance_threshold: float) -> list[Broadcast]:
        """Remove only expired and quality-rejected hand-offs from the queue at the clock's
        instant, and return those Broadcast results. Pending / waiting / sendable items are
        left untouched (nothing is sent). Lets a per-step driver keep the queue honest
        without the whole-queue send that `broadcast_due` performs."""
        now = self._resolve_clock(clock).now()
        dropped: list[Broadcast] = []
        keep: list[dict] = []
        for h in self._queue:
            b = self._decide_one(h, now, relevance_threshold)
            if b.action in ("expired", "rejected", "opted_out"):
                dropped.append(b)
            else:
                keep.append(h)
        self._queue = keep
        self._resort()
        self._tally(dropped)
        return dropped

    def _tally(self, broadcasts) -> None:
        """Add expired/rejected/opted-out outcomes to the running P5 totals (actual decisions)."""
        for b in broadcasts:
            if b.action == "rejected":
                self.rejected_count += 1
            elif b.action == "expired":
                self.expired_count += 1
            elif b.action == "opted_out":
                self.opted_out_count += 1

    def next_due(self, clock=None, *, relevance_threshold: float, ready=None):
        """The single next hand-off that would be sent right now (earliest window first), as
        a Broadcast with action 'sent', or None if nothing is sendable at this instant.

        This is the per-step read the manual trigger builds on: it looks only at what is due,
        quality-clear and inside send hours now, without touching the queue. `ready` is an
        optional predicate(handoff) -> bool; a hand-off it rejects is skipped (the scheduler
        uses it to hold a hand-off until its wait interval has passed)."""
        now = self._resolve_clock(clock).now()
        for h in self._queue:
            if ready is not None and not ready(h):
                continue
            b = self._decide_one(h, now, relevance_threshold)
            if b.action == "sent":
                return b
        return None

    def broadcast_due(self, clock=None, *, relevance_threshold: float) -> list[Broadcast]:
        """Decide, for every queued hand-off, what happens at the clock's current instant.

        `relevance_threshold` is required and explicit (keyword-only): the caller states the
        P4 relevance bar; P3 does not invent one. Returns a Broadcast per queued hand-off,
        in send-window-start order. `sent` hand-offs are delivered to the simulated app
        (`self.app`) and leave the queue, as do `expired`, `rejected` and `opted_out` ones
        (never delivered); `pending` and `waiting` stay for a later call. Reads the bound
        shared clock unless a clock is passed for this call.
        """
        now = self._resolve_clock(clock).now()
        results: list[Broadcast] = []
        keep: list[dict] = []
        for h in self._queue:
            b = self._decide_one(h, now, relevance_threshold)
            results.append(b)
            if b.action == "sent":
                self.app.deliver(h, now)
            elif b.action in ("pending", "waiting"):
                keep.append(h)
        self._queue = keep
        self._resort()
        self._tally(results)
        return results

    def _decide_one(self, handoff: dict, now: datetime, relevance_threshold: float) -> Broadcast:
        # Opt-outs always win, even for a survey that was queued before the farmer opted out.
        if self._opt_out is not None and self._opt_out.blocks(handoff):
            return Broadcast("opted_out", handoff, reason="farmer opted out of all surveys")
        not_before = parse_ist(handoff["send_window"]["not_before"])
        not_after = parse_ist(handoff["send_window"]["not_after"])
        expires = parse_ist(handoff["expires_at"])

        # Expired work is dropped before anything else: never send a stale survey.
        if now > expires:
            return Broadcast("expired", handoff, reason=f"past expiry {handoff['expires_at']}")
        # The send window has closed: schedule_handoff.schema.json says the scheduler must not
        # send outside it. Nothing can go out any more, so it is dropped like expired work.
        # (Answers to an earlier send are still accepted until expires_at; that is the
        # simulator's job, not a new send.)
        if now > not_after:
            return Broadcast("expired", handoff, reason=f"send window closed {handoff['send_window']['not_after']}")

        # Window not open yet: hold.
        if now < not_before:
            return Broadcast("pending", handoff, reason=f"window opens {handoff['send_window']['not_before']}")

        # Due. Quality gate before send -- a survey the writer did not clear never goes out.
        fails = quality_failures(handoff["survey"], relevance_threshold)
        if fails:
            return Broadcast("rejected", handoff, reason="; ".join(fails))

        # Due and clear, but only send inside the day's send hours; otherwise wait.
        if not within_send_hours(now, handoff.get("send_hours")):
            return Broadcast("waiting", handoff, reason="outside send hours")

        return Broadcast("sent", handoff)
