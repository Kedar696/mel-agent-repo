"""Survey Studio: a conversation the user types in, run through the same pipeline as the pack. Owner: app.

No model runs in the local demo (MEL_USE_LLM=0), so nothing here interprets the text. The two text boxes become
query_summary and advice_summary as typed; the Details fields (crop or animal, problem, severity, advice type,
action window, check back, channel, language, district) become the matching insight fields. Four fields no rule
reads are schema fillers: behavioral_intent "diagnosing", decision_episode_type (by advice type),
asset.growth_stage None, quality_flag "clean". Submissions live in st.session_state only: they never join the
pack, the batch, or the Overview and Evaluation numbers.
"""
from datetime import datetime

from mel.timing.window import IST

# The 14 crops and animals in the pack, with the category the schema wants.
ASSETS = {"wheat": "crop", "mustard": "crop", "lentil": "crop", "gram": "crop", "pea": "crop", "potato": "crop",
          "onion": "crop", "tomato": "crop", "cabbage": "crop", "cauliflower": "crop", "maize": "crop",
          "goat": "livestock", "cow": "livestock", "buffalo": "livestock"}
CONCERNS = {"pest_disease": "Pest or disease", "weather_climate": "Weather", "growth_issue": "Poor growth",
            "nutrient_deficiency": "Nutrient deficiency", "water_stress": "Water stress", "soil_health": "Soil health",
            "weed_management": "Weeds", "variety_selection": "Which variety to grow",
            "storage_post_harvest": "Storage after harvest", "market_price": "Market price", "yield_loss": "Yield loss",
            "livestock_health": "Animal health", "livestock_nutrition": "Animal feeding",
            "breeding_reproduction": "Breeding"}
SEVERITY = {"low": "Low", "medium": "Medium", "high": "High", "critical": "Critical (a person calls instead)"}
ADVICE_TYPES = {"direct_action": "Told the farmer what to do", "wait_and_monitor": "Told the farmer to wait and watch",
                "do_not_act": "Told the farmer not to act", "plan_created": "Made a plan with the farmer",
                "escalate_to_expert": "Sent the farmer to an expert", "generic_information": "General information only",
                "needs_more_context": "Asked the farmer for more details"}
CHECK_BACK = {"yes": "Yes", "no": "No, nothing to check"}
LANGUAGES = {"en-IN": "English", "hi-IN": "Hindi"}
DEFAULT_DISTRICT = "Patna"
# Pack ids run I-000001 to I-006999 and survey/hand-off ids keep only the digits (compose.survey_id_for), so this
# namespace can never meet a pack survey, hand-off or weekly-limit entry.
ID_BASE = 900000
# What the editor starts with; the app keeps the user's draft in session state from here on.
DEFAULTS = {"question": "", "advice": "", "asset": "mustard", "concern": "pest_disease", "severity": "medium",
            "resolution": "direct_action", "days": 3, "check": "yes", "channel": "app", "language": "en-IN",
            "district": DEFAULT_DISTRICT}
# verification.method per channel (rules.json channel_by_method maps them back to a channel)
METHOD = {"app": "push", "web": "push", "whatsapp": "whatsapp", "telegram": "push", "voice": "ivr_callback"}
EPISODE = {"plan_created": "decision", "generic_information": "general_knowledge", "needs_more_context": "exploration"}
NO_ADVICE_NOTE = "No advice was entered, so there is nothing to check yet."
# What the insight carries instead of advice (the schema wants a non-empty summary); shown on the card as is.
# Empty input only proves that no advice was supplied, so the text claims nothing more.
NO_ADVICE_TEXT = "No advice given yet."
MAX_QUESTION, MAX_ADVICE, MAX_DISTRICT = 400, 600, 80  # insight.schema.json


def validate(fields: dict) -> list[str]:
    """Problems the user must fix before anything runs. Whitespace is not context."""
    problems = []
    if not (fields.get("question") or "").strip():
        problems.append("Type what the farmer asked. The box is empty.")
    if len((fields.get("question") or "").strip()) > MAX_QUESTION:
        problems.append(f"Keep what the farmer asked under {MAX_QUESTION} characters (the insight schema's limit).")
    if len((fields.get("advice") or "").strip()) > MAX_ADVICE:
        problems.append(f"Keep the advice under {MAX_ADVICE} characters (the insight schema's limit).")
    district = (fields.get("district", DEFAULT_DISTRICT) or "").strip()
    if not district:
        problems.append("Give the district in Details (any Bihar district).")
    if len(district) > MAX_DISTRICT:
        problems.append(f"Keep the district under {MAX_DISTRICT} characters (the insight schema's limit).")
    return problems


def effective_resolution(fields: dict) -> tuple[str, str | None]:
    """The advice type the pipeline sees. With no advice there is nothing to check, which the rules file calls
    needs_more_context (R4, no survey); a critical severity still wins (R2) because the cascade checks it first."""
    if not (fields.get("advice") or "").strip():
        return "needs_more_context", NO_ADVICE_NOTE
    return fields["resolution"], None


def new_ids(n: int) -> dict:
    """Stable ids for the n-th submission of this session, outside the pack's numeric range; a new submission
    always gets new ids, so the phone starts fresh (the preview key carries the insight id)."""
    k = ID_BASE + n
    return {"insight_id": f"I-{k}", "farmer_id": f"F-{k}", "conversation_id": f"C-{k}"}


def now_ist() -> str:
    """Real wall-clock time in IST, in the schema's format. Called once per submission, never on rerender."""
    return datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S+05:30")


def build_insight(fields: dict, ids: dict, created_at: str) -> dict:
    """A schema-valid insight from the form (see the module docstring for the four schema fillers)."""
    resolution, _ = effective_resolution(fields)
    check = fields.get("check", "yes") == "yes"
    channel = fields.get("channel", "app")
    return {
        **ids,
        "created_at": created_at,
        "conversation_language": fields.get("language", "en-IN"),
        "location": {"country": "IN", "state": "Bihar", "district": (fields.get("district", DEFAULT_DISTRICT) or "").strip()},
        "asset": {"name": fields["asset"], "category": ASSETS[fields["asset"]], "growth_stage": None},
        "concern": fields["concern"],
        "behavioral_intent": "diagnosing",
        "decision_episode_type": EPISODE.get(resolution, "problem_resolution"),
        "severity": fields["severity"],
        "query_summary": fields["question"].strip(),
        "advice_summary": (fields.get("advice") or "").strip() or NO_ADVICE_TEXT,
        "resolution_type": resolution,
        "action_window_days": int(fields.get("days", 3)),
        "verification": {"needed": check, "timing": "none", "method": METHOD[channel] if check else "none"},
        "preferred_channel": channel,
        "quality_flag": "clean",
    }


def submission(fields: dict, n: int) -> dict:
    """What the app stores in session state for the n-th submission: the frozen insight plus a note. The
    submission time is the insight's created_at; the app formats it for display (Eastern Time) when drawn."""
    _, note = effective_resolution(fields)
    return {"insight": build_insight(fields, new_ids(n), now_ist()), "note": note}
