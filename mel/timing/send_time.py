"""P2: pick one send time inside the send window. Owner: P2.

Explainable rules, first match wins:
  1. high_severity   severity high/critical: send when the window opens
  2. advice_evening  advice is done in the evening: ask the next morning
  3. usual_time      calls and light users: the farmer's usual chat time (needs history)
  4. async_channel   app/web/WhatsApp/Telegram can be read later: send when the window opens
  5. calls without history fall back to domain assumptions (assumption=True):
     harvest_busy (evening), livestock_chores (afternoon), call_default (evening)

Rule 5 is not learned from data: the pack's chat times are spread evenly over the day.
Only "evening" is matched in advice text; the one "morning" in the pack is a negation.
"""
from collections import Counter
from datetime import datetime, time, timedelta
from math import comb

from mel.config import IST
from .calendar import harvest_period
from .window import fmt_ist, parse_ist

SLOTS = {"morning": (7, 10), "late_morning": (10, 13), "afternoon": (13, 16), "evening": (16, 19)}
CALL_CHANNELS = {"voice"}
CALL_METHODS = {"ivr_callback", "agent_followup"}
# ponytail: fixed thresholds and an even-spread baseline; once real answer logs exist,
# learn the slot from answers instead (a bandit over SLOTS)
MIN_HISTORY = 5
DAY_HOURS = range(6, 21)  # pack chats run 06:00-21:00
P_MAX = 0.01


def _slot(hour: int) -> str:
    """Slot holding this hour; chats before 07:00 count as morning, after 19:00 as evening."""
    return next((name for name, (_, hi) in SLOTS.items() if hour < hi), "evening")


def _tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    return sum(comb(n, j) * p**j * (1 - p) ** (n - j) for j in range(k, n + 1))


def usual_slot(history_hours) -> str | None:
    """The slot holding clearly more past chats than an even spread over the day would.

    One-sided binomial test, Bonferroni over the slots: a few chats that land in the
    same slot by chance do not count as a habit.
    """
    hours = list(history_hours)
    if len(hours) < MIN_HISTORY:
        return None
    best, k = Counter(_slot(h) for h in hours).most_common(1)[0]
    p = sum(_slot(h) == best for h in DAY_HOURS) / len(DAY_HOURS)
    return best if _tail(k, len(hours), p) * len(SLOTS) < P_MAX else None


def chat_hours(insights, farmer_id: str, before: str) -> list[int]:
    """IST hours of the farmer's chats strictly before `before`, so nothing from the future leaks in."""
    cutoff = parse_ist(before)
    hours = []
    for i in insights:
        if not isinstance(i, dict) or i.get("farmer_id") != farmer_id:
            continue
        try:
            t = parse_ist(i["created_at"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if t < cutoff:
            hours.append(t.hour)
    return hours


def _in_harvest(insight: dict, day) -> bool:
    asset = insight.get("asset") or {}
    stored = asset.get("growth_stage") == "post_harvest" or insight.get("concern") == "storage_post_harvest"
    if asset.get("category") != "crop" or stored:
        return False
    period = harvest_period(asset.get("name"))
    return bool(period) and period[0] <= day <= period[1]


def _at(window: dict, slot: str | None, rule: str, reason: str, assumption: bool = False) -> dict:
    """Earliest moment inside `window` that falls in `slot` (None: the window's opening)."""
    nb, na = parse_ist(window["not_before"]), parse_ist(window["not_after"])
    at = nb
    if slot:
        lo, hi = SLOTS[slot]
        day = nb.date()
        while day <= na.date():
            t = max(nb, datetime.combine(day, time(lo), IST))
            if t.hour < hi and t <= na:
                at = t
                break
            day += timedelta(days=1)
        else:
            slot, reason = None, reason + " That slot is not inside the window, so send when it opens."
    return {"send_at": fmt_ist(at), "slot": slot, "rule": rule, "assumption": assumption, "reason": reason}


def pick_send_time(insight: dict, window: dict, farmer: dict | None = None, history_hours=()) -> dict:
    """One send time inside `window`, with the rule and reason behind it.

    `farmer` is the farmers.csv row (optional). `history_hours` are the farmer's earlier
    chat hours (see chat_hours). Without them, rules 3 and livestock_chores never fire.
    """
    farmer = farmer or {}
    channel = insight.get("preferred_channel")
    method = (insight.get("verification") or {}).get("method")
    is_call = channel in CALL_CHANNELS or method in CALL_METHODS

    if insight.get("severity") in ("high", "critical"):
        return _at(window, None, "high_severity", "High severity: send as soon as the window opens.")
    if "evening" in (insight.get("advice_summary") or "").lower():
        return _at(window, "morning", "advice_evening",
                   "The advice is carried out in the evening, so ask the next morning.")
    usual = usual_slot(history_hours)
    if usual and (is_call or farmer.get("activity_level") == "light"):
        return _at(window, usual, "usual_time", f"The farmer usually chats in the {usual.replace('_', ' ')}.")
    if not is_call:
        return _at(window, None, "async_channel",
                   f"{channel or 'This channel'} can be read later, so send when the window opens.")
    if _in_harvest(insight, parse_ist(window["not_before"]).date()):
        return _at(window, "evening", "harvest_busy",
                   "Assumption: harvest keeps farmers in the field all day, so call in the evening.", True)
    if farmer.get("livestock"):
        return _at(window, "afternoon", "livestock_chores",
                   "Assumption: milking and feeding fill mornings and evenings, so call in the afternoon.", True)
    return _at(window, "evening", "call_default",
               "Assumption: farmers are home after field work, so call in the evening.", True)
