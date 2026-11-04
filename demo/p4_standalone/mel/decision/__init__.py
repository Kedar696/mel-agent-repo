"""P2 - decide(): survey or not, with the rule id.
R1-R8 were inferred from golden_set v1 (the brief only gives the survey/no-survey table). Write this in the README."""
from mel import core
RULES = {
 'R1': 'junk_insight: quality_flag=junk or no resolution_type',
 'R2': 'critical_needs_human_call: severity=critical (setting critical_mode)',
 'R3': 'nothing_to_verify: generic_information',
 'R4': 'waiting_for_details: needs_more_context',
 'R5': 'no_check_needed: verification.needed is false',
 'R6': 'window_after_season: window opens after 31 Mar 2027',
 'R7': 'crop_already_harvested: window opens after the last calendar date for the crop (TODO: calendar fallback for cauliflower/cabbage)',
 'R8': 'survey',
}
_cal = None
def decide(insight, cal=None):
    global _cal
    if cal is None:
        _cal = _cal if _cal is not None else core.load_calendar('data/crop_calendar_bihar_rabi.csv'); cal = _cal
    return core.decide(insight, cal)
