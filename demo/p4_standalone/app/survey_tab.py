"""Survey tab demo: what a farmer sees AFTER chatting with FarmerChat.
Run:  streamlit run app/survey_tab.py
Everything is synthetic. No real delivery happens; this simulates the sheet / chat / call and writes the answer record."""
import sys, json, random, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import streamlit as st
from mel import core
from mel.writer import history
from mel.data.loaders import load_farmers
import copy
from collections import defaultdict

st.set_page_config(page_title="FarmerChat survey tab", layout="wide")
CHANNELS = ['app', 'web', 'whatsapp', 'telegram', 'voice']
CH_NAME = {'app': 'Mobile app', 'web': 'Web chat', 'whatsapp': 'WhatsApp', 'telegram': 'Telegram', 'voice': 'Voice call'}
UI = {'hi': dict(title='आपको मिली सलाह पर एक छोटा सवाल', skip='छोड़ें', close='बंद करें', optout='दोबारा न पूछें', thanks='धन्यवाद। आपके जवाब से हम और अच्छी सलाह दे पाएँगे।',
                 thanks_fu='धन्यवाद। हमने यह नोट कर लिया है। FarmerChat आपसे इस बारे में फिर बात करेगा।', step='{n} में से {i}', start='शुरू करें', later='अभी नहीं',
                 invite='आपको मिली सलाह के बारे में FarmerChat से एक छोटा सवाल। बस एक मिनट लगेगा।'),
      'en': dict(title='A quick question about the advice you got', skip='Skip', close='Close', optout='Do not ask me again', thanks='Thank you. Your answers help us give better advice.',
                 thanks_fu='Thank you. We have noted this. FarmerChat will talk to you about it again.', step='{i} of {n}', start='Start', later='Not now',
                 invite='A short question from FarmerChat about the advice you got. It takes one minute.')}


@st.cache_data(show_spinner=False)
def load(mode):
    core.SETTINGS['window_mode'] = mode
    cal = core.load_calendar(str(ROOT / 'data/crop_calendar_bihar_rabi.csv'))
    rows = [json.loads(l) for l in open(ROOT / 'data/insights.jsonl', encoding='utf-8')]
    out = []
    for i in rows:
        if i.get('quality_flag') == 'junk': continue
        d = core.decide(i, cal); out.append((i, d))
    return out

@st.cache_resource(show_spinner=False)
def get_memory():
    rows = [json.loads(l) for l in open(ROOT / 'data/insights.jsonl', encoding='utf-8')]
    return history.FarmerMemory(rows, load_farmers(str(ROOT / 'data/farmers.csv')))

with st.sidebar:
    st.header("Settings")
    personalize = st.toggle("Use the farmer's past conversations", value=True, help="Off = generic template for the advice type.")
    mode = st.radio("Send-window rule", ['brief', 'answer_key'], format_func=lambda m: {'brief': 'Brief: opens 07:00, after action window', 'answer_key': 'Answer key: opens 09:00'}[m],
                    help="Digital Green has not yet said which is right. The brief rule is the default.")
    crit = st.radio("Critical cases", ['answer_key', 'high_priority'], format_func=lambda m: {'answer_key': 'No survey, human calls', 'high_priority': 'High-priority survey'}[m])
    core.SETTINGS['window_mode'] = mode; core.SETTINGS['critical_mode'] = crit
    st.caption("Synthetic data only. No real farmer is behind any row.")

data = load(mode) if crit == 'answer_key' else None
if data is None:
    cal = core.load_calendar(str(ROOT / 'data/crop_calendar_bihar_rabi.csv'))
    data = [(i, core.decide(i, cal)) for i, _ in load('brief')]
else:
    cal = core.load_calendar(str(ROOT / 'data/crop_calendar_bihar_rabi.csv'))

t_survey, t_sim, t_hand, t_score, t_how = st.tabs(["Survey tab (farmer's view)", "Simulate failures", "Scheduler hand-off", "Scorecard", "How it fits FarmerChat"])

# ------------------------------------------------------------------ pick an insight
with t_survey:
    c1, c2, c3 = st.columns(3)
    res = c1.selectbox("Advice type", ['direct_action', 'wait_and_monitor', 'do_not_act', 'plan_created', 'escalate_to_expert', 'generic_information', 'needs_more_context'])
    lang = c2.selectbox("Insights from farmers who chat in", ['hi-IN', 'en-IN'], format_func=lambda l: {'hi-IN': 'Hindi (हिन्दी)', 'en-IN': 'English'}[l])
    only_survey = c3.checkbox("Only insights that get a survey", value=True)
    pool = [(i, d) for i, d in data if i['resolution_type'] == res and i['conversation_language'] == lang and (d['survey'] or not only_survey)]
    if not pool:
        st.info("No insights match. Change the filters."); st.stop()
    pool = pool[:200]
    pick = st.selectbox("Insight", range(len(pool)), format_func=lambda n: f"{pool[n][0]['insight_id']} | {pool[n][0]['asset'].get('name')} | {pool[n][0].get('concern')} | {pool[n][0]['created_at'][:10]}")
    ins, dec = pool[pick]
    show_lang = st.radio("Show the survey in", ['hi-IN', 'en-IN'], index=['hi-IN', 'en-IN'].index(ins['conversation_language']) if ins['conversation_language'] in ('hi-IN', 'en-IN') else 0,
                         format_func=lambda l: {'hi-IN': 'हिन्दी (Hindi)', 'en-IN': 'English'}[l], horizontal=True, key=f"lang|{ins['insight_id']}",
                         help="Switch the farmer's survey between Hindi and English. The same insight, the same questions, two languages.")

    left, right = st.columns([1, 1])
    with left:
        st.subheader("What happened in the chat")
        st.markdown(f"**Farmer asked:** {ins['query_summary']}")
        st.markdown(f"**FarmerChat advised:** {ins['advice_summary']}")
        st.caption(f"{ins['asset'].get('name')} · {ins.get('concern')} · severity {ins.get('severity')} · prefers {ins['preferred_channel']} · {ins['created_at']}")
        st.subheader("Decision")
        if dec['survey']:
            st.success(f"Survey. Rule {dec['rule']}.")
        else:
            st.warning(f"No survey. Rule {dec['rule']}: {dec['reason_code']}. {dec['reason']}"); st.stop()
        mem = copy.copy(get_memory()); mem.responses = defaultdict(list)
        with st.expander("Pretend this farmer's survey history (demo)"):
            fake = st.selectbox("Earlier survey answers", ['none', 'said the input was not available nearby', 'said it was too costly', 'ignored the last 3 surveys'])
            when = (core.P(ins['created_at']) - __import__('datetime').timedelta(days=2)).isoformat()
            mk = lambda status, ans, d=2: {'farmer_id': ins['farmer_id'], 'status': status, 'answers': ans, 'recorded_at': (core.P(ins['created_at']) - __import__('datetime').timedelta(days=d)).isoformat(), 'counts_toward_cap': True}
            if fake.startswith('said the input'): mem.record_response(mk('completed', {'q1': 'no', 'q3': 'not_nearby'}))
            elif fake.startswith('said it was too'): mem.record_response(mk('completed', {'q1': 'no', 'q3': 'too_costly'}))
            elif fake.startswith('ignored'):
                for d in (6, 4, 2): mem.record_response(mk('expired', {}, d))
        generic = core.build_survey(ins, show_lang)
        sv = core.build_survey(ins, show_lang, memory=mem) if personalize else generic
        ho = core.build_handoff(ins, sv)
        ctx = history.build_context(ins, mem)
        st.subheader("What the agent remembers")
        for line in history.summary_lines(ctx): st.markdown("- " + line)
        if ctx['recent_topics']:
            with st.expander("Last conversations it looked at"): st.write("\n".join(ctx['recent_topics']))
        fired = sv['rationale'].split('Personalised: ')[-1] if 'Personalised' in sv['rationale'] else None
        if personalize and fired: st.success("Adapted the survey: " + fired)
        elif personalize: st.info("Nothing in the history changes this survey, so the generic questions are used.")
        if personalize and fired:
            st.markdown("**Generic vs adapted questions**")
            st.dataframe([{'#': n + 1, 'generic': (generic['items'][n]['prompt'] if n < len(generic['items']) else '(none)'), 'adapted': (sv['items'][n]['prompt'] if n < len(sv['items']) else '(none)')} for n in range(max(len(generic['items']), len(sv['items'])))], hide_index=True)
        g = __import__('mel.writer', fromlist=['x']); guard = g.check_survey(sv)
        st.markdown(f"**Send window:** {sv['send_window']['start'][:16].replace('T', ' ')} to {sv['send_window']['end'][:16].replace('T', ' ')} (India time)")
        st.markdown(f"**Priority:** {ho['priority']} · **Channels:** " + ' → '.join(c['channel'] for c in ho['channel_order']))
        st.markdown(f"**Checks:** schema/length {'pass' if not core.validate_survey(sv) else 'FAIL'} · guards {'pass' if guard['ok'] else 'FAIL ' + str(guard['failures'])} · relevance {g.relevance(sv, ins):.2f}")
        st.caption("Rationale (for reviewers, never shown to the farmer): " + sv['rationale'])
    with right:
        ch = st.radio("Channel to preview", CHANNELS, index=CHANNELS.index(ho['channel_order'][0]['channel']), format_func=CH_NAME.get, horizontal=True)
        k = 'hi' if sv['language'].startswith('hi') else 'en'; U = UI[k]; its = sv['items']; n = len(its)
        key = f"{ins['insight_id']}|{ch}|{fake}|{personalize}|{show_lang}"
        S = st.session_state.setdefault(key, {'step': 0, 'taps': {}, 'done': None})
        def finish(how): S['done'] = how
        def tap(qid, val): S['taps'][qid] = val; S['step'] += 1; S['done'] = 'finished' if S['step'] >= n else None
        def restart(): S.update(step=0, taps={}, done=None)

        box = st.container(border=True)
        with box:
            if ch in ('app', 'web'):
                st.markdown(f"**{U['title']}**")
                if S['done'] is None:
                    q = its[S['step']]
                    st.caption(U['step'].format(i=S['step'] + 1, n=n)); st.progress((S['step'] + 1) / n)
                    st.markdown(f"### {q['prompt']}")
                    for o in q['options']:
                        st.button(o['label'], key=f"{key}-{q['item_id']}-{o['value']}", on_click=tap, args=(q['item_id'], o['value']), width='stretch')
                    a, b, c = st.columns(3)
                    a.button(U['skip'], key=f'{key}-skip', on_click=lambda: S.update(step=S['step'] + 1, done='finished' if S['step'] + 1 >= n else None))
                    b.button(U['close'], key=f'{key}-close', on_click=finish, args=('closed_partway' if S['taps'] else 'dismissed',))
                    c.button(U['optout'], key=f'{key}-opt', on_click=finish, args=('opted_out',))
                    st.caption("Opens on notification tap or next app open. Never covers an answer that is still arriving." if ch == 'app' else "Web has no notifications: opens at the next visit inside the window.")
            elif ch in ('whatsapp', 'telegram'):
                st.caption(CH_NAME[ch])
                if ch == 'whatsapp': st.chat_message("assistant").write(U['invite'] + f"\n\n[{U['start']}]  [{U['later']}]")
                for qi in range(min(S['step'], n)):
                    q = its[qi]; st.chat_message("assistant").write(q['prompt'])
                    v = S['taps'].get(q['item_id']); st.chat_message("user").write(next((o['label'] for o in q['options'] if o['value'] == v), '—'))
                if S['done'] is None:
                    q = its[S['step']]; st.chat_message("assistant").write(q['prompt'])
                    for o in q['options']:
                        st.button(o['label'], key=f"{key}-{q['item_id']}-{o['value']}", on_click=tap, args=(q['item_id'], o['value']), width='stretch')
                    a, b = st.columns(2)
                    a.button("Type a message instead of tapping", key=f'{key}-ft', on_click=finish, args=('free_text',))
                    b.button("STOP" if ch == 'whatsapp' else "/stop", key=f'{key}-stop', on_click=finish, args=('opted_out',))
            else:  # voice
                st.caption("Outbound call from FarmerChat inside send hours")
                vo = core.render(sv, 'voice')
                if S['done'] is None:
                    q = vo['items'][S['step']]; qi = its[S['step']]
                    st.markdown(f"🔊 *{q['say']}*")
                    cols = st.columns(len(qi['options']) + 1)
                    for n_, o in enumerate(qi['options'], 1):
                        cols[n_ - 1].button(f"Press {n_}", key=f"{key}-k{n_}-{qi['item_id']}", on_click=tap, args=(qi['item_id'], o['value']))
                    cols[-1].button("Press 9", key=f'{key}-9', on_click=finish, args=('opted_out',))
                    st.button("Farmer hangs up", key=f'{key}-hang', on_click=finish, args=('closed_partway' if S['taps'] else 'dismissed',))

            if S['done'] is not None:
                how = S['done']
                if how == 'free_text':
                    rec = core.simulate(ho, ch, 'free_text_instead_of_choice', random.Random(1))
                else:
                    rec = core.response_from_taps(ho, ch, S['taps'], how)
                st.markdown(f"**{U['thanks_fu'] if rec['needs_follow_up'] else U['thanks']}**")
                st.button("Start over", key=f'{key}-re', on_click=restart)
        if S['done'] is not None:
            st.subheader("Answer record")
            m1, m2, m3 = st.columns(3)
            m1.metric("Status", rec['status']); m2.metric("Counts toward weekly cap", "Yes" if rec['counts_toward_cap'] else "No"); m3.metric("Next step", rec['retry_decision'])
            if rec['needs_follow_up']:
                st.error("Goes back to FarmerChat's follow-up queue: " + ', '.join(rec['follow_up_reasons']))
            if rec['failure_code']: st.warning(f"failure_code: {rec['failure_code']}")
            st.json(rec, expanded=False)

# ------------------------------------------------------------------ failures
with t_sim:
    st.write("Pick any channel and case to see the exact answer record. Values come from the brief's outcome-code table.")
    sch = st.selectbox("Channel", CHANNELS, format_func=CH_NAME.get, key='simch')
    cases = ['completed', 'negative_outcome', 'partial'] + core.BY_CHANNEL[sch] + core.COMMON
    ex = next((h for i, d in data if d['survey'] for h in [core.build_handoff(i, core.build_survey(i))] if len(h['survey']['items']) >= 2 and h['survey']['language'] == 'hi-IN'), None)
    rng = random.Random(3)
    rows = []
    for c in cases:
        r = core.simulate(ex, sch, c, rng)
        rows.append({'case': c, 'status': r['status'], 'failure_code': r['failure_code'], 'next step': r['retry_decision'], 'retry after (min)': r['retry_after_minutes'], 'counts toward cap': r['counts_toward_cap'], 'follow-up': r['needs_follow_up']})
    st.dataframe(rows, width='stretch', hide_index=True)
    one = st.selectbox("Show the full record for", cases)
    st.json(core.simulate(ex, sch, one, random.Random(3)))

# ------------------------------------------------------------------ handoff
with t_hand:
    st.write("What the scheduler receives. Nothing is sent outside the window or the send hours.")
    st.json(ho if 'ho' in dir() else {})
    if 'sv' in dir():
        st.subheader(f"How {CH_NAME[ch]} gets it"); st.json(core.render(sv, ch))

# ------------------------------------------------------------------ scorecard
with t_score:
    from mel.evaluation import score_golden
    saved = core.SETTINGS['window_mode']; rows = []
    for m in ('brief', 'answer_key'):
        core.SETTINGS['window_mode'] = m; s = score_golden(str(ROOT / 'data/golden_set.jsonl')); rows.append({'window rule': m, 'decision': f"{s['decision_acc']:.1%}", 'rule id': f"{s['rule_acc']:.1%}", 'window': f"{s['window_acc']:.1%}"})
    core.SETTINGS['window_mode'] = saved
    st.dataframe(rows, hide_index=True)
    st.caption("The window gap is a rule conflict (07:00 brief vs 09:00 answer key), not a bug. Waiting on Digital Green.")

# ------------------------------------------------------------------ how it fits
with t_how:
    st.markdown("""
**Where the survey sits in the FarmerChat journey**

1. The farmer chats with FarmerChat (app, web, WhatsApp, Telegram or voice).
2. The insight extractor summarises the chat: crop, problem, advice, whether to check back. *(Given to us as `insights.jsonl`.)*
3. **MEL agent (this project):** decide survey or not, write 1 to 3 tap questions in the farmer's language, set the send window.
4. **Scheduler hand-off:** window, channel order, weekly cap, priority, expiry, and a `farmerchat_flow` id so FarmerChat can register the survey.
5. **Survey tab:** on app and web the survey is a bottom sheet that opens from a notification tap or the next visit. On WhatsApp, Telegram and voice it is one question at a time.
6. The farmer's answers go back as an answer record. Bad outcomes (`needs_follow_up`) return to FarmerChat for help.

**Out of scope here:** real delivery and real farmers. The connection to the live FarmerChat is only described by the contract (answers post to `/v1/surveys/{flow_id}/responses`), and this demo simulates it.
""")
