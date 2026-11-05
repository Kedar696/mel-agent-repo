"""P3 - Scheduler, Channels & Simulator (answer simulator): one response record per survey attempt, successes and failures.

simulate(survey, channel, case, seed) -> one response record (reproduces the reference grid).
simulate_handoff(handoff, persona, seed) -> list of records, walking the hand-off's channel_order.
"""
from .simulate import (
    simulate, simulate_handoff, simulate_sheet, cases_for, SUCCESS_CASES, PERSONAS,
    case_for_channel, STOP_DECISIONS, CONTINUE_DECISIONS,
    next_step, earliest_send, NO_ANSWER_CODES, MAX_ATTEMPTS_PER_CHANNEL,
    reports_advice_failure, advice_failure_answer, is_late,
)
from .follow_up import follow_up_tickets
