"""P2: send window reproduces every worked scenario."""
from datetime import date, datetime, timedelta

import pytest

from mel.data import load_scenario, list_scenarios
from mel.config import IST
from mel.timing import send_window, expires_at, is_past_harvest, parse_ist
from mel.timing.window import window_days


@pytest.fixture(autouse=True)
def brief_policy(monkeypatch):
    monkeypatch.setenv("MEL_TIMING_BASIS", "brief")


def insight():
    return load_scenario("1-mustard-aphid-spray")["insight"]


def test_windows_match_scenarios():
    for n in list_scenarios():
        s = load_scenario(n)
        if s["handoff"]:
            w = send_window(s["insight"])
            assert w == s["handoff"]["send_window"], n
            assert expires_at(w) == s["handoff"]["expires_at"], n


@pytest.mark.parametrize("timing,action,expected", [
    ("same_day", 0, (1, 3)), ("next_day", 0, (1, 3)),
    ("two_to_five_days", 2, (2, 5)), ("three_to_ten_days", 5, (5, 10)),
    ("seven_to_fourteen_days", 23, (23, 25)), ("seasonal", 0, (21, 45)),
    ("none", None, (3, 9)), ("none", 0, (1, 7)),
    ("two_to_five_days", None, (2, 5)),
])
def test_timing_offsets(timing, action, expected):
    i = insight()
    i["verification"]["timing"] = timing
    i["action_window_days"] = action
    assert window_days(i) == expected


@pytest.mark.parametrize("created,expected", [
    ("2027-03-27T09:00:00+05:30", {"not_before": "2027-03-29T07:00:00+05:30", "not_after": "2027-03-31T19:00:00+05:30"}),
    ("2027-03-28T09:00:00+05:30", None),  # G-0145's case: the brief needs 2 days, the key keeps a 1-day window
    ("2027-03-31T09:00:00+05:30", None),
])
def test_season_end_retains_minimum_window(created, expected):
    i = insight()
    i["created_at"] = created
    assert send_window(i) == expected


def test_date_counting_starts_from_insight_day_even_at_night():
    i = insight()
    i["created_at"] = "2026-12-04T23:59:00+05:30"
    w = send_window(i)
    assert w["not_before"] == "2026-12-06T07:00:00+05:30"
    assert parse_ist(expires_at(w)) - parse_ist(w["not_after"]) == timedelta(days=2)


def test_timezone_conversion_and_missing_offset():
    assert parse_ist("2026-12-04T23:00:00+00:00") == datetime(2026, 12, 5, 4, 30, tzinfo=IST)
    with pytest.raises(ValueError, match="timezone"):
        parse_ist("2026-12-04T23:00:00")


@pytest.mark.parametrize("crop,on,expected", [
    ("potato", date(2027, 3, 5), False), ("potato", date(2027, 3, 6), True),
    ("lentil", date(2027, 3, 26), True),
    ("cauliflower", date(2027, 3, 11), True),
    ("cabbage", date(2027, 3, 21), True),
    (" CHICKPEAS ", date(2027, 4, 11), True),
    ("unknown crop", date(2027, 3, 31), False),
    ("unknown crop", date(2027, 4, 1), True),
    (None, date(2027, 4, 1), False),
])
def test_harvest_boundaries_and_fallback(crop, on, expected):
    assert is_past_harvest(crop, on) is expected


@pytest.mark.parametrize("timing,created,action,expected", [
    ("same_day", "2026-12-19T08:42:00+05:30", 1,
     {"not_before": "2026-12-19T12:42:00+05:30", "not_after": "2026-12-19T16:42:00+05:30"}),
    ("same_day", "2027-02-10T18:11:00+05:30", 1,
     {"not_before": "2027-02-11T09:00:00+05:30", "not_after": "2027-02-11T13:00:00+05:30"}),
    ("seasonal", "2026-11-17T06:35:00+05:30", 16,
     {"not_before": "2026-12-17T09:00:00+05:30", "not_after": "2027-01-01T19:00:00+05:30"}),
    ("three_to_ten_days", "2027-03-28T18:05:00+05:30", 10,
     {"not_before": "2027-03-31T09:00:00+05:30", "not_after": "2027-03-31T19:00:00+05:30"}),
])
def test_answer_key_conventions(monkeypatch, timing, created, action, expected):
    monkeypatch.setenv("MEL_TIMING_BASIS", "answer_key")
    i = insight()
    i.update(created_at=created, action_window_days=action)
    i["verification"]["timing"] = timing
    assert send_window(i) == expected


def test_unknown_policy_is_a_configuration_error(monkeypatch):
    monkeypatch.setenv("MEL_TIMING_BASIS", "typo")
    with pytest.raises(ValueError, match="MEL_TIMING_BASIS"):
        send_window(insight())


# Scenario 1's planned window: 2026-12-06 07:00 to 2026-12-09 19:00 IST.
@pytest.mark.parametrize("now,opens", [
    ("2026-12-02T10:00:00+05:30", "2026-12-06T07:00:00+05:30"),  # clock before the window: unchanged
    ("2026-12-06T10:30:00+05:30", "2026-12-06T10:30:00+05:30"),  # inside send hours: open now
    ("2026-12-07T05:00:00+05:30", "2026-12-07T07:00:00+05:30"),  # before 07:00: that morning
    ("2026-12-06T20:00:00+05:30", "2026-12-07T07:00:00+05:30"),  # after 19:00: next morning
    ("2026-12-06T05:00:00+00:00", "2026-12-06T10:30:00+05:30"),  # a UTC clock is read in IST
    ("2026-12-07T20:00:00+05:30", None),                         # under two days left: no window
])
def test_window_never_opens_before_the_simulated_clock(now, opens):
    expected = None if opens is None else {"not_before": opens, "not_after": "2026-12-09T19:00:00+05:30"}
    assert send_window(insight(), now=datetime.fromisoformat(now)) == expected


def test_answer_key_window_also_follows_the_clock(monkeypatch):
    monkeypatch.setenv("MEL_TIMING_BASIS", "answer_key")
    i = insight()
    i.update(created_at="2027-03-28T18:05:00+05:30", action_window_days=10)
    i["verification"]["timing"] = "three_to_ten_days"
    noon = datetime(2027, 3, 31, 12, tzinfo=IST)
    assert send_window(i, now=noon) == {"not_before": "2027-03-31T12:00:00+05:30",
                                        "not_after": "2027-03-31T19:00:00+05:30"}
    assert send_window(i, now=noon + timedelta(hours=8)) is None


def test_clock_needs_a_timezone():
    with pytest.raises(ValueError, match="timezone"):
        send_window(insight(), now=datetime(2026, 12, 7, 8))
