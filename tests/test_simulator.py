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
