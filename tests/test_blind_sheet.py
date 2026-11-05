"""The blind Bedrock-vs-template comparison: scripts/blind_sheet.py scores filled sheets against the key, and the
Dashboard panel (app/dashboard.py _blind) shows "scoring in progress" until people's scores are in, then the result."""
import csv
import importlib.util
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("blind_sheet", ROOT / "scripts" / "blind_sheet.py")
blind_sheet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blind_sheet)

KEY = {"pairs": {"1": {"A": "bedrock", "B": "template", "chars_A": 120, "chars_B": 60},
                 "2": {"A": "template", "B": "bedrock", "chars_A": 70, "chars_B": 140},
                 "3": {"A": "bedrock", "B": "template", "chars_A": 130, "chars_B": 65}}}


def _sheet(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, blind_sheet.FIELDS)
        w.writeheader()
        for pair, a, b, better in rows:
            w.writerow({"pair": pair, "advice_type": "direct_action", "score_A": a, "score_B": b, "better": better, "scorer": "ana"})


def _point_at(monkeypatch, tmp_path):
    monkeypatch.setattr(blind_sheet, "RESULTS", tmp_path)
    monkeypatch.setattr(blind_sheet, "KEY", tmp_path / "blind_sheet_key.json")
    (tmp_path / "blind_sheet_key.json").write_text(json.dumps(KEY), encoding="utf-8")


def test_score_unblinds_with_the_key_and_checks_length(monkeypatch, tmp_path):
    _point_at(monkeypatch, tmp_path)
    _sheet(tmp_path / "blind_sheet_ana.csv", [(1, 5, 3, "A"), (2, 4, 4, "same"), (3, 2, 4, "B"), (9, 5, 5, "A")])  # pair 9 is not in the key
    out = blind_sheet.score([str(tmp_path / "blind_sheet_ana.csv")])
    assert out["rows_scored"] == 3 and out["scorers"] == ["ana"]
    assert out["preferred"] == {"bedrock": 1, "same": 1, "template": 1}
    assert out["mean_score"] == {"bedrock": 3.67, "template": 3.67}           # (5+4+2)/3 and (3+4+4)/3
    assert out["longer_survey"] == {"longer won": 1, "shorter won": 1}        # pair 1: Bedrock (longer) won; pair 3: template (shorter) won
    assert out["verdict"] == "not enough answers yet" and out["avg_survey_chars"] == {"bedrock": 130.0, "template": 65.0}
    assert (tmp_path / "blind_comparison.md").exists() and json.loads((tmp_path / "blind_comparison.json").read_text())["rows_scored"] == 3


def test_sign_test():
    assert blind_sheet.sign_test(0, 0) == 1.0
    assert blind_sheet.sign_test(10, 0) < 0.01 and blind_sheet.sign_test(6, 4) > 0.5


def _panel():
    from app import dashboard
    dashboard._blind()


def _screen(monkeypatch, tmp_path):
    from app import dashboard
    monkeypatch.setattr(dashboard, "BLIND", tmp_path)
    at = AppTest.from_function(_panel, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return " ".join(m.value for m in at.markdown) + " ".join(m.value for m in at.caption)


def test_dashboard_panel_waits_then_shows_the_result(monkeypatch, tmp_path):
    assert _screen(monkeypatch, tmp_path) == ""                                     # no sheet: no panel
    (tmp_path / "blind_sheet.csv").write_text("pair\n1\n2\n", encoding="utf-8")
    assert "Scoring in progress: 2 pairs" in _screen(monkeypatch, tmp_path)
    (tmp_path / "blind_comparison.json").write_text(json.dumps({
        "verdict": "no clear winner", "scorers": ["ana", "raj"], "rows_scored": 40, "mean_score": {"bedrock": 4.1, "template": 3.9},
        "preferred": {"bedrock": 22, "template": 15, "same": 3}, "p_value_sign_test": 0.32,
        "longer_survey": {"longer won": 21, "shorter won": 16}, "avg_survey_chars": {"bedrock": 136.1, "template": 65.2}}))
    screen = _screen(monkeypatch, tmp_path)
    assert "no clear winner" in screen and "Bedrock 22" in screen and "templates 15" in screen and "longer survey won 21 of 37" in screen
