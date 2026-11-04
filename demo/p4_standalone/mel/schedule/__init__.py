"""P3 - hand-off, weekly cap, opt-outs."""
import datetime as dt
from mel import core
OPT_OUT = {'stop', '/stop', '9', 'do not ask me again'}
_opted = set()
def is_opted_out(farmer_id): return farmer_id in _opted
def register_opt_out(farmer_id, raw): 
    if raw.strip().lower() in OPT_OUT: _opted.add(farmer_id)
def build_handoff(survey, insight, decision=None, window=None, farmer=None):
    return core.build_handoff(insight, survey)
class CapLedger:
    """1 non-high survey per farmer per 7 days. TODO(P3, H+4): choose skip / move / merge and document it."""
    def __init__(self): self.sent = {}
    def admit(self, h):
        f = h['survey']['farmer_id']
        if is_opted_out(f): return 'opted_out'
        t = core.P(h['send_window']['start'])
        last = self.sent.get(f)
        if h['priority'] != 'high' and last and (t - last) < dt.timedelta(days=7): return 'skipped'
        self.sent[f] = t; return 'sent'
