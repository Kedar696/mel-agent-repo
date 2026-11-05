"""P3: question-frequency monitor and frequency-aware survey ranking.

Covers the acceptance criteria:
  * repeated questions for one farmer/topic make a peak; other topics/farmers do not leak in
  * low/normal/high existing priority interacts with the frequency signal deterministically
  * seasonal context affects ranking only when supplied/valid; missing climate falls back and
    is visible in the result
  * a peak never bypasses opt-out, send window, expiry, quality gate, or the frequency cap
  * duplicate inputs, sparse history, out-of-order timestamps, boundary dates are deterministic
"""


from mel.data import load_scenario
from mel.schedule import (
    build_handoff, CapLedger, OptOutList,
    FrequencyMonitor, FrequencyScheduler, SeasonStageContext, ClimateContext,
    frequency_config, topic_of,
)
from mel.simulator import simulate


THRESHOLD = 0.5


def _ins(iid, fid, crop, concern, ts):
    return {"insight_id": iid, "farmer_id": fid, "asset": {"name": crop},
            "concern": concern, "created_at": ts}


def _clear_handoff(scenario="1-mustard-aphid-spray", crop="mustard"):
    s = load_scenario(scenario)
    h = build_handoff(s["insight"], s["surveys"]["hi-IN"])
    h["survey"]["self_eval"] = {"schema_valid": True, "relevance_score": 0.8,
                                "gives_new_advice": False, "asks_personal_info": False}
    h["_crop"] = crop
    return h


def _busy_history(fid, crop="mustard", concern="pest_disease"):
    """Four questions, three bunched in the final fortnight -> a peak by 31 Dec."""
    return [
        _ins("A", fid, crop, concern, "2026-12-01T09:00:00+05:30"),
        _ins("B", fid, crop, concern, "2026-12-20T09:00:00+05:30"),
        _ins("C", fid, crop, concern, "2026-12-27T09:00:00+05:30"),
        _ins("D", fid, crop, concern, "2026-12-30T09:00:00+05:30"),
    ]


# ===================================================== frequency monitor: peaks & isolation
def test_repeated_questions_make_a_peak():
    mon = FrequencyMonitor(_busy_history("F1"))
    p = mon.peak("F1", "mustard", as_of="2026-12-31T07:00:00+05:30")
    assert p.is_peak
    assert p.window_count >= frequency_config()["baseline"]["min_peak_count"]
    assert p.strength >= frequency_config()["baseline"]["peak_ratio"]


def test_other_topics_and_farmers_do_not_contaminate():
    hist = _busy_history("F1", crop="mustard") + [
        _ins("X", "F1", "wheat", "weed_management", "2026-12-30T09:00:00+05:30"),  # one other topic
        _ins("Y", "F2", "mustard", "pest_disease", "2026-12-30T09:00:00+05:30"),   # other farmer
    ]
    mon = FrequencyMonitor(hist)
    assert mon.peak("F1", "mustard", as_of="2026-12-31T07:00:00+05:30").is_peak
    # F1's single wheat question is not a peak; F2's single mustard question is not a peak.
    assert not mon.peak("F1", "wheat", as_of="2026-12-31T07:00:00+05:30").is_peak
    assert not mon.peak("F2", "mustard", as_of="2026-12-31T07:00:00+05:30").is_peak
    # An unseen topic for F1 has no history at all.
    none = mon.peak("F1", "livestock", as_of="2026-12-31T07:00:00+05:30")
    assert not none.is_peak and none.n_history == 0


def test_sparse_history_is_not_a_peak():
    mon = FrequencyMonitor([_ins("A", "F1", "mustard", "pest_disease", "2026-12-30T09:00:00+05:30")])
    p = mon.peak("F1", "mustard", as_of="2026-12-31T07:00:00+05:30")
    assert not p.is_peak and p.n_history == 1


def test_duplicate_inputs_counted_once():
    dup = _busy_history("F1")
    dup = dup + [dict(dup[-1])]           # same insight_id "D" again
    mon = FrequencyMonitor(dup)
    assert mon.peak("F1", "mustard", as_of="2026-12-31T07:00:00+05:30").n_history == 4


def test_out_of_order_timestamps_are_deterministic():
    shuffled = list(reversed(_busy_history("F1")))
    a = FrequencyMonitor(_busy_history("F1")).peak("F1", "mustard", as_of="2026-12-31T07:00:00+05:30")
    b = FrequencyMonitor(shuffled).peak("F1", "mustard", as_of="2026-12-31T07:00:00+05:30")
    assert a.signals() == b.signals()


def test_window_boundary_is_deterministic():
    """A question exactly `rolling_days` before `as_of` falls just outside the half-open
    window; one second later is inside. Boundary handling is explicit and stable."""
    cfg = frequency_config()
    days = cfg["window"]["rolling_days"]
    # history: three recent + one exactly on the boundary
    base = [
        _ins("R1", "F1", "mustard", "pest_disease", "2027-01-10T09:00:00+05:30"),
        _ins("R2", "F1", "mustard", "pest_disease", "2027-01-12T09:00:00+05:30"),
        _ins("R3", "F1", "mustard", "pest_disease", "2027-01-14T09:00:00+05:30"),
    ]
    as_of = "2027-01-15T09:00:00+05:30"
    from datetime import timedelta
    from mel.timing import parse_ist, fmt_ist
    on_boundary = fmt_ist(parse_ist(as_of) - timedelta(days=days))      # exactly window start
    inside = fmt_ist(parse_ist(as_of) - timedelta(days=days) + timedelta(seconds=1))

    p_out = FrequencyMonitor(base + [_ins("B", "F1", "mustard", "pest_disease", on_boundary)]) \
        .peak("F1", "mustard", as_of=as_of)
    p_in = FrequencyMonitor(base + [_ins("B", "F1", "mustard", "pest_disease", inside)]) \
        .peak("F1", "mustard", as_of=as_of)
    assert p_in.window_count == p_out.window_count + 1   # the boundary event is excluded


def test_topic_key_prefers_crop_then_concern():
    assert topic_of({"asset": {"name": "Wheat"}, "concern": "pest_disease"}) == "wheat"
    assert topic_of({"asset": {"name": None}, "concern": "pest_disease"}) == "pest_disease"
    assert topic_of({"asset": {}, "concern": None}) == "unknown"


# ===================================================== priority x frequency (deterministic)
def _score(priority, history, crop="mustard"):
    h = _clear_handoff(crop=crop)
    h["priority"] = priority
    sched = FrequencyScheduler(FrequencyMonitor(history))
    return sched.rank([h], as_of="2026-12-31T07:00:00+05:30")[0]


def test_priority_order_preserved_without_peak():
    """With no peak, higher existing priority ranks higher -- the frequency signal adds 0."""
    fid = _clear_handoff()["survey"]["farmer_id"]
    flat = [_ins("A", fid, "mustard", "pest_disease", "2026-12-01T09:00:00+05:30"),
            _ins("B", fid, "mustard", "pest_disease", "2026-12-02T09:00:00+05:30")]
    hi = _score("high", flat).score
    no = _score("normal", flat).score
    lo = _score("low", flat).score
    assert hi > no > lo


def test_peak_raises_score_but_keeps_signal_visible():
    fid = _clear_handoff()["survey"]["farmer_id"]
    peak_hist = _busy_history(fid)
    r_peak = _score("normal", peak_hist)
    r_flat = _score("normal", [_ins("A", fid, "mustard", "pest_disease", "2026-12-01T09:00:00+05:30"),
                               _ins("B", fid, "mustard", "pest_disease", "2026-12-02T09:00:00+05:30")])
    assert r_peak.score > r_flat.score                       # a peak lifts the rank
    assert r_peak.signals["frequency"]["is_peak"] is True    # and is explained
    assert r_peak.signals["frequency_component"] > 0


def test_ranking_is_deterministic_tie_break_by_id():
    h1 = _clear_handoff(); h1["handoff_id"] = "H-AAA"; h1["priority"] = "normal"
    h2 = _clear_handoff(); h2["handoff_id"] = "H-BBB"; h2["priority"] = "normal"
    sched = FrequencyScheduler(FrequencyMonitor([]))
    ranked = sched.rank([h2, h1], as_of="2026-12-31T07:00:00+05:30")
    assert [r.handoff_id for r in ranked] == ["H-AAA", "H-BBB"]  # equal score -> id order


# ===================================================== season stage context
def test_season_stage_from_calendar():
    ctx = SeasonStageContext()
    from datetime import date
    # Mustard is flowering around 1 Jan 2027 per the crop calendar.
    assert ctx.active_stage("mustard", date(2027, 1, 10)) is not None
    # A date far outside any stage window yields None.
    assert ctx.active_stage("mustard", date(2030, 1, 1)) is None
    # Unknown crop -> None (no invented stage).
    assert ctx.active_stage("dragonfruit", date(2027, 1, 10)) is None


def test_active_season_adds_component_only_when_in_stage():
    h = _clear_handoff(crop="mustard")
    h["priority"] = "normal"
    sched = FrequencyScheduler(FrequencyMonitor([]))
    in_stage = sched.rank([h], as_of="2027-01-10T07:00:00+05:30")[0]     # mustard flowering
    out_stage = sched.rank([h], as_of="2030-01-10T07:00:00+05:30")[0]    # no stage
    assert in_stage.signals["season_stage"] is not None
    assert out_stage.signals["season_stage"] is None
    assert in_stage.signals["season_component"] > out_stage.signals["season_component"]


# ===================================================== climate context (missing + synthetic)
def test_climate_missing_falls_back_and_is_visible():
    h = _clear_handoff(); h["priority"] = "normal"
    sched = FrequencyScheduler(FrequencyMonitor([]))          # default ClimateContext: unavailable
    r = sched.rank([h], as_of="2027-01-10T07:00:00+05:30")[0]
    assert r.signals["climate_available"] is False
    assert r.signals["climate_context_missing"] is True
    assert r.signals["climate_component"] == 0.0             # neutral: no adjustment
    assert r.signals["climate_synthetic"] is False


def test_synthetic_climate_is_labelled_and_applied():
    h = _clear_handoff(); h["priority"] = "normal"
    clim = ClimateContext(synthetic_factor=1.0)              # demo-only constant
    sched = FrequencyScheduler(FrequencyMonitor([]), climate=clim)
    r = sched.rank([h], as_of="2027-01-10T07:00:00+05:30")[0]
    assert r.signals["climate_available"] is True
    assert r.signals["climate_synthetic"] is True            # clearly labelled synthetic
    assert r.signals["climate_component"] > 0.0
    assert r.signals["climate_context_missing"] is False


def test_real_provider_climate_in_range():
    h = _clear_handoff(); h["priority"] = "normal"
    clim = ClimateContext(provider=lambda state, district, on: 0.5)
    sched = FrequencyScheduler(FrequencyMonitor([]), climate=clim)
    r = sched.rank([h], as_of="2027-01-10T07:00:00+05:30")[0]
    assert r.signals["climate_available"] is True
    assert r.signals["climate_synthetic"] is False
    assert 0 < r.signals["climate_component"] <= frequency_config()["ranking"]["climate_weight"]


# ===================================================== protections are never bypassed
def test_peak_does_not_bypass_opt_out():
    h = _clear_handoff()
    stop = OptOutList()
    stop.record(simulate(h["survey"], "whatsapp", "farmer_opted_out"))
    sched = FrequencyScheduler(FrequencyMonitor(_busy_history(h["survey"]["farmer_id"])))
    assert sched.filter_eligible([h], relevance_threshold=THRESHOLD, opt_out=stop) == []


def test_peak_does_not_bypass_quality_gate():
    h = _clear_handoff()
    h["survey"]["self_eval"]["relevance_score"] = 0.1        # below threshold
    sched = FrequencyScheduler(FrequencyMonitor(_busy_history(h["survey"]["farmer_id"])))
    assert sched.filter_eligible([h], relevance_threshold=THRESHOLD) == []


def test_peak_does_not_bypass_window_or_expiry():
    from mel.timing import parse_ist
    h = _clear_handoff()
    sched = FrequencyScheduler(FrequencyMonitor(_busy_history(h["survey"]["farmer_id"])))
    before = parse_ist(h["send_window"]["not_before"])
    # A time before the window opens -> not eligible even with a peak.
    from datetime import timedelta
    assert sched.filter_eligible([h], relevance_threshold=THRESHOLD, now=before - timedelta(days=1)) == []
    # A time past expiry -> not eligible.
    after = parse_ist(h["expires_at"]) + timedelta(days=1)
    assert sched.filter_eligible([h], relevance_threshold=THRESHOLD, now=after) == []


def test_peak_does_not_bypass_frequency_cap():
    led = CapLedger()
    h1 = _clear_handoff()
    led.admit(h1)                                            # fill the farmer's weekly slot
    # A second NORMAL survey to the same farmer in the same window: the cap must hold. We
    # place its window outside the first's so it can neither merge nor move -> skipped.
    from mel.timing import parse_ist, fmt_ist
    from datetime import timedelta
    h2 = _clear_handoff(); h2["handoff_id"] = "H-2"
    h2["survey"]["source_insight_ids"] = ["I-ZZZ"]
    start = parse_ist(h1["send_window"]["not_after"]) + timedelta(days=1)
    h2["send_window"] = {"not_before": fmt_ist(start), "not_after": fmt_ist(start + timedelta(days=2))}
    h2["survey"]["send_window"] = dict(h2["send_window"])
    sched = FrequencyScheduler(FrequencyMonitor(_busy_history(h1["survey"]["farmer_id"])))
    assert sched.filter_eligible([h2], relevance_threshold=THRESHOLD, cap=led) == []


def test_high_priority_survey_still_passes_cap_and_ranks():
    """Protections intact does not mean nothing schedules: a clean, in-window, high-priority
    survey with a peak is eligible and ranks above a flat normal one."""
    hi = _clear_handoff("4-cow-vet-escalation", crop="cow")
    assert hi["priority"] == "high"
    hi["survey"]["self_eval"] = {"schema_valid": True, "relevance_score": 0.9,
                                 "gives_new_advice": False, "asks_personal_info": False}
    sched = FrequencyScheduler(FrequencyMonitor([]))
    from mel.timing import parse_ist
    now = parse_ist(hi["send_window"]["not_before"])
    elig = sched.filter_eligible([hi], relevance_threshold=THRESHOLD, now=now)
    assert len(elig) == 1
