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
def _harvest_end() -> dict[str, date]:
    out: dict[str, date] = {}
    for row in load_crop_calendar():
        # A post_harvest row describes storage, not a later standing-crop harvest.
        if row["growth_stage"] == "harvest":
            d = date.fromisoformat(row["end_date"])
            crop = _crop_key(row["crop"])
            out[crop] = max(out.get(crop, d), d)
    return out


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
