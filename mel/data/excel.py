"""Excel readers for the participant pack, with a parity check against the JSON/CSV. Owner: P1.

The pack ships the same data twice: as data/*.jsonl + *.csv and as spreadsheets/*.xlsx.
The spreadsheets flatten nested objects into dotted columns (``location.country``,
``asset.name``, ``verification.needed``) and store every cell as text, so a boolean
arrives as the string ``"true"`` and an empty cell as ``None``.

``load_insights_xlsx`` turns a sheet back into the same dicts ``load_insights`` yields
from the JSONL, so either source can feed the pipeline. ``check_insights_parity`` proves
the two sources agree, which is the integration guarantee P1 owns.
"""
import json
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

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
    wb = load_workbook(path, read_only=True, data_only=True)
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
    wb.close()
    return out


def load_insights_xlsx(path: Path) -> list[dict]:
    """Insights from ``spreadsheets/insights.xlsx`` as the same dicts as ``load_insights``."""
    return [_unflatten(flat) for flat in read_xlsx(path)]


def _norm(obj: Any) -> str:
    """Stable JSON text for comparing two values regardless of key order."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def check_insights_parity(xlsx_path: Path, jsonl_path: Path) -> list[str]:
    """Compare the Excel insights to the JSONL insights. Empty list means they match.

    Each returned string names one disagreement, so a failing parity check reads like a
    short diff instead of a single opaque "not equal".
    """
    xl = {r.get("insight_id"): r for r in load_insights_xlsx(xlsx_path)}
    js = {}
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                js[r.get("insight_id")] = r

    problems: list[str] = []
    only_xl = sorted(set(xl) - set(js))
    only_js = sorted(set(js) - set(xl))
    for i in only_xl[:10]:
        problems.append(f"{i}: only in xlsx")
    for i in only_js[:10]:
        problems.append(f"{i}: only in jsonl")

    for iid in sorted(set(xl) & set(js)):
        a, b = xl[iid], js[iid]
        # Compare the fields the spreadsheet carries; ignore keys only one side has.
        for key in sorted(set(a) & set(b)):
            if _norm(a[key]) != _norm(b[key]):
                problems.append(f"{iid}.{key}: xlsx={a[key]!r} jsonl={b[key]!r}")
        if len(problems) >= 50:
            problems.append("... (more differences omitted)")
            break
    return problems
