"""P1 - run_pipeline(): insights -> decisions -> surveys -> hand-offs -> simulated outcomes."""
import random
from mel import core
from mel.data.loaders import junk_reason
from mel.schedule import CapLedger
from mel.writer.history import FarmerMemory
from mel.data.loaders import load_farmers
def run_pipeline(insights, limit=None, farmer=None, seed=42):
    cal = core.load_calendar('data/crop_calendar_bihar_rabi.csv'); rng = random.Random(seed); cap = CapLedger()
    mem = FarmerMemory(insights, load_farmers('data/farmers.csv'))   # whole history is indexed; build_context only reads rows earlier than each insight
    out = {'no_survey': [], 'handoffs': [], 'outcomes': [], 'cap': {'sent': 0, 'skipped': 0, 'opted_out': 0}}
    rows = [i for i in insights if farmer is None or i['farmer_id'] == farmer][:limit]
    for i in sorted(rows, key=lambda i: (i['created_at'], i['farmer_id'])):
        d, ho = core.run_insight(i, cal, mem)
        if not ho: out['no_survey'].append(d); continue
        a = cap.admit(ho); out['cap'][a] = out['cap'].get(a, 0) + 1
        if a != 'sent': continue
        out['handoffs'].append(ho); rec = core.simulate(ho, ho['channel_order'][0]['channel'], 'auto', rng); out['outcomes'].append(rec); mem.record_response(rec)
    return out
