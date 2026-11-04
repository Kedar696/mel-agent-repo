"""Templates vs Bedrock on a sample of surveys (one table for P5). Owner: P4.

For each model we ask for the English baseline survey of the same insights and measure the RAW model output, before any
fallback: guard pass rate (guards + the 2-vs-3 count), mean relevance, tokens, cost and seconds. Templates are the reference row.
If Bedrock is not switched on the table says so; it never invents numbers.
Run:  python scripts/p4_compare.py            (needs MEL_USE_LLM=1 and the model ids, see mel/writer/llm.py)
"""
import time

from . import llm
from .compose import _base, BASELINE_LANG
from .guards import check_survey
from .relevance import relevance
from .templates import template_items, question_count


def sample_insights(insights, decide, n=50):
    """The first n insights that get a survey, spread evenly over the file so one crop does not dominate."""
    picked = [(i, d) for i in insights if (d := decide(i)).survey]
    step = max(1, len(picked) // n)
    return picked[::step][:n]


def _row(name, n, passed, rel, usage_after=None, usage_before=None, seconds=0.0):
    row = {"writer": name, "surveys": n, "guard_pass_rate": round(passed / n, 3) if n else None,
           "mean_relevance": round(sum(rel) / n, 3) if n else None, "seconds": round(seconds, 2)}
    if usage_after is not None:
        a, b = usage_after, usage_before or {}
        row |= {"calls": a.get("calls", 0) - b.get("calls", 0), "input_tokens": a.get("input_tokens", 0) - b.get("input_tokens", 0),
                "output_tokens": a.get("output_tokens", 0) - b.get("output_tokens", 0),
                "cost_usd": round(a.get("cost_usd", 0) - b.get("cost_usd", 0), 6)}
    return row


def compare(pairs, models: dict[str, str]) -> dict:
    """pairs = [(insight, decision)]; models = {'large': model id, 'small': model id}. -> {'status', 'rows', 'note'}."""
    rows, rel_t, ok_t = [], [], 0
    t0 = time.perf_counter()
    for i, d in pairs:
        base = _base(i, BASELINE_LANG, d.send_window)
        s = base | {"items": template_items(i, BASELINE_LANG)}
        ok_t += not check_survey(s); rel_t.append(relevance(s, i))
    rows.append(_row("templates", len(pairs), ok_t, rel_t, seconds=time.perf_counter() - t0))
    if not llm.enabled():
        return {"status": "not run", "rows": rows, "note": "Bedrock is off. Set MEL_USE_LLM=1, MEL_BEDROCK_WRITE_MODEL and MEL_BEDROCK_REGION to run the model rows."}
    for label, model_id in models.items():
        before, ok, rel, t0 = llm.usage_summary()["by_model"].get(model_id, {}), 0, [], time.perf_counter()
        for i, d in pairs:
            items = llm.llm_items(i, BASELINE_LANG, n_items=question_count(i), model_id=model_id)
            if items and len(items) == question_count(i):
                s = _base(i, BASELINE_LANG, d.send_window) | {"items": items}
                good = not check_survey(s)
                ok += good; rel.append(relevance(s, i) if good else 0.0)    # an unusable answer scores 0, so the mean is honest
            else:
                rel.append(0.0)
        after = llm.usage_summary()["by_model"].get(model_id, {})
        rows.append(_row(f"bedrock {label} ({model_id})", len(pairs), ok, rel, after, before, time.perf_counter() - t0))
    return {"status": "run", "rows": rows, "note": "Raw model output before fallback. relevance counts unusable answers as 0. Cost is 0 where no price was configured (MEL_BEDROCK_PRICES)."}


def markdown(result: dict) -> str:
    cols = ["writer", "surveys", "guard_pass_rate", "mean_relevance", "calls", "input_tokens", "output_tokens", "cost_usd", "seconds"]
    out = [f"Templates vs Bedrock (English baseline): {result['status']}", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in result["rows"]:
        out.append("| " + " | ".join(str(r.get(c, "-")) for c in cols) + " |")
    return "\n".join(out + ["", result["note"]])
