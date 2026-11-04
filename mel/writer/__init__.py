"""P4 - Survey Writing & Safety (templates, i18n, Claude writer, guardrails): turn an insight into a survey per language."""
from .compose import write_surveys
from .guards import check_survey, check_survey_result, GuardResult
from .relevance import relevance
from .templates import template_items, build_items, render_template, question_count
