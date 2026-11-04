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
the one shared clock forward so a later `step()` / `run_due()` sees different work as due.
"""
from mel.timing import parse_ist, fmt_ist
from .clock import SimClock
from .handoff import CapLedger, OptOutList
from .broadcast import Broadcaster, within_send_hours


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

        sched = SeasonScheduler("2026-11-01T07:00:00+05:30", relevance_threshold=0.5)
        sched.admit_all(handoffs)          # cap + opt-out gate, queue what is sent/moved/merged
        sched.step()                       # run the next due scheduled step (one channel attempt)
        sched.advance(7)                   # move the shared clock a week; different work is now due
        sched.run_due()                    # fire every step due at the new instant

    The clock is shared: `sched.clock is sched.broadcaster.clock` is always true, so the
    scheduler and broadcaster can never disagree about the current time. `relevance_threshold`
    is explicit (P3 invents no shared bar); it is handed to the broadcaster's quality gate.
    """

    def __init__(self, start, *, relevance_threshold: float, persona: str = "default", seed: int = 0):
        self.clock = SimClock(start)
        self.broadcaster = Broadcaster(self.clock)      # the SAME clock instance
        self.cap = CapLedger()
        self.opt_out = OptOutList()
        self.relevance_threshold = relevance_threshold
        self.persona = persona
        self.seed = seed
        self._admit_log: list = []
        self._sent_steps: dict[str, set[str]] = {}      # handoff_id -> channels already stepped

    # ------------------------------------------------------------- admission
    def admit(self, handoff: dict):
        """Gate one hand-off through opt-out + cap (the scheduler side), and queue it on the
        broadcaster when it is sent / moved / merged. Returns the Admit decision. A
        skipped / opted_out hand-off is never queued."""
        a = self.cap.admit(handoff, opt_out=self.opt_out)
        self._admit_log.append(a)
        if a.decision in ("sent", "moved", "merged"):
            self.broadcaster.queue(a.handoff)
        return a

    def admit_all(self, handoffs) -> list:
        """Admit many hand-offs in send-window order (the order they would really go out), so
        the cap sees them as it would in the batch run."""
        ordered = sorted(handoffs, key=lambda h: parse_ist(h["send_window"]["not_before"]))
        return [self.admit(h) for h in ordered]

    # -------------------------------------------------------------- the clock
    def now(self):
        return self.clock.now()

    def now_ist(self) -> str:
        return self.clock.now_ist()

    def advance(self, days: int):
        """Move the one shared clock forward. Both the scheduler's expiry/due checks and the
        broadcaster's decisions follow it, because they read the same instance."""
        return self.clock.advance(days)

    # ------------------------------------------------- the manual per-step trigger
    def step(self) -> StepResult:
        """Run exactly ONE due scheduled step at the clock's current instant, by hand.

        Picks the single next hand-off the broadcaster would send now (earliest window
        first, due, quality-clear, inside send hours), simulates its next not-yet-tried
        channel as one step, records any opt-out so later steps are blocked, and removes the
        hand-off from the queue once all its channels have been stepped or it stops. Returns
        a StepResult. If nothing is due to send now, returns StepResult("nothing").
        """
        from mel.simulator import simulate, case_for_channel, STOP_DECISIONS

        # Keep the queue honest: drop anything now expired or quality-rejected (no send).
        self.broadcaster.drop_expired_and_rejected(relevance_threshold=self.relevance_threshold)

        b = self.broadcaster.next_due(relevance_threshold=self.relevance_threshold)
        if b is None:
            return StepResult("nothing", reason="no step due at " + self.clock.now_ist())

        h = b.handoff
        hid = h["handoff_id"]
        done = self._sent_steps.setdefault(hid, set())

        # The next channel step for this hand-off that the persona can actually be reached
        # on and that has not been tried yet. Unreachable channels (case None) are skipped,
        # exactly as the broadcaster/ simulate_handoff() skip them.
        channel = case = None
        for stepdef in h["channel_order"]:
            ch = stepdef["channel"]
            if ch in done:
                continue
            c = case_for_channel(self.persona, ch)
            done.add(ch)                       # mark tried (skipped or stepped) so we advance
            if c is None:
                continue                       # unreachable: skip to the next channel
            channel, case = ch, c
            break

        if channel is None:
            # No remaining reachable channel: the hand-off is finished, drop it.
            self.broadcaster.remove(hid)
            return StepResult("nothing", handoff_id=hid, reason="no reachable channel left")

        # Simulate this one channel attempt, sending at the clock's current instant. The case
        # comes from the persona so opt-out / expiry / fall-back behaviour is preserved.
        rec = simulate(h["survey"], channel, case,
                       seed=self.seed, persona=self.persona, send_at=self.clock.now_ist())
        self.opt_out.record(rec)  # feed opt-outs back so later steps to this farmer are blocked

        # Stop the whole hand-off on an opt-out or any terminal (none/give_up) outcome, or
        # when every channel has been tried. A fall_back_to_next_channel outcome leaves the
        # hand-off queued so the next step() tries the next channel.
        opted_out = rec["failure_code"] == "farmer_opted_out"
        terminal = rec["retry_decision"] in STOP_DECISIONS
        if opted_out or terminal or len(done) >= len(h["channel_order"]):
            self.broadcaster.remove(hid)
        return StepResult("sent", handoff_id=hid, channel=channel, record=rec)

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
