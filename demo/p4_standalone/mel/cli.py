import argparse, json, collections
from mel.data.loaders import load_insights
from mel.pipeline import run_pipeline
from mel.evaluation import score_golden
from mel import core
def main():
    p = argparse.ArgumentParser(prog='mel'); p.add_argument('cmd', choices=['run', 'eval', 'validate'])
    p.add_argument('--limit', type=int); p.add_argument('--farmer'); p.add_argument('--window-mode', choices=['brief', 'answer_key'], default='brief')
    a = p.parse_args(); core.SETTINGS['window_mode'] = a.window_mode
    if a.cmd == 'eval': print(json.dumps(score_golden(), indent=1)); return
    r = run_pipeline(load_insights('data/insights.jsonl'), a.limit, a.farmer)
    if a.cmd == 'run':
        print('surveys', len(r['handoffs']), '| no_survey', len(r['no_survey']), '| cap', r['cap'])
        print('outcomes', dict(collections.Counter(o['status'] for o in r['outcomes'])))
    else:
        from mel.writer import check_survey
        bad = [h['survey']['survey_id'] for h in r['handoffs'] if not check_survey(h['survey'])['ok']]
        print('invalid surveys:', len(bad))
if __name__ == '__main__': main()
