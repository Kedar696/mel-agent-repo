"""Optional Claude-written questions, with template fallback. Owner: P4.

Enabled when ANTHROPIC_API_KEY is set and MEL_USE_LLM=1. Output is parsed JSON items and must
pass guards.check_survey, otherwise compose.py falls back to templates. Never sends PII:
only asset, concern, query_summary and advice_summary go to the model.
"""
import json
import os

MODEL = os.environ.get("MEL_MODEL", "claude-sonnet-5-5")

SYSTEM = """You write short follow-up surveys for smallholder farmers in Bihar, India.
Ask ONLY about advice the farmer already received: did they act on it, and did it work.
Never give new advice. Never ask for personal information.
Return JSON: {"items": [...]} with 1-3 items following this shape:
  {"item_id":"q1","type":"survey-confirm"|"survey-single-select","prompt":"...",
   "options":[{"value":"snake_case","label":"<=20 chars","follow_up":"advice_did_not_work|crop_or_animal_damaged|could_not_get_input|could_not_reach_expert"(optional)}]}
  or {"item_id":"q2","type":"survey-scale","prompt":"...","scale_min":1,"scale_max":5,
   "follow_up_at_or_below":1,"follow_up_reason":"advice_did_not_work"}
survey-confirm has exactly options yes/no. Mark follow_up on any answer meaning failure or harm.
Write prompts and labels in the requested language. Option values must be English snake_case."""


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("MEL_USE_LLM") == "1"


def llm_items(insight: dict, lang: str) -> list[dict] | None:
    if not enabled():
        return None
    import anthropic
    ctx = {k: insight.get(k) for k in ("asset", "concern", "resolution_type", "query_summary", "advice_summary")}
    msg = anthropic.Anthropic().messages.create(
        model=MODEL, max_tokens=1200, system=SYSTEM,
        messages=[{"role": "user", "content": f"Language: {lang}\nInsight: {json.dumps(ctx, ensure_ascii=False)}\nReturn only JSON."}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    try:
        return json.loads(text[text.index("{"): text.rindex("}") + 1])["items"]
    except (ValueError, KeyError):
        return None
