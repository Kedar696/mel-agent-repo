"""P3 - channel renderers (app, web, whatsapp, telegram, voice)."""
from mel import core
def render(survey, channel, lang=None): return core.render(survey, channel)
