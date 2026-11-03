"""P3 - Timing & Season: send window, expiry, season clamp, crop-calendar checks."""
from .window import send_window, expires_at, parse_ist, fmt_ist
from .calendar import is_past_harvest
