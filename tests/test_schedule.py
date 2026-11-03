"""P4: hand-off fields match worked scenarios."""
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
