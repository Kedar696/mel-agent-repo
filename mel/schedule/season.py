"""The season driver: one shared SimClock behind the scheduler and the broadcaster, with a
manual trigger for every scheduled step. Owner: P3.

The demo needs to move through the November-to-March rabi season in minutes, not months,
and a presenter needs to be able to fire the *next* due step by hand rather than wait for
real time. This module ties the existing pieces together without changing any of them:

  * `SimClock` (mel/schedule/clock.py) is the single source of "now". Both the scheduler
    side (admission + cap + opt-out + expiry) and the broadcaster side (due / send-hours /
    quality gate) read this one instance. Nothing here or in the broadcaster ever calls
    `datetime.now()`, so a season walk is deterministic and reproducible.

  * `CapLedger` / `OptOutList` (mel/schedule/handoff.py) still make exactly the cap and
    opt-out decisions they always did. `Broadcaster` (mel/schedule/broadcast.py) still
    decides due / pending / waiting / expired / rejected the same way. This class only
    orchestrates them around the shared clock.

  * Delivery stays simulated: a triggered step calls `mel.simulator.simulate()` with the
    clock's current instant as the send time. No real messaging is added.

A "scheduled step" is one channel attempt for one admitted hand-off (the hand-off's
`channel_order` is the list of steps). `step()` runs the single next due step; `run_due()`
runs every step that is due right now by repeatedly calling `step()`; `advance(days)` moves
the one shared clock forward (clamped at the season end) so a later `step()` / `run_due()`
sees different work as due.

The season range (November to March by default, from `Season`) is configurable and the
clock cannot advance past its end. The demo UI that drives this API lives in P5's Streamlit
app; the callable P3 surface and a Season-tab sketch are documented in
`docs/p3_season_screen_api.md`.
"""
from collections import Counter
from datetime import timedelta

from .clock import SimClock, Season
from .handoff import CapLedger, OptOutList
from .broadcast import Broadcaster


def _days(days: int) -> timedelta:
    """Validate a day count the way SimClock.advance does (whole int, >= 0, not bool) and
    return it as a timedelta. Keeps the season clamp honouring the same guards."""
    if isinstance(days, bool) or not isinstance(days, int):
        raise TypeError("advance(days) takes a whole number of days (int)")
    if days < 0:
        raise ValueError("advance(days) cannot go backwards; days must be >= 0")
    return timedelta(days=days)


class StepResult:
    """The outcome of one manually triggered scheduled step.

      kind:
        "sent"      -- a channel attempt ran; `record` is the simulated response.
        "nothing"   -- no step was due to send at the clock's current instant.
      handoff_id / channel identify which hand-off and channel the step touched (None for
      "nothing"). `record` is the simulator's response record for a "sent" step, else None.
    """
    def __init__(self, kind: str, handoff_id=None, channel=None, record=None, reason=""):
        assert kind in ("sent", "nothing"), kind
        self.kind = kind
        self.handoff_id = handoff_id
        self.channel = channel
        self.record = record
        self.reason = reason

    def __repr__(self):
        return f"StepResult({self.kind!r}, {self.handoff_id!r}, {self.channel!r}, {self.reason!r})"


class SeasonScheduler:
    """Scheduler + broadcaster sharing one SimClock, with a manual per-step trigger.

        sched = SeasonScheduler(relevance_threshold=0.5)   # starts at the rabi season's 1 Nov
        sched.admit_all(handoffs)          # cap + opt-out gate, queue what is sent/moved/merged
        sched.step()                       # run the next due scheduled step (one channel attempt)
        sched.advance(7)                   # move the shared clock a week; different work is now due
        sched.run_due()                    # fire every step due at the new instant
        sched.advance_to_end()             # jump to the season's last instant (fast-forward)

    The clock is shared: `sched.clock is sched.broadcaster.clock` is always true, so the
    scheduler and broadcaster can never disagree about the current time. `relevance_threshold`
    is explicit (P3 invents no shared bar); it is handed to the broadcaster's quality gate.

    Season range: `season` (a `Season`) defines the November-to-March range the demo walks.
    It defaults to the rabi season from config (1 Nov .. `window_rules.season_end` 19:00). The
    clock starts at `start` if given, else the season start. `advance()` never moves past the
    season end -- it clamps there and `is_season_over()` then reports True -- so a fast-forward
    cannot run off into an endless future.
    """

    def __init__(self, start=None, *, relevance_threshold: float, persona: str = "default",
                 seed: int = 0, season: Season | None = None, reachability=None, ranker=None):
        self.season = season or Season()
        self.clock = SimClock(start if start is not None else self.season.start_ist)
        self.cap = CapLedger()
        self.opt_out = OptOutList()
        # The SAME clock instance, and the same opt-out list, so a farmer who opts out on one
        # step is never sent a survey that is still queued.
        self.broadcaster = Broadcaster(self.clock, opt_out=self.opt_out)
        # Optional frequency/season/climate ranker (mel.schedule.FrequencyScheduler). It only
        # breaks ties between hand-offs whose send windows open at the same instant.
        self.ranker = ranker
        self.relevance_threshold = relevance_threshold
        self.persona = persona
        self.seed = seed
        # Optional per-farmer channel reachability (mel.channels.FarmerReachability). When set,
        # a channel the farmer cannot be reached on is skipped, exactly like a persona's
        # unreachable channel, while channel_order is preserved for reachable channels.
        self.reachability = reachability
        self._admit_log: list = []
        self._sent_steps: dict[str, set[str]] = {}      # handoff_id -> channels already stepped
        # Attempt timing. A hand-off is not stepped again until the clock reaches _next_at
        # (the previous attempt's wait interval, moved into send hours). _attempts counts tries
        # per (handoff_id, channel) so retries get distinct records; _retry_channel holds the
        # channel a retry_same_channel outcome must try again.
        self._next_at: dict[str, object] = {}
        self._attempts: dict[tuple[str, str], int] = {}
        self._retry_channel: dict[str, str] = {}
        # P5 metrics: tallies of admission decisions and per-step outcomes.
        self.admit_counts: Counter = Counter()
        self.step_counts: Counter = Counter()

    # ------------------------------------------------------------- admission
    def admit(self, handoff: dict, rank: float | None = None):
        """Gate one hand-off (opt-out, then the P4 quality gate, then the weekly cap: see
        CapLedger.admit_checked) and queue it on the broadcaster when it is sent / moved /
        merged. Returns the Admit decision. A rejected / skipped / opted_out hand-off is never
        queued; a rejected one is counted in broadcaster.counts()["rejected"] (P5's "blocked by
        quality check"). Admitting the same hand-off twice changes nothing."""
        repeat = self.cap.seen(handoff.get("handoff_id"))
        a = self.cap.admit_checked(handoff, opt_out=self.opt_out,
                                   relevance_threshold=self.relevance_threshold)
        if repeat:
            return a
        self._admit_log.append(a)
        self.admit_counts[a.decision] += 1   # P5: sent/moved/merged/skipped/opted_out/rejected
        if a.decision == "rejected":
            self.broadcaster.rejected_count += 1
        if a.decision in ("sent", "moved", "merged"):
            self.broadcaster.queue(a.handoff, rank=rank)
        return a

    def metrics(self) -> dict:
        """P5 counts from ACTUAL decisions (never hard-coded). `admitted` is the admission
        breakdown (sent/moved/merged/skipped/opted_out/rejected); `steps` is the per-step
        outcome breakdown (sent/nothing/no_reachable_channel/...); `dropped` is the
        broadcaster's rejected/expired/opted-out totals."""
        return {"admitted": dict(self.admit_counts), "steps": dict(self.step_counts),
                "dropped": self.broadcaster.counts()}

    def admit_all(self, handoffs) -> list:
        """Admit many hand-offs in send order (send-window start, ties broken by the ranker's
        score if one is set, then created time, farmer, id), so the cap sees them as it would
        in the batch run. Returns the Admit decisions in that order."""
        from .batch import schedule_in_send_order
        ranks = {h.get("handoff_id"): self.ranker.score(h) for h in handoffs} if self.ranker else {}
        out = []

        def queue(hid, a):
            self._admit_log.append(a)
            self.admit_counts[a.decision] += 1
            if a.decision == "rejected":
                self.broadcaster.rejected_count += 1
            if a.decision in ("sent", "moved", "merged"):
                self.broadcaster.queue(a.handoff, rank=ranks.get(hid))
            out.append(a)

        schedule_in_send_order(handoffs, cap=self.cap, opt_out=self.opt_out,
                               relevance_threshold=self.relevance_threshold, ranks=ranks, on_final=queue)
        return out

    # -------------------------------------------------------------- the clock
    def now(self):
        return self.clock.now()

    def now_ist(self) -> str:
        return self.clock.now_ist()

    def advance(self, days: int):
        """Move the one shared clock forward, but never past the season end: if the step
        would overshoot, the clock lands exactly on the season's last instant instead. Both
        the scheduler's expiry/due checks and the broadcaster's decisions follow the shared
        clock. Returns the new `now()`."""
        target = self.clock.now() + _days(days)          # validates days (>=0, whole int)
        if target > self.season.end:
            self.clock.set(self.season.end)               # clamp to the season boundary
        else:
            self.clock.advance(days)
        return self.clock.now()

    def advance_to_end(self):
        """Jump straight to the season's last instant -- the demo's 'fast-forward to the end
        of March' control. After this, `is_season_over()` is True."""
        self.clock.set(self.season.end)
        return self.clock.now()

    def in_season(self) -> bool:
        """True while the shared clock is within the season range."""
        return self.season.contains(self.clock.now())

    def is_season_over(self) -> bool:
        """True once the clock has reached (or been clamped to) the season end."""
        return self.clock.now() >= self.season.end

    # ------------------------------------------------- the manual per-step trigger
    def step(self) -> StepResult:
        """Run exactly ONE due scheduled step at the clock's current instant, by hand.

        Picks the single next hand-off the broadcaster would send now (earliest window
        first, due, quality-clear, inside send hours and the send window) whose previous
        attempt's wait interval has passed, simulates one channel attempt, records any opt-out
        so later steps are blocked, and schedules or ends the hand-off:
          * retry_same_channel -> the same channel again after retry_after_minutes (at most two
            tries on one channel), as a distinct record (delivery_attempt and response_key).
          * delivery failure (fall_back_to_next_channel) -> the next channel after
            retry_after_minutes.
          * no answer (window_expired / push_not_opened) on a channel that is not the last ->
            the next channel after that channel's wait_hours.
          * answered, declined, opted out, or no channel left -> done, removed from the queue.
        The next attempt time is moved into send hours; if it falls after the send window
        closes, the hand-off ends there (no send outside the window). If nothing is due, returns
        StepResult("nothing").
        """
        from mel.simulator import simulate, case_for_channel, next_step, earliest_send

        # Keep the queue honest: drop anything now expired, past its send window, or
        # quality-rejected (no send).
        for b in self.broadcaster.drop_expired_and_rejected(relevance_threshold=self.relevance_threshold):
            self._forget(b.handoff_id)

        now = self.clock.now()
        b = self.broadcaster.next_due(
            relevance_threshold=self.relevance_threshold,
            ready=lambda h: now >= self._next_at.get(h["handoff_id"], now))
        if b is None:
            self.step_counts["nothing"] += 1
            return StepResult("nothing", reason="no step due at " + self.clock.now_ist())

        h = b.handoff
        hid = h["handoff_id"]
        farmer_id = h["survey"]["farmer_id"]
        done = self._sent_steps.setdefault(hid, set())

        # A pending retry uses the same channel again; otherwise the next channel in
        # channel_order the farmer can be reached on and that has not been tried yet. A channel
        # is skipped when the persona cannot reach it or, when reachability data is supplied,
        # the farmer record marks it unreachable. channel_order is preserved.
        channel = self._retry_channel.pop(hid, None)
        if channel is None:
            for stepdef in h["channel_order"]:
                ch = stepdef["channel"]
                if ch in done:
                    continue
                done.add(ch)                   # mark tried (skipped or stepped) so we advance
                if self._reachable(farmer_id, ch):
                    channel = ch
                    break

        if channel is None:
            # No remaining reachable channel: the hand-off is finished, drop it.
            self._finish(hid)
            self.step_counts["no_reachable_channel"] += 1
            return StepResult("nothing", handoff_id=hid, reason="no reachable channel left")

        attempt = self._attempts.get((hid, channel), 0) + 1
        self._attempts[(hid, channel)] = attempt
        case = case_for_channel(self.persona, channel)

        # Simulate this one attempt, sent at the clock's current instant. The case comes from
        # the persona, so opt-out / no-answer / fall-back behaviour follows outcome_codes.json.
        rec = simulate(h["survey"], channel, case, seed=self.seed, persona=self.persona,
                       attempt=attempt, send_at=self.clock.now_ist())
        self.broadcaster.app.deliver(h, now, channel)   # the simulated app is the only target
        self.opt_out.record(rec)  # feed opt-outs back so later steps to this farmer are blocked
        self.step_counts["sent"] += 1

        action, delay = next_step(h, channel, attempt, rec)
        left = [s["channel"] for s in h["channel_order"]
                if s["channel"] not in done and self._reachable(farmer_id, s["channel"])]
        if action == "stop" or (action == "fallback" and not left):
            self._finish(hid)
        else:
            nxt = earliest_send(h, now + delay)
            if nxt is None:
                # The next attempt would fall after the send window closes: nothing more can go out.
                self._finish(hid)
                self.step_counts["window_closed_before_next_attempt"] += 1
            else:
                self._next_at[hid] = nxt
                if action == "retry":
                    self._retry_channel[hid] = channel
        return StepResult("sent", handoff_id=hid, channel=channel, record=rec)

    # -- step helpers --------------------------------------------------------
    def _reachable(self, farmer_id: str, channel: str) -> bool:
        """Reachable per the farmer data (if supplied) and the persona."""
        from mel.simulator import case_for_channel
        if self.reachability is not None and not self.reachability.reachable(farmer_id, channel):
            return False
        return case_for_channel(self.persona, channel) is not None

    def next_attempt_at(self, handoff_id: str):
        """When this hand-off's next attempt may run (None if no wait is pending)."""
        return self._next_at.get(handoff_id)

    def _forget(self, handoff_id: str) -> None:
        self._next_at.pop(handoff_id, None)
        self._retry_channel.pop(handoff_id, None)

    def _finish(self, handoff_id: str) -> None:
        self.broadcaster.remove(handoff_id)
        self._forget(handoff_id)

    def run_due(self, max_steps: int = 1000) -> list[StepResult]:
        """Trigger every step due at the clock's current instant, one `step()` at a time.
        Stops when nothing more is due (or after `max_steps`, a safety bound)."""
        out: list[StepResult] = []
        for _ in range(max_steps):
            r = self.step()
            if r.kind == "nothing":
                break
            out.append(r)
        return out

    # ------------------------------------------------------------- housekeeping
    def sweep_expired(self) -> list:
        """Drop expired / quality-rejected hand-offs from the queue at the current instant
        without sending anything. Returns the Broadcast results for the dropped items."""
        return self.broadcaster.drop_expired_and_rejected(relevance_threshold=self.relevance_threshold)

    @property
    def pending(self) -> list[dict]:
        return self.broadcaster.pending

    def __repr__(self):
        return f"SeasonScheduler(now={self.now_ist()!r}, queued={len(self.broadcaster)})"
