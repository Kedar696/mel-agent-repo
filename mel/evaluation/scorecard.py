"""Quality scorecard over a whole batch of insights. Owner: P5.

Covers the dimensions Digital Green's technical brief asks for that don't need an answer key:
  format  - schema-valid, 1-3 tap-answer items, text in the right language (Hindi has Devanagari,
            English has none)
  safety  - no new advice, no personal-information request (P4's guards in mel/writer/guards.py)
  gate    - surveys that fail format or safety but still got a scheduler hand-off (target 0)
  speed   - time per insight and for the whole batch
  relevance - P4's relevance_score, averaged (reported here, owned and improved by P4)

Relevance against the answer key (item similarity) and timeliness (window match) are in golden.py.
"""
import re
import time

from mel.data import errors
from mel.pipeline import run_insight, clean
from mel.writer import check_survey
from mel.writer.guards import relevance_score

TAP_TYPES = {"survey-single-select", "survey-confirm", "survey-scale"}
DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def format_problems(survey: dict, lang: str) -> list[str]:
    """Format checks beyond the schema: item count, tap-answerable types, language of the text."""
    probs = [f"schema: {e}" for e in errors("survey", survey)]
    items = survey.get("items", [])
    if not 1 <= len(items) <= 3:
        probs.append(f"item count {len(items)} (want 1-3)")
    if survey.get("language") != lang:
        probs.append(f"language field {survey.get('language')!r} (want {lang})")
    for it in items:
        if it.get("type") not in TAP_TYPES:
            probs.append(f"{it.get('item_id')}: not tap-answerable ({it.get('type')})")
        text = it.get("prompt", "") + " ".join(str(o.get("label", "")) for o in it.get("options", []))
        has_hi = bool(DEVANAGARI.search(text))
        if lang == "hi-IN" and not has_hi:
            probs.append(f"{it.get('item_id')}: no Hindi text")
        if lang == "en-IN" and has_hi:
            probs.append(f"{it.get('item_id')}: Hindi text in English survey")
    return probs


def safety_problems(survey: dict) -> list[str]:
    return [p for p in check_survey(survey) if "advice" in p or "personal" in p]


def run_scorecard(insights: list[dict], max_examples: int = 20) -> dict:
    """Run the pipeline over `insights` and score every survey it writes. Deterministic except timing."""
    n_surveyed = n_files = fmt_ok = safe_ok = handoff_ok = gated_leak = 0
    rel = []
    examples = []
    t0 = time.perf_counter()
    for ins in insights:
        out = run_insight(ins)
        if not out["decision"].survey:
            continue
        n_surveyed += 1
        bad_any = False
        for lang, s in out["surveys"].items():
            s = clean(s)
            n_files += 1
            fp, sp = format_problems(s, lang), safety_problems(s)
            fmt_ok += not fp
            safe_ok += not sp
            bad_any |= bool(fp or sp)
            if lang == "en-IN":
                rel.append(relevance_score(s, ins))
            if (fp or sp) and len(examples) < max_examples:
                examples.append({"insight_id": ins.get("insight_id"), "language": lang, "problems": fp + sp})
        if "handoff" in out:
            handoff_ok += not errors("schedule_handoff", out["handoff"])
            gated_leak += bad_any
    secs = time.perf_counter() - t0
    n = len(insights)
    files = max(n_files, 1)
    return {
        "n_insights": n, "n_surveyed": n_surveyed, "n_survey_files": n_files,
        "format_pass": fmt_ok / files, "safety_pass": safe_ok / files,
        "handoff_valid": handoff_ok / max(n_surveyed, 1),
        "failed_but_scheduled": gated_leak,
        "relevance_avg": round(sum(rel) / len(rel), 2) if rel else 0.0,
        "batch_seconds": round(secs, 2), "ms_per_insight": round(secs / max(n, 1) * 1000, 2),
        "examples": examples,
    }
