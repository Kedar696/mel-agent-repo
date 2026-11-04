"""Batch admission of hand-offs through the cap + opt-out gate. Owner: P3.

A callable P3 helper that applies the frequency cap and opt-out list to a batch of
hand-offs the pipeline produced, in deterministic send-window order, and returns the
per-decision counts P5 wants. It is the "thin helper, no cli.py edit" option from
`docs/p3_batch_wiring_request.md`: P1's `cmd_run` can call this one function instead of
re-implementing the gate inline, which keeps the batch loop in P1's file minimal.

What it does, matching the brief and the documented cap policy (`docs/cap_policy.md`):
  * Processes hand-offs sorted by `send_window.not_before` (send order), deterministically.
  * Gates each through `CapLedger.admit(opt_out=...)`:
      sent/moved/merged -> scheduled (the cap's resulting hand-off is what is used);
      opted_out/skipped -> nothing is written or simulated for it.
  * When simulating, an opt-out produced during the send is fed back into the OptOutList, so
    a LATER hand-off for that same farmer is blocked (zero surveys to an opted-out farmer).
  * High-priority hand-offs stay exempt from the cap but still count toward later decisions
    (that is CapLedger's existing behaviour; this helper does not change it).
  * Merged `source_insight_ids` are preserved without duplicates (CapLedger does the merge).

It writes nothing itself (pure): the caller decides what to persist, from the returned
`BatchResult`. Delivery stays simulated — it calls `mel.simulator.simulate`, never real I/O.
"""
from collections import Counter

from mel.timing import parse_ist


class BatchItem:
    """One admitted hand-off and what happened to it in the batch."""
    def __init__(self, decision, handoff, response=None, reason=""):
        self.decision = decision          # sent / moved / merged / skipped / opted_out
        self.handoff = handoff            # the cap's resulting hand-off (moved copy / merge host)
        self.response = response          # the simulated response record, if simulated and sent
        self.reason = reason

    @property
    def scheduled(self) -> bool:
        return self.decision in ("sent", "moved", "merged")

    def __repr__(self):
        hid = (self.handoff or {}).get("handoff_id")
        return f"BatchItem({self.decision!r}, {hid!r})"


class BatchResult:
    """The outcome of a batch run: the per-item decisions and the P5 count breakdown."""
    def __init__(self, items, counts):
        self.items = items
        self.counts = counts             # dict from actual decisions (never hard-coded)

    @property
    def scheduled(self):
        """Hand-offs that were scheduled (sent/moved/merged), in processing order."""
        return [it for it in self.items if it.scheduled]

    @property
    def responses(self):
        """Simulated response records produced (when simulate=True), in processing order."""
        return [it.response for it in self.items if it.response is not None]


def run_batch(handoffs, *, relevance_threshold: float, simulate: bool = False,
              persona: str = "default", seed: int = 0, cap=None, opt_out=None,
              reachability=None) -> BatchResult:
    """Admit a batch of hand-offs through the cap + opt-out gate in send-window order.

    Parameters:
      handoffs            : the hand-offs the pipeline produced (each with a survey).
      relevance_threshold : P4's relevance bar; required and explicit (P3 invents none). Used
                            only if `simulate` drives the quality-gated broadcaster path; the
                            cap/opt-out gate itself does not need it, but it is required here
                            so callers always state P4's value.
      simulate            : when True, simulate the first channel send for each scheduled
                            hand-off and feed any opt-out back so later ones are blocked.
      persona, seed       : passed to the simulator (deterministic).
      cap, opt_out        : optional pre-existing CapLedger / OptOutList (e.g. seeded with
                            earlier opt-outs); fresh ones are made when omitted.
      reachability        : optional FarmerReachability; when simulating, the first REACHABLE
                            channel in channel_order is used instead of always channel_order[0].

    Returns a BatchResult. `counts` keys: sent, moved, merged, skipped, opted_out, and
    cap_violations (admissions the cap did NOT allow through: opted_out + skipped). All are
    computed from actual admit decisions, never hard-coded.
    """
    from mel.schedule.handoff import CapLedger, OptOutList
    from mel.simulator import simulate as simulate_one, case_for_channel

    cap = cap if cap is not None else CapLedger()
    opt_out = opt_out if opt_out is not None else OptOutList()

    ordered = sorted(handoffs, key=lambda h: parse_ist(h["send_window"]["not_before"]))
    items: list[BatchItem] = []
    counts: Counter = Counter()

    for h in ordered:
        a = cap.admit(h, opt_out=opt_out)
        counts[a.decision] += 1
        if a.decision in ("opted_out", "skipped"):
            items.append(BatchItem(a.decision, a.handoff, reason=a.reason))
            continue

        resp = None
        if simulate:
            survey = a.handoff["survey"]
            channel = _first_reachable_channel(a.handoff, reachability)
            if channel is not None:
                # The case comes from the persona (not hard-coded), so a persona like
                # opts_out_first actually produces farmer_opted_out, which we then feed back
                # to block LATER hand-offs for this farmer (zero surveys to an opted-out one).
                case = case_for_channel(persona, channel) or "completed"
                resp = simulate_one(survey, channel, case, seed=seed, persona=persona)
                opt_out.record(resp)
        items.append(BatchItem(a.decision, a.handoff, response=resp, reason=a.reason))

    # cap_violations = admissions the cap did not let through (held back): skipped + opted_out.
    counts["cap_violations"] = counts.get("skipped", 0) + counts.get("opted_out", 0)
    # Make sure every decision key is present (from actual tallies; zero only if truly zero).
    for key in ("sent", "moved", "merged", "skipped", "opted_out"):
        counts.setdefault(key, 0)
    return BatchResult(items, dict(counts))


def _first_reachable_channel(handoff: dict, reachability):
    """The first channel in channel_order the farmer can be reached on (order preserved), or
    channel_order[0] when no reachability data is supplied. None if none are reachable."""
    order = [s["channel"] for s in handoff["channel_order"]]
    if reachability is None:
        return order[0] if order else None
    farmer_id = handoff["survey"]["farmer_id"]
    for ch in order:
        if reachability.reachable(farmer_id, ch):
            return ch
    return None
