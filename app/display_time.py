"""US-style date and time display for the app. Owner: app (B wrote it, C integrates). Display only: stored
timestamps, send windows and every JSON contract stay in IST ISO form.

Every human-facing clock goes through here: Eastern Time (America/New_York, so EST or EDT by date),
MM/DD/YYYY and 12-hour h:mm AM/PM. Aware datetimes and ISO timestamps (with an offset, or Z) are converted;
a date-only value keeps its calendar date; a naive datetime is refused rather than guessed.

Two zones (team decision 5 Nov): the numbers (Dashboard) stay in Eastern Time, the default; one farmer's screen
(the Survey demo phone and the send time) shows India time, because that is
where the farmer and Digital Green are. `use("india")` switches the rest of the script run; `use(None)` goes back.
"""
import contextvars
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/New_York")
ZONE_LABEL = "Eastern Time"
INDIA = ZoneInfo("Asia/Kolkata")
INDIA_LABEL = "India time (IST)"
_zone: contextvars.ContextVar = contextvars.ContextVar("mel_display_zone", default=None)   # None = ZONE


def use(zone: str | None) -> None:
    """Display zone for the rest of this script run: "india" or None (Eastern, the default)."""
    _zone.set(INDIA if zone == "india" else None)


def zone_label() -> str:
    return INDIA_LABEL if _zone.get() is INDIA else ZONE_LABEL

_DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")
_WITH_OFFSET = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})")
# An ISO date, optionally followed by a time and an offset, standing on its own (not inside an id or a number).
_TOKEN = re.compile(r"(?<![\w-])(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?)(?![\w-])")


def _eastern(value) -> datetime:
    """The instant in the display zone. Strings are ISO timestamps; Z means UTC."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.strip())
    if not isinstance(value, datetime):
        raise TypeError(f"expected a datetime or an ISO timestamp, got {type(value).__name__}")
    if value.utcoffset() is None:
        raise ValueError("naive datetime: say which zone it is in before displaying it")
    return value.astimezone(_zone.get() or ZONE)


def format_clock(value, *, include_zone: bool = False) -> str:
    """"8:30 PM", or "8:30 PM EST" with the zone."""
    d = _eastern(value)
    clock = f"{d.hour % 12 or 12}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"
    return f"{clock} {d.strftime('%Z')}" if include_zone else clock


def format_date(value) -> str:
    """"11/27/2026". A timestamp converts to the display zone first; a date-only value keeps its date."""
    if isinstance(value, str) and _DATE_ONLY.fullmatch(value.strip()):
        d = date.fromisoformat(value.strip())
    elif isinstance(value, date) and not isinstance(value, datetime):
        d = value
    else:
        d = _eastern(value)
    return f"{d.month:02d}/{d.day:02d}/{d.year}"


def format_datetime(value) -> str:
    """"11/27/2026 8:30 PM EST"."""
    d = _eastern(value)
    return f"{format_date(d)} {format_clock(d, include_zone=True)}"


def zone_abbreviation(value) -> str:
    """"EST" or "EDT": what the zone is called on that date."""
    return _eastern(value).strftime("%Z")


def format_dates_in_text(text: str) -> str:
    """Generated explanatory text with its ISO tokens in US form: a timestamp with an offset becomes
    "MM/DD/YYYY h:mm AM/PM EST", a bare date becomes MM/DD/YYYY. A naive timestamp and anything that is
    not a real date stay as written. Not for quoted user text."""
    def swap(m):
        token = m.group(1)
        try:
            if "T" in token:
                return format_datetime(token) if _WITH_OFFSET.fullmatch(token) else token
            return format_date(token)
        except ValueError:
            return token
    return _TOKEN.sub(swap, text)
