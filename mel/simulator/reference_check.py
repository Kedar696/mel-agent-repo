"""Compare generated outcomes against the reference grid, field by field. Owner: P3.

The pack ships 183 reference answer records under `data/mock/outcomes/<channel>/<qtype>/
<case>.json`. `mel.simulator.simulate()` reproduces them exactly for the anchor surveys, and
`tests/test_simulator.py::test_simulate_matches_all_183_reference_records` locks that in.

This module is the standalone, human-readable counterpart to that test: it regenerates each
record and reports mismatches **by field**, so when something drifts you see exactly which
field in which (channel, qtype, case) changed — rather than a single failed assertion.

    python -m mel.simulator.reference_check            # prints a report, exits non-zero on mismatch

Identifier policy: by default NOTHING is ignored — the simulator is fully deterministic
(even `response_key` is `rk-{survey_id}-{channel}-{case}`), so every field must match. The
`ignore_fields` argument exists only as a documented hook for a *future* generated/random ID
field; it is empty by default and must never be used to hide a non-ID field difference. Any
ignored field is listed explicitly in the report so it is never silent.
"""

import json
from pathlib import Path

from mel.config import FIXTURES, outcome_codes
from mel.data import load_scenario


# Documented, intentionally empty: the simulator generates no random/non-deterministic ids,
# so no field is ignored. Populate ONLY if a genuinely generated ID field is added later, and
# document why here. Never add a non-ID field.
DEFAULT_IGNORE_FIELDS: tuple[str, ...] = ()


def _anchor_surveys() -> dict:
    """survey (hi-IN) per question type, from the grid's anchor scenarios."""
    return {q: load_scenario(a["scenario"])["surveys"]["hi-IN"] for q, a in outcome_codes()["grid_anchor"].items()}


def _field_diffs(ref: dict, got: dict, ignore_fields) -> list[str]:
    """Per-field differences between a reference and a generated record, ignoring only the
    explicitly listed (and reported) id fields."""
    diffs = []
    for key in sorted(set(ref) | set(got)):
        if key in ignore_fields:
            continue
        if ref.get(key) != got.get(key):
            diffs.append(f"{key}: reference={ref.get(key)!r} generated={got.get(key)!r}")
    return diffs


def compare(outcomes_dir: Path | None = None, ignore_fields=DEFAULT_IGNORE_FIELDS) -> dict:
    """Compare every reference record with its freshly generated counterpart.

    Returns a report dict:
      total            - reference files found (expected 183),
      matched          - records that matched field-for-field,
      mismatches       - list of {channel, qtype, case, file, diffs:[...]},
      ignored_fields   - the id fields intentionally ignored (for transparency; empty today).
    """
    from mel.simulator import simulate

    root = Path(outcomes_dir) if outcomes_dir else (FIXTURES / "outcomes")
    files = sorted(root.rglob("*.json"))
    surveys = _anchor_surveys()

    matched = 0
    mismatches = []
    for p in files:
        channel, qtype, case = p.parent.parent.name, p.parent.name, p.stem
        ref = json.loads(p.read_text(encoding="utf-8"))
        got = simulate(surveys[qtype], channel, case)
        diffs = _field_diffs(ref, got, ignore_fields)
        if diffs:
            mismatches.append(
                {"channel": channel, "qtype": qtype, "case": case, "file": str(p.relative_to(root)), "diffs": diffs}
            )
        else:
            matched += 1
    return {"total": len(files), "matched": matched, "mismatches": mismatches, "ignored_fields": list(ignore_fields)}


def format_report(report: dict) -> str:
    lines = [f"Reference grid: {report['matched']}/{report['total']} records match field-for-field."]
    if report["ignored_fields"]:
        lines.append(f"Intentionally ignored id fields: {', '.join(report['ignored_fields'])}")
    else:
        lines.append(
            "Intentionally ignored id fields: none (simulator is fully deterministic; every field is compared)."
        )
    for m in report["mismatches"]:
        lines.append(f"\nMISMATCH {m['channel']}/{m['qtype']}/{m['case']} ({m['file']}):")
        for d in m["diffs"]:
            lines.append(f"    - {d}")
    if not report["mismatches"]:
        lines.append("All records match. No mismatches.")
    return "\n".join(lines)


def main() -> int:
    report = compare()
    print(format_report(report))
    # Non-zero exit when anything mismatches or the expected 183 are not all present.
    ok = not report["mismatches"] and report["total"] == 183 and report["matched"] == 183
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
