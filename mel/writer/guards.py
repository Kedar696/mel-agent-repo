"""Safety and format guardrails every survey must pass before hand-off. Owner: P6."""
import re

from mel.data.validate import errors

# Imperative / advice-giving phrasing (the survey must ask about advice, never give new advice).
ADVICE = re.compile(r"\b(you should|please (apply|spray|use|give|buy)|try (using|applying)|we recommend)\b"
                    r"|(डालें|छिड़कें|इस्तेमाल करें|खरीदें|दें)[।?]?$", re.I)
# Personal information requests.
PII = re.compile(r"\b(name|phone|mobile|aadhaa?r|address|bank|account|income|age)\b|नाम|फ़ोन|फोन|मोबाइल|आधार|पता|बैंक|खाता", re.I)


def check_survey(survey: dict) -> list[str]:
    """Returns a list of problems; empty list means the survey is safe to send."""
    probs = [f"schema: {e}" for e in errors("survey", survey)]
    for it in survey.get("items", []):
        p = it.get("prompt", "")
        if ADVICE.search(p):
            probs.append(f"{it['item_id']}: gives new advice")
        if PII.search(p):
            probs.append(f"{it['item_id']}: asks personal info")
        for o in it.get("options", []):
            if len(o["label"]) > 20:
                probs.append(f"{it['item_id']}: label over 20 chars: {o['label']!r}")
        if it.get("type") == "survey-scale" and it["scale_max"] - it["scale_min"] + 1 > 10:
            probs.append(f"{it['item_id']}: scale over 10 steps")
    ids = [it.get("item_id") for it in survey.get("items", [])]
    if len(ids) != len(set(ids)):
        probs.append("duplicate item_id")
    return probs


def relevance_score(survey: dict, insight: dict | None) -> float:
    """Share of questions that name the crop/animal or a word from the advice (0..1).
    Baseline only. TODO(P6): replace with a better measure (e.g. a Claude judge) and report it."""
    if not insight or not survey.get("items"):
        return 0.0
    from .i18n import asset_word
    keys = {asset_word(insight, survey.get("language", "en-IN")).lower()}
    keys |= {w for w in re.findall(r"[a-z]{5,}", (insight.get("advice_summary") or "").lower())}
    hits = sum(any(k and k in it.get("prompt", "").lower() for k in keys) for it in survey["items"])
    return round(hits / len(survey["items"]), 2)


def self_eval(survey: dict, insight: dict | None = None) -> dict:
    probs = check_survey(survey)
    out = {"schema_valid": not any(p.startswith("schema") for p in probs),
           "gives_new_advice": any("advice" in p for p in probs),
           "asks_personal_info": any("personal" in p for p in probs)}
    if insight is not None:
        out["relevance_score"] = relevance_score(survey, insight)
    return out
