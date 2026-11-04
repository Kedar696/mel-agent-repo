"""P3: edge-case coverage for the frequency feature, complementing tests/test_frequency.py.

These target code paths the main frequency tests do not exercise: the monitor's accessors
and `as_of` defaulting, config overrides, missing insight_id, concern-first topic keying, the
scheduler's no-crop fallback to a farmer's strongest topic, and the cap merge-host path.
"""
import copy

import pytest

from mel.data import load_scenario
from mel.schedule import (
    build_handoff, CapLedger, OptOutList,
    FrequencyMonitor, FrequencyPeak, FrequencyScheduler, ClimateContext,
    frequency_config, topic_of,
)


def _ins(iid, fid, crop, concern, ts):
    return {"insight_id": iid, "farmer_id": fid, "asset": {"name": crop},
            "concern": concern, "created_at": ts}


def _clear_handoff(scenario="1-mustard-aphid-spray", crop="mustard"):
    s = load_scenario(scenario)
    h = build_handoff(s["insight"], s["surveys"]["hi-IN"])
    h["survey"]["self_eval"] = {"schema_valid": True, "relevance_score": 0.8,
                                "gives_new_advice": False, "asks_personal_info": False}
    if crop is not None:
        h["_crop"] = crop
    return h


# ===================================================== monitor accessors / as_of defaulting
def test_topics_lists_sorted_farmer_topic_pairs():
    hist = [_ins("A", "F2", "wheat", "pest_disease", "2027-01-10T09:00:00+05:30"),
            _ins("B", "F1", "mustard", "pest_disease", "2027-01-10T09:00:00+05:30"),
            _ins("C", "F1", "mustard", "pest_disease", "2027-01-11T09:00:00+05:30")]
    mon = FrequencyMonitor(hist)
    assert mon.topics() == [("F1", "mustard"), ("F2", "wheat")]   # sorted, de-grouped


def test_as_of_defaults_to_latest_event():
    """With no as_of, the monitor uses the latest event as 'now' -- data-driven, not wall
    clock. The default result matches passing that latest timestamp explicitly."""
    hist = [_ins("A", "F1", "mustard", "pest_disease", "2026-12-20T09:00:00+05:30"),
            _ins("B", "F1", "mustard", "pest_disease", "2026-12-27T09:00:00+05:30"),
            _ins("C", "F1", "mustard", "pest_disease", "2026-12-30T09:00:00+05:30")]
    mon = FrequencyMonitor(hist)
    default = mon.peak("F1", "mustard")                              # as_of=None
    explicit = mon.peak("F1", "mustard", as_of="2026-12-30T09:00:00+05:30")
    assert default.signals() == explicit.signals()


def test_peak_on_empty_history_is_safe_not_a_peak():
    """Asking for a peak with no history at all returns a clean 'not a peak' (n_history 0),
    rather than erroring -- the scheduler can query any farmer/topic safely."""
    p = FrequencyMonitor([]).peak("F1", "mustard")
    assert p.is_peak is False and p.n_history == 0 and p.window_count == 0


def test_peak_topic_lookup_is_case_and_space_insensitive():
    hist = [_ins("A", "F1", "Mustard", "pest_disease", "2026-12-27T09:00:00+05:30"),
            _ins("B", "F1", "Mustard", "pest_disease", "2026-12-30T09:00:00+05:30")]
    mon = FrequencyMonitor(hist)
    assert mon.peak("F1", "  MUSTARD  ", as_of="2026-12-31T07:00:00+05:30").n_history == 2


# ===================================================== config / topic keying variants
def test_concern_first_topic_keying_via_config():
    cfg = copy.deepcopy(frequency_config())
    cfg["topic"]["prefer"] = "concern"
    # concern-first: the concern is the key even when a crop name is present
    assert topic_of({"asset": {"name": "wheat"}, "concern": "pest_disease"}, cfg) == "pest_disease"
    hist = [_ins("A", "F1", "wheat", "pest_disease", "2026-12-27T09:00:00+05:30"),
            _ins("B", "F1", "wheat", "pest_disease", "2026-12-30T09:00:00+05:30")]
    mon = FrequencyMonitor(hist, cfg=cfg)
    # grouped under the concern, not the crop
    assert mon.peak("F1", "pest_disease", as_of="2026-12-31T07:00:00+05:30").n_history == 2
    assert mon.peak("F1", "wheat", as_of="2026-12-31T07:00:00+05:30").n_history == 0


def test_lower_threshold_config_detects_smaller_peak():
    """A caller-supplied config with a lower bar flags a peak the default would not."""
    hist = [_ins("A", "F1", "mustard", "pest_disease", "2026-12-01T09:00:00+05:30"),
            _ins("B", "F1", "mustard", "pest_disease", "2026-12-28T09:00:00+05:30"),
            _ins("C", "F1", "mustard", "pest_disease", "2026-12-30T09:00:00+05:30")]
    as_of = "2026-12-31T07:00:00+05:30"
    assert not FrequencyMonitor(hist).peak("F1", "mustard", as_of=as_of).is_peak  # default: no
    cfg = copy.deepcopy(frequency_config())
    cfg["baseline"]["peak_ratio"] = 1.0
    cfg["baseline"]["min_peak_count"] = 2
    assert FrequencyMonitor(hist, cfg=cfg).peak("F1", "mustard", as_of=as_of).is_peak  # now yes


def test_missing_insight_id_is_not_treated_as_duplicate():
    """Insights without an insight_id are all counted (no id to dedupe on), rather than
    collapsed into one."""
    hist = [{"farmer_id": "F1", "asset": {"name": "mustard"}, "concern": "pest_disease",
             "created_at": "2026-12-2%dT09:00:00+05:30" % d} for d in (7, 8, 9)]
    mon = FrequencyMonitor(hist)
    assert mon.peak("F1", "mustard", as_of="2026-12-31T07:00:00+05:30").n_history == 3


# ===================================================== FrequencyPeak surface
def test_peak_signals_are_rounded_and_pii_free():
    hist = [_ins("A", "F1", "mustard", "pest_disease", "2026-12-20T09:00:00+05:30"),
            _ins("B", "F1", "mustard", "pest_disease", "2026-12-27T09:00:00+05:30"),
            _ins("C", "F1", "mustard", "pest_disease", "2026-12-30T09:00:00+05:30")]
    sig = FrequencyMonitor(hist).peak("F1", "mustard", as_of="2026-12-31T07:00:00+05:30").signals()
    assert set(sig) == {"farmer_id", "topic", "is_peak", "window_count", "baseline",
                        "strength", "n_history"}
    # only ids/counts, no free text; rounded to 3 dp
    assert sig["farmer_id"] == "F1" and sig["topic"] == "mustard"
    assert round(sig["baseline"], 3) == sig["baseline"]


# ===================================================== scheduler: no-crop fallback
def test_rank_handoff_without_crop_uses_farmers_strongest_topic():
    """A hand-off that carries no crop falls back to the farmer's strongest peak topic, so a
    genuine surge still informs its rank."""
    h = _clear_handoff(crop=None)                    # no _crop on the hand-off
    assert "_crop" not in h
    fid = h["survey"]["farmer_id"]
    # History spread over a month with a recent cluster, so the last fortnight genuinely
    # exceeds this pair's own baseline -> a real peak (not one dense cluster).
    busy = [_ins("A", fid, "mustard", "pest_disease", "2026-12-01T09:00:00+05:30"),
            _ins("B", fid, "mustard", "pest_disease", "2026-12-27T09:00:00+05:30"),
            _ins("C", fid, "mustard", "pest_disease", "2026-12-29T09:00:00+05:30"),
            _ins("D", fid, "mustard", "pest_disease", "2026-12-30T09:00:00+05:30")]
    sched = FrequencyScheduler(FrequencyMonitor(busy))
    r = sched.rank([h], as_of="2026-12-31T07:00:00+05:30")[0]
    assert r.signals["frequency"]["topic"] == "mustard"    # picked the farmer's busy topic
    assert r.signals["frequency"]["is_peak"] is True


def test_rank_handoff_for_farmer_with_no_history_is_safe():
    h = _clear_handoff(crop=None)
    sched = FrequencyScheduler(FrequencyMonitor([]))         # no history at all
    r = sched.rank([h], as_of="2026-12-31T07:00:00+05:30")[0]
    assert r.signals["frequency"]["is_peak"] is False
    assert r.signals["frequency_component"] == 0.0
    # score is just the existing priority base (no frequency/season/climate boost needed to be present)
    assert r.score >= frequency_config()["ranking"]["priority_base"]["normal"] - 1e-9


# ===================================================== scheduler: cap merge returns host
def test_filter_eligible_returns_cap_merge_host():
    """When the cap merges a second survey into an open one, filter_eligible yields the merge
    HOST (not the raw second hand-off), so the cap stays authoritative."""
    led = CapLedger()
    h1 = _clear_handoff()
    led.admit(h1)                                           # first survey takes the slot
    h2 = copy.deepcopy(h1)
    h2["handoff_id"] = "H-MERGE"
    h2["survey"]["source_insight_ids"] = ["I-NEW"]
    sched = FrequencyScheduler(FrequencyMonitor([]))
    elig = sched.filter_eligible([h2], relevance_threshold=0.5, cap=led)
    assert len(elig) == 1
    host = elig[0]
    # the host is the first survey (merge target), and it carries BOTH insight id sets
    assert host["handoff_id"] == h1["handoff_id"]
    assert "I-NEW" in host["survey"]["source_insight_ids"]


def test_filter_eligible_passes_clean_handoff_through_unchanged():
    h = _clear_handoff()
    sched = FrequencyScheduler(FrequencyMonitor([]))
    elig = sched.filter_eligible([h], relevance_threshold=0.5)   # no cap, clean survey
    assert elig == [h]
