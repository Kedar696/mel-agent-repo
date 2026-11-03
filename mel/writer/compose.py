"""Assemble a full survey document per language. Owner: P4."""
import re

from mel.config import LANGS
from . import llm
from .guards import check_survey, self_eval
from .templates import template_items

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


def write_surveys(insight: dict, send_window: dict, langs=LANGS) -> dict[str, dict]:
    """Returns {lang: survey}. The farmer's copy is surveys[insight['conversation_language']]."""
    out = {}
    for lang in langs:
        items, source = llm.llm_items(insight, lang), "llm"
        base = {
            "survey_id": survey_id_for(insight), "farmer_id": insight["farmer_id"],
            "source_insight_ids": [insight["insight_id"]], "language": lang,
            "send_window": send_window, "rationale": RATIONALE[insight["resolution_type"]],
        }
        if not items or check_survey(base | {"items": items}):
            items, source = template_items(insight, lang), "template"
        s = base | {"items": items}
        s["self_eval"] = self_eval(s, insight)
        s["_source"] = source  # stripped before writing; handy in the UI
        out[lang] = s
    return out
