"""P3 - seeded answer simulator, failures included. Gap: app rows come from the 13 reference files; other channels are assumptions.
TODO(P3): personas (responsive / never answers), late flag, fallback across channel_order, app/web sent once."""
import random
from mel import core
def simulate(handoff, persona='responsive', seed=0, channel=None):
    ch = channel or handoff['channel_order'][0]['channel']
    case = 'completed' if persona == 'responsive' else 'push_not_opened' if ch == 'app' else 'voice_no_answer' if ch == 'voice' else 'window_expired'
    return [core.simulate(handoff, ch, case, random.Random(seed))]
