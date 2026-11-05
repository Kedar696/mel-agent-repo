"""Per-farmer channel reachability from farmers.csv. Owner: P3 (channel handling).

The broadcaster/simulator walk a hand-off's `channel_order` and skip channels a farmer
cannot be reached on. Until now that was modelled only by test personas (`unreachable` sets).
This reads the project's real farmer records (`data/mock/farmers.csv`, via P1's
`load_farmers`) so reachability reflects the data, not a hard-coded persona.

## The data contract we actually have
`farmers.csv` columns (P1-owned, read-only here):
`farmer_id, country, state, district, language, preferred_channel, crops, land_size_band,
 livestock, activity_level`

There is **no explicit per-channel reachability column** — only `preferred_channel`. The
task is clear that `preferred_channel` must NOT be read as "every other channel is
unreachable": it is where the farmer talks most, not the only place they can be reached. So
without richer data we do not invent unreachability.

## The documented, deterministic rule (smallest change)
`reachable(farmer_id, channel)`:
  * A farmer's `preferred_channel` is always reachable.
  * Every other channel is reachable **by default**, because the CSV carries no signal that
    would rule it out. (We refuse to guess that, e.g., a push-preferring farmer has no phone.)
  * A channel may be excluded only by an explicit, documented override passed in by the
    caller (`unreachable_by_farmer`) — the hook for real reachability data when it arrives.
  * **Missing farmer record** (not in farmers.csv): fall back to *all channels reachable*,
    and surface it via `is_known()` so a caller can log/branch. We do not drop a farmer we
    simply have no row for.

This keeps `channel_order` intact for reachable channels and only skips a channel when there
is a concrete reason to (today: an explicit override; tomorrow: a real data column).

## Contract to add real reachability (request to P1)
If/when farmers gain real per-channel reachability, the cleanest shape is a boolean-ish set
per farmer, e.g. a `reachable_channels` column (pipe-separated like `crops`) or a separate
table. Until then, construct `FarmerReachability(load_farmers(), unreachable_by_farmer=...)`
to inject known gaps for a demo (clearly a stand-in, not real data).
"""


class FarmerReachability:
    """Answers "can this farmer be reached on this channel?" from farmer records.

        from mel.data import load_farmers
        reach = FarmerReachability(load_farmers())
        reach.reachable("F-000008", "voice")      # True/False
        reach.reachable_channels("F-000008", channel_order)  # filtered, order preserved

    `farmers` is the dict `load_farmers()` returns ({farmer_id: row}); pass {} to treat every
    farmer as unknown (all channels reachable). `unreachable_by_farmer` is an optional
    explicit override {farmer_id: {channel, ...}} — the documented hook for real data or a
    labelled demo stand-in.
    """

    def __init__(self, farmers: dict | None = None, unreachable_by_farmer: dict | None = None):
        self._farmers = farmers or {}
        self._blocked = {fid: set(chs) for fid, chs in (unreachable_by_farmer or {}).items()}

    def is_known(self, farmer_id: str) -> bool:
        """True if we have a farmer record for this id (else reachability is a fallback)."""
        return farmer_id in self._farmers

    def preferred_channel(self, farmer_id: str) -> str | None:
        row = self._farmers.get(farmer_id)
        return (row or {}).get("preferred_channel") or None

    def reachable(self, farmer_id: str, channel: str) -> bool:
        """Can `farmer_id` be reached on `channel`?

        The preferred channel is always reachable. Any channel in an explicit override set is
        unreachable. Everything else is reachable by default (no data says otherwise). An
        unknown farmer is reachable on every channel (documented fallback)."""
        if channel == self.preferred_channel(farmer_id):
            return True
        if channel in self._blocked.get(farmer_id, set()):
            return False
        return True

    def reachable_channels(self, farmer_id: str, channel_order):
        """The channels from `channel_order` the farmer can be reached on, in the SAME order.

        `channel_order` may be the hand-off's list of step dicts ({"channel": ...}) or a plain
        list of channel strings. Order is preserved for reachable channels; unreachable ones
        are dropped."""
        out = []
        for step in channel_order:
            ch = step["channel"] if isinstance(step, dict) else step
            if self.reachable(farmer_id, ch):
                out.append(ch)
        return out

    def __repr__(self) -> str:
        return f"FarmerReachability(farmers={len(self._farmers)}, overrides={len(self._blocked)})"
