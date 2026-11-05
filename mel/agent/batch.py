"""Write surveys for many conversations with the agent, tracking cost. Owner: P5.

    python -m mel.agent.batch --sample 40 --judge --label "pilot: Haiku 4.5, hi+en"     measure, then project
    python -m mel.agent.batch --max-usd 40 --judge --label "full set: Haiku 4.5, hi+en"  the whole dataset
    python -m mel.agent.batch --limit 200                                               the first 200 insights

Runs mel.agent.run_agent on every insight (history rules and activity attention off: the scoring defaults) on a thread
pool, writes the files to out/agent_batch/<run>/, the summary to docs/results/full_bedrock_run.json (a full run) or
the console (a pilot), and one row to docs/results/cost_history.jsonl.

Budget: with --max-usd the run stops sending new conversations once the spend reaches the cap; the ones in flight
finish. Resume: run the same command again. Everything already written comes from P4's on-disk cache for $0, so only
what is missing (or failed) is paid for. Needs MEL_USE_LLM=1 and the Bedrock settings, or it writes templates for $0.
"""
import argparse
import json
import os
import random
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait

from mel.config import OUT, ROOT
from mel.evaluation.costs import CostMeter, record_cost, row_from_results, FULL_SET_SURVEYS
from mel.pipeline import clean
from mel.writer import llm

from .inputs import Pack
from .orchestrator import run_agent, MAX_REVISIONS

FULL_SUMMARY = ROOT / "docs" / "results" / "full_bedrock_run.json"


def stratified_sample(insights, n: int, seed: int = 5) -> list[dict]:
    """n insights that get a survey, spread across advice types (round-robin), same every time."""
    from mel.decision import decide
    by = defaultdict(list)
    for i in insights:
        if decide(i).survey:
            by[i.get("resolution_type")].append(i)
    rnd = random.Random(seed)
    for v in by.values():
        rnd.shuffle(v)
    out, keys = [], sorted(by, key=str)
    while len(out) < n and any(by.values()):
        for k in keys:
            if by[k] and len(out) < n:
                out.append(by[k].pop())
    return out


def run_batch(insights, pack: Pack, *, workers: int = 8, max_usd: float | None = None, judge=None,
              guardrail=None, max_revisions: int = MAX_REVISIONS, progress=print, every: int = 50):
    """-> (results in input order, meter, stopped_at_cap). Each result is run_agent's final 'result' event."""
    meter = CostMeter()
    llm.client()                                   # one shared client, made before the threads start
    results: list = [None] * len(insights)
    stopped = False
    lock = threading.Lock()
    done = [0]
    t0 = time.perf_counter()

    def one(k, ins):
        res = None
        for e in run_agent(ins, memory=None, attention=None, guardrail=guardrail, judge=judge,
                           max_revisions=max_revisions, **pack.inputs_for(ins)):
            res = e
        results[k] = res
        with lock:
            done[0] += 1
            if progress and (done[0] % every == 0 or done[0] == len(insights)):
                spent = meter.spent()
                el = time.perf_counter() - t0
                left = el / done[0] * (len(insights) - done[0])
                progress(f"  {done[0]:>5}/{len(insights)}  spent ${spent:.2f}  "
                         f"{el:.0f} s elapsed, about {left / 60:.0f} min left")

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        pending = set()
        it = iter(enumerate(insights))
        for k, ins in it:
            if max_usd is not None and meter.spent() >= max_usd:
                stopped = True
                break
            pending.add(ex.submit(one, k, ins))
            if len(pending) >= workers * 2:          # keep the queue short so the cap is checked often
                finished, pending = wait(pending, return_when=FIRST_COMPLETED)
                for f in finished:
                    f.result()
        for f in pending:
            f.result()
    return results, meter, stopped


def _write_files(results, run_dir):
    for r in results:
        if r is None:
            continue
        if r.get("no_survey"):
            p = run_dir / "no_survey" / f"{r['insight_id']}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(r["no_survey"], ensure_ascii=False, indent=1), encoding="utf-8")
            continue
        for lang, s in (r.get("surveys") or {}).items():
            p = run_dir / "surveys" / f"{s['survey_id']}.{lang}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(clean(s), ensure_ascii=False, indent=1), encoding="utf-8")
        h = r.get("handoff")
        if h:
            p = run_dir / "handoffs" / f"{h['handoff_id']}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(h, ensure_ascii=False, indent=1), encoding="utf-8")


def summarise(results, insights) -> dict:
    """Counts for the committed summary: sources per language, fallbacks, revisions, schema, judge per advice type."""
    from mel.data.validate import errors
    res_type = {i.get("insight_id"): i.get("resolution_type") for i in insights}
    done = [r for r in results if r is not None]
    surveyed = [r for r in done if r.get("surveys")]
    src, fb, judge, bad = Counter(), Counter(), defaultdict(list), 0
    for r in surveyed:
        for lang, s in r["surveys"].items():
            src[f"{lang} {s.get('_source')}"] += 1
            if s.get("_fallback_reason"):
                fb[s["_fallback_reason"]] += 1
            bad += bool(errors("survey", clean(s)))
            j = (s.get("_verifier") or {}).get("judge")
            if j is not None:
                judge[res_type.get(r["insight_id"])].append(j)
        bad += bool(errors("schedule_handoff", r["handoff"]))
    lengths = [len(q.get("prompt") or "") for r in surveyed for s in r["surveys"].values()
               if s.get("_source") == "bedrock" for q in s["items"]]
    all_j = [x for v in judge.values() for x in v]
    return {"insights": len(insights), "processed": len(done), "surveys": len(surveyed),
            "no_survey": sum(1 for r in done if r.get("no_survey")),
            "files": sum(len(r["surveys"]) for r in surveyed) + len(surveyed),
            "schema_invalid_files": bad, "sources": dict(sorted(src.items())), "fallbacks": dict(fb.most_common()),
            "revisions": sum((r.get("metrics") or {}).get("revisions", 0) for r in surveyed),
            "surveys_revised": sum(1 for r in surveyed if (r.get("metrics") or {}).get("revisions")),
            "avg_bedrock_question_chars": round(sum(lengths) / len(lengths), 1) if lengths else None,
            "judge_relevance": round(sum(all_j) / len(all_j), 2) if all_j else None,
            "judge_by_advice_type": {k: round(sum(v) / len(v), 2) for k, v in sorted(judge.items(), key=lambda kv: str(kv[0]))}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--sample", type=int, help="a pilot: this many surveyed insights spread across advice types")
    g.add_argument("--limit", type=int, help="only the first N insights")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-usd", type=float, default=None)
    ap.add_argument("--judge", action="store_true", help="also score each survey with the AI judge (MEL_JUDGE_MODEL)")
    ap.add_argument("--label", default="")
    a = ap.parse_args()

    pack = Pack()
    insights = (stratified_sample(pack.insights, a.sample) if a.sample else
                pack.insights[:a.limit] if a.limit else pack.insights)
    kind = "pilot" if a.sample else "batch" if not a.limit else "partial"
    judge = None
    if a.judge:
        from mel.evaluation.judge import BedrockClient
        judge = BedrockClient()
    guard = None
    if os.environ.get("MEL_GUARDRAIL_ID"):
        from .orchestrator import bedrock_guardrail
        guard = bedrock_guardrail(os.environ["MEL_GUARDRAIL_ID"], os.environ.get("MEL_GUARDRAIL_VERSION", "DRAFT"))
    writer = llm.write_model() if llm.enabled() else None
    print(f"{len(insights)} insights · writer {writer or 'templates only (MEL_USE_LLM is off)'} · "
          f"{a.workers} workers" + (f" · cap ${a.max_usd:.2f}" if a.max_usd is not None else ""))
    t0 = time.perf_counter()
    results, meter, stopped = run_batch(insights, pack, workers=a.workers, max_usd=a.max_usd, judge=judge,
                                        guardrail=guard)
    secs = round(time.perf_counter() - t0, 1)
    run_dir = OUT / "agent_batch" / time.strftime("%Y%m%dT%H%M%S")
    _write_files(results, run_dir)
    summary = summarise(results, insights)
    row = row_from_results(kind, a.label or kind, meter, [r for r in results if r is not None],
                           writer=writer, checker=llm.check_model() or None,
                           judge=getattr(judge, "model_id", None), seconds=secs, stopped_at_cap=stopped,
                           max_usd=a.max_usd, judge_relevance=summary["judge_relevance"])
    if writer:
        rec = record_cost(row)
    else:                                  # templates only: nothing was paid for, so nothing goes in the ledger
        rec = {**row, "run": "-"}
    if kind == "batch" and writer:
        FULL_SUMMARY.write_text(json.dumps({"label": rec["label"], "at": rec["at"], "commit": rec["commit"],
                                            "writer": writer, "judge": row["judge"], "seconds": secs,
                                            "stopped_at_cap": stopped, "cost": {k: rec.get(k) for k in (
                                                "spent_usd", "usd_per_survey", "usd_per_1000_surveys",
                                                "projected_full_usd", "calls", "cached_calls", "failed_calls",
                                                "input_tokens", "output_tokens", "by_purpose")},
                                            **summary}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nDone in {secs:.0f} s{' (STOPPED AT THE BUDGET CAP: run again to finish)' if stopped else ''}.")
    print(f"Surveys {summary['surveys']} ({summary['files']} files, {summary['schema_invalid_files']} schema-invalid) "
          f"· sources {summary['sources']}")
    print(f"Revisions {summary['revisions']} on {summary['surveys_revised']} surveys · fallbacks {summary['fallbacks']}")
    if summary["judge_relevance"] is not None:
        print(f"AI judge relevance {summary['judge_relevance']} · by advice type {summary['judge_by_advice_type']}")
    print(f"Spent ${rec['spent_usd']:.4f} on {rec['calls']} model calls ({rec['cached_calls']} from cache, "
          f"{rec['failed_calls']} failed, {rec['unpriced_calls']} unpriced) · by purpose "
          + ", ".join(f"{k} ${v['usd']:.4f}" for k, v in rec["by_purpose"].items()))
    if rec.get("usd_per_survey") is not None:
        print(f"Cost per survey ${rec['usd_per_survey']:.5f} (both languages) · per 1,000 ${rec['usd_per_1000_surveys']:.2f}"
              f" · projected full dataset ({FULL_SET_SURVEYS:,} surveys) ${rec['projected_full_usd']:.2f}")
    print(f"Files in {run_dir.relative_to(ROOT)}"
          + (f" · ledger row {rec['run']} in docs/results/cost_history.jsonl" if writer else
             " · not added to the cost ledger (templates only, $0)")
          + (" · summary docs/results/full_bedrock_run.json" if kind == "batch" and writer else ""))


if __name__ == "__main__":
    main()
