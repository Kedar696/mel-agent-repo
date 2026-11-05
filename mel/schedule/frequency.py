"""Question-frequency monitor and frequency-aware survey ranking. Owner: P3.

What this adds (P3 scope: scheduling, not decisions or survey writing):
  * `FrequencyMonitor` groups a farmer's question history by (farmer, topic) over a
    documented rolling window, computes that pair's own baseline, and flags a *peak* when
    recent questions run well above that baseline. Topic is the crop (`asset.name`), falling
    back to the `concern`. It reads only existing insight fields (ids + timestamps); it logs
    no personal information.
  * `SeasonStageContext` labels the crop's growth stage for a date from P2's crop calendar
    (read-only; it does not redefine P2's R7 / harvest rules).
  * `ClimateContext` is a pluggable regional-climate signal. This repo ships NO climate data,
    so the default is a neutral no-adjustment fallback that reports the context is missing.
  * `FrequencyScheduler.rank()` orders ELIGIBLE hand-offs using the peak signal, the survey's
    EXISTING priority, the season stage, and (only if supplied) climate -- and explains each
    result by its contributing signals. It never changes eligibility: opt-outs, the frequency
    cap, send windows, expiry and the quality gate still decide what may go out; this only
    ranks/times what is already allowed.

Everything configurable lives in `frequency_config.json` next to this file (not in
config/rules/, so P1's pack-parity check is untouched). Defaults are explained there.

Delivery stays simulated elsewhere (mel.simulator); this module schedules, it does not send.
"""
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from mel.timing import parse_ist
from .broadcast import quality_failures

_CONFIG_PATH = Path(__file__).with_name("frequency_config.json")


@lru_cache
def frequency_config() -> dict:
    """The P3 frequency config (cached). See frequency_config.json for documented defaults."""
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- topic key
def topic_of(insight: dict, cfg: dict | None = None) -> str:
    """The grouping topic for one insight: the crop (asset.name) when present, else the
    concern, else the literal 'unknown'. Deterministic; unrelated crops/concerns never share
    a key, so one farmer's wheat questions cannot contaminate their livestock questions."""
    cfg = cfg or frequency_config()
    asset = (insight.get("asset") or {})
    crop = asset.get("name")
    concern = insight.get("concern")
    if cfg["topic"]["prefer"] == "crop":
        return (crop or concern or "unknown").strip().lower()
    return (concern or crop or "unknown").strip().lower()


def _ts(insight: dict) -> datetime:
    """The insight's created_at as a tz-aware IST datetime (parse_ist rejects naive)."""
    return parse_ist(insight["created_at"])


# --------------------------------------------------------------------- frequency monitor
class FrequencyPeak:
    """A monitor result for one (farmer, topic). No free text, only ids and counts.

      is_peak      -- True when recent questions run at/above baseline * peak_ratio and meet
                      the minimum count (so a sparse 1->2 jump is not a 'peak').
      window_count -- questions in the most recent rolling window ending at `as_of`.
      baseline     -- the pair's own average questions per window over its history.
      strength     -- window_count / baseline (1.0 = at baseline), 0.0 if baseline is 0.
    """
    def __init__(self, farmer_id, topic, *, is_peak, window_count, baseline, strength, n_history):
        self.farmer_id = farmer_id
        self.topic = topic
        self.is_peak = is_peak
        self.window_count = window_count
        self.baseline = baseline
        self.strength = strength
        self.n_history = n_history

    def signals(self) -> dict:
        """A compact, PII-free dict for explaining a scheduling result."""
        return {"farmer_id": self.farmer_id, "topic": self.topic, "is_peak": self.is_peak,
                "window_count": self.window_count, "baseline": round(self.baseline, 3),
                "strength": round(self.strength, 3), "n_history": self.n_history}

    def __repr__(self):
        return (f"FrequencyPeak({self.farmer_id!r}, {self.topic!r}, peak={self.is_peak}, "
                f"count={self.window_count}, baseline={self.baseline:.2f})")


class FrequencyMonitor:
    """Counts questions per (farmer, topic) over a rolling window and flags peaks.

        mon = FrequencyMonitor(history_insights)      # a list of insight dicts
        peak = mon.peak("F-000123", "wheat", as_of="2027-01-15T07:00:00+05:30")

    Transparent and deterministic: same history + same as_of -> same peak. Duplicate inputs
    (same insight_id) are counted once; out-of-order timestamps are sorted; sparse history is
    handled (no baseline -> no peak). Reads only ids, timestamps, crop and concern -- never
    the farmer's words.
    """

    def __init__(self, history, cfg: dict | None = None):
        self.cfg = cfg or frequency_config()
        # group timestamps by (farmer, topic), de-duplicating by insight_id
        self._seen_ids: set[str] = set()
        self._events: dict[tuple[str, str], list[datetime]] = defaultdict(list)
        for ins in history:
            iid = ins.get("insight_id")
            if iid is not None and iid in self._seen_ids:
                continue  # duplicate input -> count once
            if iid is not None:
                self._seen_ids.add(iid)
            key = (ins["farmer_id"], topic_of(ins, self.cfg))
            self._events[key].append(_ts(ins))
        for key in self._events:
            self._events[key].sort()  # out-of-order timestamps handled deterministically

    def topics(self):
        """Sorted (farmer_id, topic) pairs that have any history."""
        return sorted(self._events)

    def _as_of(self, as_of) -> datetime:
        if as_of is None:
            # Default to the latest event across all history, so "now" is data-driven and
            # never the wall clock (keeps results deterministic and reproducible).
            allts = [t for ev in self._events.values() for t in ev]
            if not allts:
                raise ValueError("no history to infer as_of from; pass as_of explicitly")
            return max(allts)
        return parse_ist(as_of) if isinstance(as_of, str) else as_of

    def peak(self, farmer_id: str, topic: str, as_of=None) -> FrequencyPeak:
        """The peak result for one (farmer, topic) at instant `as_of` (default: latest event).

        Baseline = the pair's own mean questions per rolling window across the span of its
        history (self-relative). A peak needs both the window count >= baseline*peak_ratio and
        >= min_peak_count, and at least `min_history` total questions. Everything else is
        'not a peak', reported transparently."""
        w = self.cfg["window"]
        b = self.cfg["baseline"]
        rolling = timedelta(days=w["rolling_days"])
        events = self._events.get((farmer_id, topic.strip().lower()), [])
        if as_of is not None:
            # Only questions asked by `as_of` count. A scheduling decision made on 1 December must
            # not see questions from January (no look-ahead into the farmer's future).
            now = self._as_of(as_of)
            events = [t for t in events if t <= now]
        n = len(events)
        if n < w["min_history"]:
            return FrequencyPeak(farmer_id, topic, is_peak=False, window_count=n,
                                 baseline=0.0, strength=0.0, n_history=n)

        if as_of is None:
            now = self._as_of(None)
        window_start = now - rolling
        window_count = sum(1 for t in events if window_start < t <= now)

        # Baseline: spread history across however many whole windows it spans (>=1), so the
        # baseline is this pair's own average load per window.
        span = (events[-1] - events[0])
        n_windows = max(1, (span / rolling))
        baseline = n / n_windows
        strength = (window_count / baseline) if baseline > 0 else 0.0

        is_peak = (baseline > 0 and strength >= b["peak_ratio"]
                   and window_count >= b["min_peak_count"])
        return FrequencyPeak(farmer_id, topic, is_peak=is_peak, window_count=window_count,
                             baseline=baseline, strength=strength, n_history=n)


# ------------------------------------------------------------------- season stage context
class SeasonStageContext:
    """Labels a crop's growth stage for a date, from P2's crop calendar (read-only).

    This does not redefine P2's harvest / R7 rules; it only reports which calendar stage a
    date falls in, as a scheduling signal. `active_stage(crop, on)` returns the stage label
    or None (unknown crop, or a date outside every stage window)."""

    def __init__(self, calendar=None):
        from mel.data import load_crop_calendar
        self._rows = calendar if calendar is not None else load_crop_calendar()

    @staticmethod
    def _crop_key(crop):
        from mel.timing.calendar import _crop_key
        return _crop_key(crop) if crop else None

    def active_stage(self, crop, on: date):
        """The growth_stage whose [start,end] contains `on` for this crop, else None."""
        key = self._crop_key(crop)
        if not key:
            return None
        for row in self._rows:
            if self._crop_key(row["crop"]) != key or not row["growth_stage"]:
                continue
            s = date.fromisoformat(row["start_date"])
            e = date.fromisoformat(row["end_date"])
            if s <= on <= e:
                return row["growth_stage"]
        return None

    def is_active(self, crop, on: date) -> bool:
        """True if the crop is in a named growth stage on `on` (a live window to survey about)."""
        return self.active_stage(crop, on) is not None


# ----------------------------------------------------------------------- climate context
class ClimateContext:
    """Regional climate signal -- neutral by default because this repo ships no climate data.

    `factor(state, district, on)` returns a stress factor in [0,1] (higher = more climate
    stress, e.g. a dry/heat spell that makes timely follow-up more useful), or None when no
    context is available. With the default (no provider, config available=false) it always
    returns None and `available` is False, so the scheduler applies NO climate adjustment and
    marks the result context_missing.

    To add real data, pass `provider=callable(state, district, date) -> float|None`. For a
    DEMO only, a constant synthetic factor may be set in config (synthetic_demo_factor) or
    passed as `synthetic_factor=`; such values are clearly labelled synthetic in results.
    """

    def __init__(self, provider=None, synthetic_factor=None, cfg: dict | None = None):
        cfg = cfg or frequency_config()
        self._provider = provider
        self._cfg_available = bool(cfg["climate"]["available"])
        self._synthetic = (synthetic_factor if synthetic_factor is not None
                           else cfg["climate"].get("synthetic_demo_factor"))

    @property
    def available(self) -> bool:
        """True when a climate signal can be produced: a real provider, a config flag, or a
        synthetic demo constant. `is_synthetic` distinguishes the demo-only case, and results
        always surface whether the value is synthetic so it is never mistaken for real data."""
        return self._provider is not None or self._cfg_available or self._synthetic is not None

    @property
    def is_synthetic(self) -> bool:
        """True when the only climate value is a demo/synthetic constant (no real provider)."""
        return self._provider is None and self._synthetic is not None

    def factor(self, state, district, on: date):
        """Stress factor in [0,1], or None if no context. Real provider wins; else a labelled
        synthetic demo constant; else None (the neutral fallback)."""
        if self._provider is not None:
            v = self._provider(state, district, on)
            return None if v is None else max(0.0, min(1.0, float(v)))
        if self._synthetic is not None:
            return max(0.0, min(1.0, float(self._synthetic)))
        return None


# -------------------------------------------------------------- frequency-aware scheduler
class RankedHandoff:
    """One eligible hand-off with its computed rank score and the signals behind it."""
    def __init__(self, handoff, score, signals):
        self.handoff = handoff
        self.score = score
        self.signals = signals

    @property
    def handoff_id(self):
        return self.handoff.get("handoff_id")

    def __repr__(self):
        return f"RankedHandoff({self.handoff_id!r}, score={self.score:.3f}, {self.signals})"


class FrequencyScheduler:
    """Ranks ELIGIBLE survey hand-offs using the frequency peak + existing priority + season
    stage + (optional) climate, and explains every result.

        sched = FrequencyScheduler(FrequencyMonitor(history))
        ranked = sched.rank(eligible_handoffs, as_of="2027-01-15T07:00:00+05:30")

    Protections are never bypassed. `rank()` only accepts hand-offs that are already eligible;
    use `filter_eligible()` (or the existing CapLedger/OptOutList/quality gate) first. A
    frequency peak raises a survey's rank; it can never admit an opted-out farmer, a capped
    survey, an expired/out-of-window survey, or a survey that fails the quality gate.
    """

    def __init__(self, monitor: FrequencyMonitor, *, season: SeasonStageContext | None = None,
                 climate: ClimateContext | None = None, cfg: dict | None = None, insights=None):
        self.cfg = cfg or frequency_config()
        self.monitor = monitor
        self.season = season if season is not None else SeasonStageContext()
        self.climate = climate if climate is not None else ClimateContext(cfg=self.cfg)
        # insight_id -> insight, so a hand-off's crop (season stage, topic) and region (climate)
        # come from the insight it was built from, never from a guess. Hand-offs carry no crop
        # field (the schema forbids extra fields), so without this the season and topic signals
        # simply do not apply.
        self._insights = {i.get("insight_id"): i for i in (insights or []) if isinstance(i, dict)}

    @classmethod
    def from_insights(cls, insights, **kw) -> "FrequencyScheduler":
        """A ranker built from the batch's own question history (the insights): the frequency
        monitor reads their ids/timestamps/crop/concern, and each hand-off is linked back to
        its source insight. Climate stays neutral unless a real ClimateContext is passed."""
        insights = [i for i in insights if isinstance(i, dict) and i.get("farmer_id") and i.get("created_at")]
        return cls(FrequencyMonitor(insights), insights=insights, **kw)

    def score(self, handoff: dict, as_of=None) -> float:
        """The rank score of one hand-off, measured as of its send-window start by default (only
        questions asked by then count). Used as a tie-break in send order."""
        return self.explain(handoff, as_of).score

    def explain(self, handoff: dict, as_of=None) -> "RankedHandoff":
        """Score plus the signals behind it, as of `as_of` (default: the send-window start)."""
        when = as_of if as_of is not None else handoff["send_window"]["not_before"]
        return self._score_one(handoff, parse_ist(when) if isinstance(when, str) else when)

    def _source_insight(self, handoff: dict):
        for iid in handoff.get("survey", {}).get("source_insight_ids", []):
            if iid in self._insights:
                return self._insights[iid]
        return None

    # -- eligibility gate (wraps existing protections; never bypassed) -------
    def filter_eligible(self, handoffs, *, relevance_threshold, opt_out=None, cap=None,
                        now=None):
        """Keep only hand-offs that pass every existing protection, so ranking only ever sees
        allowed surveys. Order of checks: opt-out, quality gate, expiry/window (if `now`), and
        the frequency cap (if a CapLedger is supplied). Returns the eligible list; dropped
        ones are never ranked. This does not re-implement those rules -- it calls them."""
        out = []
        for h in handoffs:
            if opt_out is not None and opt_out.blocks(h):
                continue  # opt-out always wins
            if quality_failures(h["survey"], relevance_threshold):
                continue  # invalid / low-relevance survey never scheduled
            if now is not None:
                nb = parse_ist(h["send_window"]["not_before"])
                na = parse_ist(h["send_window"]["not_after"])
                exp = parse_ist(h["expires_at"])
                if not (nb <= now <= na and now <= exp):
                    continue  # outside the send window (nothing is sent after not_after) or past expiry
            if cap is not None:
                a = cap.admit(h, opt_out=opt_out)
                if a.decision in ("opted_out", "skipped"):
                    continue  # cap holds; a peak cannot force it through
                # sent/moved/merged: the cap decided what is scheduled. Rank the hand-off the
                # cap produced (a moved copy, or the merge host), not the raw input, so the
                # cap stays authoritative and a merge is not double-counted.
                out.append(a.handoff)
                continue
            out.append(h)
        return out

    # -- ranking (eligible only) --------------------------------------------
    def rank(self, eligible_handoffs, as_of=None):
        """Rank already-eligible hand-offs, highest score first. Deterministic: ties break by
        handoff_id. Each result carries the signals that produced its score."""
        now_dt = parse_ist(as_of) if isinstance(as_of, str) else as_of
        ranked = [self._score_one(h, now_dt) for h in eligible_handoffs]
        ranked.sort(key=lambda r: (-r.score, r.handoff_id or ""))
        return ranked

    def _score_one(self, handoff: dict, now_dt) -> RankedHandoff:
        survey = handoff["survey"]
        farmer_id = survey["farmer_id"]
        rk = self.cfg["ranking"]

        # 1) existing priority (unchanged, just read)
        priority = handoff.get("priority", "normal")
        base = rk["priority_base"].get(priority, rk["priority_base"]["normal"])

        # 2) frequency peak for this farmer+topic. Topic comes from the survey's source insight
        # crop if the handoff carries it; else fall back to any topic the monitor knows for the
        # farmer with the strongest signal.
        peak = self._peak_for_handoff(handoff, now_dt)
        freq_component = rk["frequency_weight"] * (peak.strength if peak and peak.is_peak else 0.0)

        # 3) season stage (active crop window -> a small boost)
        on = (now_dt.date() if now_dt is not None
              else parse_ist(handoff["send_window"]["not_before"]).date())
        crop = self._handoff_crop(handoff)
        stage = self.season.active_stage(crop, on) if crop else None
        season_component = rk["season_stage_weight"] if stage else 0.0

        # 4) climate (only when real/available; neutral otherwise). The region is the source
        # insight's own state/district; with no insight the provider is asked for (None, None).
        loc = (self._source_insight(handoff) or {}).get("location") or {}
        clim_factor = self.climate.factor(loc.get("state"), loc.get("district"), on)
        climate_component = (rk["climate_weight"] * clim_factor
                             if (self.climate.available and clim_factor is not None) else 0.0)

        score = base + freq_component + season_component + climate_component
        signals = {
            "priority": priority,
            "priority_base": base,
            "frequency": (peak.signals() if peak else {"is_peak": False, "reason": "no topic history"}),
            "frequency_component": round(freq_component, 3),
            "season_stage": stage,
            "season_component": round(season_component, 3),
            "climate_available": self.climate.available,
            "climate_synthetic": self.climate.is_synthetic,
            "climate_context_missing": not (self.climate.available and clim_factor is not None),
            "climate_factor": clim_factor,
            "climate_component": round(climate_component, 3),
            "score": round(score, 3),
        }
        return RankedHandoff(handoff, score, signals)

    # -- helpers -------------------------------------------------------------
    def _handoff_crop(self, handoff: dict):
        """The crop a hand-off is about: an explicit `_crop` (tests, callers), else the crop of
        its source insight. May be None (the season signal then simply does not apply)."""
        return (handoff.get("_crop")
                or (handoff.get("survey", {}).get("_crop"))
                or handoff.get("crop")
                or ((self._source_insight(handoff) or {}).get("asset") or {}).get("name"))

    def _peak_for_handoff(self, handoff: dict, now_dt):
        """The best peak signal for this hand-off's farmer. Prefers the hand-off's own topic
        when known; otherwise picks the farmer's strongest peak so a genuine surge on any of
        that farmer's topics can still inform timing. Returns None if the farmer has no
        history at all."""
        farmer_id = handoff["survey"]["farmer_id"]
        as_of = None if now_dt is None else now_dt
        topic = self._handoff_topic(handoff)
        if topic is not None:
            return self.monitor.peak(farmer_id, topic, as_of=as_of)
        candidates = [self.monitor.peak(f, t, as_of=as_of)
                      for (f, t) in self.monitor.topics() if f == farmer_id]
        if not candidates:
            return None
        candidates.sort(key=lambda p: (-(p.strength if p.is_peak else 0.0), p.topic))
        return candidates[0]

    def _handoff_topic(self, handoff: dict):
        """The monitor topic key for a hand-off: its crop, or (from its source insight) the same
        key the monitor groups by (crop, else concern). None lets the scheduler fall back to the
        farmer's strongest topic."""
        crop = self._handoff_crop(handoff)
        if crop:
            return crop.strip().lower()
        ins = self._source_insight(handoff)
        return topic_of(ins, self.cfg) if ins else None
