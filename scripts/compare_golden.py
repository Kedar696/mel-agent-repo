"""Compare two golden sets (an old and a new answer key).

Usage: python scripts/compare_golden.py OLD NEW

OLD and NEW are golden_set.jsonl files (or golden_set.xlsx workbooks). Prints the golden ids
that were added, removed and changed (with the fields that changed), and how many rows each
rule R1-R8 has in each file. Two identical files print no golden ids.
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mel.data import load_golden, load_golden_xlsx  # noqa: E402
from mel.data.excel import _flat, _norm  # noqa: E402

RULES = [f"R{n}" for n in range(1, 9)]


def load(path: Path) -> dict[str, dict]:
    rows = load_golden_xlsx(path) if path.suffix.lower() == ".xlsx" else load_golden(path)
    return {r["golden_id"]: r for r in rows}


def changed_fields(a: dict, b: dict) -> list[str]:
    fa, fb = _flat(a), _flat(b)
    return [k for k in sorted(set(fa) | set(fb)) if k not in fa or k not in fb or _norm(fa[k]) != _norm(fb[k])]


def rule_counts(rows: dict[str, dict]) -> Counter:
    return Counter(r.get("expected", {}).get("rule") for r in rows.values())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("old", type=Path, help="the old golden set")
    ap.add_argument("new", type=Path, help="the new golden set")
    a = ap.parse_args(argv)
    for p in (a.old, a.new):
        if not p.is_file():
            print(f"error: file not found: {p}", file=sys.stderr)
            return 2
    old, new = load(a.old), load(a.new)
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = {i: changed_fields(old[i], new[i]) for i in sorted(set(old) & set(new))}
    changed = {i: f for i, f in changed.items() if f}

    print(f"old: {a.old.name}  rows={len(old)}")
    print(f"new: {a.new.name}  rows={len(new)}")
    print(f"added:   {len(added)}" + (f"  {', '.join(added)}" if added else ""))
    print(f"removed: {len(removed)}" + (f"  {', '.join(removed)}" if removed else ""))
    print(f"changed: {len(changed)}")
    for i, fields in changed.items():
        print(f"  {i}: {', '.join(fields)}")
    co, cn = rule_counts(old), rule_counts(new)
    print("rule   old   new  diff")
    for r in RULES + sorted((set(co) | set(cn)) - set(RULES), key=str):
        print(f"{str(r):<5}{co[r]:>5}{cn[r]:>6}{cn[r] - co[r]:>+6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
