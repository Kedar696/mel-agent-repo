"""P1: Excel loaders, parity check, compare_golden, lazy openpyxl (items 4, 11, 12, 13)."""

import json
import shutil
import subprocess
import sys

import pytest

from mel.config import PACK, ROOT
from mel.data import (
    load_golden,
    load_farmers,
    load_crop_calendar,
    load_insights,
    load_golden_xlsx,
    load_farmers_xlsx,
    load_crop_calendar_xlsx,
    load_insights_xlsx,
)
from mel.data.excel import check_all_parity, check_insights_parity, check_dir_parity, diff_records

SHEETS, DATA = PACK / "spreadsheets", PACK / "data"
has_pack = (SHEETS / "golden_set.xlsx").exists() and (DATA / "golden_set.jsonl").exists()
needs_pack = pytest.mark.skipif(not has_pack, reason="full participant pack not present")


def norm(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True)


def run(*args, **kw):
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", **kw)


# --- openpyxl is lazy (4) ---------------------------------------------------------------


def test_importing_the_package_does_not_load_openpyxl():
    r = run("-c", "import sys, mel.cli, mel.pipeline, mel.data; print('openpyxl' in sys.modules)")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "False"


def test_a_normal_run_does_not_load_openpyxl(tmp_path):
    code = (
        "import sys, argparse, mel.cli as c; "
        "c.OUT = __import__('pathlib').Path(sys.argv[1]); "
        "c.cmd_run(argparse.Namespace(insights=None, simulate=False, limit=3, farmer=None, clean=False)); "
        "print('LOADED' if 'openpyxl' in sys.modules else 'NOT-LOADED')"
    )
    r = run("-c", code, str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().endswith("NOT-LOADED")


# --- loaders return what the JSON/CSV loaders return (11) --------------------------------


@needs_pack
def test_golden_xlsx_equals_golden_jsonl():
    xl, js = load_golden_xlsx(SHEETS / "golden_set.xlsx"), load_golden(DATA / "golden_set.jsonl")
    assert len(xl) == len(js) == 150
    assert xl == js and norm(xl) == norm(js)


@needs_pack
def test_golden_xlsx_rebuilds_items_and_send_window():
    g = {r["golden_id"]: r for r in load_golden_xlsx(SHEETS / "golden_set.xlsx")}
    e = g["G-0002"]["expected"]
    assert e["send_window"] == {"start": "2026-11-13T09:00:00+05:30", "end": "2026-11-20T19:00:00+05:30"}
    assert e["items"][0] == {
        "id": "q1",
        "text": "How much of the plan have you done?",
        "options": ["All steps", "Some steps", "Not started"],
    }
    assert g["G-0002"]["insight"]["location"]["district"] == "Bhojpur"
    three = g["G-0008"]["expected"]["items"][2]
    assert three["show_if"] == "q1 != Yes" and len(three["options"]) == 4
    assert "items" not in g["G-0001"]["expected"] and g["G-0001"]["expected"]["survey"] is False


@needs_pack
def test_farmers_and_calendar_xlsx_equal_csv():
    assert load_farmers_xlsx(SHEETS / "farmers.xlsx") == load_farmers(DATA / "farmers.csv")
    assert load_crop_calendar_xlsx(SHEETS / "crop_calendar.xlsx") == load_crop_calendar(
        DATA / "crop_calendar_bihar_rabi.csv"
    )


@needs_pack
def test_insights_xlsx_equals_jsonl():
    xl, js = load_insights_xlsx(SHEETS / "insights.xlsx"), load_insights(DATA / "insights.jsonl")
    assert norm(xl) == norm(js)


# --- parity (12) ------------------------------------------------------------------------


@needs_pack
def test_parity_default_passes_on_the_committed_pack():
    assert check_all_parity() == []
    r = run("-m", "mel.cli", "parity")
    assert r.returncode == 0 and "differences: 0" in r.stdout


def test_diff_records_reports_one_sided_keys_and_missing_rows():
    a = {"I-1": {"severity": "low", "only_a": 1}, "I-2": {"severity": "x"}}
    b = {"I-1": {"severity": "high", "only_b": 2}, "I-3": {"severity": "x"}}
    out = "\n".join(diff_records(a, b, "xlsx", "json"))
    assert "I-1 severity" in out and "I-1 only_a" in out and "I-1 only_b" in out
    assert "I-2 missing in json" in out and "I-3 missing in xlsx" in out


@needs_pack
def test_parity_names_row_and_field_and_missing_rows(tmp_path):
    rows = (DATA / "insights.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    first["severity"] = "changed-on-purpose"
    first["extra_key"] = "x"
    edited = [json.dumps(first, ensure_ascii=False)] + rows[2:]  # also drop row 2
    j = tmp_path / "insights.jsonl"
    j.write_text("\n".join(edited) + "\n", encoding="utf-8")
    diffs = check_insights_parity(SHEETS / "insights.xlsx", j)
    first_id, dropped = first["insight_id"], json.loads(rows[1])["insight_id"]
    assert any(d.startswith(f"{first_id} severity") for d in diffs)
    assert any(d.startswith(f"{first_id} extra_key") for d in diffs)
    assert any(d.startswith(f"{dropped} missing in jsonl") for d in diffs)


@needs_pack
def test_cli_parity_exits_nonzero_on_a_difference(tmp_path):
    pack = tmp_path / "pack"
    shutil.copytree(PACK, pack)
    rules = pack / "json" / "rules" / "rules.json"
    rules.write_text(rules.read_text(encoding="utf-8").replace("direct_action", "direct_actionX", 1), encoding="utf-8")
    (pack / "json" / "schemas" / "response.schema.json").unlink()
    r = run("-m", "mel.cli", "parity", "--pack", str(pack))
    assert r.returncode == 1
    assert "config/rules/rules.json" in r.stdout and "response.schema.json" in r.stdout


def test_dir_parity_by_file_name(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    (a / "x").mkdir(parents=True)
    (b / "x").mkdir(parents=True)
    (a / "x" / "same.json").write_text('{"k": 1}', encoding="utf-8")
    (b / "x" / "same.json").write_text('{ "k": 1 }', encoding="utf-8")
    (a / "only_a.json").write_text("{}", encoding="utf-8")
    (b / "diff.json").write_text("{}", encoding="utf-8")
    out = check_dir_parity(a, b, "lbl")
    assert out == ["lbl/only_a.json: only in repo", "lbl/diff.json: only in pack"]


# --- compare_golden (13) ----------------------------------------------------------------


@needs_pack
def test_compare_golden_identical_files_print_no_ids():
    g = str(DATA / "golden_set.jsonl")
    r = run("scripts/compare_golden.py", g, g)
    assert r.returncode == 0, r.stderr
    assert "G-0" not in r.stdout
    assert "added:   0" in r.stdout and "removed: 0" in r.stdout and "changed: 0" in r.stdout
    for n in range(1, 9):
        assert f"R{n}" in r.stdout


def test_compare_golden_reports_added_removed_changed(tmp_path):
    rows = [
        json.loads(l) for l in (ROOT / "data" / "mock" / "golden_set.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    old, new = tmp_path / "old.jsonl", tmp_path / "new.jsonl"
    old.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    changed = json.loads(json.dumps(rows[1]))
    changed["expected"]["rule"] = "R3"
    added = json.loads(json.dumps(rows[0]))
    added["golden_id"] = "G-9999"
    new_rows = [changed] + rows[2:] + [added]  # rows[0] removed, rows[1] changed
    new.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in new_rows) + "\n", encoding="utf-8")
    r = run("scripts/compare_golden.py", str(old), str(new))
    assert r.returncode == 0, r.stderr
    assert "added:   1  G-9999" in r.stdout
    assert f"removed: 1  {rows[0]['golden_id']}" in r.stdout
    assert f"{rows[1]['golden_id']}: expected.rule" in r.stdout
