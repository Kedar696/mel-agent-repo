"""Deterministic survey / no-survey cascade. Owner: P2.

Golden-set rule ids (inferred from data/golden_set.jsonl, rules.json does not list them):
  R1 junk_insight              quality_flag == junk, or fails insight schema
  R2 critical_needs_human_call severity == critical  (a human should call, not a survey)
  R3 nothing_to_verify         resolution generic_information (or null)
  R4 waiting_for_details       resolution needs_more_context
  R5 no_check_needed           verification.needed is false
  R6 window_after_season       window would open after 31 March
  R7 crop_already_harvested    crop past harvest on the send date
  R8 survey
"""
from dataclasses import dataclass, field
from datetime import date

from mel.config import rules
from mel.data.validate import is_valid
from mel.timing import send_window, parse_ist, is_past_harvest

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
    "window_after_season": "The send window would open after the rabi season ends (31 March).",
    "crop_already_harvested": "The crop will already be harvested by the time the survey would go out.",
}


@dataclass
class Decision:
    survey: bool
    rule: str
    reason_code: str | None = None
    send_window: dict | None = None
    notes: list[str] = field(default_factory=list)

    def no_survey_record(self, insight: dict) -> dict:
        return {
            "insight_id": insight.get("insight_id", "unknown"),
            "farmer_id": insight.get("farmer_id", "unknown"),
            "decision": "no_survey",
            "reason_code": SCHEMA_REASON[self.reason_code],
            "reason": f"[{self.rule} {self.reason_code}] {REASON_TEXT[self.reason_code]}"[:300],
        }


def _no(rule, code):
    return Decision(False, rule, code)


def decide(insight: dict) -> Decision:
    if insight.get("quality_flag") == "junk" or not is_valid("insight", insight):
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
    if asset.get("category") == "crop" and is_past_harvest(asset.get("name"), date.fromisoformat(win["not_before"][:10])):
        return _no("R7", "crop_already_harvested")
    return Decision(True, "R8", None, win)
