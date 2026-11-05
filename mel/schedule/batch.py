"""Batch scheduling of hand-offs through the opt-out, quality and weekly-cap gate. Owner: P3.

`run_batch` is the P3 scheduling path for a whole batch: P1's `mel.cli run` should call it
(see `docs/p3_batch_wiring_request.md`) instead of writing every hand-off unconditionally.

What it does (policy: `docs/cap_policy.md`):
  * Works on deep copies, so the caller's hand-offs (and the surveys they hold) are not changed.
  * Orders hand-offs by send-window start; ties at the same start are broken by the optional
    frequency ranker's score, then created time, farmer and handoff_id (`queue_key`). A rank
    never moves a hand-off ahead of one whose window opens earlier.
  * Gates each hand-off (`CapLedger.admit_checked`):
      1. opted_out -- the farmer is on the opt-out list (always wins);
      2. rejected  -- the P4 quality gate fails (schema_valid false, any P4 guard failure, or
                      relevance below the threshold P4 supplies). It never takes a weekly slot;
      3. the weekly cap -- sent / moved / merged / skipped.
  * A repeated handoff_id is counted once (`duplicates`) and otherwise ignored.
  * When simulating, each scheduled hand-off is walked through its channel_order
    (`simulate_handoff`: fallback, waits, send hours, send window, reachability). An opt-out
    produced there is fed back, so a LATER hand-off for that farmer becomes opted_out.
  * Merged hand-offs record every contributing insight ID on the host survey (de-duplicated,
    within survey.schema.json's limit), and the host's simulated records carry the same list.

`counts` (all from actual decisions): sent, moved, merged, skipped, opted_out, rejected,
duplicates, prevented (skipped + opted_out + rejected: surveys the gate held back -- these are
NOT cap violations), and cap_violations: scheduled non-high-priority sends that fall less than
7 days after another scheduled send to the same farmer. That last number is an independent
audit of the output and should be 0.

It writes nothing itself: the caller persists what it wants from the returned BatchResult.
Delivery stays simulated (mel.simulator); there is no real messaging here.
"""
import copy
from collections import Counter

from mel.timing import parse_ist

SCHEDULED = ("sent", "moved", "merged")


class BatchItem:
    """One input hand-off and what happened to it in the batch."""
    def __init__(self, decision, handoff, responses=None, reason="", signals=None, input_id=None):
        self.decision = decision          # sent / moved / merged / skipped / opted_out / rejected
        self.handoff = handoff            # the resulting hand-off (moved copy, merge host, or input)
        self.responses = responses or []  # simulated records for this send (empty if not sent)
        self.reason = reason
        self.signals = signals            # ranking signals (when a ranker is used), else None
        self.input_id = input_id          # the handoff_id that came in (differs from host for merged)

    @property
    def response(self):
        """The last simulated record of this send (the outcome), or None."""
        return self.responses[-1] if self.responses else None

    @property
    def scheduled(self) -> bool:
        return self.decision in SCHEDULED

    def __repr__(self):
        return f"BatchItem({self.decision!r}, {self.input_id!r})"


class BatchResult:
    """The outcome of a batch run: the per-item decisions and the P5 count breakdown."""
    def __init__(self, items, counts):
        self.items = items
        self.counts = counts             # dict from actual decisions (never hard-coded)

    @property
    def scheduled(self):
        """Items that were scheduled (sent/moved/merged), in processing order."""
        return [it for it in self.items if it.scheduled]

    @property
    def handoffs_to_send(self):
        """The hand-offs that actually go out (sent and moved; a merged one rides on its host),
        in processing order. This is what a batch writer should persist as hand-offs."""
        return [it.handoff for it in self.items if it.decision in ("sent", "moved")]

    @property
    def responses(self):
        """Every simulated record produced (when simulate=True), in processing order."""
        return [r for it in self.items for r in it.responses]


def run_batch(handoffs, *, relevance_threshold: float, simulate: bool = False,
              persona: str = "default", seed: int = 0, cap=None, opt_out=None,
              reachability=None, ranker=None) -> BatchResult:
    """Schedule a batch of hand-offs: opt-out, quality gate, weekly cap, in send order.

      handoffs            : the hand-offs the pipeline produced (not modified).
      relevance_threshold : P4's relevance bar, required and explicit (P3 invents none). A
                            score equal to it passes.
      simulate            : walk each scheduled hand-off's channel_order with the simulator.
      persona, seed       : simulator persona and seed (deterministic).
      cap, opt_out        : optional existing CapLedger / OptOutList (e.g. earlier opt-outs).
      reachability        : optional FarmerReachability; unreachable channels are skipped.
      ranker              : optional FrequencyScheduler; breaks ties at the same window start.
    """
    from mel.schedule.handoff import CapLedger, OptOutList
    from mel.simulator import simulate_handoff

    cap = cap if cap is not None else CapLedger()
    opt_out = opt_out if opt_out is not None else OptOutList()
    work = [copy.deepcopy(h) for h in handoffs]

    explained = {}
    if ranker is not None:
        for h in work:
            explained.setdefault(h.get("handoff_id"), ranker.explain(h))
    ranks = {hid: r.score for hid, r in explained.items()}

    items: list[BatchItem] = []
    counts: Counter = Counter()

    def finalize(hid, a):
        counts[a.decision] += 1
        recs = []
        if simulate and a.decision in ("sent", "moved"):
            recs = simulate_handoff(copy.deepcopy(a.handoff), persona, seed=seed, reachability=reachability)
            for r in recs:
                opt_out.record(r)  # an opt-out here blocks later hand-offs for this farmer
        sig = explained[hid].signals if hid in explained else None
        items.append(BatchItem(a.decision, a.handoff, recs, a.reason, sig, input_id=hid))

    _, counts["duplicates"] = schedule_in_send_order(work, cap=cap, opt_out=opt_out,
                                                     relevance_threshold=relevance_threshold,
                                                     ranks=ranks, on_final=finalize)

    # A merge adds insight IDs to its host after the host may already have been simulated. Put
    # the host's final list on the host's records, so the answer links back to every insight.
    final_ids = {it.handoff["handoff_id"]: list(it.handoff["survey"]["source_insight_ids"])
                 for it in items if it.decision in ("sent", "moved")}
    for it in items:
        for r in it.responses:
            r["source_insight_ids"] = list(final_ids.get(it.handoff["handoff_id"], r["source_insight_ids"]))

    for key in ("sent", "moved", "merged", "skipped", "opted_out", "rejected", "duplicates"):
        counts.setdefault(key, 0)
    counts["prevented"] = counts["skipped"] + counts["opted_out"] + counts["rejected"]
    counts["cap_violations"] = len(cap_violations([it.handoff for it in items if it.decision in ("sent", "moved")]))
    return BatchResult(items, dict(counts))


def schedule_in_send_order(handoffs, *, cap, opt_out, relevance_threshold: float, ranks=None,
                           on_final=None):
    """Decide every hand-off in true send order and return ([(input_id, Admit), ...], duplicates).

    Hand-offs are taken from a priority queue keyed by `queue_key` (send-window start, then
    rank, created time, farmer, id). A survey the cap MOVES is not placed at its new date
    straight away: its moved copy goes back into the queue at the new start and is decided again
    when its turn comes. So a high-priority survey that opens in between is seen first, and the
    moved survey is moved again, merged or skipped instead of landing inside that week.
    `on_final(input_id, admit)` is called as each decision becomes final, in send order (the
    batch simulates there, so an opt-out it produces blocks every later decision)."""
    import heapq
    from mel.schedule.broadcast import queue_key
    from mel.schedule.handoff import Admit

    ranks = ranks or {}
    key = lambda h: queue_key(h, ranks.get(h.get("handoff_id")))
    heap, seen, dups, seq = [], set(), 0, 0
    for h in sorted(handoffs, key=key):
        hid = h.get("handoff_id")
        if hid in seen or cap.seen(hid):
            dups += 1          # same hand-off twice (in this input or already decided): once only
            continue
        seen.add(hid)
        heap.append((key(h), seq, hid, h, False)); seq += 1
    heapq.heapify(heap)

    out = []
    while heap:
        _, _, iid, h, was_moved = heapq.heappop(heap)
        a = cap.admit_checked(h, opt_out=opt_out, relevance_threshold=relevance_threshold, defer_move=True)
        if a.decision == "moved":
            heapq.heappush(heap, (key(a.handoff), seq, iid, a.handoff, True)); seq += 1
            continue
        if was_moved and a.decision == "sent":
            a = Admit("moved", a.handoff, reason=f"moved to {a.handoff['send_window']['not_before']}")
            cap.relabel(iid, a)
        out.append((iid, a))
        if on_final is not None:
            on_final(iid, a)
    return out, dups


def cap_violations(sent_handoffs) -> list[tuple[str, str]]:
    """Audit a list of hand-offs that actually go out: every (earlier, later) pair where a
    non-high-priority hand-off starts less than the cap window after another hand-off to the
    same farmer. High-priority hand-offs are exempt themselves but still count as the earlier
    send. Independent of CapLedger, so it checks the output rather than repeating the policy."""
    from datetime import timedelta
    by_key: dict[str, list] = {}
    for h in sent_handoffs:
        by_key.setdefault(h["frequency_cap"]["key"], []).append(h)
    out = []
    for hs in by_key.values():
        hs = sorted(hs, key=lambda h: (parse_ist(h["send_window"]["not_before"]), h["handoff_id"]))
        for i, later in enumerate(hs):
            if later["frequency_cap"]["exempt"]:
                continue
            window = timedelta(days=later["frequency_cap"]["window_days"])
            t = parse_ist(later["send_window"]["not_before"])
            for earlier in hs[:i]:
                if t - parse_ist(earlier["send_window"]["not_before"]) < window:
                    out.append((earlier["handoff_id"], later["handoff_id"]))
    return out
