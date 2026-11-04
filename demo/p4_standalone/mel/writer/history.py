"""History-aware survey writing (P4).

The agent remembers what it knows about a farmer BEFORE the insight was created and adapts the survey:
  H1  repeat problem   : same crop + same concern earlier this season -> ask "same problem again?"
  H2  known barrier    : an earlier survey said the input was not available / too costly -> ask about that directly
  H3  survey fatigue   : the last surveys went unanswered -> shorter survey (2 or 1 questions)
  H4  light user       : activity_level == 'light' -> at most 2 questions

Safety: only data strictly earlier than the insight is used (no leakage). Rules never add advice or ask for personal info.
No farmer id, name or phone is ever put into an LLM prompt.
"""
import datetime as dt
from collections import defaultdict

P = dt.datetime.fromisoformat
REPEAT_DAYS = 45
NON_RESPONSE = {'expired', 'declined'}
ACTIONABLE = {'direct_action', 'wait_and_monitor', 'do_not_act', 'plan_created', 'escalate_to_expert'}


def O(value, en, hi, fu=None):
    return {'value': value, 'en': en, 'hi': hi, **({'follow_up': fu} if fu else {})}


class FarmerMemory:
    """Per-farmer memory built from past insights, the farmer profile and past answer records."""

    def __init__(self, insights, farmers=None):
        self.by = defaultdict(list)
        for r in insights:
            if r.get('quality_flag') != 'junk' and r.get('resolution_type'):
                self.by[r['farmer_id']].append(r)
        for v in self.by.values():
            v.sort(key=lambda r: r['created_at'])
        self.farmers = farmers or {}
        self.responses = defaultdict(list)

    def record_response(self, rec):
        self.responses[rec['farmer_id']].append(rec)

    def prior_insights(self, i):
        return [p for p in self.by.get(i['farmer_id'], []) if p['created_at'] < i['created_at'] and p['insight_id'] != i['insight_id']]

    def prior_responses(self, i):
        return sorted((r for r in self.responses.get(i['farmer_id'], []) if r['recorded_at'] < i['created_at']), key=lambda r: r['recorded_at'])


def build_context(i, mem):
    """Plain-data summary of what we remember. Used by the rules, the UI and the LLM prompt."""
    prior = mem.prior_insights(i)
    t0 = P(i['created_at'])
    same = [p for p in prior if p['asset'].get('name') == i['asset'].get('name') and p.get('concern') == i.get('concern')
            and p['conversation_id'] != i['conversation_id'] and (t0 - P(p['created_at'])).days <= REPEAT_DAYS]
    resp = mem.prior_responses(i)
    asked = [r for r in resp if r.get('counts_toward_cap')]
    last3 = asked[-3:]
    barrier = None
    for r in reversed(resp):
        vals = {v for v in (r.get('answers') or {}).values()}
        for b in ('not_nearby', 'too_costly'):
            if b in vals: barrier = b; break
        if barrier: break
    prof = mem.farmers.get(i['farmer_id'], {})
    return {
        'prior_insight_count': len(prior),
        'repeat': {'count': len(same), 'last_date': same[-1]['created_at'][:10], 'last_resolution': same[-1]['resolution_type']} if same else None,
        'barrier': barrier,
        'non_responses_in_last3': sum(r['status'] in NON_RESPONSE for r in last3) if len(last3) == 3 else sum(r['status'] in NON_RESPONSE for r in last3),
        'last_surveys_seen': len(last3),
        'activity_level': prof.get('activity_level'),
        'crops': (prof.get('crops') or '').split('|') if prof.get('crops') else [],
        'recent_topics': [f"{p['created_at'][:10]} {p['asset'].get('name')}/{p.get('concern')}/{p['resolution_type']}" for p in prior[-5:]],
    }


def summary_lines(ctx):
    L = [f"Earlier insights for this farmer: {ctx['prior_insight_count']}"]
    if ctx['repeat']: L.append(f"Same crop and problem raised {ctx['repeat']['count']}x before (last {ctx['repeat']['last_date']}, advice was {ctx['repeat']['last_resolution']})")
    if ctx['barrier']: L.append(f"An earlier survey answer said: {ctx['barrier']}")
    if ctx['last_surveys_seen']: L.append(f"Last {ctx['last_surveys_seen']} surveys: {ctx['non_responses_in_last3']} not answered")
    if ctx['activity_level']: L.append(f"Activity level: {ctx['activity_level']}")
    return L


def personalize(items, i, mem):
    """items: list of (type, prompt_en, prompt_hi, options[dict]) from the generic template.
    Returns (items, notes). notes = [(rule, why)]."""
    ctx = build_context(i, mem)
    items = list(items); notes = []
    rt = i['resolution_type']
    extra = None
    # H2 known barrier (direct_action only: the barrier was about getting or affording an input)
    if rt == 'direct_action' and ctx['barrier'] == 'not_nearby':
        extra = ('survey-single-select', 'Last time you said it was not available nearby. Is it available now?',
                 'पिछली बार आपने बताया था कि पास में नहीं मिला। क्या अब मिल रहा है?',
                 [O('yes_now', 'Yes, available now', 'हाँ, अब मिल रहा है'), O('still_not', 'Still not available', 'अभी भी नहीं', 'input_not_available'), O('not_checked', 'Did not check', 'देखा नहीं')])
        notes.append(('H2', 'earlier survey: input not available nearby'))
    elif rt == 'direct_action' and ctx['barrier'] == 'too_costly':
        extra = ('survey-single-select', 'Last time you said it was too costly. Were you able to manage it this time?',
                 'पिछली बार आपने बताया था कि यह बहुत महँगा है। क्या इस बार हो पाया?',
                 [O('managed', 'Yes, managed', 'हाँ, हो गया'), O('still_costly', 'No, still costly', 'नहीं, अब भी महँगा', 'cost_barrier'), O('not_needed', 'Did not need it', 'ज़रूरत नहीं पड़ी')])
        notes.append(('H2', 'earlier survey: input too costly'))
    # H1 repeat problem
    elif ctx['repeat'] and rt in ACTIONABLE:
        extra = ('survey-single-select', 'Is this the same problem you told us about before?',
                 'क्या यह वही समस्या है जो आपने पहले बताई थी?',
                 [O('same_again', 'Yes, same problem', 'हाँ, वही समस्या', 'problem_recurring'), O('different', 'No, a different one', 'नहीं, दूसरी समस्या'), O('none_now', 'No problem now', 'अब कोई समस्या नहीं')])
        notes.append(('H1', f"same crop and problem raised {ctx['repeat']['count']}x before, last {ctx['repeat']['last_date']}"))
    if extra:
        if len(items) >= 3: items[-1] = extra      # swaps out the "what stopped you" question
        else: items.append(extra)
    # H3 fatigue, H4 light user -> shorter survey. Keep the action question first and the outcome second.
    limit = 3
    if ctx['last_surveys_seen'] >= 2 and ctx['non_responses_in_last3'] >= 2:
        limit = 1 if ctx['non_responses_in_last3'] >= 3 else 2
        notes.append(('H3', f"{ctx['non_responses_in_last3']} of last {ctx['last_surveys_seen']} surveys not answered"))
    if ctx['activity_level'] == 'light':
        if limit > 2: notes.append(('H4', 'light user'))
        limit = min(limit, 2)
    if len(items) > limit:
        items = items[:limit]          # action question first, outcome second; the personalised extra is last and goes first
    return items, notes
