"""Assemble a full survey document per language. Owner: P4.

Contract signatures (Team Contracts, P4):
  compose_survey(decision, insight, lang)  -> Survey      lang is a BCP 47 code: "hi-IN" or "en-IN"
  write_survey_llm(decision, insight, lang)-> Survey | None   Bedrock only; None when off, unreachable or rejected
  write_surveys(insight, send_window)      -> {lang: Survey}  both languages (kept: mel/pipeline.py calls it)

English (en-IN) is the evaluation baseline; Hindi comes from the same code when passed hi-IN.
Every survey carries self_eval: schema_valid, relevance_score, gives_new_advice, asks_personal_info.
"""
import re

from mel.config import LANGS
from . import llm
from .guards import check_survey, self_eval
from .relevance import relevance   # re-exported
from .templates import template_items, question_count, build_items, STYLE

BASELINE_LANG = "en-IN"

RATIONALE = {
    "direct_action": "Direct-action advice. Ask after the action window whether the farmer acted and whether it worked.",
    "wait_and_monitor": "Wait-and-watch advice. Ask right after the watch period whether the problem is growing.",
    "do_not_act": "Advice to hold off. Ask whether the farmer held off and what happened.",
    "plan_created": "A plan was created. Ask whether the first step was followed.",
    "escalate_to_expert": "Sent to an expert. Ask whether the expert was reached and how the crop or animal is.",
}


def survey_id_for(insight: dict) -> str:
    digits = re.sub(r"\D", "", insight["insight_id"]) or "0"
    return f"S-{int(digits):05d}"


def norm_lang(lang: str) -> str:
    """'hi', 'hi-IN', 'hi_in' -> 'hi-IN'; 'en', 'en-IN' -> 'en-IN'. Anything else is an error, never a silent guess."""
    primary = str(lang).replace("_", "-").split("-")[0].lower()
    for known in LANGS:
        if known.split("-")[0] == primary:
            return known
    raise ValueError(f"unsupported language {lang!r}; use one of {LANGS}")


def _window(decision) -> dict:
    """Accepts a Decision object, a dict with 'send_window', or the window dict itself."""
    if isinstance(decision, dict):
        return decision.get("send_window", decision)
    return decision.send_window


def _base(insight: dict, lang: str, send_window: dict) -> dict:
    return {
        "survey_id": survey_id_for(insight), "farmer_id": insight["farmer_id"],
        "source_insight_ids": [insight["insight_id"]], "language": lang,
        "send_window": send_window, "rationale": RATIONALE[insight["resolution_type"]],
    }


def _finish(s: dict, insight: dict, source: str, model: str = "", fallback: str = "") -> dict:
    s["self_eval"] = self_eval(s, insight)
    s["_source"] = source           # keys starting with _ are stripped before writing; the UI reads them
    if model: s["_model"] = model
    if fallback: s["_fallback_reason"] = fallback
    return s


def _try_model(base: dict, insight: dict, lang: str, attention=None, source_items=None) -> tuple[dict | None, str]:
    """-> (survey or None, reason it was not used). The model survey is used only if it passes ALL of:
    guards, relevance at least as good as the template for this insight, and the small-model check (when one is configured).
    `attention` (off by default) feeds question_count so the 2-vs-3 rule and the steady_high cap hold here too.
    `source_items` (the approved English survey) turns the request into a translation (see llm.llm_items)."""
    if not llm.enabled():
        return None, "model_off"
    n = question_count(insight, attention)
    items = llm.llm_items(insight, lang, n_items=n, source_items=source_items)
    if not items:
        return None, "model_unavailable_or_unreadable"
    if len(items) != n:        # the 2-vs-3 rule (and steady_high cap) holds on the model path too
        return None, "wrong_question_count"
    cand = base | {"items": items}
    bad = check_survey(cand)
    if bad:
        return None, "guard:" + ",".join(sorted({p.split(": ")[1].split(" ")[0] for p in bad}))
    template = base | {"items": template_items(insight, lang, attention=attention)}
    if relevance(cand, insight) < relevance(template, insight):
        return None, "less_relevant_than_template"
    opinion = llm.model_check(cand, insight)
    if opinion and any(opinion.values()):
        return None, "model_check:" + ",".join(k for k, v in opinion.items() if v)
    return cand, ""


def write_survey_llm(decision, insight: dict, lang: str = BASELINE_LANG) -> dict | None:
    """The Bedrock-written survey after every check, or None (then use compose_survey, which falls back to the template)."""
    lang = norm_lang(lang)
    cand, _ = _try_model(_base(insight, lang, _window(decision)), insight, lang)
    return _finish(cand, insight, "llm", llm.write_model()) if cand else None


def history_notes(insight: dict, memory, attention=None) -> list[tuple[str, str]]:
    """Which history rules (H1-H4) change this farmer's survey, and why. Empty without memory.
    `attention` is passed through so a `surge` survey (which skips H4) does not report an H4 note it did not use."""
    if memory is None:
        return []
    from .history import personalize
    return personalize(build_items(insight, STYLE, attention), insight, memory, attention)[1]


def compose_survey(decision, insight: dict, lang: str = BASELINE_LANG, memory=None, attention=None,
                   source_items=None) -> dict:
    """One survey in one language: Bedrock when switched on and everything passes, otherwise the template. Never raises for a model problem.
    With `memory` (history.FarmerMemory), the history rules adapt the template; a personalised survey always uses the template.
    `attention` (activity-attention, off by default): `surge` keeps up to 3 questions (H4 skipped), `steady_high` caps at 2.
    `source_items`: the approved English items to translate instead of writing `lang` from scratch."""
    lang = norm_lang(lang)
    base = _base(insight, lang, _window(decision))
    notes = history_notes(insight, memory, attention)
    if not notes:
        cand, why = _try_model(base, insight, lang, attention, source_items)
        if cand:
            return _finish(cand, insight, "llm", llm.write_model())
    else:
        why = "model_off"
        base["rationale"] = (base["rationale"] + " Personalised: "
                             + "; ".join(f"{rule} {reason}" for rule, reason in notes))[:400]
    s = _finish(base | {"items": template_items(insight, lang, memory=memory, attention=attention)}, insight,
                "template", fallback="" if why == "model_off" else why)
    s["_history"] = notes
    return s


def write_surveys(insight: dict, send_window: dict, langs=LANGS, memory=None, attention=None) -> dict[str, dict]:
    """Returns {lang: survey}. The farmer's copy is surveys[insight['conversation_language']].
    English first: a Bedrock-written English survey is translated into Hindi, not written again."""
    done, source = {}, None
    for lang in sorted(langs, key=lambda l: norm_lang(l) != "en-IN"):   # English is written first, whatever the order
        s = compose_survey({"send_window": send_window}, insight, lang, memory, attention, source_items=source)
        done[norm_lang(lang)] = s
        if source is None and norm_lang(lang) == "en-IN" and s.get("_source") == "llm":
            source = s["items"]
    return {norm_lang(lang): done[norm_lang(lang)] for lang in langs}      # in the caller's order, as before
