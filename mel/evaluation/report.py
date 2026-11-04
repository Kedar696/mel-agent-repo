"""One entry point for every published number. Owner: P5.

    run_eval()                       score both timing rules: golden set (full + mock) and batch scorecard
    run_eval(record="what changed")  ...and append a row per timing rule to the run history
    write_outputs(results)           rewrite the README results block and docs/results/scorecard.md

Used by scripts/readme_numbers.py and the app. P1 can call run_eval() from `mel.cli eval` so every
eval run lands in the history (team contract, P5 H+12).
"""
import os
import re
from contextlib import contextmanager

from mel.config import PACK_DATA, ROOT
from mel.data import load_golden, load_insights

from .golden import score_golden
from .history import load_history, record_run
from .scorecard import run_scorecard

BASES = ("brief", "answer_key")
BASIS_LABEL = {"brief": "Brief rules (default)", "answer_key": "Answer-key setting"}
README = ROOT / "README.md"
SCORECARD = ROOT / "docs" / "results" / "scorecard.md"
START, END = "<!-- results:start -->", "<!-- results:end -->"


@contextmanager
def timing_basis(basis: str):
    """Temporarily select P2's send-window rule (mel.timing reads MEL_TIMING_BASIS on every call)."""
    old = os.environ.get("MEL_TIMING_BASIS")
    os.environ["MEL_TIMING_BASIS"] = basis
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("MEL_TIMING_BASIS", None)
        else:
            os.environ["MEL_TIMING_BASIS"] = old


def evaluate(basis: str = "brief") -> dict:
    """Golden set (full pack if present, and the mock subset) plus the batch scorecard, under one timing rule."""
    full_path, ins_path = PACK_DATA / "golden_set.jsonl", PACK_DATA / "insights.jsonl"
    with timing_basis(basis):
        mock = score_golden()
        full = score_golden(load_golden(full_path)) if full_path.exists() else None
        card = run_scorecard(load_insights(ins_path if ins_path.exists() else None))
    return {"basis": basis, "full": full, "mock": mock, "card": card}


def run_eval(bases=BASES, record: str | None = None) -> dict:
    """Score each timing rule in `bases`; with `record`, append one history row per rule."""
    results = {b: evaluate(b) for b in bases}
    if record:
        for b, r in results.items():
            record_run(record, r["full"] or r["mock"], r["card"], timing_basis=b)
    return results


# ---------------------------------------------------------------- text output

def pct(x):
    return "—" if x is None else f"{x:.1%}"


def rules_changed(history: list[dict] | None = None) -> list[dict]:
    """Each recorded run compared with the run before it: the 'Rules we changed' list, never typed."""
    hist = load_history() if history is None else history
    out = []
    for prev, cur in zip(hist, hist[1:]):
        out.append({"run": cur["run"], "change": cur["label"], "timing_basis": cur["timing_basis"],
                    **{k: (prev.get(k), cur.get(k)) for k in
                       ("decision_acc", "rule_acc", "window_acc", "timeliness_pass", "misses")}})
    return out


def _arrow(pair, as_pct=True):
    a, b = pair
    f = pct if as_pct else (lambda v: "—" if v is None else str(v))
    return f(b) if a == b else f"{f(a)} → {f(b)}"


def rules_changed_md() -> str:
    rows = rules_changed()
    if not rows:
        return "_Only the baseline run so far._"
    out = ["| Run | What changed | Timing rule | Decision | Rule | Window match | Timeliness | Misses |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['run']} | {r['change']} | {BASIS_LABEL.get(r['timing_basis'], r['timing_basis'])} "
                   f"| {_arrow(r['decision_acc'])} | {_arrow(r['rule_acc'])} | {_arrow(r['window_acc'])} "
                   f"| {_arrow(r['timeliness_pass'])} | {_arrow(r['misses'], as_pct=False)} |")
    return "\n".join(out)


def history_md() -> str:
    hist = load_history()
    if not hist:
        return "_No recorded runs yet._"
    out = ["| Run | When | Commit | What changed | Timing rule | Decision | Rule | Window | Timeliness | Item sim | Misses |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for h in hist:
        out.append(f"| {h['run']} | {h['at'][:16].replace('T', ' ')} | `{h['commit']}`{'*' if h.get('uncommitted_changes') else ''} "
                   f"| {h['label']} | {h['timing_basis']} | {pct(h['decision_acc'])} | {pct(h['rule_acc'])} "
                   f"| {pct(h['window_acc'])} | {pct(h.get('timeliness_pass'))} | {h['item_similarity_avg']:.2f} | {h['misses']} |")
    out += ["", "`*` = the eval code itself had uncommitted changes when this run was recorded."]
    return "\n".join(out)


def results_md(results: dict) -> str:
    bases = [b for b in BASES if b in results]
    hdr = " | ".join(BASIS_LABEL[b] for b in bases)
    g = {b: results[b]["full"] or results[b]["mock"] for b in bases}
    c = {b: results[b]["card"] for b in bases}
    first = results[bases[0]]
    n_full = g[bases[0]]["n"]

    def row(label, fn):
        return f"| {label} | " + " | ".join(fn(b) for b in bases) + " |"

    out = [f"**Answer key** ({n_full} rows{'' if first['full'] else ', mock subset'}), under each send-time rule.", "",
           f"| Measure | {hdr} |", "|---" * (len(bases) + 1) + "|",
           row("Decision (survey or not)", lambda b: pct(g[b]["decision_acc"])),
           row("Rule (which of R1–R8)", lambda b: pct(g[b]["rule_acc"])),
           row("First channel", lambda b: pct(g[b]["channel_acc"])),
           row("Send window (exact match with answer key)", lambda b: pct(g[b]["window_acc"])),
           row("Item similarity (keyword overlap)", lambda b: f"{g[b]['item_similarity_avg']:.2f}"),
           row("Misses", lambda b: str(len(g[b]["misses"]))),
           "", f"**Every survey we write** ({c[bases[0]]['n_insights']:,} insights; Hindi + English files).", "",
           f"| Measure | {hdr} |", "|---" * (len(bases) + 1) + "|",
           row("Surveys (files)", lambda b: f"{c[b]['n_surveyed']:,} ({c[b]['n_survey_files']:,})"),
           row("Format (schema, 1–3 tap items, right language)", lambda b: pct(c[b]["format_pass"])),
           row("Safety (no new advice, no personal info)", lambda b: pct(c[b]["safety_pass"])),
           row("Timeliness (after the action window, 07:00–19:00, in season, before harvest)",
               lambda b: pct(c[b]["timeliness_pass"])),
           row("Failing surveys handed to the scheduler", lambda b: str(c[b]["failed_but_scheduled"])),
           row("Relevance (P4's score, 0–1)", lambda b: f"{c[b]['relevance_avg']:.2f}"),
           row("Speed", lambda b: f"{c[b]['s_per_survey'] * 1000:.1f} ms per survey · {c[b]['batch_seconds']:.0f} s for all"),
           "", "**Rules we changed** (each recorded run vs the one before it)", "", rules_changed_md()]
    misses = g[bases[0]]["misses"]
    if misses:
        out += ["", f"Misses under {BASIS_LABEL[bases[0]].lower()}: " + ", ".join(
            f"{m['golden_id']} (expected {m['expected']}, got {m['got']})" for m in misses)]
    out += ["", "_Generated by `python scripts/readme_numbers.py --write`. Do not edit by hand._"]
    return "\n".join(out)


def write_outputs(results: dict) -> list:
    """Rewrite the README results block and the offline scorecard. Returns the paths written."""
    body = results_md(results)
    text = README.read_text(encoding="utf-8")
    block = f"{START}\n{body}\n{END}"
    if START in text and END in text:
        text = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, text, flags=re.S)
    else:
        text = text.rstrip() + "\n\n## Results\n" + block + "\n"
    README.write_text(text, encoding="utf-8")

    card = results[next(iter(results))]["card"]
    fails = "\n".join(f"- {e['insight_id']} ({e['language']}): {'; '.join(e['problems'])}"
                      for e in card["examples"]) or "None."
    late = {b: r["card"]["timeliness_examples"] for b, r in results.items()}
    late_md = "\n".join(f"- **{BASIS_LABEL[b]}**: " + ("none" if not ex else "; ".join(
        f"{e['insight_id']}: {e['problems'][0]}" for e in ex[:5])) for b, ex in late.items())
    SCORECARD.parent.mkdir(parents=True, exist_ok=True)
    SCORECARD.write_text(
        "# MEL Survey Agent: offline scorecard\n\n"
        "Backup for the demo: open this file if the app won't start. Same numbers as the Evaluation tab.\n\n"
        f"{body}\n\n## Run history (hill-climb)\n\n{history_md()}\n\n"
        f"## Surveys that failed format or safety (first {len(card['examples'])})\n\n{fails}\n\n"
        f"## Send windows that failed timeliness (first 5 per rule)\n\n{late_md}\n", encoding="utf-8")
    return [README, SCORECARD]
