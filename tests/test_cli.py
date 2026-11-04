"""P1: CLI behaviour: validate, --limit, --clean, run_summary.json, junk_report.csv (items 1, 2, 7, 9, 10)."""
import csv
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mel import pipeline
from mel.config import PACK, ROOT
from mel.data import load_insights

FULL_DATA = PACK / "data"
has_pack = (FULL_DATA / "insights.jsonl").exists()


def mel(*args, out: Path, data: Path | None = None):
    env = {**os.environ, "MEL_OUT_DIR": str(out)}
    if data:
        env["MEL_DATA_DIR"] = str(data)
    return subprocess.run([sys.executable, "-m", "mel.cli", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8")


# --- validate (1) -----------------------------------------------------------------------

def test_validate_fails_on_missing_folder(tmp_path):
    r = mel("validate", out=tmp_path / "nope")
    assert r.returncode != 0
    assert "Traceback" not in r.stderr


def test_validate_fails_on_empty_folder_unless_allowed(tmp_path):
    r = mel("validate", out=tmp_path)
    assert r.returncode != 0 and "files checked: 0" in r.stdout
    ok = mel("validate", "--allow-empty", out=tmp_path)
    assert ok.returncode == 0 and "files checked: 0" in ok.stdout


def test_validate_reports_count_and_bad_json_by_name(tmp_path):
    assert mel("run", "--limit", "5", "--simulate", out=tmp_path).returncode == 0
    r = mel("validate", out=tmp_path)
    assert r.returncode == 0
    checked = int(r.stdout.split("files checked:")[1].split()[0])
    assert checked > 0
    (tmp_path / "surveys" / "broken.hi-IN.json").write_text("{not json", encoding="utf-8")
    bad = mel("validate", out=tmp_path)
    assert bad.returncode != 0
    assert "broken.hi-IN.json" in bad.stdout and "Traceback" not in bad.stderr


# --- --limit (2) ------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", ["run", "junk"])
def test_negative_limit_is_an_error_without_traceback(tmp_path, cmd):
    r = mel(cmd, "--limit", "-1", out=tmp_path)
    assert r.returncode != 0
    assert "Traceback" not in r.stderr and "--limit" in r.stderr
    assert not (tmp_path / "run_summary.json").exists()


def test_limit_zero_processes_nothing(tmp_path):
    r = mel("run", "--limit", "0", out=tmp_path)
    assert r.returncode == 0
    summary = json.loads((tmp_path / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["rows_processed"] == 0 and sum(summary["by_rule"].values()) == 0
    assert not list(tmp_path.glob("*/*.json"))


# --- --clean (7) ------------------------------------------------------------------------

def test_clean_empties_only_the_four_output_folders(tmp_path):
    for d in ("surveys", "handoffs", "no_survey", "responses"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "stale.json").write_text("{}", encoding="utf-8")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "keep.txt").write_text("keep", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("keep", encoding="utf-8")
    assert mel("run", "--limit", "0", "--clean", out=tmp_path).returncode == 0
    for d in ("surveys", "handoffs", "no_survey", "responses"):
        assert list((tmp_path / d).iterdir()) == []
    assert (tmp_path / "other" / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert (tmp_path / "notes.txt").exists()


def test_without_clean_stale_files_stay(tmp_path):
    (tmp_path / "surveys").mkdir()
    (tmp_path / "surveys" / "stale.json").write_text("{}", encoding="utf-8")
    assert mel("run", "--limit", "0", out=tmp_path).returncode == 0
    assert (tmp_path / "surveys" / "stale.json").exists()


# --- run_pipeline (8) -------------------------------------------------------------------

def test_run_pipeline_signature_and_result():
    params = list(inspect.signature(pipeline.run_pipeline).parameters)
    assert params[:3] == ["insights", "limit", "farmer"]
    assert pipeline.run_pipeline([]) is not None
    import mel.cli
    assert not hasattr(mel.cli, "_select")


def test_run_pipeline_filters_and_limits():
    rows = load_insights()
    farmer = rows[0]["farmer_id"]
    res = pipeline.run_pipeline(rows, farmer=farmer)
    assert res.rows_processed == sum(r["farmer_id"] == farmer for r in rows)
    assert pipeline.run_pipeline(rows, limit=3).rows_processed == 3
    assert pipeline.run_pipeline(rows, limit=0).rows_processed == 0
    with pytest.raises(ValueError):
        pipeline.run_pipeline(rows, limit=-1)


def test_cmd_run_calls_run_pipeline(monkeypatch, tmp_path):
    import argparse
    import mel.cli as cli
    seen = {}
    real = cli.run_pipeline

    def spy(insights, limit=None, farmer=None):
        seen.update(limit=limit, farmer=farmer)
        return real(insights, limit=limit, farmer=farmer)

    monkeypatch.setattr(cli, "run_pipeline", spy)
    monkeypatch.setattr(cli, "OUT", tmp_path)
    cli.cmd_run(argparse.Namespace(insights=None, simulate=False, limit=2, farmer=None, clean=False))
    assert seen == {"limit": 2, "farmer": None}


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_two_runs_write_identical_output(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert mel("run", "--simulate", out=a).returncode == 0
    assert mel("run", "--simulate", out=b).returncode == 0
    assert _tree(a) == _tree(b) and len(_tree(a)) > 10


# --- run_summary.json (9) ---------------------------------------------------------------

def _summary(out: Path) -> dict:
    return json.loads((out / "run_summary.json").read_text(encoding="utf-8"))


def test_run_summary_shape_and_consistency(tmp_path):
    r = mel("run", "--simulate", out=tmp_path)
    assert r.returncode == 0
    s = _summary(tmp_path)
    assert list(s["by_rule"]) == [f"R{n}" for n in range(1, 9)]
    assert set(s["by_language"]) == {"hi-IN", "en-IN"}
    assert set(s["by_priority"]) == {"high", "normal", "low"}
    assert s["rows_processed"] == sum(s["by_rule"].values()) == len(load_insights())
    assert sum(s["by_first_channel"].values()) == sum(s["by_priority"].values()) == s["surveys"]
    assert s["input_path"].endswith("insights.jsonl")
    assert all(f"R{n}" in r.stdout for n in range(1, 9))   # the printed summary names the rule ids
    assert len(list((tmp_path / "handoffs").glob("*.json"))) == s["surveys"]


def test_run_summary_respects_limit_and_farmer(tmp_path):
    rows = load_insights()
    assert mel("run", "--limit", "7", out=tmp_path).returncode == 0
    s = _summary(tmp_path)
    assert s["rows_processed"] == 7 and sum(s["by_rule"].values()) == 7
    farmer = rows[0]["farmer_id"]
    expect = sum(r["farmer_id"] == farmer for r in rows)
    out2 = tmp_path / "f"
    assert mel("run", "--farmer", farmer, out=out2).returncode == 0
    s2 = _summary(out2)
    assert s2["rows_processed"] == expect == sum(s2["by_rule"].values())


# --- junk_report.csv (10) ---------------------------------------------------------------

def _junk(out: Path) -> list[dict]:
    with open(out / "junk_report.csv", encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        assert rd.fieldnames == ["insight_id", "category", "detail"]
        return list(rd)


def test_junk_report_matches_junk_rows_and_never_changes_decisions(tmp_path):
    from mel.data import why_junk
    assert mel("run", out=tmp_path).returncode == 0
    rows = _junk(tmp_path)
    expect = [i["insight_id"] for i in load_insights() if why_junk(i)]
    assert [r["insight_id"] for r in rows] == expect and expect
    assert _summary(tmp_path)["by_rule"]["R1"] >= len(rows)
    for r in rows:
        if r["category"] != "schema_failure":
            assert "schema" not in (r["category"] + r["detail"]).lower()


def test_junk_report_respects_limit(tmp_path):
    assert mel("run", "--limit", "0", out=tmp_path).returncode == 0
    assert _junk(tmp_path) == []


@pytest.mark.skipif(not has_pack, reason="full participant pack not present")
def test_junk_report_categories_on_full_pack(tmp_path):
    assert mel("run", out=tmp_path, data=FULL_DATA).returncode == 0
    rows = _junk(tmp_path)
    cats = {r["category"] for r in rows}
    assert {"schema_failure", "greeting", "thanks", "about_the_app", "unclear_voice", "acknowledgement"} <= cats
    assert len(rows) == 723
    for r in rows:
        if r["category"] == "schema_failure":
            for f in ("query_summary", "advice_summary", "resolution_type"):
                assert f in r["detail"]
        else:
            assert "schema" not in (r["category"] + r["detail"]).lower()
    s = _summary(tmp_path)
    assert s["by_rule"] == {"R1": 723, "R2": 25, "R3": 1287, "R4": 875, "R5": 1312, "R6": 111, "R7": 115, "R8": 2551}
