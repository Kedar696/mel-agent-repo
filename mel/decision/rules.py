"""Deterministic survey / no-survey cascade. Owner: P2.

Golden-set rule ids (inferred from data/golden_set.jsonl, rules.json does not list them):
  R1 junk_insight              quality_flag == junk, or fails insight schema
  R2 critical_needs_human_call severity == critical  (a human should call, not a survey)
  R3 nothing_to_verify         resolution generic_information
  R4 waiting_for_details       resolution needs_more_context
  R5 no_check_needed           verification.needed is false
  R6 window_after_season       no usable window before season end
  R7 crop_already_harvested    standing-crop advice after harvest (not storage advice)
  R8 survey
"""
from dataclasses import dataclass, field
from datetime import date

from mel.config import rules
from mel.data.validate import is_valid
from mel.timing import send_window, parse_ist, is_past_harvest, pick_send_time

# no_survey.schema.json only allows these two reason codes; extended code goes in `reason`.
SCHEMA_REASON = {
    "junk_insight": "generic_information", "critical_needs_human_call": "needs_more_context",
    "nothing_to_verify": "generic_information", "waiting_for_details": "needs_more_context",
    "no_check_needed": "generic_information", "window_after_season": "generic_information",
    "crop_already_harvested": "generic_information",
}
REASON_TEXT = {
    "junk_insight": "Broken or empty insight; nothing reliable to ask about.",
    "critical_needs_human_call": "Critical case: a person should call the farmer instead of an automated survey.",
    "nothing_to_verify": "General information only. No action was advised, so there is nothing to check.",
    "waiting_for_details": "FarmerChat asked for more details; no advice was given yet.",
    "no_check_needed": "The insight says this advice does not need verification.",
    "window_after_season": "No usable send window remains before the rabi season ends (31 March).",
    "crop_already_harvested": "The crop will already be harvested by the time the survey would go out.",
}


@dataclass
class Decision:
    survey: bool
    rule: str
    reason_code: str | None = None
    send_window: dict | None = None
    notes: list[str] = field(default_factory=list)
    send_time: dict | None = None  # {send_at, slot, rule, assumption, reason}; surveys only
    attention: dict | None = None  # {tier, reason, baseline_per_week, recent_count, weight, explanation}; None = off

    def no_survey_record(self, insight: dict) -> dict:
        def record_id(key):
            value = insight.get(key)
            return value[:64] if isinstance(value, str) and value else "unknown"

        return {
            "insight_id": record_id("insight_id"),
            "farmer_id": record_id("farmer_id"),
            "decision": "no_survey",
            "reason_code": SCHEMA_REASON[self.reason_code],
            "reason": f"[{self.rule} {self.reason_code}] {REASON_TEXT[self.reason_code]}"[:300],
        }


def _no(rule, code):
    return Decision(False, rule, code)


def decide(insight: dict, farmer: dict | None = None, history_hours=(), attention: dict | None = None) -> Decision:
    """`farmer`, `history_hours` and `attention` only refine the send time (and ride on the Decision for the
    scheduler/writer to read); none of them ever change survey vs no-survey, the rule, or the send window.
    `attention` is the activity-attention result (mel.data.activity). pick_send_time runs inside decide(), so
    it must be passed here; a surge sends as soon as the window opens (still inside the window)."""
    if insight.get("quality_flag") == "junk" or not is_valid("insight", insight):
        return _no("R1", "junk_insight")
    # The shared schema validator checks patterns but does not enable date-time
    # format validation. Impossible calendar dates must still become R1, not crash.
    try:
        parse_ist(insight["created_at"])
    except (ValueError, OverflowError):
        return _no("R1", "junk_insight")
    if insight.get("severity") == "critical":
        return _no("R2", "critical_needs_human_call")
    res = insight.get("resolution_type")
    if res is None or not rules()["survey_by_resolution"].get(res, {}).get("survey"):
        return _no("R4", "waiting_for_details") if res == "needs_more_context" else _no("R3", "nothing_to_verify")
    if not (insight.get("verification") or {}).get("needed"):
        return _no("R5", "no_check_needed")
    win = send_window(insight)
    if win is None:
        return _no("R6", "window_after_season")
    asset = insight.get("asset") or {}
    post_harvest = asset.get("growth_stage") == "post_harvest" or insight.get("concern") == "storage_post_harvest"
    if asset.get("category") == "crop" and not post_harvest and is_past_harvest(asset.get("name"), date.fromisoformat(win["not_before"][:10])):
        return _no("R7", "crop_already_harvested")
    return Decision(True, "R8", None, win,
                    send_time=pick_send_time(insight, win, farmer, history_hours, attention),
                    attention=attention)
