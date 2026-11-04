"""P4: every survey we write is schema-valid and passes guardrails, in both languages."""
from mel.data import load_insights
from mel.decision import decide
from mel.writer import write_surveys, check_survey
from mel.pipeline import clean


def test_all_surveys_pass_guards():
    n = 0
    for i in load_insights():
        d = decide(i)
        if d.survey:
            for s in write_surveys(i, d.send_window).values():
                assert check_survey(clean(s)) == [], i["insight_id"]
            n += 1
    assert n > 0


def test_guards_catch_advice_and_pii():
    s = {"survey_id": "S-00001", "farmer_id": "F", "source_insight_ids": ["I"], "language": "en-IN",
         "send_window": {"not_before": "2026-12-06T07:00:00+05:30", "not_after": "2026-12-09T19:00:00+05:30"},
         "rationale": "x", "items": [{"item_id": "q1", "type": "survey-confirm",
                                      "prompt": "You should spray now. What is your phone number?",
                                      "options": [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}]}]}
    p = check_survey(s)
    assert any("advice" in x for x in p) and any("personal" in x for x in p)


def test_relevance_score_in_range():
    n = 0
    for i in load_insights():
        d = decide(i)
        if d.survey:
            for s in write_surveys(i, d.send_window).values():
                r = s["self_eval"]["relevance_score"]
                assert 0 <= r <= 1
                n += r > 0
    assert n > 0

# ======================================================================================================
# P4 additions: templates, 2-vs-3 rule, Hindi gender, guards in both languages, relevance v2
# ======================================================================================================
import itertools
import pytest
from mel.writer import write_surveys, check_survey, check_survey_result, relevance, template_items, render_template, templates, i18n, guards

ACTIONABLE = ['direct_action', 'wait_and_monitor', 'do_not_act', 'plan_created', 'escalate_to_expert']

def mk(**kw):
    base = dict(insight_id='I-X', farmer_id='F-T', conversation_id='C-X', created_at='2026-12-10T09:00:00+05:30', conversation_language='hi-IN',
                asset={'name': 'wheat', 'category': 'crop', 'growth_stage': 'tillering'}, concern='pest_disease', severity='medium',
                query_summary='Farmer asks about insects.', advice_summary='Advised to spray a recommended insecticide as per the label.',
                resolution_type='direct_action', action_window_days=2, verification={'needed': True, 'timing': 'two_to_five_days', 'method': 'push'},
                preferred_channel='app', quality_flag='clean')
    base.update(kw); return base

@pytest.fixture(autouse=True)
def _reset():
    templates.STYLE = 'golden'; yield; templates.STYLE = 'golden'

def survey(items, lang='en-IN'):
    return {'survey_id': 'S-00001', 'farmer_id': 'F-T', 'source_insight_ids': ['I-X'], 'language': lang, 'rationale': 'test',
            'send_window': {'not_before': '2026-12-10T09:00:00+05:30', 'not_after': '2026-12-12T09:00:00+05:30'}, 'items': items}
def sv(i, lang='en-IN'): return survey(template_items(i, lang), lang)
def prompts(i, lang='en-IN'): return [q['prompt'] for q in sv(i, lang)['items']]

# ---------------------------------------------------------------- 2-vs-3 rule (from golden set v1: low -> 2, medium/high -> 3)
@pytest.mark.parametrize('sev,n', [('low', 2), ('medium', 3), ('high', 3)])
def test_direct_action_question_count_follows_severity(sev, n): assert len(sv(mk(severity=sev))['items']) == n

@pytest.mark.parametrize('rt', ['wait_and_monitor', 'do_not_act', 'plan_created', 'escalate_to_expert'])
@pytest.mark.parametrize('sev', ['low', 'medium', 'high'])
def test_other_advice_types_always_two_questions(rt, sev):
    assert len(sv(mk(resolution_type=rt, severity=sev, advice_summary='Advised to wait and watch for new spots on the pods over the next few days before acting.'))['items']) == 2

# ---------------------------------------------------------------- every resolution x top-10 concern x style x language
@pytest.mark.parametrize('rt,cn,style,lang', list(itertools.product(ACTIONABLE, templates.TOP10, ["golden", "concern"], ["hi-IN", "en-IN"])))
def test_every_resolution_and_top10_concern_has_a_safe_template(rt, cn, style, lang):
    templates.STYLE = style
    cat = 'livestock' if cn.startswith('livestock') else 'crop'; name = 'cow' if cat == 'livestock' else 'mustard'
    i = mk(resolution_type=rt, concern=cn, asset={'name': name, 'category': cat, 'growth_stage': None},
           advice_summary={'plan_created': 'Gave a plan in stages: first open drains, then watch for new spots and take the next step if needed.'}.get(rt, 'Advised something.'))
    s = sv(i, lang); g = check_survey_result(s)
    assert g.ok, g.failures
    assert 0 <= relevance(s, i) <= 1
    assert 1 <= len(s['items']) <= 3

def test_labels_in_glossary_fit_20_characters():
    for k, (en, hi) in i18n.LABELS.items():
        assert len(en) <= 20 and len(hi) <= 20, (k, en, hi)

# ---------------------------------------------------------------- Hindi gender agreement
def test_hindi_agrees_with_feminine_and_masculine_crops():
    assert prompts(mk(asset={'name': 'mustard', 'category': 'crop', 'growth_stage': None}), 'hi-IN')[1] == 'अब आपकी सरसों कैसी है?'
    assert prompts(mk(asset={'name': 'wheat', 'category': 'crop', 'growth_stage': None}), 'hi-IN')[1] == 'अब आपका गेहूँ कैसा है?'
    assert prompts(mk(asset={'name': 'lentil', 'category': 'crop', 'growth_stage': None}), 'hi-IN')[1] == 'अब आपकी मसूर कैसी है?'

def test_hindi_animal_questions_use_feminine_forms():
    templates.STYLE = 'concern'
    i = mk(concern='livestock_nutrition', asset={'name': 'cow', 'category': 'livestock', 'growth_stage': None})
    assert 'क्या आपकी गाय अब ठीक से खा रही है?' in prompts(i, 'hi-IN')

def test_no_masculine_possessive_before_a_feminine_asset_anywhere():
    for name, f in [(n, g == 'f') for n, (_, g) in i18n.ASSETS.items()]:
        for rt in ACTIONABLE:
            for style in ('golden', 'concern'):
                templates.STYLE = style
                cat = 'livestock' if name in ('cow', 'goat', 'buffalo') else 'crop'
                i = mk(resolution_type=rt, asset={'name': name, 'category': cat, 'growth_stage': None}, severity='medium', advice_summary='Advised something.')
                for p in prompts(i, 'hi-IN'):
                    if f: assert f'आपका {i18n.name_hi(name)}' not in p and f'आपके {i18n.name_hi(name)}' not in p, p

def test_expert_question_avoids_farmer_gender_in_hindi():
    p = prompts(mk(resolution_type='escalate_to_expert'), 'hi-IN')[0]
    assert 'मिले' not in p and 'मुलाकात' in p

# ---------------------------------------------------------------- answer-key style wording
def test_wait_and_monitor_first_question_is_have_you_seen_x():
    i = mk(resolution_type='wait_and_monitor', advice_summary='Advised to wait and watch for insects in the bins over the next few days before acting.')
    assert prompts(i)[0] == 'Have you seen insects in the bins?' and prompts(i, 'hi-IN')[0] == 'क्या आपको भंडारण के डिब्बों में कीड़े दिखे?'

@pytest.mark.parametrize('advice,en', [('Advised to apply zinc as per soil test advice and repeat the soil test next season.', 'Did you apply zinc?'),
                                       ('Advised to apply a sulphur fertiliser as per soil test advice.', 'Did you apply sulphur?'),
                                       ('Advised to call the nearest veterinary doctor today and keep the animal separate.', 'Did you call the vet?'),
                                       ('Advised to open drains on the low side of the field within a day.', 'Did you drain the field?')])
def test_direct_action_first_question_comes_from_the_advice(advice, en): assert prompts(mk(advice_summary=advice))[0] == en

def test_unknown_advice_falls_back_to_a_concern_question():
    assert prompts(mk(advice_summary='Advised something nobody wrote a rule for.'))[0] == 'Did you treat the pest or disease?'

def test_concern_style_plan_asks_about_the_first_step():
    templates.STYLE = 'concern'
    i = mk(resolution_type='plan_created', advice_summary='Gave a plan in stages: first stop irrigation on windy days and do not add more nitrogen, then watch for more plants falling and take the next step if needed.')
    assert prompts(i)[0] == 'Did you avoid irrigation on windy days?'

def test_concern_style_flags_the_bad_answer_for_follow_up():
    templates.STYLE = 'concern'
    s = sv(mk(concern='nutrient_deficiency'))
    assert any(o.get('follow_up') == 'crop_or_animal_damaged' for o in s['items'][1]['options'])

def test_render_template_fills_slots_in_both_languages():
    S = i18n.slots('cow')
    assert render_template('now', S, 'en-IN') == 'How is your cow now?' and render_template('now', S, 'hi-IN') == 'अब आपकी गाय कैसी है?'

def test_write_surveys_returns_both_languages_with_self_eval():
    out = write_surveys(mk(), {'not_before': '2026-12-10T09:00:00+05:30', 'not_after': '2026-12-12T09:00:00+05:30'})
    assert set(out) == {'hi-IN', 'en-IN'} and out['hi-IN']['language'] == 'hi-IN'
    assert out['en-IN']['self_eval']['gives_new_advice'] is False and out['en-IN']['self_eval']['schema_valid'] is True
    assert 0 < out['en-IN']['self_eval']['relevance_score'] <= 1

# ---------------------------------------------------------------- guards, English and Hindi
def S(prompt, labels=('Yes', 'No'), lang='en-IN', fu=None, typ='survey-confirm'):
    return survey([{'item_id': 'q1', 'type': typ, 'prompt': prompt, 'options': [{'value': f'v{n}', 'label': l, **({'follow_up': fu} if (fu and n == 0) else {})} for n, l in enumerate(labels)]}], lang)

@pytest.mark.parametrize('text', ['You should spray the field today?', 'Please spray neem oil now.', 'Spray the insecticide in the evening.', 'We recommend more water?',
                                  'Make sure to dry the grain?', 'Apply zinc this week.', 'It is better to wait?'])
def test_english_advice_is_blocked(text): assert 'gives_new_advice' in check_survey_result(S(text)).codes

@pytest.mark.parametrize('text', ['आपको गेहूँ में दवा छिड़कनी चाहिए?', 'क्या आप आज दवा डालें?', 'कृपया तुरंत छिड़काव कीजिए।', 'क्या आपको पानी देना होगा?', 'क्या आप खेत में पानी दें?'])
def test_hindi_advice_is_blocked(text): assert 'gives_new_advice' in check_survey_result(S(text, ('हाँ', 'नहीं'), 'hi-IN')).codes

@pytest.mark.parametrize('text', ['Did you spray for rust?', 'Did you apply zinc?', 'Do you need more help?', 'Did you contact the vet?', 'Is the plan working so far?'])
def test_english_questions_about_actions_are_allowed(text): assert check_survey_result(S(text)).ok

@pytest.mark.parametrize('text', ['क्या आपने सल्फर खाद डाली?', 'क्या आपको और मदद चाहिए?', 'क्या आपने पशु डॉक्टर को बुलाया?', 'अगर नहीं किया, तो क्या रुकावट थी?', 'क्या आपने पानी निकाला?'])
def test_hindi_questions_about_actions_are_allowed(text): assert check_survey_result(S(text, ('हाँ', 'नहीं'), 'hi-IN')).ok

@pytest.mark.parametrize('text', ['What is your name?', 'Can you share your phone number?', 'What is your Aadhaar number?', 'What is your monthly income?', 'Where is your address?',
                                  'Which bank account do you use?', 'What is your age?', 'Tell us the OTP'])
def test_english_personal_info_is_blocked(text): assert 'asks_personal_info' in check_survey_result(S(text)).codes

@pytest.mark.parametrize('text', ['आपका नाम क्या है?', 'आपका फ़ोन नंबर क्या है?', 'आपका आधार नंबर बताइए?', 'आपकी आमदनी कितनी है?', 'आपका पता क्या है?', 'आपका बैंक खाता कौन सा है?', 'आपकी उम्र क्या है?'])
def test_hindi_personal_info_is_blocked(text): assert 'asks_personal_info' in check_survey_result(S(text, ('हाँ', 'नहीं'), 'hi-IN')).codes

def test_hindi_dont_know_is_not_an_address():
    assert check_survey_result(S('क्या आपको समस्या दिखी?', ('हाँ', 'पता नहीं'), 'hi-IN')).ok

def test_the_devanagari_word_aaya_is_not_income():   # regression: substring match flagged "आया" because it contains "आय"
    assert check_survey_result(S('क्या यह समझ आया?', ('हाँ', 'नहीं'), 'hi-IN')).ok

def test_wrong_language_is_caught():
    assert 'wrong_language' in check_survey_result(S('क्या आपने सल्फर डाली?', ('Yes', 'No'), 'en-IN')).codes
    assert 'wrong_language' in check_survey_result(S('Did you apply sulphur?', ('Yes', 'No'), 'hi-IN')).codes

def test_structure_guards():
    assert 'label_too_long' in check_survey_result(S('Did you do it?', ('Yes, with a lot of difficulty', 'No'))).codes
    assert 'unknown_follow_up' in check_survey_result(S('Did you do it?', ('Yes', 'No'), fu='made_up')).codes
    assert 'confirm_needs_two' in check_survey_result(S('Did you do it?', ('Yes', 'No', 'Maybe'), typ='survey-confirm')).codes
    assert 'bad_item_count' in check_survey_result(survey([])).codes
    four = survey(S('Did you do it?')['items'] * 4)
    assert 'bad_item_count' in check_survey_result(four).codes

def test_allow_list_entry_needs_exact_text_and_is_tested(monkeypatch):
    t = 'Which name did the vet give the medicine?'            # asks for a medicine name, not the farmer's name
    assert 'asks_personal_info' in check_survey_result(S(t)).codes
    monkeypatch.setattr(guards, 'ALLOW', {('asks_personal_info', t)})
    assert check_survey_result(S(t)).ok
    assert 'asks_personal_info' in check_survey_result(S('What name do you use?')).codes

def test_check_survey_returns_a_list_of_strings_like_before():
    assert check_survey(S('Did you do it?')) == [] and any('advice' in p for p in check_survey(S('You should spray now.')))

def test_guard_result_still_works_like_a_dict():
    r = check_survey_result(S('Did you do it?')); assert r['ok'] is True and r.failures == []

# ---------------------------------------------------------------- relevance v2
def test_relevance_rewards_crop_concern_and_advice_in_both_languages():
    i = mk(asset={'name': 'wheat', 'category': 'crop', 'growth_stage': None}, concern='nutrient_deficiency', advice_summary='Advised to apply zinc as per soil test advice and repeat the soil test next season.')
    assert relevance(sv(i, 'en-IN'), i) >= 0.8 and relevance(sv(i, "hi-IN"), i) >= 0.8
    off = S('Is the sky blue?')
    assert relevance(off, i) < 0.5

def test_relevance_is_between_0_and_1():
    for rt in ACTIONABLE:
        i = mk(resolution_type=rt); assert 0 <= relevance(sv(i), i) <= 1


def test_duplicate_item_ids_are_caught():
    one = S('Did you do it?')['items'][0]
    two = {**one, 'prompt': 'Is it better now?'}      # same item_id 'q1'
    assert 'duplicate_item_id' in check_survey_result(survey([one, two])).codes

def test_scale_of_more_than_10_steps_is_caught():
    scale = lambda hi: {'item_id': 'q1', 'type': 'survey-scale', 'prompt': 'How useful was the plan?', 'scale_min': 1, 'scale_max': hi}
    assert 'scale_over_10_steps' in check_survey_result(survey([scale(11)])).codes
    assert check_survey_result(survey([scale(5)])).ok

def test_options_over_10_are_caught():
    labels = tuple(str(n) for n in range(11))
    assert 'bad_option_count' in check_survey_result(S('How bad is it?', labels, typ='survey-single-select')).codes

def test_schema_errors_surface_as_schema_problems():
    s = S('Did you do it?'); del s['survey_id']
    r = check_survey_result(s)
    assert 'schema_invalid' in r.codes and any(p.startswith('schema') for p in check_survey(s))

def test_follow_up_reasons_are_the_four_in_the_shared_schema():
    assert guards.ALLOWED_FOLLOW_UP == {'advice_did_not_work', 'crop_or_animal_damaged', 'could_not_get_input', 'could_not_reach_expert'}
    for rt, cn, st in itertools.product(ACTIONABLE, templates.TOP10, ['golden', 'concern']):
        templates.STYLE = st
        for lang in ('hi-IN', 'en-IN'):
            for q in template_items(mk(resolution_type=rt, concern=cn), lang):
                for o in q.get('options', []): assert o.get('follow_up') in (None, *guards.ALLOWED_FOLLOW_UP), (rt, cn, o)

def test_every_pack_insight_gets_a_valid_survey_in_both_languages():
    n = 0
    for i in load_insights():
        d = decide(i)
        if d.survey:
            for s in write_surveys(i, d.send_window).values():
                assert check_survey(clean(s)) == [], i['insight_id']; n += 1
    assert n > 0
