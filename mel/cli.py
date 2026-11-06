"""Command line. Owner: P1.
python -m mel.cli run [--insights PATH] [--simulate] [--limit N] [--farmer ID] [--clean]
                                                      write out/{surveys,handoffs,no_survey,responses}
                                                      plus out/run_summary.json and out/junk_report.csv
python -m mel.cli eval [--golden PATH] [--history]    golden-set scores
python -m mel.cli eval --record "what changed"        full report (both timing rules, full pack + mock,
                                                      scorecard) appended to docs/results run history
python -m mel.cli validate [--allow-empty]            schema-check everything in out/ (fails if there is nothing)
python -m mel.cli junk [--insights PATH] [--limit N] [--farmer ID]
                                                      list input rows that get no survey, and why
python -m mel.cli parity [--xlsx FILE] [--jsonl FILE] [--pack DIR]
                                                      check the Excel workbooks and the JSON/CSV agree
"""

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path
from mel.config import DATA, OUT, PACK
from mel.data import (
    load_insights,
    load_golden,
    load_farmers,
    errors,
    why_junk,
    junk_row,
    check_insights_parity,
    check_all_parity,
)
from mel.pipeline import run_pipeline, select_insights, clean

OUT_SUBDIRS = ("surveys", "handoffs", "no_survey", "responses")  # the only folders --clean touches
JUNK_COLUMNS = ("insight_id", "category", "detail")


def _dump(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _non_negative(text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if n < 0:
        raise argparse.ArgumentTypeError(f"must be 0 or more, got {n}")
    return n


def _fail(msg: str, code: int = 1):
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _clean_out(out: Path):
    """Empty surveys/, handoffs/, no_survey/ and responses/. Anything else in `out` stays."""
    for name in OUT_SUBDIRS:
        d = out / name
        if d.is_symlink() or d.is_file():
            d.unlink()
        elif d.is_dir():
            for child in d.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        d.mkdir(parents=True, exist_ok=True)


def _write_junk_report(path: Path, insights: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(JUNK_COLUMNS)
        for ins in insights:
            row = junk_row(ins)
            if row:
                w.writerow([ins.get("insight_id", "unknown"), *row])
                n += 1
    return n


def cmd_run(a):
    from mel.schedule import run_batch, FrequencyScheduler
    from mel.channels import FarmerReachability
    from mel.simulator import is_late
    from mel.writer import RELEVANCE_THRESHOLD  # P4's published send bar (0.3)

    path = Path(a.insights) if a.insights else DATA / "insights.jsonl"
    try:
        insights = load_insights(path)
    except FileNotFoundError:
        _fail(f"insights file not found: {path}")
    if a.clean:
        _clean_out(OUT)
    try:
        farmers = load_farmers()
    except FileNotFoundError:
        farmers = {}  # send time then uses the insight alone
    attention = getattr(a, "attention", False)  # tolerate Namespaces that omit it (older arg builders)
    result = run_pipeline(insights, limit=a.limit, farmer=a.farmer, farmers=farmers, attention=attention)

    # The pipeline plans a hand-off per survey. The weekly cap, opt-outs and the P4 quality gate
    # decide what actually goes out: P3's `run_batch` (docs/p3_batch_wiring_request.md, policy in
    # docs/cap_policy.md). No-survey rows are written as before; junk report and summary unchanged.
    by_handoff = {}
    for ins, out in zip(result.insights, result.outputs):
        if "no_survey" in out:
            _dump(OUT / "no_survey" / f"{ins.get('insight_id', 'unknown')}.json", out["no_survey"])
        else:
            by_handoff[out["handoff"]["handoff_id"]] = out
    batch = run_batch(
        [o["handoff"] for o in by_handoff.values()],
        relevance_threshold=RELEVANCE_THRESHOLD,
        simulate=a.simulate,
        reachability=FarmerReachability(farmers),
        ranker=FrequencyScheduler.from_insights(insights),
    )
    for h in batch.handoffs_to_send:  # sent + moved; merged ride on the host
        ids = h["survey"]["source_insight_ids"]
        for lang, s in by_handoff[h["handoff_id"]]["surveys"].items():
            _dump(
                OUT / "surveys" / f"{s['survey_id']}.{lang}.json",
                {**clean(s), "source_insight_ids": ids, "send_window": h["send_window"]},
            )
        _dump(OUT / "handoffs" / f"{h['handoff_id']}.json", h)
    for r in batch.responses:
        _dump(OUT / "responses" / f"{r['response_key']}.json", r)
    # Late answers (after the hand-off's expires_at) are counted here, not flagged on the record:
    # response.schema.json allows no extra field (docs/h4_schema_change_request_late.md, option B).
    expires = {h["survey"]["survey_id"]: h["expires_at"] for h in batch.handoffs_to_send}
    late = sum(1 for r in batch.responses if r["survey_id"] in expires and is_late(r, expires[r["survey_id"]]))

    junk = _write_junk_report(OUT / "junk_report.csv", result.insights)
    counts = result.counts()
    surveys = sum(1 for o in result.outputs if "handoff" in o)  # hand-offs the pipeline planned
    summary = {
        "input_path": str(path),
        "rows_read": result.rows_read,
        "rows_processed": result.rows_processed,
        "limit": a.limit,
        "farmer": a.farmer,
        "surveys": surveys,
        "no_survey": result.rows_processed - surveys,
        "junk_rows": junk,
        **counts,
        "schedule": {**batch.counts, "late_answers": late},  # sent/moved/merged/skipped/opted_out/rejected/...
    }
    if attention:  # only when on, so the off path writes a byte-for-byte identical summary
        summary.update(result.attention_counts())
    _dump(OUT / "run_summary.json", summary)
    sc = batch.counts
    print(
        f"insights={result.rows_processed}  surveys={surveys}  no_survey={summary['no_survey']}  "
        f"junk={junk}  input={path}"
    )
    print("decisions by rule:  ", "  ".join(f"{r}={n}" for r, n in counts["by_rule"].items()))
    print("by language:        ", "  ".join(f"{k}={n}" for k, n in counts["by_language"].items()))
    print("by first channel:   ", "  ".join(f"{k}={n}" for k, n in counts["by_first_channel"].items()))
    print("by priority:        ", "  ".join(f"{k}={n}" for k, n in counts["by_priority"].items()))
    print(
        f"schedule:            sent={sc['sent']}  moved={sc['moved']}  merged={sc['merged']}  "
        f"skipped={sc['skipped']}  rejected={sc['rejected']}  opted_out={sc['opted_out']}  "
        f"cap_violations={sc['cap_violations']}  (sent+moved go out = {sc['sent'] + sc['moved']})"
    )
    print(f"-> {OUT}  (run_summary.json, junk_report.csv)")


def cmd_junk(a):
    """Report which input rows are junk and why, instead of dropping them silently."""
    insights = select_insights(
        load_insights(Path(a.insights) if a.insights else None),
        farmer=a.farmer,
        limit=a.limit,
    )
    junk = 0
    for ins in insights:
        reasons = why_junk(ins)
        if reasons:
            junk += 1
            print(f"{ins.get('insight_id', 'unknown')}: {'; '.join(reasons[:3])}")
    print(f"junk rows: {junk} of {len(insights)}")


def cmd_parity(a):
    """Prove the Excel workbooks and the JSON/CSV agree (P1 integration guarantee)."""
    if a.xlsx:  # one workbook: insights only
        xlsx = Path(a.xlsx)
        jsonl = Path(a.jsonl) if a.jsonl else DATA / "insights.jsonl"
        diffs = check_insights_parity(xlsx, jsonl)
        what = f"{xlsx.name} vs {jsonl.name}"
    else:  # everything, against the committed pack
        pack = Path(a.pack) if a.pack else PACK
        if not pack.is_dir():
            _fail(f"participant pack not found: {pack}", 2)
        diffs = check_all_parity(pack)
        what = f"4 workbooks + rules, schemas, scenarios, outcomes vs {pack}"
    for d in diffs[:30]:
        print(" ", d)
    if len(diffs) > 30:
        print(f"  ... and {len(diffs) - 30} more")
    print(f"differences: {len(diffs)}  ({what})")
    raise SystemExit(1 if diffs else 0)


def cmd_eval(a):
    from mel.evaluation import score_golden
    from mel.evaluation.report import farmer_memory, run_eval

    if a.record:  # the published numbers: both timing rules, full pack + mock, scorecard; one history row each
        for basis, r in run_eval(record=a.record, history=a.history).items():
            g = r["full"] or r["mock"]
            print(
                f"{basis}: n={g['n']}  decision={g['decision_acc']:.1%}  rule={g['rule_acc']:.1%}  "
                f"window={g['window_acc']:.1%}  (recorded: {a.record})"
            )
        return
    r = score_golden(load_golden(Path(a.golden)) if a.golden else None, memory=farmer_memory() if a.history else None)
    print(
        f"n={r['n']}  decision={r['decision_acc']:.1%}  rule={r['rule_acc']:.1%}  "
        f"channel={r['channel_acc']:.1%}  window={r['window_acc']:.1%}"
    )
    for m in r["misses"][:20]:
        print("  miss", m)


def cmd_validate(a):
    kinds = {"surveys": "survey", "handoffs": "schedule_handoff", "no_survey": "no_survey", "responses": "response"}
    if not OUT.is_dir() and not a.allow_empty:
        print("files checked: 0")
        _fail(f"output folder not found: {OUT} (run `python -m mel.cli run` first, or pass --allow-empty)")
    checked = bad = 0
    for d, kind in kinds.items():
        for p in sorted((OUT / d).glob("*.json")):
            checked += 1
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                bad += 1
                print(f"{d}/{p.name}: unparseable JSON ({exc})")
                continue
            e = errors(kind, obj)
            if e:
                bad += 1
                print(p.name, e[:3])
    print("files checked:", checked)
    print("invalid files:", bad)
    if checked == 0 and not a.allow_empty:
        _fail(f"no files to check in {OUT} (run `python -m mel.cli run` first, or pass --allow-empty)")
    raise SystemExit(1 if bad else 0)


def main():
    ap = argparse.ArgumentParser(prog="mel")
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run")
    r.add_argument("--insights")
    r.add_argument("--simulate", action="store_true")
    r.add_argument("--limit", type=_non_negative, help="process only the first N insights (0 = none)")
    r.add_argument("--farmer", help="process only this farmer_id")
    r.add_argument(
        "--clean",
        action="store_true",
        help="first empty surveys/, handoffs/, no_survey/ and responses/ in the output folder",
    )
    r.add_argument(
        "--attention",
        action="store_true",
        help="turn on activity attention (off by default; changes priority, question count and send time)",
    )
    r.set_defaults(f=cmd_run)
    e = sp.add_parser("eval")
    e.add_argument("--golden")
    e.add_argument("--history", action="store_true", help="score with P4's history rules on (off by default)")
    e.add_argument(
        "--record",
        metavar="LABEL",
        help="run the full evaluation (both timing rules) and append it to the run history under this label",
    )
    e.set_defaults(f=cmd_eval)
    v = sp.add_parser("validate")
    v.add_argument("--allow-empty", action="store_true", help="exit 0 even when there are no files to check")
    v.set_defaults(f=cmd_validate)
    j = sp.add_parser("junk")
    j.add_argument("--insights")
    j.add_argument("--limit", type=_non_negative)
    j.add_argument("--farmer")
    j.set_defaults(f=cmd_junk)
    p = sp.add_parser("parity")
    p.add_argument("--xlsx", help="check only this insights workbook (default: all four workbooks + config folders)")
    p.add_argument("--jsonl", help="with --xlsx: data/insights.jsonl (defaults to the active data dir)")
    p.add_argument("--pack", help="participant-pack folder (default: the committed pack)")
    p.set_defaults(f=cmd_parity)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
