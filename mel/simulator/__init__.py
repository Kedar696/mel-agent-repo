"""P3 - Scheduler, Channels & Simulator (answer simulator): one response record per survey attempt, successes and failures.

simulate(survey, channel, case, seed) -> one response record (reproduces the reference grid).
simulate_handoff(handoff, persona, seed) -> list of records, walking the hand-off's channel_order.
"""
from .simulate import simulate, simulate_handoff, simulate_sheet, cases_for, SUCCESS_CASES, PERSONAS
