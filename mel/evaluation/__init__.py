"""P5 - Evaluation & Demo: golden-set scoring, batch quality scorecard, run history."""
from .golden import score_golden, item_similarity
from .scorecard import run_scorecard, format_problems, safety_problems
from .history import load_history, record_run
