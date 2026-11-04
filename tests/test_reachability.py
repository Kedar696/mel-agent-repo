"""P3: per-farmer channel reachability from farmers.csv (requirement 4).

Covers: preferred channel always reachable, other channels reachable by default (the CSV
carries no signal to exclude them), explicit override, unknown-farmer fallback, and that
channel_order is preserved for reachable channels while unreachable ones are skipped.
"""
import pytest

from mel.config import CHANNELS
from mel.data import load_farmers, load_scenario
from mel.channels import FarmerReachability
from mel.schedule import build_handoff, SeasonScheduler


def _real_farmers():
    return load_farmers()


def test_preferred_channel_is_always_reachable():
    farmers = _real_farmers()
    reach = FarmerReachability(farmers)
    fid, row = next(iter(farmers.items()))
    assert reach.reachable(fid, row["preferred_channel"]) is True


def test_other_channels_reachable_by_default():
    """The CSV has only preferred_channel; we do NOT read that as 'others unreachable'."""
    farmers = _real_farmers()
    reach = FarmerReachability(farmers)
    fid = next(iter(farmers))
    for ch in CHANNELS:
        assert reach.reachable(fid, ch) is True


def test_explicit_override_marks_a_channel_unreachable():
    farmers = _real_farmers()
    fid, row = next(iter(farmers.items()))
    # pick a channel that is NOT the preferred one (preferred stays reachable regardless)
    other = next(c for c in CHANNELS if c != row["preferred_channel"])
    reach = FarmerReachability(farmers, unreachable_by_farmer={fid: {other}})
    assert reach.reachable(fid, other) is False
    assert reach.reachable(fid, row["preferred_channel"]) is True   # preferred still reachable


def test_unknown_farmer_falls_back_to_all_reachable():
    reach = FarmerReachability(_real_farmers())
    assert reach.is_known("F-DOES-NOT-EXIST") is False
    for ch in CHANNELS:
        assert reach.reachable("F-DOES-NOT-EXIST", ch) is True


def test_empty_farmers_treats_everyone_as_unknown():
    reach = FarmerReachability({})
    assert reach.is_known("F-000008") is False
    assert reach.reachable("F-000008", "voice") is True


def test_reachable_channels_preserves_order_and_drops_unreachable():
    farmers = _real_farmers()
    fid, row = next(iter(farmers.items()))
    order = ["app", "web", "whatsapp", "telegram", "voice"]
    drop = next(c for c in order if c != row["preferred_channel"])
    reach = FarmerReachability(farmers, unreachable_by_farmer={fid: {drop}})
    kept = reach.reachable_channels(fid, order)
    assert kept == [c for c in order if c != drop]          # order preserved, only drop removed


def test_reachable_channels_accepts_handoff_channel_order_dicts():
    farmers = _real_farmers()
    reach = FarmerReachability(farmers)
    s = load_scenario("4-cow-vet-escalation")               # channel_order has voice
    h = build_handoff(s["insight"], s["surveys"]["hi-IN"])
    kept = reach.reachable_channels(h["survey"]["farmer_id"], h["channel_order"])
    assert kept == [c["channel"] for c in h["channel_order"]]  # all reachable by default


# ===================================================== scheduler honours reachability
def test_scheduler_skips_unreachable_channel_but_keeps_order():
    """With reachability wired in, SeasonScheduler.step() skips a channel the farmer cannot
    be reached on and uses the next reachable channel in channel_order."""
    s = load_scenario("4-cow-vet-escalation")               # order: voice, whatsapp
    h = build_handoff(s["insight"], s["surveys"]["hi-IN"])
    h["survey"]["self_eval"] = {"schema_valid": True, "relevance_score": 0.9,
                                "gives_new_advice": False, "asks_personal_info": False}
    fid = h["survey"]["farmer_id"]
    order = [c["channel"] for c in h["channel_order"]]
    first = order[0]
    # make the first channel unreachable; the step should use the next reachable one
    reach = FarmerReachability(load_farmers(), unreachable_by_farmer={fid: {first}})
    sched = SeasonScheduler(h["send_window"]["not_before"], relevance_threshold=0.5,
                            reachability=reach)
    sched.admit_all([h])
    r = sched.step()
    assert r.kind == "sent"
    assert r.channel != first and r.channel in order        # skipped first, used a later one
