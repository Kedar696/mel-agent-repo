"""P2 send windows. Default: brief rules; MEL_TIMING_BASIS=answer_key: v1 compatibility.

The answer-key convention deliberately differs from the brief. See README.md in
this directory for the conflicts and commands to evaluate both policies.
"""

from datetime import date, datetime, time, timedelta

from mel.config import IST, env, rules


def parse_ist(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.utcoffset() is None:
        raise ValueError("A timestamp must include a timezone offset")
    return dt.astimezone(IST)


def fmt_ist(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%Y-%m-%dT%H:%M:%S+05:30")


def _hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def window_days(insight: dict) -> tuple[int, int]:
    """(start_day, end_day) offsets from the insight's date."""
    r, wr = rules()["send_window_days"], rules()["window_rules"]
    timing = (insight.get("verification") or {}).get("timing") or "none"
    aw = insight.get("action_window_days")
    aw = wr["action_window_days_if_null"] if aw is None else aw
    if timing == "none" or r.get(timing) == "from_action_window":
        start, end = aw + wr["none_start_after_action_window_days"], aw + wr["none_end_after_action_window_days"]
    else:
        start, end = r[timing]
    start = max(start, wr["earliest_start_day"])
    if wr["start_not_before_action_window_end"]:
        start = max(start, aw)
    end = max(end, start + wr["min_width_days"])
    return start, end


def send_window(insight: dict, now: datetime | None = None) -> dict | None:
    """Return IST bounds, or None when the selected policy has no usable window.

    `now` is the simulated clock's instant (P3's `SeasonScheduler.clock.now()`), tz-aware.
    None keeps the old behaviour: the window is planned from the insight's own date.
    Read the policy on each call so callers/tests can select it without reimporting.
    Public input/output shapes remain unchanged.
    """
    basis = env("MEL_TIMING_BASIS", "brief")
    if basis not in {"brief", "answer_key"}:
        raise ValueError("MEL_TIMING_BASIS must be 'brief' or 'answer_key'")
    if basis == "answer_key":
        return _from_now(_answer_key_window(insight), now, 0)
    wr = rules()["window_rules"]
    d0 = parse_ist(insight["created_at"]).date()
    s, e = window_days(insight)
    season_end = date.fromisoformat(wr["season_end"])
    start_d, end_d = d0 + timedelta(days=s), min(d0 + timedelta(days=e), season_end)
    if start_d > season_end or (end_d - start_d).days < wr["min_width_days"]:
        return None
    nb = datetime.combine(start_d, _hm(wr["not_before_time"]), IST)
    na = datetime.combine(end_d, _hm(wr["not_after_time"]), IST)
    return _from_now({"not_before": fmt_ist(nb), "not_after": fmt_ist(na)}, now, wr["min_width_days"])


def _from_now(win: dict | None, now: datetime | None, min_days: int) -> dict | None:
    """Never open in the past. Once the clock is past the opening, open at the next send hour
    (now, or 07:00 if before it, or 07:00 tomorrow if after 19:00) and keep the end. None when
    fewer than `min_days` calendar days are left (brief: 2, the same rule as the season-end clip)."""
    if win is None or now is None:
        return win
    if now.utcoffset() is None:
        raise ValueError("now must include a timezone offset")
    wr = rules()["window_rules"]
    start, end = parse_ist(win["not_before"]), parse_ist(win["not_after"])
    now = now.astimezone(IST).replace(microsecond=0)
    if now <= start:
        return win
    opens, closes = _hm(wr["not_before_time"]), _hm(wr["not_after_time"])
    if now.time() >= closes:
        start = datetime.combine(now.date() + timedelta(days=1), opens, IST)
    else:
        start = max(now, datetime.combine(now.date(), opens, IST))
    if start >= end or (end.date() - start.date()).days < min_days:
        return None
    return {"not_before": fmt_ist(start), "not_after": win["not_after"]}


def _answer_key_window(insight: dict) -> dict | None:
    """Reproduce the v1 answer-key convention without reading expected outputs.

    This evaluation mode permits same-day and short season-clipped windows and
    ignores action deadlines, exactly where the answer key conflicts with the brief.
    Its same-day end can exceed 19:00; scheduler send_hours still apply.
    """
    r = rules()
    created = parse_ist(insight["created_at"])
    timing = (insight.get("verification") or {}).get("timing") or "none"
    season_end = datetime.combine(date.fromisoformat(r["window_rules"]["season_end"]), time(19), IST)
    if timing == "same_day":
        start = created + timedelta(hours=4)
        if start.time() >= time(19):
            start = datetime.combine(start.date() + timedelta(days=1), time(9), IST)
        elif start.time() < time(9):
            start = datetime.combine(start.date(), time(9), IST)
        end = start + timedelta(hours=4)
    else:
        if timing == "seasonal":
            first, last = 30, 45
        elif timing == "none":
            aw = insight.get("action_window_days")
            wr = r["window_rules"]
            aw = wr["action_window_days_if_null"] if aw is None else aw
            first, last = aw + wr["none_start_after_action_window_days"], aw + wr["none_end_after_action_window_days"]
        else:
            first, last = r["send_window_days"][timing]
        start = datetime.combine(created.date() + timedelta(days=first), time(9), IST)
        end = datetime.combine(created.date() + timedelta(days=last), time(19), IST)
    if start > season_end:
        return None
    return {"not_before": fmt_ist(start), "not_after": fmt_ist(min(end, season_end))}


def expires_at(window: dict) -> str:
    return fmt_ist(parse_ist(window["not_after"]) + timedelta(days=rules()["expiry_days_after_window"]))
