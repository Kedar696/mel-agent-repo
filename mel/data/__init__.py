"""P1 - Data & Integration: loading pack files and validating every artifact against its JSON Schema."""

from .loader import load_insights, load_golden, load_farmers, load_crop_calendar, load_scenario, list_scenarios
from .validate import validate, is_valid, errors, failed_fields, why_junk
from .junk import junk_row
from .activity import Attention, ActivityHistory
from .excel import (
    load_insights_xlsx,
    load_golden_xlsx,
    load_farmers_xlsx,
    load_crop_calendar_xlsx,
    read_xlsx,
    check_insights_parity,
    check_all_parity,
)
