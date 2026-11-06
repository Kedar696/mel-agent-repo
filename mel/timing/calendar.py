"""Crop-calendar checks (golden rule R7: crop_already_harvested). Owner: P2."""

from datetime import date
from functools import lru_cache

from mel.config import rules
from mel.data.loader import load_crop_calendar

ALIASES = {"chickpea": "gram", "chickpeas": "gram", "peas": "pea"}


def _crop_key(crop: str) -> str:
    name = crop.strip().lower()
    return ALIASES.get(name, name)


@lru_cache
def _harvest_periods() -> dict[str, tuple[date, date]]:
    out: dict[str, tuple[date, date]] = {}
    for row in load_crop_calendar():
        # A post_harvest row describes storage, not a later standing-crop harvest.
        if row["growth_stage"] == "harvest":
            s, e = date.fromisoformat(row["start_date"]), date.fromisoformat(row["end_date"])
            crop = _crop_key(row["crop"])
            old_s, old_e = out.get(crop, (s, e))
            out[crop] = (min(old_s, s), max(old_e, e))
    return out


def _harvest_end() -> dict[str, date]:
    return {crop: end for crop, (_, end) in _harvest_periods().items()}


def harvest_period(crop: str | None) -> tuple[date, date] | None:
    """(first, last) harvest day for a crop in the calendar; None if unnamed or unknown."""
    return _harvest_periods().get(_crop_key(crop)) if crop else None


def is_past_harvest(crop: str | None, on: date) -> bool:
    """True strictly after harvest ends, including aliases and unknown-crop fallback.

    For a named crop absent from the calendar, use the configured season end;
    do not invent a vegetable harvest date. A missing crop name stays unknown.
    The decision cascade separately exempts explicit post-harvest advice.
    """
    if not crop:
        return False
    end = _harvest_end().get(_crop_key(crop), date.fromisoformat(rules()["window_rules"]["season_end"]))
    return on > end
