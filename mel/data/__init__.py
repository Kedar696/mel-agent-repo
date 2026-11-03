"""P1 - Data & Contracts: loading pack files and validating every artifact against its JSON Schema."""
from .loader import load_insights, load_golden, load_farmers, load_crop_calendar, load_scenario, list_scenarios
from .validate import validate, is_valid, errors
