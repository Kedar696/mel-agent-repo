"""Send-window maths from rules.json. Owner: P3.

Verified against all 5 worked scenarios (tests/test_timing.py). Open question for P3:
golden R8 rows sometimes start at 09:00, not 07:00 - investigate with `python -m mel.cli eval`.
"""
from datetime import date, datetime, time, timedelta

from mel.config import IST, rules


def parse_ist(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(IST)


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


def send_window(insight: dict) -> dict | None:
    """{'not_before','not_after'} in IST, or None if the window would open after season end."""
    wr = rules()["window_rules"]
    d0 = parse_ist(insight["created_at"]).date()
    s, e = window_days(insight)
    season_end = date.fromisoformat(wr["season_end"])
    start_d, end_d = d0 + timedelta(days=s), min(d0 + timedelta(days=e), season_end)
    if start_d > season_end:
        return None
    nb = datetime.combine(start_d, _hm(wr["not_before_time"]), IST)
    na = datetime.combine(end_d, _hm(wr["not_after_time"]), IST)
    return {"not_before": fmt_ist(nb), "not_after": fmt_ist(na)}


def expires_at(window: dict) -> str:
    return fmt_ist(parse_ist(window["not_after"]) + timedelta(days=rules()["expiry_days_after_window"]))
