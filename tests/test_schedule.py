"""P3: hand-off fields match worked scenarios."""
from mel.data import load_scenario, list_scenarios, errors
from mel.schedule import build_handoff


def test_handoffs_match_scenarios():
    for n in list_scenarios():
        s = load_scenario(n)
        if not s["handoff"]:
            continue
        h = build_handoff(s["insight"], s["surveys"]["hi-IN"])
        assert not errors("schedule_handoff", h)
        for k in ("channel_order", "priority", "expires_at", "frequency_cap", "send_hours"):
            assert h[k] == s["handoff"][k], (n, k)


def test_opt_out_blocks_future_surveys():
    from mel.schedule import OptOutList
    from mel.simulator import simulate
    s = load_scenario("1-mustard-aphid-spray")
    h = build_handoff(s["insight"], s["surveys"]["hi-IN"])
    stop = OptOutList()
    assert not stop.blocks(h)
    stop.record(simulate(h["survey"], "whatsapp", "farmer_opted_out"))
    assert stop.blocks(h) and stop.blocks(h["survey"]["farmer_id"])


# --- P3 additions: cap policy (admit), opt-out gate, high-priority exemption ---
import copy

from mel.schedule import CapLedger


def _handoff(scenario="1-mustard-aphid-spray"):
    s = load_scenario(scenario)
    return build_handoff(s["insight"], s["surveys"]["hi-IN"])


def test_admit_first_survey_is_sent():
    led = CapLedger()
    a = led.admit(_handoff())
    assert a.decision == "sent"


def test_admit_opted_out_blocks():
    from mel.schedule import OptOutList
    from mel.simulator import simulate
    h = _handoff()
    stop = OptOutList()
    stop.record(simulate(h["survey"], "whatsapp", "farmer_opted_out"))
    a = CapLedger().admit(h, opt_out=stop)
    assert a.decision == "opted_out"


def test_admit_high_priority_is_exempt_but_counts():
    """A high-priority survey is always sent even when the cap is full, and it still counts
    toward the window for a later normal survey."""
    led = CapLedger()
    hi = _handoff("4-cow-vet-escalation")  # escalate_to_expert -> high priority, exempt
    assert hi["frequency_cap"]["exempt"] is True
    assert led.admit(hi).decision == "sent"
    # A second high-priority survey in the same window is still sent (exempt).
    hi2 = copy.deepcopy(hi); hi2["handoff_id"] = "H-88888"
    assert led.admit(hi2).decision == "sent"


def test_admit_second_normal_in_same_window_merges_and_preserves_insight_ids():
    """Two normal surveys to one farmer in the same 7-day window: the second cannot move
    (its window is fully inside the first's), so it merges, keeping both insight IDs."""
    led = CapLedger()
    h1 = _handoff()
    a1 = led.admit(h1)
    assert a1.decision == "sent"
    h2 = copy.deepcopy(h1)
    h2["handoff_id"] = "H-99999"
    h2["survey"]["source_insight_ids"] = ["I-999999"]
    a2 = led.admit(h2)
    assert a2.decision == "merged"
    assert "I-004512" in a2.handoff["survey"]["source_insight_ids"]
    assert "I-999999" in a2.handoff["survey"]["source_insight_ids"]


def test_admit_moves_when_a_later_date_fits_the_window():
    """A capped survey whose own window extends past the blocking 7-day window is moved to
    the next eligible day rather than skipped."""
    led = CapLedger()
    h1 = _handoff()
    led.admit(h1)
    h2 = copy.deepcopy(h1)
    h2["handoff_id"] = "H-77777"
    # Widen h2's window so a day 7+ out still fits inside it.
    nb = h2["send_window"]["not_before"]
    h2["send_window"]["not_after"] = nb[:10].replace(nb[:4], nb[:4]) + "T19:00:00+05:30"
    # push not_after 20 days after not_before
    from mel.timing import parse_ist, fmt_ist
    from datetime import timedelta
    h2["send_window"]["not_after"] = fmt_ist(parse_ist(nb) + timedelta(days=20))
    h2["survey"]["send_window"] = dict(h2["send_window"])
    a2 = led.admit(h2)
    assert a2.decision == "moved"
    assert parse_ist(a2.handoff["send_window"]["not_before"]) >= parse_ist(nb) + timedelta(days=7)


def test_admit_skips_when_cannot_move_or_merge():
    """A capped survey whose window cannot reach a free day and whose open host does not
    cover its day is skipped."""
    from mel.timing import parse_ist, fmt_ist
    from datetime import timedelta
    led = CapLedger()
    h1 = _handoff()
    led.admit(h1)
    # h2 opens the day after h1's window closed (so h1 no longer covers it -> no merge host)
    # but still inside h1's 7-day block window, with a window only 2 days wide so the next
    # free day (7 days after h1's send) falls past h2's not_after -> cannot move either.
    h2 = copy.deepcopy(h1)
    h2["handoff_id"] = "H-66666"
    start = parse_ist(h1["send_window"]["not_after"]) + timedelta(days=1)
    h2["send_window"] = {"not_before": fmt_ist(start), "not_after": fmt_ist(start + timedelta(days=2))}
    h2["survey"]["send_window"] = dict(h2["send_window"])
    a2 = led.admit(h2)
    assert a2.decision == "skipped"


def test_allow_still_works_as_before():
    led = CapLedger()
    h = _handoff()
    assert led.allow(h) is True   # first within cap
    h2 = copy.deepcopy(h); h2["handoff_id"] = "H-55555"
    assert led.allow(h2) is False  # second non-exempt in same window blocked
