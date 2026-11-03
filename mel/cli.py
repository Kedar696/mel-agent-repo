"""Command line. Owner: P1.

  python -m mel.cli run [--insights PATH] [--simulate] [--limit N] [--farmer ID]
                                                        write out/{surveys,handoffs,no_survey,responses}
  python -m mel.cli eval [--golden PATH]                golden-set scores
  python -m mel.cli validate                            schema-check everything in out/
  python -m mel.cli junk [--insights PATH] [--limit N] [--farmer ID]
                                                        list input rows that get no survey, and why
  python -m mel.cli parity --xlsx FILE [--jsonl FILE]   check an Excel sheet matches the JSON
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from mel.config import DATA, OUT
from mel.data import load_insights, load_golden, errors, why_junk, check_insights_parity
from mel.pipeline import run_insight, clean


def _dump(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _select(insights, farmer=None, limit=None):
    """Narrow a batch for a focused run: one farmer, a head slice, or both."""
    if farmer:
        insights = [i for i in insights if i.get("farmer_id") == farmer]
    if limit is not None:
        insights = insights[:limit]
    return insights


def cmd_run(a):
    from mel.simulator import simulate
    stats = Counter()
    insights = _select(
        load_insights(Path(a.insights) if a.insights else None),
        farmer=a.farmer, limit=a.limit,
    )
    for ins in insights:
        out = run_insight(ins)
        stats[out["decision"].rule] += 1
        if "no_survey" in out:
            _dump(OUT / "no_survey" / f"{ins.get('insight_id','unknown')}.json", out["no_survey"])
            continue
        for lang, s in out["surveys"].items():
            _dump(OUT / "surveys" / f"{s['survey_id']}.{lang}.json", clean(s))
        h = out["handoff"]
        _dump(OUT / "handoffs" / f"{h['handoff_id']}.json", h)
        if a.simulate:
            ch = h["channel_order"][0]["channel"]
            r = simulate(h["survey"], ch, "completed")
            _dump(OUT / "responses" / f"{r['response_key']}.json", r)
    print(f"insights={len(insights)}  decisions by rule:", dict(sorted(stats.items())), "->", OUT)


def cmd_junk(a):
    """Report which input rows are junk and why, instead of dropping them silently."""
    insights = _select(
        load_insights(Path(a.insights) if a.insights else None),
        farmer=a.farmer, limit=a.limit,
    )
    junk = 0
    for ins in insights:
        reasons = why_junk(ins)
        if reasons:
            junk += 1
            print(f"{ins.get('insight_id', 'unknown')}: {'; '.join(reasons[:3])}")
    print(f"junk rows: {junk} of {len(insights)}")


def cmd_parity(a):
    """Prove the Excel spreadsheet and the JSON/CSV agree (P1 integration guarantee)."""
    xlsx = Path(a.xlsx)
    jsonl = Path(a.jsonl) if a.jsonl else DATA / "insights.jsonl"
    diffs = check_insights_parity(xlsx, jsonl)
    for d in diffs[:20]:
        print(" ", d)
    print(f"differences: {len(diffs)}  ({xlsx.name} vs {jsonl.name})")
    raise SystemExit(1 if diffs else 0)


def cmd_eval(a):
    from mel.evaluation import score_golden
    r = score_golden(load_golden(Path(a.golden)) if a.golden else None)
    print(f"n={r['n']}  decision={r['decision_acc']:.1%}  rule={r['rule_acc']:.1%}  "
          f"channel={r['channel_acc']:.1%}  window={r['window_acc']:.1%}")
    for m in r["misses"][:20]:
        print("  miss", m)


def cmd_validate(a):
    kinds = {"surveys": "survey", "handoffs": "schedule_handoff", "no_survey": "no_survey", "responses": "response"}
    bad = 0
    for d, kind in kinds.items():
        for p in sorted((OUT / d).glob("*.json")):
            e = errors(kind, json.loads(p.read_text(encoding="utf-8")))
            if e:
                bad += 1
                print(p.name, e[:3])
    print("invalid files:", bad)
    raise SystemExit(1 if bad else 0)


def main():
    ap = argparse.ArgumentParser(prog="mel")
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run")
    r.add_argument("--insights")
    r.add_argument("--simulate", action="store_true")
    r.add_argument("--limit", type=int, help="process only the first N insights")
    r.add_argument("--farmer", help="process only this farmer_id")
    r.set_defaults(f=cmd_run)
    e = sp.add_parser("eval"); e.add_argument("--golden"); e.set_defaults(f=cmd_eval)
    v = sp.add_parser("validate"); v.set_defaults(f=cmd_validate)
    j = sp.add_parser("junk")
    j.add_argument("--insights")
    j.add_argument("--limit", type=int)
    j.add_argument("--farmer")
    j.set_defaults(f=cmd_junk)
    p = sp.add_parser("parity")
    p.add_argument("--xlsx", required=True, help="spreadsheets/insights.xlsx")
    p.add_argument("--jsonl", help="data/insights.jsonl (defaults to the active data dir)")
    p.set_defaults(f=cmd_parity)
    a = ap.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
