"""app/display_time.py: Eastern Time, MM/DD/YYYY, 12-hour clock, EST/EDT by date; inputs never changed."""
import copy
from datetime import date, datetime, timedelta, timezone

import pytest

from app.display_time import (ZONE_LABEL, format_clock, format_date, format_datetime, format_dates_in_text,
                              zone_abbreviation)

IST = timezone(timedelta(hours=5, minutes=30))


def test_winter_ist_morning_is_the_previous_evening_est():
    stamp = "2027-01-09T08:00:00+05:30"  # the pack's scenario send time
    assert format_clock(stamp) == "9:30 PM"
    assert format_clock(stamp, include_zone=True) == "9:30 PM EST"
    assert format_date(stamp) == "01/08/2027"
    assert format_datetime(stamp) == "01/08/2027 9:30 PM EST"
    assert zone_abbreviation(stamp) == "EST"


def test_summer_uses_edt():
    stamp = datetime(2026, 7, 9, 8, 0, tzinfo=IST)
    assert format_datetime(stamp) == "07/08/2026 10:30 PM EDT"
    assert zone_abbreviation(stamp) == "EDT"


def test_midnight_noon_and_z_input():
    assert format_clock("2027-01-09T05:00:00Z") == "12:00 AM"  # midnight Eastern, from UTC with Z
    assert format_date("2027-01-09T05:00:00Z") == "01/09/2027"
    assert format_clock("2027-01-09T17:00:00+00:00") == "12:00 PM"
    assert format_clock("2027-01-10T04:59:00Z") == "11:59 PM"
    assert format_datetime(datetime(2027, 1, 9, 12, 0, tzinfo=timezone.utc)) == "01/09/2027 7:00 AM EST"


def test_date_only_values_keep_their_calendar_date():
    assert format_date("2026-11-27") == "11/27/2026"
    assert format_date(" 2026-03-31 ") == "03/31/2026"
    assert format_date(date(2026, 11, 27)) == "11/27/2026"
    assert ZONE_LABEL == "Eastern Time"


def test_naive_and_wrong_inputs_are_refused_not_guessed():
    with pytest.raises(ValueError):
        format_clock(datetime(2026, 11, 27, 8, 30))
    with pytest.raises(ValueError):
        format_datetime("2026-11-27T08:30:00")
    with pytest.raises(TypeError):
        format_clock(1764235800)


def test_inputs_are_left_unmodified():
    stamp = datetime(2027, 1, 9, 8, 0, tzinfo=IST)
    record = {"timestamps": {"sent": "2027-01-09T08:00:00+05:30"}, "recorded_at": "2027-01-09T08:25:00+05:30"}
    before = copy.deepcopy(record)
    format_datetime(stamp)
    format_dates_in_text(record["recorded_at"])
    assert stamp.tzinfo is IST and stamp.hour == 8 and record == before


def test_generated_text_tokens_only():
    text = ("Same crop and problem raised 1x before (last 2026-11-19), sent 2026-12-04T09:12:00+05:30, "
            "survey S-20931, id I-004512, draft 2026-11-04T16:20:00, bad 2026-13-45, window 2027-03-31.")
    assert format_dates_in_text(text) == (
        "Same crop and problem raised 1x before (last 11/19/2026), sent 12/03/2026 10:42 PM EST, "
        "survey S-20931, id I-004512, draft 2026-11-04T16:20:00, bad 2026-13-45, window 03/31/2027.")
    assert format_dates_in_text("Spray in the evening; check after 3 days.") == "Spray in the evening; check after 3 days."
    assert format_dates_in_text("at 2026-07-09T08:00:00Z") == "at 07/09/2026 4:00 AM EDT"
