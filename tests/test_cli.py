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

    def spy(insights, limit=None, farmer=None, **kw):
        seen.update(limit=limit, farmer=farmer)
        return real(insights, limit=limit, farmer=farmer, **kw)

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
    # cmd_run now applies P3's weekly cap + opt-outs + quality gate (run_batch): what goes out is
    # schedule.sent + schedule.moved, not every planned hand-off. `surveys` stays the planned count.
    sched = s["schedule"]
    assert len(list((tmp_path / "handoffs").glob("*.json"))) == sched["sent"] + sched["moved"]


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
    assert s["by_rule"] == {"R1": 723, "R2": 25, "R3": 1287, "R4": 875, "R5": 1312, "R6": 147, "R7": 14, "R8": 2616}


# --- weekly limit, opt-outs, quality gate in `run` (P3 batch wiring) ---------------------
# cmd_run now routes planned hand-offs through mel.schedule.run_batch (docs/cap_policy.md),
# so the files written are what actually goes out (sent + moved; merged ride their host).

def _handoffs(out: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((out / "handoffs").glob("*.json"))]


def test_schedule_block_in_summary(tmp_path):
    assert mel("run", "--simulate", out=tmp_path).returncode == 0
    sched = _summary(tmp_path)["schedule"]
    for k in ("sent", "moved", "merged", "skipped", "opted_out", "rejected",
              "duplicates", "prevented", "cap_violations"):
        assert k in sched
    # Files written equal what goes out, and every response links to a written hand-off.
    assert len(_handoffs(tmp_path)) == sched["sent"] + sched["moved"]
    assert len(list((tmp_path / "responses").glob("*.json"))) == sched["sent"] + sched["moved"]


def test_cap_violations_is_zero_and_no_non_high_within_seven_days(tmp_path):
    """No non-high-priority survey goes to a farmer within 7 days of another, on real data."""
    from datetime import timedelta
    from mel.schedule.batch import cap_violations
    from mel.timing import parse_ist
    assert mel("run", out=tmp_path).returncode == 0
    hs = _handoffs(tmp_path)
    # 1) The summary's independent audit is 0.
    assert _summary(tmp_path)["schedule"]["cap_violations"] == 0
    # 2) Re-audit the files on disk directly: same answer, 0.
    assert cap_violations(hs) == []
    # 3) Spell it out: group by farmer, every non-exempt send is >= 7 days after any earlier send.
    by_farmer: dict[str, list] = {}
    for h in hs:
        by_farmer.setdefault(h["frequency_cap"]["key"], []).append(h)
    for sends in by_farmer.values():
        sends.sort(key=lambda h: parse_ist(h["send_window"]["not_before"]))
        for i, later in enumerate(sends):
            if later["frequency_cap"]["exempt"]:
                continue
            win = timedelta(days=later["frequency_cap"]["window_days"])
            t = parse_ist(later["send_window"]["not_before"])
            assert all(t - parse_ist(e["send_window"]["not_before"]) >= win for e in sends[:i])


def test_opted_out_farmer_gets_nothing_after_opting_out():
    """A farmer on the opt-out list before scheduling receives no hand-off, and the output
    carries no survey or response for them. Tests the gate run_batch applies inside cmd_run."""
    from mel.schedule import run_batch, OptOutList
    from mel.schedule.handoff import priority as brief_priority
    from mel.pipeline import run_pipeline
    from mel.data import load_farmers
    from mel.writer import RELEVANCE_THRESHOLD
    rows = load_insights()
    res = run_pipeline(rows, farmers=load_farmers())
    handoffs = [o["handoff"] for o in res.outputs if "handoff" in o]
    assert handoffs, "need at least one survey to opt a farmer out of"
    # Opt out the farmer behind the first planned hand-off.
    victim = handoffs[0]["survey"]["farmer_id"]
    opt = OptOutList()
    opt.record({"farmer_id": victim, "failure_code": "farmer_opted_out"})
    batch = run_batch(handoffs, relevance_threshold=RELEVANCE_THRESHOLD, opt_out=opt)
    out_ids = {h["survey"]["farmer_id"] for h in batch.handoffs_to_send}
    assert victim not in out_ids
    assert batch.counts["opted_out"] >= 1
    # And a farmer who did NOT opt out is still scheduled (the gate is targeted, not global).
    others = {h["survey"]["farmer_id"] for h in handoffs} - {victim}
    if others:
        assert out_ids & others


@pytest.mark.skipif(not has_pack, reason="full participant pack not present")
def test_weekly_cap_reduces_output_on_full_pack(tmp_path):
    """On the full pack the cap moves/merges/skips surveys, so fewer hand-offs than planned go
    out, while the R1-R8 decision counts are untouched and cap_violations stays 0."""
    assert mel("run", "--simulate", out=tmp_path, data=FULL_DATA).returncode == 0
    s = _summary(tmp_path)
    sched = s["schedule"]
    assert sched["cap_violations"] == 0
    # Something was actually held back by the weekly rule (moved/merged/skipped), so the files
    # written are fewer than the planned survey count.
    assert sched["moved"] + sched["merged"] + sched["skipped"] > 0
    assert sched["sent"] + sched["moved"] < s["surveys"]
    assert len(_handoffs(tmp_path)) == sched["sent"] + sched["moved"]
    # Decision counts are the regression guard: unchanged by the cap.
    assert s["by_rule"] == {"R1": 723, "R2": 25, "R3": 1287, "R4": 875,
                            "R5": 1312, "R6": 147, "R7": 14, "R8": 2616}


# --- --attention still changes output -----------------------------------------------------

@pytest.mark.skipif(not has_pack, reason="full participant pack not present")
def test_attention_flag_changes_output(tmp_path):
    """`run --attention` must still alter the run (priority/question count/send time) after the
    cap wiring. Compare the two summaries and the set of files written."""
    off, on = tmp_path / "off", tmp_path / "on"
    assert mel("run", "--simulate", out=off, data=FULL_DATA).returncode == 0
    assert mel("run", "--simulate", "--attention", out=on, data=FULL_DATA).returncode == 0
    s_off, s_on = _summary(off), _summary(on)
    # Attention adds its tier/reason breakdown to the summary only when on.
    assert "by_tier" in s_on and "by_tier" not in s_off
    # Decisions never change; attention only re-prioritises / re-times.
    assert s_on["by_rule"] == s_off["by_rule"]
    # The actual output differs: either the priority mix or the files written move.
    off_tree = _tree(off)
    on_tree = _tree(on)
    assert off_tree != on_tree
