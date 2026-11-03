"""Crop-calendar checks (golden rule R7: crop_already_harvested). Owner: P3."""
from datetime import date
from functools import lru_cache

from mel.data.loader import load_crop_calendar

HARVEST_STAGES = {"harvest", "post_harvest"}


@lru_cache
def _harvest_end() -> dict[str, date]:
    out: dict[str, date] = {}
    for row in load_crop_calendar():
        if row["growth_stage"] == "harvest" or "harvest" in row["stage_label"].lower():
            d = date.fromisoformat(row["end_date"])
            out[row["crop"]] = max(out.get(row["crop"], d), d)
    return out


def is_past_harvest(crop: str | None, on: date) -> bool:
    """True when the send date falls after the crop's harvest stage ends.
    TODO(P3): crops missing from the calendar (e.g. cauliflower) currently return False;
    golden R7 row I-... is cauliflower, so add a fallback (vegetable default / season end)."""
    if not crop:
        return False
    end = _harvest_end().get(crop.lower())
    return bool(end and on > end)
