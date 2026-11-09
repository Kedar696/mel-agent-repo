"""Measure the activity-attention change on the full pack: run the pipeline with attention OFF and ON and
report the before/after. Owner: P1 (with P5 for the Evaluation tab). Writes:
  docs/results/activity_attention.md    human-readable before/after, naming the representative's request
  docs/results/activity_attention.json  the same numbers for the app's Evaluation tab

Run:  python scripts/activity_report.py
      MEL_DATA_DIR=mel-survey-agent-participant-pack/participant-pack/data python scripts/activity_report.py

This is reporting only: it never changes a decision, the rule, or the send window (asserted below).
The thresholds in config/activity_attention.json are starting values; adjust them with the evidence here.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mel.config import ROOT
from mel.data import load_insights, load_farmers
from mel.evaluation.golden import item_similarity
from mel.evaluation.scorecard import run_scorecard
from mel.pipeline import run_pipeline, clean

RESULTS = ROOT / "docs" / "results"
REASON = "the beneficiary's representative asked us to focus survey attention on positive CHANGE in a farmer's activity, not on high activity itself"


def _by_activity(insights, outputs, farmers):
    """Tier/reason counts and average questions per survey, broken down by farmers.csv activity_level."""
    tier = defaultdict(Counter)
    reason = defaultdict(Counter)
    q_sum = defaultdict(int)
    q_n = defaultdict(int)
    for ins, out in zip(insights, outputs):
        al = (farmers.get(ins.get("farmer_id")) or {}).get("activity_level", "unknown")
        att = getattr(out["decision"], "attention", None)
        if att:
            tier[al][att["tier"]] += 1
            reason[al][att["reason"]] += 1
        if "handoff" in out:
            q_sum[al] += len(out["handoff"]["survey"]["items"])
            q_n[al] += 1
    avg_q = {al: round(q_sum[al] / q_n[al], 3) for al in q_n}
    return ({al: dict(c) for al, c in tier.items()}, {al: dict(c) for al, c in reason.items()}, avg_q)


def _priority_counts(outputs):
    return dict(Counter(o["handoff"]["priority"] for o in outputs if "handoff" in o))


def _cap_counts(outputs):
    """Replay the weekly cap in send order (P3's CapLedger.admit), as the app does, to report sent/moved/..."""
    import copy
    from mel.schedule import CapLedger

    hs = sorted(
        (copy.deepcopy(o["handoff"]) for o in outputs if "handoff" in o),
        key=lambda h: (h["send_window"]["not_before"], h["created_at"], h["frequency_cap"]["key"]),
    )
    led, c = CapLedger(), Counter()
    for h in hs:
        c[led.admit(h).decision] += 1
    return dict(c)


def _golden_metrics(insights, attention):
    """Decision/rule/channel accuracy and item similarity on the golden set, with attention off or on.

    Attention is computed from the FULL insight list (`insights`), so each golden row is scored with its real
    history, not against the 150-row golden subset alone. We then look up each golden row's output by
    insight_id. History stays off here, matching how `mel.cli eval` scores the golden set; the item-similarity
    drop with attention on therefore reflects attention's question-count changes (steady_high trims to 2)
    measured against the golden set's generic expected items."""
    from mel.data import load_golden

    golden = load_golden()
    res = run_pipeline(insights, attention=attention)
    by_id = {i.get("insight_id"): o for i, o in zip(res.insights, res.outputs)}
    hits = Counter()
    sims = []
    for g in golden:
        exp = g["expected"]
        gid = g["insight"]["insight_id"]
        out = by_id.get(gid)
        if out is None:  # a golden row not in the full pack: score it on its own (no history)
            out = run_pipeline([g["insight"]], attention=attention).outputs[0]
        d = out["decision"]
        hits["decision"] += d.survey == exp["survey"]
        hits["rule"] += d.rule == exp.get("rule")
        if exp["survey"] and d.survey:
            hits["survey_rows"] += 1
            hits["channel"] += out["handoff"]["channel_order"][0]["channel"] == exp.get("channel")
            if exp.get("items"):
                our = clean(out.get("surveys", {}).get("en-IN") or out.get("surveys", {}).get("hi-IN", {}))
                sims.append(item_similarity(our, exp["items"]))
    n = len(golden)
    sr = max(hits["survey_rows"], 1)
    return {
        "n": n,
        "decision_acc": round(hits["decision"] / n, 4),
        "rule_acc": round(hits["rule"] / n, 4),
        "channel_acc": round(hits["channel"] / sr, 4),
        "item_similarity_avg": round(sum(sims) / len(sims), 3) if sims else 0.0,
    }


def _scorecard(insights, attention):
    """Reuse P5's scorecard. It calls run_insight directly, so pass attention per-insight from a full run."""
    res = run_pipeline(insights, attention=attention)
    att_by_id = {
        i.get("insight_id"): getattr(o["decision"], "attention", None) for i, o in zip(res.insights, res.outputs)
    }
    # run_scorecard uses run_insight(ins, memory=...); wrap it so attention is applied per insight.
    from mel.evaluation import scorecard as sc

    orig = sc.run_insight

    def patched(ins, farmer=None, history_hours=(), memory=None, attention=None):
        return orig(ins, farmer, history_hours, memory, att_by_id.get(ins.get("insight_id")))

    sc.run_insight = patched
    try:
        card = run_scorecard(insights)
    finally:
        sc.run_insight = orig
    return {
        k: card[k]
        for k in (
            "format_pass",
            "safety_pass",
            "timeliness_pass",
            "failed_but_scheduled",
            "n_surveyed",
            "relevance_avg",
        )
    }


def measure():
    insights = load_insights()
    farmers = load_farmers()
    off = run_pipeline(insights, farmers=farmers)
    on = run_pipeline(insights, farmers=farmers, attention=True)

    # Invariant: attention never changes survey vs no-survey, the rule, or the send window.
    for a, b in zip(off.outputs, on.outputs):
        assert a["decision"].survey == b["decision"].survey
        assert a["decision"].rule == b["decision"].rule
        if a["decision"].survey:
            assert a["decision"].send_window == b["decision"].send_window

    tier_on, reason_on, avgq_on = _by_activity(on.insights, on.outputs, farmers)
    _, _, avgq_off = _by_activity(off.insights, off.outputs, farmers)

    # The app runs with BOTH history and attention on, so also report average questions per survey that way,
    # alongside history-on/attention-off for a fair comparison (history alone changes the question counts).
    off_hist = run_pipeline(insights, farmers=farmers, history=True)
    _, _, avgq_off_history = _by_activity(off_hist.insights, off_hist.outputs, farmers)
    on_hist = run_pipeline(insights, farmers=farmers, history=True, attention=True)
    _, _, avgq_on_history = _by_activity(on_hist.insights, on_hist.outputs, farmers)

    return {
        "reason": REASON,
        "n_insights": off.rows_processed,
        "tier_by_activity": tier_on,
        "reason_by_activity": reason_on,
        "tier_totals": dict(Counter(t for al in tier_on.values() for t, n in al.items() for _ in range(n))),
        "reason_totals": dict(Counter(r for al in reason_on.values() for r, n in al.items() for _ in range(n))),
        "priority_off": _priority_counts(off.outputs),
        "priority_on": _priority_counts(on.outputs),
        "cap_off": _cap_counts(off.outputs),
        "cap_on": _cap_counts(on.outputs),
        "avg_questions_off": avgq_off,
        "avg_questions_on": avgq_on,
        "avg_questions_off_history": avgq_off_history,
        "avg_questions_on_history": avgq_on_history,
        "golden_off": _golden_metrics(insights, False),
        "golden_on": _golden_metrics(insights, True),
        "scorecard_off": _scorecard(insights, False),
        "scorecard_on": _scorecard(insights, True),
    }


def _table(title, off, on, keys=None):
    keys = keys or sorted(set(off) | set(on))
    lines = [f"### {title}", "", "| | off | on |", "|---|---|---|"]
    for k in keys:
        lines.append(f"| {k} | {off.get(k, 0)} | {on.get(k, 0)} |")
    return "\n".join(lines) + "\n"


def write_report(m):
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "activity_attention.json").write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")

    md = [
        "# Activity attention: before / after\n",
        f"**Why this change:** {m['reason']}. Per `CLAUDE.md`, a deliberate change to the brief is shown "
        f"with numbers. Attention is OFF by default (scoring and the CLI) and ON in the app.\n",
        f"Full pack: **{m['n_insights']:,} insights**.\n",
        "## Tiers and reasons (attention on)\n",
        "### Tier totals\n",
        "| tier | count |",
        "|---|---|",
        *[f"| {t} | {n} |" for t, n in sorted(m["tier_totals"].items())],
        "",
        "### Reason totals\n",
        "| reason | count |",
        "|---|---|",
        *[f"| {r} | {n} |" for r, n in sorted(m["reason_totals"].items())],
        "",
        "### Tier by activity_level (attention on)\n",
        "| activity_level | " + " | ".join(("surge", "neutral", "steady_high")) + " |",
        "|---|---|---|---|",
    ]
    for al in sorted(m["tier_by_activity"]):
        c = m["tier_by_activity"][al]
        md.append(f"| {al} | {c.get('surge', 0)} | {c.get('neutral', 0)} | {c.get('steady_high', 0)} |")
    md += [
        "",
        _table("Priority counts", m["priority_off"], m["priority_on"], ["high", "normal", "low"]),
        _table(
            "Weekly cap (sent / moved / merged / skipped / opted_out)",
            m["cap_off"],
            m["cap_on"],
            ["sent", "moved", "merged", "skipped", "opted_out"],
        ),
        "### Average questions per survey, by activity_level\n",
        "`on + history` is how the app runs (both history rules and attention on); compare it with "
        "`off + history`, since history alone changes the question counts.\n",
        "| activity_level | off | on | off + history | on + history |",
        "|---|---|---|---|---|",
    ]
    for al in sorted(set(m["avg_questions_off"]) | set(m["avg_questions_on"])):
        md.append(
            f"| {al} | {m['avg_questions_off'].get(al, '—')} | {m['avg_questions_on'].get(al, '—')} "
            f"| {m.get('avg_questions_off_history', {}).get(al, '—')} "
            f"| {m.get('avg_questions_on_history', {}).get(al, '—')} |"
        )
    md += [
        "",
        "### Golden set (decision / rule / channel / item similarity)\n",
        "| metric | off | on |",
        "|---|---|---|",
        f"| decision_acc | {m['golden_off']['decision_acc']:.1%} | {m['golden_on']['decision_acc']:.1%} |",
        f"| rule_acc | {m['golden_off']['rule_acc']:.1%} | {m['golden_on']['rule_acc']:.1%} |",
        f"| channel_acc | {m['golden_off']['channel_acc']:.1%} | {m['golden_on']['channel_acc']:.1%} |",
        f"| item_similarity_avg | {m['golden_off']['item_similarity_avg']} | {m['golden_on']['item_similarity_avg']} |",
        "",
        "### Scorecard (format / safety / timeliness must stay 100%)\n",
        "| metric | off | on |",
        "|---|---|---|",
        f"| format_pass | {m['scorecard_off']['format_pass']:.1%} | {m['scorecard_on']['format_pass']:.1%} |",
        f"| safety_pass | {m['scorecard_off']['safety_pass']:.1%} | {m['scorecard_on']['safety_pass']:.1%} |",
        f"| timeliness_pass | {m['scorecard_off']['timeliness_pass']:.1%} | {m['scorecard_on']['timeliness_pass']:.1%} |",
        f"| failed_but_scheduled | {m['scorecard_off']['failed_but_scheduled']} | {m['scorecard_on']['failed_but_scheduled']} |",
        "",
        "## Notes\n",
        "- Decision, rule and send window are identical off vs on (asserted in this script and in "
        "`tests/test_activity.py`): attention only moves priority, question count and the send moment.",
        "- A prototype on raw data flagged far more (≈109 quiet_then_high_weight, ≈63 activity_jump, ≈303 "
        "steady_high); those did not go through the real pipeline (which drops junk, counts distinct "
        "conversations, and respects the 28-day/dataset-start rule), so the real counts are lower. The "
        "thresholds in `config/activity_attention.json` are starting values to adjust with this evidence.",
        "",
    ]
    (RESULTS / "activity_attention.md").write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {RESULTS / 'activity_attention.md'} and .json")
    print(f"tier totals: {m['tier_totals']}")
    print(
        f"format/safety/timeliness on: {m['scorecard_on']['format_pass']:.1%} / "
        f"{m['scorecard_on']['safety_pass']:.1%} / {m['scorecard_on']['timeliness_pass']:.1%}"
    )


if __name__ == "__main__":
    write_report(measure())
