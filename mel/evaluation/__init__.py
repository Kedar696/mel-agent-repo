"""P5 - Evaluation & Demo: golden-set scoring, batch quality scorecard, run history, published report."""
from .golden import score_golden, item_similarity
from .scorecard import run_scorecard, format_problems, safety_problems, timeliness_problems
from .history import load_history, record_run
from .report import run_eval, evaluate, write_outputs, rules_changed, timing_basis
