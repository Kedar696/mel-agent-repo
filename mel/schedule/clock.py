"""A deterministic simulated clock for the season walk-through. Owner: P3.

The demo (P5's "Season" screen) fast-forwards through the rabi season and asks the
broadcaster, at each step, "what would go out now?". Nothing here reads the wall clock:
the time only moves when `advance()` is called, so the same sequence of calls always
produces the same sequence of `now()` values. That determinism is the whole point -- the
broadcaster's decisions (due / not due / expired) must be reproducible for the demo and
for tests.

Design choices, matching the P3 acceptance checklist:
  * `now()` and `advance(days)` are deterministic. Construct with a fixed start; the clock
    never consults `datetime.now()`.
  * `advance(days)` rejects negative or non-integer day counts -- time only moves forward,
    a whole day at a time, so a season walk cannot silently skip backwards or land on a
    fractional instant the window maths was never meant to see.
  * Naive datetimes are rejected. A timestamp with no timezone is ambiguous (07:00 where?),
    and the rest of the system works entirely in IST, so the clock insists on a tz-aware
    start and reports IST.
"""
from datetime import datetime, timedelta

from mel.config import IST
from mel.timing import parse_ist, fmt_ist


class SimClock:
    """A clock you move by hand, one or more whole days at a time.

        clock = SimClock("2026-11-04T07:00:00+05:30")
        clock.now()        -> datetime (tz-aware, IST)
        clock.now_ist()    -> "2026-11-04T07:00:00+05:30"
        clock.advance(7)   -> moves forward 7 days, returns the new now()

    The start may be an IST timestamp string or a tz-aware datetime. A naive datetime (no
    offset) is rejected because it cannot be placed on the IST timeline unambiguously.
    """

    def __init__(self, start):
        self._now = self._coerce(start)

    @staticmethod
    def _coerce(value) -> datetime:
        if isinstance(value, str):
            # parse_ist already rejects an offset-less string.
            return parse_ist(value)
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("SimClock needs a timezone-aware datetime; a naive one is ambiguous")
            return value.astimezone(IST)
        raise TypeError(f"SimClock start must be an IST string or a tz-aware datetime, not {type(value).__name__}")

    def now(self) -> datetime:
        """The current simulated instant, tz-aware in IST."""
        return self._now

    def now_ist(self) -> str:
        """The current instant as an IST timestamp string (the shape the rest of P3 uses)."""
        return fmt_ist(self._now)

    def advance(self, days: int) -> datetime:
        """Move the clock forward by whole days and return the new `now()`.

        Rejects a negative count (time does not run backwards here) and a non-integer count
        (the season walk steps a whole day at a time; a fractional day would land on an
        instant the window/send-hour maths was not written for). `bool` is an `int`
        subclass in Python, so it is rejected explicitly to avoid `advance(True)` meaning 1.
        """
        if isinstance(days, bool) or not isinstance(days, int):
            raise TypeError("advance(days) takes a whole number of days (int)")
        if days < 0:
            raise ValueError("advance(days) cannot go backwards; days must be >= 0")
        self._now = self._now + timedelta(days=days)
        return self._now

    def __repr__(self) -> str:
        return f"SimClock({self.now_ist()!r})"
