"""P3: every channel x case record is schema-valid; reference grid records validate."""

import json

from mel.config import FIXTURES, CHANNELS
from mel.data import load_scenario, errors
from mel.channels import render
from mel.simulator import simulate, cases_for


def test_every_case_is_valid():
    s = load_scenario("3-potato-blight-wait")["surveys"]["hi-IN"]
    for ch in CHANNELS:
        render(s, ch)
        for c in cases_for(ch):
            assert not errors("response", simulate(s, ch, c)), (ch, c)


def test_negative_outcome_flags_follow_up():
    s = load_scenario("4-cow-vet-escalation")["surveys"]["hi-IN"]
    r = simulate(s, "whatsapp", "negative_outcome")
    assert r["needs_follow_up"] and r["follow_up_reasons"]


def test_reference_grid_valid():
    files = list((FIXTURES / "outcomes").rglob("*.json"))
    assert files
    for p in files:
        recs = json.loads(p.read_text(encoding="utf-8"))
        for r in recs if isinstance(recs, list) else [recs]:
            assert not errors("response", r), p.name


def test_render_matches_reference_files():
    """Our channel payloads equal the pack's reference renders, field by field."""
    from mel.data import list_scenarios

    for sc in list_scenarios():
        s = load_scenario(sc)
        for lang, survey in s["surveys"].items():
            for f in (FIXTURES / "scenarios" / sc / "render" / lang).glob("*.json"):
                assert render(survey, f.stem) == json.loads(f.read_text(encoding="utf-8")), (sc, lang, f.stem)


# --- P3 additions: exact reference-grid match, hand-off walk, app/web submit-once ---
from mel.config import outcome_codes
from mel.schedule import build_handoff
from mel.simulator import simulate_handoff, simulate_sheet, PERSONAS


def _anchor_surveys():
    """survey (hi-IN) for each question type, from the grid's anchor scenarios."""
    out = {}
    for qtype, a in outcome_codes()["grid_anchor"].items():
        out[qtype] = load_scenario(a["scenario"])["surveys"]["hi-IN"]
    return out


def test_simulate_matches_all_183_reference_records():
    """Every record simulate() produces equals the pack's reference record, field for field."""
    surveys = _anchor_surveys()
    files = list((FIXTURES / "outcomes").rglob("*.json"))
    assert len(files) == 183, len(files)
    for p in files:
        channel, qtype, case = p.parent.parent.name, p.parent.name, p.stem
        ref = json.loads(p.read_text(encoding="utf-8"))
        got = simulate(surveys[qtype], channel, case)
        assert got == ref, (
            channel,
            qtype,
            case,
            {k: (ref.get(k), got.get(k)) for k in set(ref) | set(got) if ref.get(k) != got.get(k)},
        )


def test_simulate_is_deterministic():
    s = load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]
    assert simulate(s, "app", "completed", seed=0) == simulate(s, "app", "completed", seed=7)


def test_handoff_walk_completes_on_first_channel():
    s = load_scenario("1-mustard-aphid-spray")
    h = build_handoff(s["insight"], s["surveys"]["hi-IN"])
    recs = simulate_handoff(h, "default")
    assert len(recs) == 1 and recs[0]["channel"] == h["channel_order"][0]["channel"]
    assert recs[0]["status"] == "completed"
    assert all(not errors("response", r) for r in recs)


def test_handoff_walk_falls_back_then_completes():
    """A dead push address on app falls back to the next channel, which completes."""
    s = load_scenario("1-mustard-aphid-spray")
    h = build_handoff(s["insight"], s["surveys"]["hi-IN"])
    recs = simulate_handoff(h, "app_push_dead")
    chans = [r["channel"] for r in recs]
    assert chans == [c["channel"] for c in h["channel_order"]]  # app then whatsapp
    assert recs[0]["failure_code"] == "push_token_invalid"
    assert recs[0]["retry_decision"] == "fall_back_to_next_channel"
    assert recs[-1]["status"] == "completed"


def test_handoff_walk_stops_on_opt_out():
    s = load_scenario("1-mustard-aphid-spray")
    h = build_handoff(s["insight"], s["surveys"]["hi-IN"])
    recs = simulate_handoff(h, "opts_out_first")
    assert len(recs) == 1 and recs[0]["failure_code"] == "farmer_opted_out"


def test_handoff_walk_skips_unavailable_channel():
    s = load_scenario("4-cow-vet-escalation")  # high priority -> channel_order includes voice
    h = build_handoff(s["insight"], s["surveys"]["hi-IN"])
    assert any(c["channel"] == "voice" for c in h["channel_order"])
    recs = simulate_handoff(h, "no_voice")
    assert all(r["channel"] != "voice" for r in recs)


def test_handoff_walk_records_are_schema_valid():
    s = load_scenario("4-cow-vet-escalation")
    h = build_handoff(s["insight"], s["surveys"]["hi-IN"])
    for persona in PERSONAS:
        for r in simulate_handoff(h, persona):
            assert not errors("response", r), (persona, r["channel"])


def test_sheet_submitted_once_when_finished():
    s = load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]
    r = simulate_sheet(s, "app", ["q1", "q2", "q3"])
    assert r["status"] == "completed" and r["complete"] and not errors("response", r)
    assert r["sheet_outcome"] == "finished"


def test_sheet_retains_answers_when_closed_early():
    """Closing the sheet early submits once, keeping the answers already given."""
    s = load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]
    r = simulate_sheet(s, "web", ["q1", "q2"], closed=True)
    assert r["status"] == "partial" and r["sheet_outcome"] == "closed_partway"
    assert set(r["answers"]) == {"q1", "q2"}
    assert [it["result"] for it in r["items"]] == ["answered", "answered", "skipped"]
    assert not errors("response", r)


def test_sheet_late_answer_stays_schema_valid_by_default():
    """A submission after expiry keeps the answer and stays valid (no `late` field until
    P1 adds it to the shared schema; see docs/h4_schema_change_request_late.md)."""
    s = load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]
    r = simulate_sheet(s, "web", ["q1"], closed=True, submit_at="2027-02-01T10:00:00+05:30")
    assert "late" not in r  # schema forbids extra fields today
    assert not errors("response", r)
    assert r["answers"] == {"q1": "yes"}  # the given answer is retained
