"""P2 - compute_window(). Default = brief rule (07:00, after action window). Set core.SETTINGS['window_mode']='answer_key' for 09:00."""
from mel import core
def compute_window(insight, decision=None, now=None):
    s, e = core.send_window(insight)
    return {'start': s.isoformat(), 'end': e.isoformat(), 'timezone': 'Asia/Kolkata', 'basis': core.SETTINGS['window_mode']}
def crop_season(crop, date):
    """TODO(P2, H+24): look up the stage in the calendar, fall back to a generic offset if the crop is missing."""
    return None
