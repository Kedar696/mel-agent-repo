"""End-to-end glue: insight -> decision -> surveys -> hand-off. Owner: P1 (integration lead).
Keep this thin: each step lives in its owner's package."""
from mel.decision import decide
from mel.schedule import build_handoff
from mel.writer import write_surveys


def clean(survey: dict) -> dict:
    return {k: v for k, v in survey.items() if not k.startswith("_")}


def run_insight(insight: dict) -> dict:
    """Returns {'decision', 'no_survey'} or {'decision', 'surveys', 'handoff'} (hand-off in farmer's language)."""
    d = decide(insight)
    if not d.survey:
        return {"decision": d, "no_survey": d.no_survey_record(insight)}
    surveys = write_surveys(insight, d.send_window)
    lang = insight.get("conversation_language", "hi-IN")
    farmer_copy = clean(surveys.get(lang) or surveys["hi-IN"])
    return {"decision": d, "surveys": surveys, "handoff": build_handoff(insight, farmer_copy)}
