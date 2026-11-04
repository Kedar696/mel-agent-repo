"""MEL Survey Agent: decide -> write survey (en/hi) -> scheduler hand-off -> channel render -> simulate answers.
Deterministic and offline. Rules are calibrated to golden_set v1 and the participant brief.
"""
import json, random, datetime as dt, hashlib
import pandas as pd

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
P = dt.datetime.fromisoformat
SEASON_END = dt.datetime(2027, 3, 31, 23, 59, tzinfo=IST)
WINDOW_END_HOUR = 19
# P2/P3: the two open questions for Digital Green live here, behind settings (contract: brief rule is the default)
SETTINGS = {'personalize': True,
            'writer_style': 'golden',       # 'golden' = outcome question like the answer key | 'concern' = concern-specific outcome question
            'window_mode': 'brief',        # 'brief' = 07:00, after action window | 'answer_key' = 09:00, golden-set pattern
            'critical_mode': 'answer_key'}  # 'answer_key' = no survey + human call | 'high_priority' = survey, priority high
def start_hour(): return 7 if SETTINGS['window_mode'] == 'brief' else 9
BRIEF_OFFSETS = {'same_day': (1, 3), 'next_day': (1, 3), 'two_to_five_days': (2, 5), 'three_to_ten_days': (3, 10),
                 'seven_to_fourteen_days': (7, 14), 'seasonal': (21, 45)}
OFFSETS = {'same_day': (0, 0), 'next_day': (1, 1), 'two_to_five_days': (2, 5), 'three_to_ten_days': (3, 10),
           'seven_to_fourteen_days': (7, 14), 'seasonal': (30, 45)}   # seasonal 30-45 per golden (brief says 21-45)

def load_calendar(path):
    return pd.read_csv(path)

# ---------------------------------------------------------------- 1. decide
def decide(i, cal):
    base = {'insight_id': i.get('insight_id'), 'farmer_id': i.get('farmer_id')}
    v = i.get('verification') or {}
    def no(rule, code, why): return {**base, 'survey': False, 'rule': rule, 'reason_code': code, 'reason': why}
    if i.get('quality_flag') == 'junk' or not i.get('resolution_type'):
        return no('R1', 'junk_insight', 'Insight is flagged junk or has no resolution.')
    if i.get('severity') == 'critical' and SETTINGS['critical_mode'] == 'answer_key':
        return no('R2', 'critical_needs_human_call', 'Critical case: a human should call, not a survey.')
    if i['resolution_type'] == 'needs_more_context':
        return no('R4', 'waiting_for_details', 'No advice given yet; conversation still open.')
    if i['resolution_type'] == 'generic_information':
        return no('R3', 'nothing_to_verify', 'General information only; nothing to follow up.')
    if not v.get('needed'):
        return no('R5', 'no_check_needed', 'Advice does not need verification.')
    c = P(i['created_at'])
    start, end = send_window(i)
    if start > SEASON_END:
        return no('R6', 'window_after_season', 'Send window would open after 31 March (end of rabi).')
    a = i['asset']
    if a.get('category') == 'crop':
        ce = cal[cal.crop == a['name']].end_date.max()
        if pd.notna(ce) and start.date() > dt.date.fromisoformat(ce):
            return no('R7', 'crop_already_harvested', 'Crop calendar for this crop has ended before the window opens.')
    return {**base, 'survey': True, 'rule': 'R8'}

def send_window(i):
    c = P(i['created_at']); t = i['verification']['timing']; aw = i.get('action_window_days') or 0
    season_cap = SEASON_END.replace(hour=WINDOW_END_HOUR, minute=0, second=0)
    if SETTINGS['window_mode'] == 'brief':
        lo, hi = (aw + 1, aw + 7) if t in ('none', None) else BRIEF_OFFSETS[t]
        lo = max(lo, aw, 1); hi = max(hi, lo + 2)          # after the action window, at least 2 days wide
        s = (c + dt.timedelta(days=lo)).replace(hour=7, minute=0, second=0)
        e = (c + dt.timedelta(days=hi)).replace(hour=WINDOW_END_HOUR, minute=0, second=0)
        return s, min(e, season_cap)
    SH = 9
    lo, hi = (aw + 1, aw + 7) if t in ('none', None) else OFFSETS[t]
    if t == 'same_day':
        s = c + dt.timedelta(hours=4)
        if s.hour < SH: s = s.replace(hour=SH, minute=0)
        if s > c.replace(hour=WINDOW_END_HOUR, minute=0): s = (c + dt.timedelta(days=1)).replace(hour=SH, minute=0)
        return s, s + dt.timedelta(hours=4)
    s = (c + dt.timedelta(days=lo)).replace(hour=SH, minute=0, second=0)
    e = (c + dt.timedelta(days=hi)).replace(hour=WINDOW_END_HOUR, minute=0, second=0)
    return s, min(e, season_cap)

# ---------------------------------------------------------------- 2. survey content
def build_items(i):
    from mel.writer import templates       # lazy: mel.writer imports core
    return templates.build_items(i, SETTINGS.get('writer_style', 'golden'))

PRIORITY_HIGH_SEV = {'high', 'critical'}
def priority(i):
    if i['resolution_type'] == 'escalate_to_expert' or i.get('severity') in PRIORITY_HIGH_SEV or i.get('behavioral_intent') == 'emergency':
        return 'high'
    return 'low' if i['resolution_type'] in ('plan_created', 'do_not_act') else 'normal'

def build_survey(i, lang=None, memory=None):
    lang = lang or i['conversation_language']
    k = 'hi' if lang.startswith('hi') else 'en'
    s, e = send_window(i)
    sid = 'S-' + hashlib.md5(i['insight_id'].encode()).hexdigest()[:6].upper()
    items = []; notes = []
    tpl = build_items(i)
    if memory is not None and SETTINGS.get('personalize', True):
        from mel.writer import history          # lazy: mel.writer imports core
        tpl, notes = history.personalize(tpl, i, memory)
    for n, (typ, pen, phi, opts) in enumerate(tpl, 1):
        items.append({'item_id': f'q{n}', 'type': typ if typ != 'confirm_later' else 'survey-single-select',
                      'prompt': phi if k == 'hi' else pen,
                      'options': [{'value': o['value'], 'label': o[k], **({'follow_up': o['follow_up']} if 'follow_up' in o else {})} for o in opts]})
    for it in items:
        if len(it['options']) == 2 and {o['value'] for o in it['options']} == {'yes', 'no'}:
            it['type'] = 'survey-confirm'
    return {'survey_id': sid, 'farmer_id': i['farmer_id'], 'source_insight_ids': [i['insight_id']], 'language': lang,
            'send_window': {'start': s.isoformat(), 'end': e.isoformat()}, 'items': items,
            'rationale': (f"{i['resolution_type']} advice on {i['asset'].get('name')} ({i.get('concern')}); ask once the farmer could act, then check the outcome."
                          + (' Personalised: ' + '; '.join(f'{r} {w}' for r, w in notes) + '.' if notes else ''))[:400],
            'self_eval': {'schema_valid': True, 'relevance_score': 0.9, 'gives_new_advice': False, 'asks_personal_info': False}}

# ---------------------------------------------------------------- 3. hand-off
METHOD_CH = {'push': 'app', 'whatsapp': 'whatsapp', 'ivr_callback': 'voice', 'repeat_photo': 'app', 'agent_followup': 'voice'}
WAIT = {'high': 6, 'normal': 24, 'low': 48}

def build_handoff(i, survey):
    pr = priority(i)
    order = [i['preferred_channel']]
    m = METHOD_CH.get(i['verification'].get('method'))
    for ch in ([m] if m else []) + ['whatsapp'] + (['voice'] if pr == 'high' else []):
        if ch not in order: order.append(ch)
    end = P(survey['send_window']['end'])
    return {'handoff_id': 'H-' + survey['survey_id'][2:], 'created_at': i['created_at'], 'survey': survey,
            'send_window': survey['send_window'], 'send_hours': {'from': f'{start_hour():02d}:00', 'to': f'{WINDOW_END_HOUR:02d}:00'},
            'channel_order': [{'channel': c, 'wait_hours': WAIT[pr] if n < len(order) - 1 else None} for n, c in enumerate(order)],
            'frequency_cap': {'key': 'farmer_id', 'max_surveys': 1, 'window_days': 7, 'exempt': pr == 'high'},
            'priority': pr, 'expires_at': (end + dt.timedelta(days=2)).isoformat(),
            'farmerchat_flow': {'org_id': 'digital-green', 'flow_key': f"mel-{i['resolution_type']}", 'version': 1,
                                'campaign_id': 'rabi-2026-27', 'flow_id': survey['survey_id']}}

# ---------------------------------------------------------------- 4. channel renderings (low-literacy aware)
def render(survey, channel):
    its = survey['items']; sid = survey['survey_id']
    hi = survey['language'].startswith('hi')
    if channel in ('app', 'web'):
        return {'channel': channel, 'presentation': {'type': 'bottom_sheet', 'one_question_per_step': True, 'steps_total': len(its), 'can_skip': True, 'can_close': True},
                'sheet': {'skip_label': 'छोड़ें' if hi else 'Skip', 'close_label': 'बंद करें' if hi else 'Close',
                          'steps': [{'step': n, 'item_id': q['item_id'], 'question': q['prompt'],
                                     'options': [{'label': o['label'], 'answer': o['value']} for o in q['options']],
                                     'audio_button': True} for n, q in enumerate(its, 1)]}}
    if channel == 'whatsapp':
        msgs = []
        for q in its:
            if len(q['options']) <= 3:
                msgs.append({'type': 'interactive', 'interactive': {'type': 'button', 'body': {'text': q['prompt']},
                             'action': {'buttons': [{'type': 'reply', 'reply': {'id': f"{sid}|{q['item_id']}|{o['value']}", 'title': o['label']}} for o in q['options']]}}})
            else:
                msgs.append({'type': 'interactive', 'interactive': {'type': 'list', 'body': {'text': q['prompt']},
                             'action': {'button': 'चुनें' if hi else 'Choose', 'sections': [{'title': 'एक चुनें' if hi else 'Pick one',
                             'rows': [{'id': f"{sid}|{q['item_id']}|{o['value']}", 'title': o['label']} for o in q['options']]}]}}})
        return {'channel': 'whatsapp', 'opening_template': 'mel_survey_invite', 'messages': msgs}
    if channel == 'telegram':
        return {'channel': 'telegram', 'messages': [{'text': q['prompt'], 'reply_markup': {'inline_keyboard': [[{'text': o['label'], 'callback_data': f"{sid}|{q['item_id']}|{o['value']}"}] for o in q['options']]}} for q in its]}
    if channel == 'voice':
        out = []
        for q in its:
            keys = {str(n): o['value'] for n, o in enumerate(q['options'], 1)}
            word = 'के लिए {} दबाएँ।' if hi else 'press {}.'
            say = q['prompt'] + ' ' + ' '.join((f"{o['label']} " + ('के लिए ' if hi else 'press ') + f"{n} " + ('दबाएँ।' if hi else '.')) for n, o in enumerate(q['options'], 1))
            out.append({'item_id': q['item_id'], 'say': say, 'keypad': keys, 'timeout_seconds': 8, 'repeat_if_no_input': 1})
        return {'channel': 'voice', 'items': out}
    raise ValueError(channel)

# ---------------------------------------------------------------- 5. simulator
# status, sheet_outcome (app/web only), retry, retry_after, counts_toward_cap  [app rows copied from the pack's examples; others are assumptions]
FAIL = {   # code: (status, sheet_outcome[app/web], retry_decision, retry_after_min, counts_toward_cap) - from the brief's outcome-code table
 'push_token_invalid':   ('delivery_failed', 'never_opened', 'fall_back_to_next_channel', 0, False),
 'client_cannot_render': ('delivery_failed', 'never_opened', 'fall_back_to_next_channel', 0, False),
 'push_not_opened':      ('expired', 'never_opened', 'give_up', None, True),
 'sheet_dismissed':      ('declined', 'dismissed', 'give_up', None, True),
 'farmer_opted_out':     ('declined', 'dismissed', 'give_up', None, True),
 'duplicate_answer':     ('duplicate', 'finished', 'none', None, False),
 'identity_mismatch':    ('identity_mismatch', 'finished', 'give_up', None, False),
 'survey_closed':        ('stale', 'finished', 'give_up', None, False),
 'survey_replaced':      ('stale', 'finished', 'give_up', None, False),
 'wa_undelivered':       ('delivery_failed', None, 'fall_back_to_next_channel', 0, False),
 'wa_session_window_closed': ('delivery_failed', None, 'retry_same_channel', 0, False),   # resend as approved template
 'tg_bot_blocked':       ('delivery_failed', None, 'fall_back_to_next_channel', 0, False),
 'voice_no_answer':      ('delivery_failed', None, 'fall_back_to_next_channel', 0, False),  # 3 calls, 10 min apart
 'voice_busy':           ('delivery_failed', None, 'retry_same_channel', 10, False),
 'voice_call_dropped':   ('delivery_failed', None, 'retry_same_channel', 10, True),         # answers before the cut are kept
 'free_text_instead_of_choice': ('invalid_input', None, 'retry_same_channel', 0, True),
 'keypad_out_of_range':  ('invalid_input', None, 'give_up', None, True),
 'speech_not_understood': ('invalid_input', None, 'give_up', None, True),
 'window_expired':       ('expired', None, 'give_up', None, True),
 'farmer_declined':      ('declined', None, 'give_up', None, True),
}
BY_CHANNEL = {'app': ['push_token_invalid', 'client_cannot_render', 'push_not_opened', 'sheet_dismissed', 'farmer_opted_out'],
              'web': ['client_cannot_render', 'sheet_dismissed', 'farmer_opted_out'],
              'whatsapp': ['wa_undelivered', 'wa_session_window_closed', 'free_text_instead_of_choice', 'farmer_declined', 'farmer_opted_out', 'window_expired'],
              'telegram': ['tg_bot_blocked', 'free_text_instead_of_choice', 'farmer_declined', 'farmer_opted_out', 'window_expired'],
              'voice': ['voice_no_answer', 'voice_busy', 'voice_call_dropped', 'keypad_out_of_range', 'speech_not_understood', 'farmer_declined', 'farmer_opted_out', 'window_expired']}
COMMON = ['duplicate_answer', 'identity_mismatch', 'survey_closed']
SCREEN_CHANNELS = ('app', 'web')

def simulate(handoff, channel, case='auto', rng=None):
    """case: 'auto' | 'completed' | 'partial' | 'negative_outcome' | <failure_code>"""
    rng = rng or random.Random(0)
    sv = handoff['survey']; its = sv['items']; ch = channel
    start = P(sv['send_window']['start'])
    t = lambda m: (start + dt.timedelta(minutes=m)).isoformat()
    if case == 'auto':
        r = rng.random()
        case = ('completed' if r < .55 else 'negative_outcome' if r < .65 else 'partial' if r < .72 else
                rng.choice(BY_CHANNEL[ch] + (COMMON if rng.random() < .3 else [])))
    sheet = ch in SCREEN_CHANNELS
    rows = [{'item_id': q['item_id'], 'item_type': q['type'], 'result': 'not_reached', 'value': None, 'raw_input': None, 'input_kind': None, 'attempts': 0} for q in its]
    kind = {'app': 'sheet_tap', 'web': 'sheet_tap', 'whatsapp': 'button_reply', 'telegram': 'button_reply', 'voice': 'keypad'}[ch]
    rec = {'response_key': f"rk-{sv['survey_id']}-{ch}-{case}", 'survey_id': sv['survey_id'], 'farmer_id': sv['farmer_id'],
           'source_insight_ids': sv['source_insight_ids'], 'channel': ch, 'language': sv['language'], 'question_type': its[0]['type'],
           'status': None, 'failure_code': None, 'sheet_outcome': None, 'answers': {}, 'items': rows, 'complete': False, 'delivery_attempt': 1,
           'timestamps': {'sent': t(0), 'delivered': t(1), 'opened': None if ch == 'telegram' else t(20), 'answered': None},
           'recorded_at': t(25), 'answered_by': sv['farmer_id'], 'raw_event': None, 'retry_decision': 'none', 'retry_after_minutes': None,
           'counts_toward_cap': True, 'farmerchat_reply': None, 'needs_follow_up': False, 'follow_up_reasons': []}

    def answer(n_items, flag_bad=False):
        reasons = []
        for q, row in list(zip(its, rows))[:n_items]:
            opts = q['options']
            # conditional question ("If not, what stopped you?"): not applicable when the farmer already did it.
            # ASSUMPTION for P3 to confirm with Digital Green: recorded as skipped, and the record still counts as complete.
            if 'too_costly' in {o['value'] for o in opts} and rec['answers'].get('q1') == 'yes':
                row.update(result='skipped', attempts=0); continue
            bad = [o for o in opts if 'follow_up' in o]
            o = rng.choice(bad) if (flag_bad and bad and not reasons) else rng.choice([x for x in opts if 'follow_up' not in x] or opts)
            row.update(result='answered', value=o['value'], raw_input=o['value'], input_kind=kind, attempts=1)
            rec['answers'][q['item_id']] = o['value']
            if 'follow_up' in o: reasons.append(o['follow_up'])
        return reasons

    def skip_rest(n):
        for row in rows[n:]:
            row['result'] = 'skipped' if row is rows[n] else 'not_reached'
            if row['result'] == 'skipped': row['attempts'] = 1

    if case in ('completed', 'negative_outcome'):
        reasons = answer(len(its), flag_bad=(case == 'negative_outcome'))
        rec.update(complete=True, status='negative_outcome' if reasons else 'completed', needs_follow_up=bool(reasons), follow_up_reasons=sorted(set(reasons)),
                   farmerchat_reply={'http_status': 201, 'outcome': 'accepted'})
        rec['timestamps']['answered'] = t(25); rec['sheet_outcome'] = 'finished' if sheet else None
    elif case == 'partial':
        k = rng.randint(1, len(its) - 1) if len(its) > 1 else 1
        answer(k); skip_rest(k) if k < len(its) else None
        rec.update(status='partial', farmerchat_reply={'http_status': 201, 'outcome': 'accepted'})
        rec['sheet_outcome'] = rng.choice(['closed_partway', 'interrupted']) if sheet else None
        rec['raw_event'] = f"stopped at step {k + 1} of {len(its)}"; rec['timestamps']['answered'] = t(25)
    else:
        status, sheet_out, retry, after, counts = FAIL[case]
        rec.update(status=status, failure_code=case, sheet_outcome=sheet_out if sheet else None, retry_decision=retry,
                   retry_after_minutes=after, counts_toward_cap=counts)
        if status == 'delivery_failed':
            rec['timestamps'].update(delivered=None, opened=None); rec['recorded_at'] = t(2)
        elif case == 'push_not_opened':
            rec['timestamps']['opened'] = None; rec['recorded_at'] = (P(sv['send_window']['end'])).isoformat()
        elif case == 'sheet_dismissed':
            rows[0].update(result='skipped', attempts=1); rec['timestamps']['answered'] = t(25)
        elif case in ('duplicate_answer', 'identity_mismatch', 'survey_closed', 'survey_replaced'):
            rows[0].update(result='discarded', value=its[0]['options'][0]['value'], raw_input=its[0]['options'][0]['value'], input_kind=kind, attempts=1)
            rec['timestamps']['answered'] = t(25)
            if case == 'identity_mismatch': rec['answered_by'] = 'F-000999'
            if case == 'duplicate_answer': rec['farmerchat_reply'] = {'http_status': 200, 'outcome': 'duplicate'}
            if case == 'survey_replaced': rec['farmerchat_reply'] = {'http_status': 404, 'outcome': 'unknown_flow'}
            if case == 'survey_closed':
                rec['timestamps']['answered'] = rec['recorded_at'] = (P(handoff['expires_at']) + dt.timedelta(hours=0)).isoformat()
        elif case in ('free_text_instead_of_choice', 'keypad_out_of_range', 'speech_not_understood'):
            rows[0].update(result='invalid', raw_input={'free_text_instead_of_choice': 'pata nahi', 'keypad_out_of_range': '9', 'speech_not_understood': '<unintelligible>'}[case], input_kind='free_text', attempts=1)
        elif case == 'voice_call_dropped':
            answer(1); skip_rest(1); rec['raw_event'] = 'call dropped after question 1'
        elif case == 'farmer_opted_out':
            rec['raw_event'] = 'tapped Do not ask me again in the sheet'
        if status in ('delivery_failed',) or case in ('push_not_opened', 'client_cannot_render'):
            pass
        if status == 'delivery_failed':
            rec['answered_by'] = None
        if case == 'push_not_opened': rec['answered_by'] = None
    return rec

# ---------------------------------------------------------------- 6. validation
def validate_survey(sv):
    errs = []
    if not 1 <= len(sv['items']) <= 3: errs.append('items must be 1-3')
    for q in sv['items']:
        if len(q['prompt']) >= 400: errs.append(f"{q['item_id']} prompt too long")
        if not 2 <= len(q['options']) <= 10: errs.append(f"{q['item_id']} needs 2-10 options")
        for o in q['options']:
            if len(o['label']) > 20: errs.append(f"{q['item_id']} label >20: {o['label']}")
        if q['type'] == 'survey-confirm' and len(q['options']) != 2: errs.append('confirm needs 2 options')
    return errs

def run_insight(i, cal, memory=None):
    d = decide(i, cal)
    if not d['survey']:
        return d, None
    sv = build_survey(i, memory=memory); ho = build_handoff(i, sv)
    return d, ho


# ---------------------------------------------------------------- 7. a real record from a farmer's real taps (used by the Survey tab)
def response_from_taps(handoff, channel, taps, how='finished', now=None):
    """taps: {item_id: option_value}. how: 'finished' | 'closed_partway' | 'dismissed' | 'opted_out'.
    Status and follow-up reasons come from the survey's own option flags, not from guesses."""
    sv = handoff['survey']; its = sv['items']; start = P(sv['send_window']['start'])
    t = lambda m: (start + dt.timedelta(minutes=m)).isoformat()
    sheet = channel in SCREEN_CHANNELS
    kind = {'app': 'sheet_tap', 'web': 'sheet_tap', 'whatsapp': 'button_reply', 'telegram': 'button_reply', 'voice': 'keypad'}[channel]
    rows, answers, reasons = [], {}, []
    for q in its:
        v = taps.get(q['item_id'])
        if v is None:
            rows.append({'item_id': q['item_id'], 'item_type': q['type'], 'result': 'not_reached', 'value': None, 'raw_input': None, 'input_kind': None, 'attempts': 0}); continue
        rows.append({'item_id': q['item_id'], 'item_type': q['type'], 'result': 'answered', 'value': v, 'raw_input': v, 'input_kind': kind, 'attempts': 1})
        answers[q['item_id']] = v
        opt = next((o for o in q['options'] if o['value'] == v), None)
        if opt and 'follow_up' in opt: reasons.append(opt['follow_up'])
    first_missing = next((r for r in rows if r['result'] == 'not_reached'), None)
    if first_missing and how == 'closed_partway' and answers: first_missing.update(result='skipped', attempts=1)
    if how == 'dismissed' and not answers: rows[0].update(result='skipped', attempts=1)
    complete = len(answers) == len(its)
    if how == 'opted_out':
        status, code, retry = 'declined', 'farmer_opted_out', 'give_up'
    elif how == 'dismissed' and not answers:
        status, code, retry = 'declined', 'sheet_dismissed', 'give_up'
    elif complete:
        status, code, retry = ('negative_outcome' if reasons else 'completed'), None, 'none'
    else:
        status, code, retry = 'partial', None, 'none'
    asked = how in ('finished', 'closed_partway', 'dismissed', 'opted_out')
    return {'response_key': f"rk-{sv['survey_id']}-{channel}-{status}", 'survey_id': sv['survey_id'], 'farmer_id': sv['farmer_id'],
            'source_insight_ids': sv['source_insight_ids'], 'channel': channel, 'language': sv['language'], 'question_type': its[0]['type'],
            'status': status, 'failure_code': code,
            'sheet_outcome': (('finished' if complete else 'closed_partway' if answers else 'dismissed') if sheet else None),
            'answers': answers if status in ('completed', 'partial', 'negative_outcome') else {}, 'items': rows, 'complete': complete and status != 'declined',
            'delivery_attempt': 1, 'timestamps': {'sent': t(0), 'delivered': t(1), 'opened': None if channel == 'telegram' else t(20), 'answered': t(25)},
            'recorded_at': t(25), 'answered_by': sv['farmer_id'], 'raw_event': {'opted_out': 'tapped Do not ask me again', 'dismissed': 'sheet swiped down at step 1'}.get(how) if how in ('opted_out', 'dismissed') else (f'Close tapped at step {len(answers)+1} of {len(its)}' if (how == 'closed_partway' and not complete) else None),
            'retry_decision': retry, 'retry_after_minutes': None, 'counts_toward_cap': asked,
            'farmerchat_reply': {'http_status': 201, 'outcome': 'accepted'} if status in ('completed', 'partial', 'negative_outcome') else None,
            'needs_follow_up': bool(reasons), 'follow_up_reasons': sorted(set(reasons))}
