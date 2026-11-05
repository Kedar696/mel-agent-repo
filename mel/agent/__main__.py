"""Run the agent from the command line, or record runs for the app. Owner: P5.

    python -m mel.agent I-001253                    run one conversation, print each step
    python -m mel.agent --record                    record the Survey demo's picks into docs/results/agent_runs/
    python -m mel.agent --record I-001253 I-001645  record these
    python -m mel.agent --remote ARN I-001253       run it on Amazon Bedrock AgentCore instead (prints the stream)

With MEL_USE_LLM=1 and the Bedrock model settings the Analyst writes with Bedrock; MEL_GUARDRAIL_ID adds Bedrock
Guardrails and MEL_AGENT_JUDGE=1 (with MEL_JUDGE_MODEL) the AI judge to the Verifier. Recorded runs are committed so
the hosted app (no AWS keys) can show a real Bedrock run.
"""
import argparse
import json
import os
import sys
import time

from mel.config import ROOT

RUNS = ROOT / "docs" / "results" / "agent_runs"
DEMO_PICKS = ["I-001253", "I-001645", "I-005625", "I-001996", "I-000291"]   # the app's Survey demo picks


def _inputs(insight_id):
    from mel.config import PACK_DATA
    from mel.data import load_insights, load_farmers
    from mel.timing import chat_hours
    pack = (PACK_DATA / "insights.jsonl").exists() and not os.environ.get("MEL_DATA_DIR")
    insights = load_insights(PACK_DATA / "insights.jsonl" if pack else None)
    farmers = load_farmers(PACK_DATA / "farmers.csv" if pack else None)
    ins = next((i for i in insights if i.get("insight_id") == insight_id), None)
    if ins is None:
        sys.exit(f"unknown insight {insight_id}")
    same = [i for i in insights if i.get("farmer_id") == ins.get("farmer_id")]
    return ins, {"farmer": farmers.get(ins.get("farmer_id")),
                 "history_hours": chat_hours(same, ins.get("farmer_id"), ins.get("created_at"))}


def _extras():
    from mel.agent import bedrock_guardrail
    kw = {}
    if os.environ.get("MEL_GUARDRAIL_ID"):
        kw["guardrail"] = bedrock_guardrail(os.environ["MEL_GUARDRAIL_ID"], os.environ.get("MEL_GUARDRAIL_VERSION", "DRAFT"))
    if os.environ.get("MEL_AGENT_JUDGE") == "1":
        from mel.evaluation.judge import BedrockClient
        kw["judge"] = BedrockClient()
    return kw


def _print(e):
    if e["step"] == "result":
        print("result:", json.dumps(e.get("metrics"), ensure_ascii=False))
        return
    print(f"[{e['step']:<11}] {'ok ' if e['status'] == 'ok' else 'FAIL'} {e['title']}"
          + (f" ({e['ms']:.0f} ms)" if e.get("ms") is not None else ""))
    for q in (e.get("data") or {}).get("questions") or []:
        print("      -", q)
    for p in (e.get("data") or {}).get("problems") or []:
        print("      x", p)
    if e["detail"] and e["step"] not in ("verifier",):
        print("     ", e["detail"][:200])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("insight_ids", nargs="*")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--remote", metavar="ARN")
    a = ap.parse_args()
    from mel.agent import run_agent
    from mel.writer import llm
    ids = a.insight_ids or (DEMO_PICKS if a.record else [])
    if not ids:
        ap.error("give an insight id (or --record for the demo picks)")
    for iid in ids:
        ins, inputs = _inputs(iid)
        if a.remote:
            from mel.agent.remote import invoke
            stream = invoke(a.remote, {"insight": ins})
        else:
            stream = run_agent(ins, memory=None, **inputs, **_extras())
        events = []
        print(f"\n=== {iid}")
        for e in stream:
            events.append(e)
            _print(e)
        if a.record:
            RUNS.mkdir(parents=True, exist_ok=True)
            judge = os.environ.get("MEL_JUDGE_MODEL") if os.environ.get("MEL_AGENT_JUDGE") == "1" else None
            rec = {"insight_id": iid, "recorded": time.strftime("%Y-%m-%d %H:%M"),
                   "where": "agentcore" if a.remote else "local",
                   "writer": llm.write_model() if llm.enabled() else None, "checker": llm.check_model() or None,
                   "judge": judge, "guardrail": os.environ.get("MEL_GUARDRAIL_ID") or None, "events": events}
            (RUNS / f"{iid}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(f"recorded -> {(RUNS / f'{iid}.json').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
