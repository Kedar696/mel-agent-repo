"""Quality scorecard over a whole batch of insights. Owner: P5.

Covers the dimensions Digital Green's technical brief asks for that don't need an answer key:
  format  - schema-valid, 1-3 tap-answer items, text in the right language (Hindi has Devanagari,
            English has none)
  safety  - no new advice, no personal-information request (P4's guards in mel/writer/guards.py)
  timeliness - every send window: opens after the farmer could act (action window over), only
            between 07:00 and 19:00, closes by season end, and (for standing crops) before harvest.
            Independent of which timing rule is active; the exact match vs the answer key is in golden.py.
  gate    - surveys that fail format or safety but still got a scheduler hand-off (target 0)
  speed   - seconds per survey, ms per insight, and seconds for the whole batch
  relevance - P4's relevance_score, averaged (reported here, owned and improved by P4)

Relevance against the answer key (item similarity) and exact window match are in golden.py.
"""

import re
import time
from datetime import date, time as clock, timedelta

from mel.config import rules
from mel.data import errors
from mel.pipeline import run_insight, clean
from mel.writer import check_survey
from mel.timing import parse_ist, is_past_harvest
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


def timeliness_problems(insight: dict, window: dict) -> list[str]:
    """Is this send window sensible for this farmer? Uses the brief's principles, not the answer key."""
    wr = rules()["window_rules"]
    nb, na = parse_ist(window["not_before"]), parse_ist(window["not_after"])
    created = parse_ist(insight["created_at"]).date()
    aw = insight.get("action_window_days")
    aw = wr["action_window_days_if_null"] if aw is None else aw
    probs = []
    if nb.date() < created + timedelta(days=aw):
        probs.append(f"opens {nb.date()} before the action window ends ({created + timedelta(days=aw)})")
    open_t, close_t = clock.fromisoformat(wr["not_before_time"]), clock.fromisoformat(wr["not_after_time"])
    if nb.time() < open_t or nb.time() > close_t:
        probs.append(f"opens at {nb.time():%H:%M}, outside {open_t:%H:%M}-{close_t:%H:%M}")
    if na.time() > close_t or na.time() < open_t:
        probs.append(f"closes at {na.time():%H:%M}, outside {open_t:%H:%M}-{close_t:%H:%M}")
    if na.date() > date.fromisoformat(wr["season_end"]):
        probs.append(f"closes {na.date()} after the season ends")
    asset = insight.get("asset") or {}
    storage = asset.get("growth_stage") == "post_harvest" or insight.get("concern") == "storage_post_harvest"
    if asset.get("category") == "crop" and not storage and is_past_harvest(asset.get("name"), nb.date()):
        probs.append(f"opens {nb.date()} after the {asset.get('name')} harvest")
    return probs


def run_scorecard(insights: list[dict], max_examples: int = 20, memory=None) -> dict:
    """Run the pipeline over `insights` and score every survey it writes. Deterministic except timing."""
    n_surveyed = n_files = fmt_ok = safe_ok = handoff_ok = gated_leak = timely_ok = 0
    rel = []
    examples, late_examples = [], []
    t0 = time.perf_counter()
    for ins in insights:
        out = run_insight(ins, memory=memory)
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
            tp = timeliness_problems(ins, out["handoff"]["send_window"])
            timely_ok += not tp
            if tp and len(late_examples) < max_examples:
                late_examples.append({"insight_id": ins.get("insight_id"), "problems": tp})
            gated_leak += bad_any
    secs = time.perf_counter() - t0
    n = len(insights)
    files = max(n_files, 1)
    return {
        "n_insights": n,
        "n_surveyed": n_surveyed,
        "n_survey_files": n_files,
        "format_pass": fmt_ok / files,
        "safety_pass": safe_ok / files,
        "handoff_valid": handoff_ok / max(n_surveyed, 1),
        "failed_but_scheduled": gated_leak,
        "timeliness_pass": timely_ok / max(n_surveyed, 1),
        "relevance_avg": round(sum(rel) / len(rel), 2) if rel else 0.0,
        "batch_seconds": round(secs, 2),
        "ms_per_insight": round(secs / max(n, 1) * 1000, 2),
        "s_per_survey": round(secs / max(n_surveyed, 1), 4),
        "examples": examples,
        "timeliness_examples": late_examples,
    }
