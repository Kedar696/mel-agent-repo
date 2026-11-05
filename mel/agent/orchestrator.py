"""The Fasal Pulse agent: one farmer conversation in, a checked survey out, as four steps. Owner: P5.

Follows the AWS associate's design for Amazon Bedrock AgentCore (docs/agentcore.md):

    Evidence Extractor -> Analyst -> Verifier -> Synthesizer
                            ^-----------|  bounded revision (at most MAX_REVISIONS, then the template)

  Evidence Extractor  what we know: the insight, the farmer's profile and chat hours, the farmer's memory (P4's history
                      rules) and activity attention (P1).
  Analyst             decides survey or not and when (P2's decide), then drafts the questions: Bedrock when the writer is
                      switched on (P4's llm_items), else P4's templates.
  Verifier            P4's guards and relevance, the send bar (RELEVANCE_THRESHOLD), short questions, P4's small-model
                      check, Amazon Bedrock Guardrails when one is configured, and the AI judge's score (P5) when given.
                      A rejected model draft goes back to the Analyst with the reasons; after MAX_REVISIONS it falls
                      back to the template, which is always safe.
  Synthesizer         both language files, P3's hand-off, the farmer's channel renders, schema checks and the run's
                      metrics (model calls, tokens, cost, time).

`run_agent()` yields one event per step, as plain JSON-ready dicts, so the same events can stream to the Streamlit UI
from a local run or from AgentCore. The last event has step "result". Nothing here sends anything to a farmer.
"""
import time

from mel.channels import render
from mel.data.validate import errors as schema_errors
from mel.decision import decide
from mel.pipeline import clean
from mel.schedule import build_handoff
from mel.writer import llm, RELEVANCE_THRESHOLD
from mel.writer.compose import _base, history_notes, norm_lang, RATIONALE
from mel.writer.guards import check_survey, self_eval
from mel.writer.relevance import relevance
from mel.writer.templates import question_count, template_items

MAX_REVISIONS = 2          # bounded revision: drafts after the first one, before falling back to the template
MAX_PROMPT_CHARS = 120     # short, tap-to-answer. Model drafts averaged 114 characters on 5 Nov; templates 28
LANGS = ("en-IN", "hi-IN")


def _event(step, status, title, detail="", t0=None, **data):
    e = {"step": step, "status": status, "title": title, "detail": detail}
    if t0 is not None:
        e["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    if data:
        e["data"] = data
    return e


def _decision_dict(d) -> dict:
    return {"survey": d.survey, "rule": d.rule, "reason_code": d.reason_code, "send_window": d.send_window,
            "send_time": d.send_time, "attention": d.attention, "notes": list(d.notes or [])}


# ---------------------------------------------------------------- Verifier
def verify(survey: dict, insight: dict, n_items: int, *, template: dict | None = None, guardrail=None,
           judge=None) -> dict:
    """Every check on one draft. -> {"ok", "problems" (what to fix, plain English), "relevance", "judge"}.
    `template` (the template survey for this insight) adds "at least as relevant as the template" for model drafts.
    `guardrail` (a callable text -> reason or None, e.g. bedrock_guardrail()) and `judge` (an AI judge client) are
    optional; the judge's score is reported, not a gate."""
    problems = []
    items = survey.get("items") or []
    if len(items) != n_items:
        problems.append(f"write exactly {n_items} questions (got {len(items)})")
    for f in check_survey(survey):
        problems.append(f"safety/format check failed: {f}")
    rel = relevance(survey, insight)
    if rel < RELEVANCE_THRESHOLD:
        problems.append(f"relevance {rel:.2f} is below the send bar {RELEVANCE_THRESHOLD}: name the crop or animal, "
                        "the problem, or the advised action")
    # "At least as relevant as the template" only in English. P4's score looks for fixed word lists that the Hindi
    # templates are written from, so a good Hindi draft with other words or spellings scores lower than the template
    # (5 Nov pilot: 43 of 44 Hindi rejections were this check). Hindi drafts still need the 0.3 send bar.
    hindi = str(survey.get("language", "")).startswith("hi")
    if template is not None and not hindi and rel < relevance(template, insight):
        problems.append("less relevant than the template: ask about the specific advised action")
    long_ = [q.get("item_id", "?") for q in items if len(q.get("prompt") or "") > MAX_PROMPT_CHARS]
    if long_:
        problems.append(f"questions {', '.join(long_)} are longer than {MAX_PROMPT_CHARS} characters: one short "
                        "question each, and do not repeat the advice back")
    if not problems and llm.check_model():
        opinion = llm.model_check(survey, insight)
        for k, v in (opinion or {}).items():
            if v:
                problems.append({"gives_new_advice": "the checker model says it gives new advice",
                                 "asks_personal_info": "the checker model says it asks for personal information",
                                 "contradicts_advice": "the checker model says it contradicts the advice"}[k])
    if not problems and guardrail is not None:
        text = "\n".join([q.get("prompt") or "" for q in items]
                         + [o.get("label") or "" for q in items for o in q.get("options", [])])
        why = guardrail(text)
        if why:
            problems.append(f"Bedrock Guardrails blocked it: {why}")
    score = None
    if judge is not None and not problems:
        from mel.evaluation import judge as J
        score = J.judge_survey(survey, insight, judge, cache_dir=J.CACHE)["score"]
    return {"ok": not problems, "problems": problems, "relevance": round(rel, 2), "judge": score}


def bedrock_guardrail(guardrail_id: str, version: str = "DRAFT", runtime=None):
    """A Verifier check through Amazon Bedrock Guardrails (ApplyGuardrail on the survey text). Returns a callable
    text -> reason or None. Needs a guardrail created in the account (MEL_GUARDRAIL_ID); never called otherwise."""
    if runtime is None:
        import boto3
        runtime = boto3.client("bedrock-runtime", region_name=llm.region() or None)

    def check(text: str):
        r = runtime.apply_guardrail(guardrailIdentifier=guardrail_id, guardrailVersion=version, source="OUTPUT",
                                    content=[{"text": {"text": text}}])
        if r.get("action") == "GUARDRAIL_INTERVENED":
            names = sorted({p.get("name") or p.get("type") or "policy"
                            for a in r.get("assessments", [])
                            for group in a.values() if isinstance(group, dict)
                            for lst in group.values() if isinstance(lst, list) for p in lst if isinstance(p, dict)})
            return ", ".join(names) or "intervened"
        return None
    return check


# ---------------------------------------------------------------- Analyst + Verifier loop, one language
def _write_one(insight, decision, lang, memory, attention, guardrail, judge, max_revisions, events):
    lang = norm_lang(lang)
    base = _base(insight, lang, decision.send_window)
    n = question_count(insight, attention)
    template = base | {"items": template_items(insight, lang, memory=memory, attention=attention)}
    notes = history_notes(insight, memory, attention)
    use_model = llm.enabled() and not notes        # a personalised survey always uses the template (P4's rule)
    why_template = ("the Bedrock writer is off (MEL_USE_LLM)" if not llm.enabled() else
                    "the farmer's history adapts the template questions" if notes else "")
    attempt, feedback, previous = 0, None, None
    while use_model and attempt <= max_revisions:
        t0 = time.perf_counter()
        items = llm.llm_items(insight, lang, n_items=n, feedback=feedback, previous=previous)
        label = "Analyst drafts" if attempt == 0 else f"Analyst revises (round {attempt} of {max_revisions})"
        if not items:
            events.append(_event("analyst", "fail", f"{label} [{lang}]", "Bedrock gave no usable draft", t0,
                                 lang=lang, model=llm.write_model()))
            why_template = "Bedrock gave no usable draft"
            break
        cand = base | {"items": items}
        events.append(_event("analyst", "ok", f"{label} [{lang}]", f"{len(items)} questions from Bedrock", t0,
                             lang=lang, model=llm.write_model(), questions=[q.get("prompt") for q in items]))
        t0 = time.perf_counter()
        v = verify(cand, insight, n, template=template, guardrail=guardrail, judge=judge)
        events.append(_event("verifier", "ok" if v["ok"] else "fail", f"Verifier [{lang}]",
                             "passed every check" if v["ok"] else "; ".join(v["problems"]), t0, lang=lang, **v))
        if v["ok"]:
            return _final(cand, insight, "bedrock", attempt, notes, v)
        attempt += 1
        # the round number keeps each revision a new request (an identical one would come back from the cache)
        feedback, previous = v["problems"] + [f"this is revision {attempt} of {max_revisions}"], items
        why_template = f"still failing after {max_revisions} revisions"
    # the template: always available, always checked
    t0 = time.perf_counter()
    events.append(_event("analyst", "ok", f"Analyst uses the template [{lang}]", why_template, t0, lang=lang,
                         questions=[q.get("prompt") for q in template["items"]]))
    t0 = time.perf_counter()
    v = verify(template, insight, n, guardrail=None, judge=judge)
    events.append(_event("verifier", "ok" if v["ok"] else "fail", f"Verifier [{lang}]",
                         "passed every check" if v["ok"] else "; ".join(v["problems"]), t0, lang=lang, **v))
    return _final(template, insight, "template", attempt, notes, v, fallback=why_template)


def _final(s, insight, source, revisions, notes, v, fallback=""):
    s = dict(s)
    if notes:
        s["rationale"] = (s["rationale"] + " Personalised: " + "; ".join(f"{r} {why}" for r, why in notes))[:400]
    s["self_eval"] = self_eval(s, insight)
    s["_source"], s["_revisions"], s["_verifier"] = source, revisions, v
    if source == "bedrock":
        s["_model"] = llm.write_model()
    if fallback:
        s["_fallback_reason"] = fallback
    s["_history"] = notes
    return s


# ---------------------------------------------------------------- the whole run
def run_agent(insight: dict, farmer: dict | None = None, history_hours=(), memory=None, attention=None,
              langs=LANGS, guardrail=None, judge=None, max_revisions: int = MAX_REVISIONS):
    """Yield the run's events, step by step. The last one is {"step": "result", ...} with the decision, both surveys,
    the hand-off, the renders and the metrics. Same input and the same model answers give the same events."""
    start = time.perf_counter()
    before = llm.usage_summary()

    # Evidence Extractor
    t0 = time.perf_counter()
    a = insight.get("asset") or {}
    notes = history_notes(insight, memory, attention)
    evidence = {"crop_or_animal": a.get("name"), "growth_stage": a.get("growth_stage"),
                "concern": insight.get("concern"), "severity": insight.get("severity"),
                "advice_type": insight.get("resolution_type"), "farmer_asked": insight.get("query_summary"),
                "advice_given": insight.get("advice_summary"),
                "district": (farmer or {}).get("district"), "preferred_channel": insight.get("preferred_channel"),
                "chat_hours_known": len(history_hours or ()), "history_rules": [r for r, _ in notes],
                "attention": (attention or {}).get("tier")}
    yield _event("evidence", "ok", "Evidence Extractor",
                 f"{evidence['crop_or_animal']} · {str(evidence['concern']).replace('_', ' ')} · "
                 f"{str(evidence['advice_type']).replace('_', ' ')}"
                 + (f" · history {', '.join(evidence['history_rules'])}" if notes else ""), t0, **evidence)

    # Analyst: survey or not, and when
    t0 = time.perf_counter()
    d = decide(insight, farmer, history_hours, attention)
    if not d.survey:
        rec = d.no_survey_record(insight)
        yield _event("analyst", "ok", "Analyst decides: no survey", rec["reason"], t0, decision=_decision_dict(d))
        t0 = time.perf_counter()
        yield _event("synthesizer", "ok", "Synthesizer", "no-survey record", t0, no_survey=rec,
                     schema_errors=schema_errors("no_survey", rec))
        yield _result(insight, d, None, None, None, start, before)
        return
    sw = d.send_window or {}
    yield _event("analyst", "ok", f"Analyst decides: survey (rule {d.rule})",
                 f"{RATIONALE.get(insight.get('resolution_type'), '')} Window {sw.get('not_before', '?')} to "
                 f"{sw.get('not_after', '?')}.", t0, decision=_decision_dict(d))

    # Analyst <-> Verifier, per language
    surveys = {}
    for lang in langs:
        events: list = []
        surveys[norm_lang(lang)] = _write_one(insight, d, lang, memory, attention, guardrail, judge, max_revisions,
                                              events)
        yield from events

    # Synthesizer
    t0 = time.perf_counter()
    lang = insight.get("conversation_language", "hi-IN")
    farmer_copy = clean(surveys.get(lang) or next(iter(surveys.values())))
    handoff = build_handoff(insight, farmer_copy, attention)
    renders = {c["channel"]: render(farmer_copy, c["channel"]) for c in handoff["channel_order"]}
    errs = {k: schema_errors("survey", clean(s)) for k, s in surveys.items()}
    errs["handoff"] = schema_errors("schedule_handoff", handoff)
    bad = sum(len(v) for v in errs.values())
    yield _event("synthesizer", "ok" if not bad else "fail", "Synthesizer",
                 f"{len(surveys)} survey files, hand-off ({handoff['priority']} priority, first channel "
                 f"{handoff['channel_order'][0]['channel']}), {len(renders)} channel renders; "
                 + ("all schema-valid" if not bad else f"{bad} schema errors"), t0,
                 schema_errors={k: v for k, v in errs.items() if v})
    yield _result(insight, d, surveys, handoff, renders, start, before)


def _result(insight, d, surveys, handoff, renders, start, before):
    after = llm.usage_summary()
    metrics = {k: round(after[k] - before[k], 6) if isinstance(after[k], float) else after[k] - before[k]
               for k in ("calls", "cached", "failed", "input_tokens", "output_tokens", "cost_usd")}
    metrics["seconds"] = round(time.perf_counter() - start, 3)
    if surveys:
        metrics["revisions"] = sum(s.get("_revisions", 0) for s in surveys.values())
        metrics["sources"] = {k: s.get("_source") for k, s in surveys.items()}
    return {"step": "result", "status": "ok", "title": "Result", "insight_id": insight.get("insight_id"),
            "decision": _decision_dict(d), "surveys": surveys, "handoff": handoff, "renders": renders,
            "no_survey": None if d.survey else d.no_survey_record(insight), "metrics": metrics}


def run_agent_to_end(insight: dict, **kw) -> tuple[list[dict], dict]:
    """(every step event, the result) for callers that don't stream."""
    evs = list(run_agent(insight, **kw))
    return evs[:-1], evs[-1]
