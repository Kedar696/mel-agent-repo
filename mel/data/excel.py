"""Excel readers for the participant pack, with parity checks against the JSON/CSV. Owner: P1.

The pack ships the same data twice: as data/*.jsonl + *.csv and as spreadsheets/*.xlsx.
Each loader here returns exactly what its JSON/CSV twin returns, so either source can feed
the pipeline:

* ``load_insights_xlsx``      == ``load_insights``      (dotted columns become nested dicts)
* ``load_golden_xlsx``        == ``load_golden``        (``insight_*`` / ``expected_*`` columns)
* ``load_farmers_xlsx``       == ``load_farmers``
* ``load_crop_calendar_xlsx`` == ``load_crop_calendar``

The ``check_*_parity`` functions prove the two sources agree and name every difference by row
id and field (``I-000123 severity``) or by file name. ``openpyxl`` is imported only inside
the functions that open a workbook, so importing ``mel.cli`` or ``mel.data`` stays light.
"""

import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from mel.config import PACK, ROOT

# Dotted columns that carry something other than a free-text string. Everything
# else is passed through as-is (string, or None for an empty cell).
_BOOL_COLS = {"verification.needed"}
_INT_COLS = {"action_window_days"}


def _coerce(col: str, value: Any) -> Any:
    """Turn one text cell into the JSON type the schema expects for that column."""
    if value is None or value == "":
        return None
    if col in _BOOL_COLS:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() == "true"
    if col in _INT_COLS:
        return int(value)
    return value


def _unflatten(flat: dict[str, Any]) -> dict[str, Any]:
    """``{'location.country': 'IN'}`` -> ``{'location': {'country': 'IN'}}``."""
    out: dict[str, Any] = {}
    for col, raw in flat.items():
        value = _coerce(col, raw)
        if "." in col:
            head, tail = col.split(".", 1)
            out.setdefault(head, {})[tail] = value
        else:
            out[col] = value
    return out


def read_xlsx(path: Path, sheet: str | None = None) -> list[dict]:
    """Every data row of a sheet as a list of flat ``{column: value}`` dicts."""
    from openpyxl import load_workbook  # lazy: only runs that read Excel pay for it

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        rows = ws.iter_rows(values_only=True)
        try:
            header = [str(h) if h is not None else "" for h in next(rows)]
        except StopIteration:
            return []
        out = []
        for row in rows:
            if all(cell is None for cell in row):
                continue  # trailing blank line
            out.append(dict(zip(header, row)))
        return out
    finally:
        wb.close()


def load_insights_xlsx(path: Path) -> list[dict]:
    """Insights from ``spreadsheets/insights.xlsx`` as the same dicts as ``load_insights``."""
    return [_unflatten(flat) for flat in read_xlsx(path)]


# --- golden set -------------------------------------------------------------------------

_GOLDEN_TOP = {"golden_id", "insight_id"}  # columns that belong to the golden row itself
_INSIGHT_NESTED = ("location", "asset", "verification")
_INSIGHT_BOOL = {"verification.needed"}
_INSIGHT_INT = {"action_window_days"}
_EXPECTED_SCALARS = ("reason_code", "rule", "channel", "method")


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v == "")


def _to_bool(v: Any) -> bool | None:
    if _blank(v):
        return None
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() == "true"


def _golden_insight(flat: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the nested ``insight`` object from the ``insight_*`` columns."""
    ins: dict[str, Any] = {}
    for col, raw in flat.items():
        if col in _GOLDEN_TOP or not col.startswith("insight_"):
            continue
        name = col[len("insight_") :]  # insight_insight_id -> insight_id
        head, _, tail = name.partition("_")
        if head in _INSIGHT_NESTED and tail:
            key = f"{head}.{tail}"
        else:
            key = name
        if key in _INSIGHT_BOOL:
            value = _to_bool(raw)
        elif key in _INSIGHT_INT:
            value = None if _blank(raw) else int(raw)
        else:
            value = None if _blank(raw) else raw
        if "." in key:
            h, t = key.split(".", 1)
            ins.setdefault(h, {})[t] = value
        else:
            ins[key] = value
    return ins


def _golden_expected(flat: dict[str, Any]) -> dict[str, Any]:
    """Rebuild ``expected`` (including ``send_window`` and ``items``); empty cells are omitted."""
    exp: dict[str, Any] = {"survey": _to_bool(flat.get("expected_survey"))}
    for name in _EXPECTED_SCALARS:
        v = flat.get(f"expected_{name}")
        if not _blank(v):
            exp[name] = v
    start, end = flat.get("expected_send_window_start"), flat.get("expected_send_window_end")
    if not (_blank(start) and _blank(end)):
        exp["send_window"] = {"start": None if _blank(start) else start, "end": None if _blank(end) else end}
    items = []
    for n in (1, 2, 3):
        iid = flat.get(f"expected_items{n}_id")
        text = flat.get(f"expected_items{n}_text")
        opts = flat.get(f"expected_items{n}_options")
        show_if = flat.get(f"expected_items{n}_show_if")
        if all(_blank(v) for v in (iid, text, opts, show_if)):
            continue
        item: dict[str, Any] = {"id": iid, "text": text}
        if not _blank(show_if):
            item["show_if"] = show_if
        if not _blank(opts):
            item["options"] = str(opts).split(", ")
        items.append(item)
    if items:
        exp["items"] = items
    return exp


def load_golden_xlsx(path: Path) -> list[dict]:
    """Golden set from ``spreadsheets/golden_set.xlsx`` as the same dicts as ``load_golden``."""
    return [
        {
            "golden_id": flat.get("golden_id"),
            "insight_id": flat.get("insight_id"),
            "insight": _golden_insight(flat),
            "expected": _golden_expected(flat),
        }
        for flat in read_xlsx(path)
    ]


# --- farmers and crop calendar ----------------------------------------------------------


def _cell_text(v: Any) -> str:
    """A cell as the text the CSV reader would give for it ('' for an empty cell)."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == datetime.min.time() else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _text_rows(path: Path) -> list[dict[str, str]]:
    return [{k: _cell_text(v) for k, v in row.items()} for row in read_xlsx(path)]


def load_farmers_xlsx(path: Path) -> dict[str, dict]:
    """Farmers from ``spreadsheets/farmers.xlsx`` as the same dict as ``load_farmers``."""
    return {r["farmer_id"]: r for r in _text_rows(path)}


def load_crop_calendar_xlsx(path: Path) -> list[dict]:
    """Crop calendar from ``spreadsheets/crop_calendar.xlsx``, same rows as ``load_crop_calendar``."""
    return _text_rows(path)


# --- parity checks ----------------------------------------------------------------------

_MISSING = object()


def _norm(obj: Any) -> str:
    """Stable JSON text for comparing two values regardless of key order (True != 1)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _flat(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested dicts and lists to ``{'verification.needed': True, 'items[0].id': 'q1'}``."""
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        if not obj and prefix:
            out[prefix] = obj
        for k, v in obj.items():
            out.update(_flat(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        if not obj and prefix:
            out[prefix] = obj
        for i, v in enumerate(obj):
            out.update(_flat(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def _show(v: Any) -> str:
    return "<missing>" if v is _MISSING else repr(v)


def _index(rows: list[dict], key, source: str, problems: list[str]) -> dict[str, dict]:
    """Rows by id. A repeated id is reported instead of silently overwriting the first row."""
    out: dict[str, dict] = {}
    for n, r in enumerate(rows, start=1):
        rid = key(r, n)
        if rid in out:
            problems.append(f"{rid} duplicated in {source}")
        out[rid] = r
    return out


def diff_records(a_rows: dict[str, dict], b_rows: dict[str, dict], a_name: str, b_name: str) -> list[str]:
    """One line per disagreement: missing rows, then every field that differs or exists on one side only."""
    problems: list[str] = []
    for rid in sorted(set(a_rows) - set(b_rows)):
        problems.append(f"{rid} missing in {b_name} (only in {a_name})")
    for rid in sorted(set(b_rows) - set(a_rows)):
        problems.append(f"{rid} missing in {a_name} (only in {b_name})")
    for rid in sorted(set(a_rows) & set(b_rows)):
        fa, fb = _flat(a_rows[rid]), _flat(b_rows[rid])
        for field in sorted(set(fa) | set(fb)):
            va, vb = fa.get(field, _MISSING), fb.get(field, _MISSING)
            if va is _MISSING or vb is _MISSING or _norm(va) != _norm(vb):
                problems.append(f"{rid} {field}: {a_name}={_show(va)} {b_name}={_show(vb)}")
    return problems


def _jsonl_rows(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _keyed_parity(xl_rows, js_rows, key, xl_name="xlsx", js_name="json") -> list[str]:
    problems: list[str] = []
    xl = _index(xl_rows, key, xl_name, problems)
    js = _index(js_rows, key, js_name, problems)
    return problems + diff_records(xl, js, xl_name, js_name)


def check_insights_parity(xlsx_path: Path, jsonl_path: Path) -> list[str]:
    """Compare the Excel insights to the JSONL insights. Empty list means they match.

    Every disagreement is its own line (``I-000123 severity: xlsx='low' jsonl='high'``), and a
    key that only one side has counts as a disagreement.
    """
    key = lambda r, n: r.get("insight_id") or f"row {n}"
    return _keyed_parity(load_insights_xlsx(xlsx_path), _jsonl_rows(jsonl_path), key, "xlsx", "jsonl")


def check_golden_parity(xlsx_path: Path, jsonl_path: Path) -> list[str]:
    key = lambda r, n: r.get("golden_id") or f"row {n}"
    return _keyed_parity(load_golden_xlsx(xlsx_path), _jsonl_rows(jsonl_path), key, "xlsx", "jsonl")


def check_farmers_parity(xlsx_path: Path, csv_path: Path) -> list[str]:
    key = lambda r, n: r.get("farmer_id") or f"row {n}"
    with open(csv_path, encoding="utf-8", newline="") as f:
        csv_rows = list(csv.DictReader(f))
    return _keyed_parity(list(load_farmers_xlsx(xlsx_path).values()), csv_rows, key, "xlsx", "csv")


def check_crop_calendar_parity(xlsx_path: Path, csv_path: Path) -> list[str]:
    with open(csv_path, encoding="utf-8", newline="") as f:
        csv_rows = list(csv.DictReader(f))
    xl_rows = load_crop_calendar_xlsx(xlsx_path)
    problems: list[str] = []
    if len(xl_rows) != len(csv_rows):
        problems.append(f"crop calendar row count: xlsx={len(xl_rows)} csv={len(csv_rows)}")
    # Rows are matched by position (the calendar has no unique id), keyed so a message names the row.
    xl = {f"row {n} ({r.get('crop')}/{r.get('growth_stage') or '-'})": r for n, r in enumerate(xl_rows, 1)}
    cv = {f"row {n} ({r.get('crop')}/{r.get('growth_stage') or '-'})": r for n, r in enumerate(csv_rows, 1)}
    return problems + diff_records(xl, cv, "xlsx", "csv")


def _files(root: Path) -> dict[str, Path]:
    return {p.relative_to(root).as_posix(): p for p in sorted(root.rglob("*")) if p.is_file() and p.name != ".DS_Store"}


def _same_file(a: Path, b: Path) -> bool:
    if a.suffix == ".json":
        try:
            return _norm(json.loads(a.read_text(encoding="utf-8"))) == _norm(json.loads(b.read_text(encoding="utf-8")))
        except (ValueError, UnicodeDecodeError):
            pass
    return a.read_bytes() == b.read_bytes()


def check_dir_parity(repo_dir: Path, pack_dir: Path, label: str) -> list[str]:
    """Compare two folders of files. Differences are named by file path under ``label``."""
    if not repo_dir.is_dir():
        return [f"{label}: folder missing in repo ({repo_dir})"]
    if not pack_dir.is_dir():
        return [f"{label}: folder missing in pack ({pack_dir})"]
    a, b = _files(repo_dir), _files(pack_dir)
    problems = [f"{label}/{n}: only in repo" for n in sorted(set(a) - set(b))]
    problems += [f"{label}/{n}: only in pack" for n in sorted(set(b) - set(a))]
    problems += [f"{label}/{n}: content differs" for n in sorted(set(a) & set(b)) if not _same_file(a[n], b[n])]
    return problems


# (label, folder in this repo, folder in the pack)
_DIR_PAIRS = (
    ("config/rules", "config/rules", "json/rules"),
    ("config/schemas", "config/schemas", "json/schemas"),
    ("data/mock/scenarios", "data/mock/scenarios", "json/scenarios"),
    ("data/mock/outcomes", "data/mock/outcomes", "json/outcomes"),
)


def check_all_parity(pack: Path | None = None, repo: Path | None = None) -> list[str]:
    """Everything P1 guarantees: the four workbooks match their JSON/CSV, and the repo's
    rules, schemas, scenarios and outcomes match the pack. Empty list means all agree."""
    pack, repo = Path(pack or PACK), Path(repo or ROOT)
    sheets, data = pack / "spreadsheets", pack / "data"
    jobs = (
        ("insights.xlsx", check_insights_parity, sheets / "insights.xlsx", data / "insights.jsonl"),
        ("golden_set.xlsx", check_golden_parity, sheets / "golden_set.xlsx", data / "golden_set.jsonl"),
        ("farmers.xlsx", check_farmers_parity, sheets / "farmers.xlsx", data / "farmers.csv"),
        (
            "crop_calendar.xlsx",
            check_crop_calendar_parity,
            sheets / "crop_calendar.xlsx",
            data / "crop_calendar_bihar_rabi.csv",
        ),
    )
    problems: list[str] = []
    for label, fn, xl, other in jobs:
        for p in (xl, other):
            if not p.exists():
                problems.append(f"{label}: file missing ({p})")
                break
        else:
            problems += [f"[{label}] {d}" for d in fn(xl, other)]
    for label, mine, theirs in _DIR_PAIRS:
        problems += [
            f"[{label}] {d}" if not d.startswith(label) else d
            for d in check_dir_parity(repo / mine, pack / theirs, label)
        ]
    return problems
