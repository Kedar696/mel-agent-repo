"""P3: late-answer handling (req 2), reference-grid tool (req 6), quality-gate counts (req 7).

The `late` schema field itself is a P1 change (parity-checked schema + a note to Digital
Green, see docs/h4_schema_change_request_late.md). On the P3 side the flag is computed and
emitted only when MEL_RESPONSE_LATE_FIELD=1, so default records stay schema-valid and the
183 reference records still match. These tests exercise the P3 computation and the boundary,
and confirm default records carry no `late` field.
"""
from datetime import timedelta


from mel.data import load_scenario, errors
from mel.simulator import simulate_sheet
from mel.timing import parse_ist, fmt_ist, expires_at
import importlib
sim = importlib.import_module("mel.simulator.simulate")   # the module, not the re-exported function


def _survey():
    return load_scenario("1-mustard-aphid-spray")["surveys"]["hi-IN"]


# ===================================================== late boundary (req 2)
def test_answer_exactly_at_expiry_is_not_late(monkeypatch):
    monkeypatch.setattr(sim, "_EMIT_LATE", True)       # as if P1 had added the schema field
    s = _survey()
    at_expiry = expires_at(s["send_window"])           # exactly the expiry instant
    r = simulate_sheet(s, "web", ["q1"], closed=True, submit_at=at_expiry)
    assert "late" not in r                             # at expiry is NOT late (strict >): no field


def test_answer_after_expiry_is_late(monkeypatch):
    monkeypatch.setattr(sim, "_EMIT_LATE", True)
    s = _survey()
    after = fmt_ist(parse_ist(expires_at(s["send_window"])) + timedelta(seconds=1))
    r = simulate_sheet(s, "web", ["q1"], closed=True, submit_at=after)
    assert r.get("late") is True                       # one second past expiry is late
    assert r["answers"] == {"q1": "yes"}               # the answer is still retained


def test_late_answer_default_has_no_late_field_and_is_schema_valid():
    """With the flag OFF (default), a post-expiry answer keeps the answer, carries no `late`
    field, and validates against today's schema -- so the 183 reference records still match."""
    s = _survey()
    after = fmt_ist(parse_ist(expires_at(s["send_window"])) + timedelta(days=1))
    r = simulate_sheet(s, "web", ["q1"], closed=True, submit_at=after)
    assert "late" not in r
    assert not errors("response", r)
    assert r["answers"] == {"q1": "yes"}               # answer preserved even when late


def test_late_field_when_enabled_is_still_schema_valid_only_if_schema_allows():
    """With the flag on, an on-time sheet answer carries NO late field (normal records never
    get `late: false`, so they keep matching the reference records), and stays schema-valid
    against today's schema."""
    s = _survey()
    old = sim._EMIT_LATE
    try:
        sim._EMIT_LATE = True
        r = simulate_sheet(s, "web", ["q1", "q2", "q3"])   # finished, on time
        assert "late" not in r
        assert not errors("response", r)
    finally:
        sim._EMIT_LATE = old


# ===================================================== reference-grid tool (req 6)
def test_reference_check_matches_all_183_field_for_field():
    from mel.simulator.reference_check import compare
    report = compare()
    assert report["total"] == 183
    assert report["matched"] == 183
    assert report["mismatches"] == []


def test_reference_check_ignores_no_fields_by_default():
    """The simulator is deterministic, so nothing is ignored -- the report says so, and no
    non-ID field is ever silently skipped."""
    from mel.simulator.reference_check import compare, DEFAULT_IGNORE_FIELDS
    assert DEFAULT_IGNORE_FIELDS == ()
    assert compare()["ignored_fields"] == []


def test_reference_check_reports_a_field_mismatch():
    """If a generated record drifts from the reference, the tool reports it by field name
    rather than hiding it."""
    from mel.simulator import reference_check
    report = reference_check.compare()
    assert report["matched"] == report["total"] == 183 and not report["mismatches"]
    # sanity: the comparator's field-diff helper flags a changed non-ID field
    ref = {"status": "completed", "answered_by": "F-1"}
    got = {"status": "partial", "answered_by": "F-1"}
    diffs = reference_check._field_diffs(ref, got, ())
    assert any(d.startswith("status:") for d in diffs)
    assert not any(d.startswith("answered_by:") for d in diffs)


def test_reference_check_format_report_is_readable():
    from mel.simulator.reference_check import compare, format_report
    text = format_report(compare())
    assert "183" in text and "match" in text


# ===================================================== quality-gate counts (req 7)
def test_broadcaster_tracks_rejected_and_expired_counts():
    from mel.schedule import Broadcaster, SimClock, build_handoff
    import copy
    s = load_scenario("1-mustard-aphid-spray")
    base = build_handoff(s["insight"], s["surveys"]["hi-IN"])
    base["survey"]["self_eval"] = {"schema_valid": True, "relevance_score": 0.8,
                                   "gives_new_advice": False, "asks_personal_info": False}

    # one below-threshold survey -> rejected
    bad = copy.deepcopy(base); bad["handoff_id"] = "H-BAD"
    bad["survey"]["self_eval"]["relevance_score"] = 0.1
    # one expired survey (clock far past its expiry) -> expired
    exp = copy.deepcopy(base); exp["handoff_id"] = "H-EXP"

    clock = SimClock(base["send_window"]["not_before"])
    bc = Broadcaster(clock)
    bc.queue(bad)
    bc.broadcast_due(relevance_threshold=0.5)          # drops bad as rejected
    assert bc.counts()["rejected"] == 1

    clock.set(fmt_ist(parse_ist(exp["expires_at"]) + timedelta(days=1)))
    bc.queue(exp)
    bc.broadcast_due(relevance_threshold=0.5)          # drops exp as expired
    assert bc.counts()["expired"] == 1


def test_scheduler_exposes_p5_metrics_from_actual_decisions():
    from mel.schedule import SeasonScheduler, build_handoff
    s = load_scenario("1-mustard-aphid-spray")
    h = build_handoff(s["insight"], s["surveys"]["hi-IN"])
    h["survey"]["self_eval"] = {"schema_valid": True, "relevance_score": 0.8,
                                "gives_new_advice": False, "asks_personal_info": False}
    sched = SeasonScheduler(h["send_window"]["not_before"], relevance_threshold=0.5)
    sched.admit_all([h])
    sched.run_due()
    m = sched.metrics()
    assert m["admitted"].get("sent") == 1             # from the actual admit decision
    assert m["steps"].get("sent", 0) >= 1             # from the actual step
