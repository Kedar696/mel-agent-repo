"""Why an input row is junk, as a category plus a detail line for the junk report. Owner: P1.

Two kinds of junk (see ``why_junk``): rows that fail the insight schema, and rows labelled
``quality_flag == "junk"`` that are schema-valid. The first get ``schema_failure`` and name
every failed field. The second are sorted by what the row says, so the report tells a human
*what* the farmer sent, not how the file is shaped. This only describes rows; it never
changes a survey decision (that stays in ``mel.decision``).
"""
import re

from .validate import failed_fields, why_junk

SCHEMA_FAILURE = "schema_failure"
FALLBACK = "other_junk"

# First match wins, so the narrow cases come before the broad ones.
_CONTENT_RULES = (
    ("unclear_voice", re.compile(r"voice (note|message)|no clear speech|audio|recording", re.I)),
    ("unclear_text", re.compile(r"few letters|could not be understood|gibberish|unclear|unreadable", re.I)),
    ("thanks", re.compile(r"\bthank", re.I)),
    ("greeting", re.compile(r"\b(hello|hi|hey|namaste|greet\w*|good (morning|evening))\b", re.I)),
    ("about_the_app", re.compile(r"who (made|built|created|are you)|about the (app|assistant)|the app\b", re.I)),
    ("acknowledgement", re.compile(r"was fine|\bokay\b|\bok\b|got it|agreed?\b|acknowledg\w*|understood", re.I)),
    ("off_topic", re.compile(r"cricket|loan|bank|movie|politic\w*|lottery|\bscore\b", re.I)),
)


def content_category(insight: dict) -> str:
    """Category for a schema-valid junk row, from what the farmer said (then what was answered)."""
    for field in ("query_summary", "advice_summary"):
        text = insight.get(field)
        if not isinstance(text, str):
            continue
        for category, pattern in _CONTENT_RULES:
            if pattern.search(text):
                return category
    return FALLBACK


def junk_row(insight: dict) -> tuple[str, str] | None:
    """``(category, detail)`` for a junk insight, or ``None`` when the row is not junk."""
    if not why_junk(insight):
        return None
    fields = failed_fields("insight", insight)
    if fields:
        return SCHEMA_FAILURE, "failed fields: " + "; ".join(fields)
    summary = insight.get("query_summary") or ""
    return content_category(insight), f"labelled junk: {summary}".strip()
