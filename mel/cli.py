"""Command line. Owner: P1.

  python -m mel.cli run [--insights PATH] [--simulate]   write out/{surveys,handoffs,no_survey,responses}
  python -m mel.cli eval [--golden PATH]                 golden-set scores
  python -m mel.cli validate                             schema-check everything in out/
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from mel.config import OUT
from mel.data import load_insights, load_golden, errors
from mel.pipeline import run_insight, clean


def _dump(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_run(a):
    from mel.simulator import simulate
    stats = Counter()
    for ins in load_insights(Path(a.insights) if a.insights else None):
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
    print("decisions by rule:", dict(sorted(stats.items())), "->", OUT)


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
    r = sp.add_parser("run"); r.add_argument("--insights"); r.add_argument("--simulate", action="store_true"); r.set_defaults(f=cmd_run)
    e = sp.add_parser("eval"); e.add_argument("--golden"); e.set_defaults(f=cmd_eval)
    v = sp.add_parser("validate"); v.set_defaults(f=cmd_validate)
    a = ap.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
