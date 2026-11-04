"""P5 - scoring against the golden set."""
import json, collections
from mel import core
def score_golden(golden_path='data/golden_set.jsonl'):
    cal = core.load_calendar('data/crop_calendar_bihar_rabi.csv')
    n = dec = rule = win = surv = 0; conf = collections.Counter()
    for l in open(golden_path):
        x = json.loads(l); e = x['expected']; d, ho = core.run_insight(x['insight'], cal); n += 1
        dec += d['survey'] == e['survey']; rule += d['rule'] == e['rule']; conf[(e['rule'], d['rule'])] += 1
        if e['survey'] and ho:
            surv += 1; w = ho['send_window']; win += (w['start'], w['end']) == (e['send_window']['start'], e['send_window']['end'])
    return {'n': n, 'decision_acc': dec/n, 'rule_acc': rule/n, 'window_acc': win/max(surv,1), 'window_mode': core.SETTINGS['window_mode'],
            'confusion': {f'{a}->{b}': c for (a, b), c in sorted(conf.items()) if a != b}}
def item_similarity(survey, golden_items): raise NotImplementedError('TODO(P5, H+12)')
