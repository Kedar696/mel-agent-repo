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
from mel.writer import check_survey_result, relevance, template_items, render_template, templates, i18n, guards

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


def test_brief_mustard_scenario_asks_about_the_main_action_not_the_evening_detail():
    """The brief's worked scenario 1: 'Spray the recommended insecticide within 2 days ... Spray in the evening when bees are not active.'"""
    i = mk(asset={'name': 'mustard', 'category': 'crop', 'growth_stage': None}, advice_summary='These are aphids. Spray the recommended insecticide within 2 days if no rain is forecast. Spray in the evening when bees are not active.')
    assert prompts(i)[0] == 'Did you spray the insecticide?' and prompts(i, 'hi-IN')[0] == 'क्या आपने कीटनाशक का छिड़काव किया?'

# ======================================================================================================
# P4 Bedrock path (Team Contracts, 4 Nov): ModelClient, hi-IN / en-IN, English baseline, self_eval on every survey.
# No test calls AWS: a fake bedrock-runtime object stands in for boto3.
# ======================================================================================================
import json
from mel.writer import compose_survey, write_survey_llm, norm_lang, BASELINE_LANG, llm

WINDOW = {'not_before': '2026-12-10T09:00:00+05:30', 'not_after': '2026-12-12T09:00:00+05:30'}


class ClientErr(Exception):
    def __init__(self, code):
        super().__init__(code); self.response = {'Error': {'Code': code}}


class FakeRuntime:
    """Stands in for boto3's bedrock-runtime. `replies` are texts returned in order (last one repeats); `errors` are raised first, in order."""
    def __init__(self, replies, errors=()):
        self.replies, self.errors, self.calls = list(replies), list(errors), []
    def converse(self, **kw):
        self.calls.append(kw)
        if self.errors:
            e = self.errors.pop(0)
            if e: raise e
        text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return {'output': {'message': {'content': [{'text': text}]}}, 'usage': {'inputTokens': 100, 'outputTokens': 50}, 'metrics': {'latencyMs': 5}}


def items_json(insight, lang):
    return json.dumps({'items': template_items(insight, lang)}, ensure_ascii=False)


@pytest.fixture
def bedrock(tmp_path, monkeypatch):
    """Switch the model path on with a temp cache and log; returns a function that installs a fake runtime."""
    monkeypatch.setenv('MEL_USE_LLM', '1')
    monkeypatch.setenv('MEL_BEDROCK_WRITE_MODEL', 'test-write-model')
    monkeypatch.setenv('MEL_CACHE_DIR', str(tmp_path / 'cache'))
    monkeypatch.setenv('MEL_LLM_LOG', str(tmp_path / 'calls.jsonl'))
    monkeypatch.setenv('MEL_BEDROCK_PRICES', json.dumps({'test-write-model': {'in': 0.003, 'out': 0.015}, 'test-check-model': {'in': 0.001, 'out': 0.002}}))
    def install(replies, errors=(), max_attempts=4):
        rt = FakeRuntime(replies, errors)
        llm.set_client(llm.ModelClient(runtime=rt, max_attempts=max_attempts, sleep=lambda s: None))
        return rt
    yield install
    llm.set_client(None)


def test_model_path_is_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv('MEL_USE_LLM', raising=False); monkeypatch.setenv('MEL_LLM_LOG', str(tmp_path / 'calls.jsonl'))
    s = compose_survey({'send_window': WINDOW}, mk(), 'en-IN')
    assert s['_source'] == 'template' and 'self_eval' in s and not (tmp_path / 'calls.jsonl').exists()


def test_model_path_needs_a_model_id(monkeypatch):
    monkeypatch.setenv('MEL_USE_LLM', '1'); monkeypatch.delenv('MEL_BEDROCK_WRITE_MODEL', raising=False)
    assert llm.enabled() is False


@pytest.mark.parametrize('given,expected', [('hi', 'hi-IN'), ('hi-IN', 'hi-IN'), ('hi_in', 'hi-IN'), ('en', 'en-IN'), ('en-IN', 'en-IN'), ('EN-in', 'en-IN')])
def test_norm_lang(given, expected):
    assert norm_lang(given) == expected


def test_norm_lang_refuses_unknown_language():
    with pytest.raises(ValueError): norm_lang('ta-IN')
    with pytest.raises(ValueError): compose_survey({'send_window': WINDOW}, mk(), 'fr')


def test_english_is_the_baseline_and_both_languages_come_from_the_same_code():
    assert BASELINE_LANG == 'en-IN'
    out = write_surveys(mk(), WINDOW)
    assert set(out) == {'hi-IN', 'en-IN'} and out['en-IN']['language'] == 'en-IN' and out['hi-IN']['language'] == 'hi-IN'
    assert compose_survey({'send_window': WINDOW}, mk()) ['language'] == 'en-IN'      # no language given -> English


@pytest.mark.parametrize('lang', ['en-IN', 'hi-IN'])
def test_every_survey_carries_a_complete_self_eval(lang):
    ev = compose_survey({'send_window': WINDOW}, mk(), lang)['self_eval']
    assert set(ev) == {'schema_valid', 'relevance_score', 'gives_new_advice', 'asks_personal_info'}
    assert ev['schema_valid'] is True and ev['gives_new_advice'] is False and ev['asks_personal_info'] is False and 0 < ev['relevance_score'] <= 1


def test_bedrock_survey_is_used_when_it_passes_everything(bedrock):
    rt = bedrock([items_json(mk(), 'en-IN')])
    s = compose_survey({'send_window': WINDOW}, mk(), 'en-IN')
    assert s['_source'] == 'llm' and s['_model'] == 'test-write-model' and 'self_eval' in s and check_survey(clean_s(s)) == []
    call = rt.calls[0]
    assert call['modelId'] == 'test-write-model' and call['inferenceConfig']['maxTokens'] > 0 and 'en-IN' in call['messages'][0]['content'][0]['text']


def clean_s(s): return {k: v for k, v in s.items() if not k.startswith('_')}


def test_bedrock_hindi_goes_through_hi_IN(bedrock):
    bedrock([items_json(mk(), 'hi-IN')])
    s = compose_survey({'send_window': WINDOW}, mk(), 'hi-IN')
    assert s['_source'] == 'llm' and s['language'] == 'hi-IN' and guards._DEV.search(s['items'][0]['prompt'])


def test_write_survey_llm_returns_none_when_off(monkeypatch):
    monkeypatch.delenv('MEL_USE_LLM', raising=False)
    assert write_survey_llm({'send_window': WINDOW}, mk(), 'en-IN') is None


def test_write_survey_llm_returns_survey_when_on(bedrock):
    bedrock([items_json(mk(), 'en-IN')])
    s = write_survey_llm({'send_window': WINDOW}, mk(), 'en-IN')
    assert s and s['self_eval']['schema_valid'] and s['_source'] == 'llm'


def test_only_the_five_allowed_fields_are_sent_to_the_model(bedrock):
    rt = bedrock([items_json(mk(), 'en-IN')])
    compose_survey({'send_window': WINDOW}, mk(farmer_id='F-SECRET-9', conversation_id='C-SECRET-9'), 'en-IN')
    sent = json.dumps(rt.calls[0], ensure_ascii=False)
    assert 'F-SECRET-9' not in sent and 'C-SECRET-9' not in sent and 'wheat' in sent and 'advice_summary' in sent


def test_model_survey_that_gives_advice_falls_back_to_template(bedrock):
    bad = json.loads(items_json(mk(), 'en-IN')); bad['items'][0]['prompt'] = 'You should spray the insecticide today.'
    bedrock([json.dumps(bad)])
    s = compose_survey({'send_window': WINDOW}, mk(), 'en-IN')
    assert s['_source'] == 'template' and s['_fallback_reason'].startswith('guard:') and 'gives_new_advice' in s['_fallback_reason']
    assert s['self_eval']['gives_new_advice'] is False        # self_eval describes the survey that is actually sent


def test_model_survey_that_asks_personal_info_falls_back(bedrock):
    bad = json.loads(items_json(mk(), 'en-IN')); bad['items'][1]['prompt'] = 'What is your phone number?'
    bedrock([json.dumps(bad)])
    s = compose_survey({'send_window': WINDOW}, mk(), 'en-IN')
    assert s['_source'] == 'template' and 'asks_personal_info' in s['_fallback_reason']


def test_model_survey_with_wrong_number_of_questions_falls_back(bedrock):
    two = json.loads(items_json(mk(), 'en-IN')); two['items'] = two['items'][:2]       # medium-severity direct_action needs 3
    bedrock([json.dumps(two)])
    assert compose_survey({'send_window': WINDOW}, mk(), 'en-IN')['_fallback_reason'] == 'wrong_question_count'


def test_model_survey_less_relevant_than_template_falls_back(bedrock):
    generic = {'items': [{'item_id': f'q{n}', 'type': 'survey-confirm', 'prompt': 'Is everything fine?',
                          'options': [{'value': 'yes', 'label': 'Yes'}, {'value': 'no', 'label': 'No'}]} for n in (1, 2, 3)]}
    bedrock([json.dumps(generic)])
    assert compose_survey({'send_window': WINDOW}, mk(), 'en-IN')['_fallback_reason'] == 'less_relevant_than_template'


def test_unreadable_model_answer_falls_back(bedrock):
    bedrock(['Sorry, I cannot help with that.'])
    assert compose_survey({'send_window': WINDOW}, mk(), 'en-IN')['_fallback_reason'] == 'model_unavailable_or_unreadable'


def test_small_model_check_can_veto(bedrock, monkeypatch):
    monkeypatch.setenv('MEL_BEDROCK_CHECK_MODEL', 'test-check-model')
    # call 1 = the writer (valid items), call 2 = the checker (says: contradicts the advice)
    bedrock([items_json(mk(), 'en-IN'), json.dumps({'gives_new_advice': False, 'asks_personal_info': False, 'contradicts_advice': True})])
    s = compose_survey({'send_window': WINDOW}, mk(), 'en-IN')
    assert s['_source'] == 'template' and s['_fallback_reason'] == 'model_check:contradicts_advice'


def test_small_model_check_that_approves_lets_the_survey_through(bedrock, monkeypatch):
    monkeypatch.setenv('MEL_BEDROCK_CHECK_MODEL', 'test-check-model')
    rt = bedrock([items_json(mk(), 'en-IN'), json.dumps({'gives_new_advice': False, 'asks_personal_info': False, 'contradicts_advice': False})])
    assert compose_survey({'send_window': WINDOW}, mk(), 'en-IN')['_source'] == 'llm'
    assert [c['modelId'] for c in rt.calls] == ['test-write-model', 'test-check-model']       # small model checks, larger one writes


def test_unreadable_check_answer_means_no_opinion_not_safe(bedrock, monkeypatch):
    monkeypatch.setenv('MEL_BEDROCK_CHECK_MODEL', 'test-check-model')
    bedrock([items_json(mk(), 'en-IN'), 'maybe'])
    assert llm.model_check({'language': 'en-IN', 'items': []}, mk()) is None


def test_throttling_is_retried_then_succeeds(bedrock):
    rt = bedrock([items_json(mk(), 'en-IN')], errors=[ClientErr('ThrottlingException'), ClientErr('ThrottlingException')])
    assert compose_survey({'send_window': WINDOW}, mk(), 'en-IN')['_source'] == 'llm' and len(rt.calls) == 3


def test_endless_throttling_gives_up_and_uses_the_template(bedrock):
    rt = bedrock([items_json(mk(), 'en-IN')], errors=[ClientErr('ThrottlingException')] * 10, max_attempts=3)
    s = compose_survey({'send_window': WINDOW}, mk(), 'en-IN')
    assert s['_source'] == 'template' and len(rt.calls) == 3 and s['_fallback_reason'] == 'model_unavailable_or_unreadable'


def test_model_not_enabled_is_not_retried(bedrock):
    rt = bedrock([items_json(mk(), 'en-IN')], errors=[ClientErr('AccessDeniedException')])
    assert compose_survey({'send_window': WINDOW}, mk(), 'en-IN')['_source'] == 'template' and len(rt.calls) == 1


def test_no_boto3_or_credentials_means_templates(bedrock, monkeypatch):
    llm.set_client(llm.ModelClient())          # real client, but boto3 is not installed here / has no credentials
    s = compose_survey({'send_window': WINDOW}, mk(), 'en-IN')
    assert s['_source'] == 'template' and 'self_eval' in s


def test_second_identical_request_is_served_from_the_disk_cache(bedrock):
    rt = bedrock([items_json(mk(), 'en-IN')])
    compose_survey({'send_window': WINDOW}, mk(), 'en-IN'); compose_survey({'send_window': WINDOW}, mk(), 'en-IN')
    assert len(rt.calls) == 1
    u = llm.usage_summary()
    assert u['calls'] == 2 and u['cached'] == 1


def test_every_call_logs_tokens_cost_and_time(bedrock):
    bedrock([items_json(mk(), 'en-IN')])
    compose_survey({'send_window': WINDOW}, mk(), 'en-IN')
    row = json.loads(llm.log_path().read_text(encoding='utf-8').splitlines()[0])
    assert row['model'] == 'test-write-model' and row['input_tokens'] == 100 and row['output_tokens'] == 50 and row['tag'] == 'I-X'
    assert row['cost_usd'] == pytest.approx(100 / 1000 * 0.003 + 50 / 1000 * 0.015) and row['seconds'] >= 0 and row['ok'] and not row['cached']


def test_usage_summary_adds_up_a_run_and_never_invents_a_price(bedrock, monkeypatch):
    monkeypatch.setenv('MEL_BEDROCK_CHECK_MODEL', 'unpriced-model')
    bedrock([items_json(mk(), 'en-IN'), json.dumps({'gives_new_advice': False, 'asks_personal_info': False, 'contradicts_advice': False})])
    compose_survey({'send_window': WINDOW}, mk(), 'en-IN')
    u = llm.usage_summary()
    assert u['calls'] == 2 and u['input_tokens'] == 200 and u['output_tokens'] == 100
    assert u['unpriced_calls'] == 1 and u['cost_usd'] == pytest.approx(0.00075 * 0 + 100 / 1000 * 0.003 + 50 / 1000 * 0.015)
    assert set(u['by_model']) == {'test-write-model', 'unpriced-model'}


def test_failed_calls_are_logged_too(bedrock):
    bedrock(['x'], errors=[ClientErr('AccessDeniedException')])
    compose_survey({'send_window': WINDOW}, mk(), 'en-IN')
    u = llm.usage_summary()
    assert u['failed'] == 1 and u['ok'] == 0


def test_template_english_surveys_pass_end_to_end_on_every_insight():
    """English is the evaluation baseline: every English survey is valid, safe and carries a passing self_eval."""
    n = 0
    for i in load_insights():
        d = decide(i)
        if d.survey:
            s = compose_survey(d, i, 'en-IN')
            assert check_survey(clean_s(s)) == [] and s['self_eval']['schema_valid'] and not s['self_eval']['gives_new_advice'] and not s['self_eval']['asks_personal_info']
            n += 1
    assert n > 0


def test_comparison_says_not_run_when_bedrock_is_off(monkeypatch):
    from mel.writer.compare import compare, markdown, sample_insights
    monkeypatch.delenv('MEL_USE_LLM', raising=False)
    r = compare(sample_insights(load_insights(), decide, 10), {'large': 'x'})
    assert r['status'] == 'not run' and [row['writer'] for row in r['rows']] == ['templates'] and r['rows'][0]['guard_pass_rate'] == 1.0
    assert 'not run' in markdown(r)


def test_comparison_measures_raw_model_output_for_each_model(bedrock):
    from mel.writer.compare import compare, sample_insights
    pairs = sample_insights(load_insights(), decide, 5)
    class Echo(FakeRuntime):                       # answers every request with the template items for that insight's language
        def converse(self, **kw):
            self.calls.append(kw)
            text = kw['messages'][0]['content'][0]['text']
            ins = next(i for i, _ in pairs if i['advice_summary'] in text)
            return {'output': {'message': {'content': [{'text': items_json(ins, 'en-IN')}]}}, 'usage': {'inputTokens': 10, 'outputTokens': 5}}
    llm.set_client(llm.ModelClient(runtime=Echo([]), sleep=lambda s: None))
    r = compare(pairs, {'large': 'test-write-model'})
    assert r['status'] == 'run' and len(r['rows']) == 2
    big = r['rows'][1]
    assert big['writer'].startswith('bedrock large') and big['guard_pass_rate'] == 1.0 and big['calls'] == len(pairs) and big['input_tokens'] == 10 * len(pairs)
    assert big['cost_usd'] > 0


# ---------------------------------------------------------------- plan surveys name the first step and the crop (4 Nov)
def test_plan_survey_asks_first_step_and_names_the_crop():
    from mel.writer.templates import build_items
    ins = {"resolution_type": "plan_created", "concern": "nutrient_deficiency", "severity": "medium",
           "asset": {"name": "mustard", "category": "crop"},
           "advice_summary": "Gave a plan in stages: first apply zinc as per soil test advice, then watch for new leaves."}
    items = build_items(ins)
    assert items[0][1] == "Did you apply zinc?"
    assert items[1][1] == "Is the plan working for your mustard so far?" and "सरसों" in items[1][2]
    ins["advice_summary"] = "Gave a plan in stages."                       # no recognisable first step
    assert build_items(ins)[0][1] == "How much of the plan have you done?"  # answer-key wording stays as fallback


def test_send_bar_is_agreed_and_blocks_no_template_survey():
    from mel.data import load_insights
    from mel.pipeline import run_pipeline
    from mel.writer import RELEVANCE_THRESHOLD
    assert RELEVANCE_THRESHOLD == 0.3
    scores = [o["handoff"]["survey"]["self_eval"]["relevance_score"]
              for o in run_pipeline(load_insights(None)).outputs if "handoff" in o]
    assert scores and min(scores) >= RELEVANCE_THRESHOLD


def test_comparison_adds_ai_judge_relevance_when_given_a_judge(bedrock, tmp_path):
    """P5's AI judge scores the templates and each model's usable surveys on the same 1-5 scale."""
    from mel.writer.compare import compare, markdown, sample_insights
    pairs = sample_insights(load_insights(), decide, 4)
    class Echo(FakeRuntime):
        def converse(self, **kw):
            self.calls.append(kw)
            text = kw['messages'][0]['content'][0]['text']
            ins = next(i for i, _ in pairs if i['advice_summary'] in text)
            return {'output': {'message': {'content': [{'text': items_json(ins, 'en-IN')}]}}, 'usage': {'inputTokens': 10, 'outputTokens': 5}}
    llm.set_client(llm.ModelClient(runtime=Echo([]), sleep=lambda s: None))
    class Judge:
        model_id = "judge-x"
        def complete(self, system, user):
            return ('{"score": 4, "reason": "ok"}', {"input_tokens": 1, "output_tokens": 1})
    import mel.evaluation.judge as J
    J_CACHE, J.CACHE = J.CACHE, tmp_path / "jc"
    try:
        r = compare(pairs, {'large': 'test-write-model'}, judge=Judge())
        r2 = compare(pairs, {'large': 'judge-x'}, judge=Judge())
    finally:
        J.CACHE = J_CACHE
    assert [row['judge_relevance'] for row in r['rows']] == [4.0, 4.0]
    assert all(row['judged'] == len(pairs) for row in r['rows'])
    assert 'judge_relevance' in markdown(r) and 'judge-x' in r['note']
    assert 'grades its own writing' in r2['note']


def test_prices_fall_back_to_the_team_price_file(monkeypatch):
    """No MEL_BEDROCK_PRICES: cost comes from docs/results/bedrock_prices.json (per 1M -> per 1K), and an inference
    profile id (us....) costs what its model costs."""
    import json
    from mel.config import ROOT
    monkeypatch.delenv("MEL_BEDROCK_PRICES", raising=False)
    f = json.loads((ROOT / "docs" / "results" / "bedrock_prices.json").read_text(encoding="utf-8"))
    mid = next(k for k, v in f.items() if v.get("in") is not None and v.get("out") is not None)
    want = round(1000 / 1000 * f[mid]["in"] / 1000 + 1000 / 1000 * f[mid]["out"] / 1000, 6)
    assert llm.cost_usd(mid, 1000, 1000) == want
    assert llm.cost_usd("us." + mid, 1000, 1000) == want
    assert llm.cost_usd("no-such-model", 1000, 1000) is None


# ---------------------------------------------------------------- compact lines, Hindi by translation, reading, replay (5 Nov)
from mel.data import errors as data_errors
from mel.writer import compose, llm as _llm

COMPACT = """confirm | Did you spray the insecticide on the mustard? | Yes | No*i
select | How are the aphids now? | Gone | Fewer | Same*f | Worse*d
scale | How well did the spray work?"""


def _surveyed():
    return next(i for i in load_insights(None) if decide(i).survey)


def test_compact_lines_become_schema_items():
    items = _llm.parse_lines(COMPACT, 'en-IN')
    assert [q['item_id'] for q in items] == ['q1', 'q2', 'q3']
    assert items[0]['type'] == 'survey-confirm'
    assert items[0]['options'] == [{'value': 'yes', 'label': 'Yes'}, {'value': 'no', 'label': 'No', 'follow_up': 'could_not_get_input'}]
    assert items[1]['type'] == 'survey-single-select' and [o['value'] for o in items[1]['options']] == ['gone', 'fewer', 'same', 'worse']
    assert items[1]['options'][2]['follow_up'] == 'advice_did_not_work' and items[1]['options'][3]['follow_up'] == 'crop_or_animal_damaged'
    assert 'follow_up' not in items[1]['options'][0]
    assert items[2] == {'item_id': 'q3', 'type': 'survey-scale', 'prompt': 'How well did the spray work?', 'scale_min': 1,
                        'scale_max': 5, 'follow_up_at_or_below': 2, 'follow_up_reason': 'advice_did_not_work'}
    i = _surveyed()
    sv = {**compose._base(i, 'en-IN', decide(i).send_window), 'items': items}
    assert check_survey(sv) == [] and data_errors('survey', clean(sv)) == []
    assert _llm.lines_from(items) == COMPACT                                       # the same lines go back for a translation
    assert _llm.parse_lines('Here you go:\n```\n1. confirm | Did it help? | Yes | No\n```', 'en-IN')[0]['prompt'] == 'Did it help?'
    assert _llm.parse_lines('confirm | Did it help? | Yes | Not yet | No', 'en-IN')[0]['type'] == 'survey-single-select'
    assert _llm.parse_lines('no survey here', 'en-IN') is None


def test_hindi_translation_keeps_the_english_values(bedrock):
    en = _llm.parse_lines(COMPACT, 'en-IN')
    rt = bedrock(["confirm | क्या आपने सरसों पर दवा छिड़की? | हाँ | नहीं*i\nselect | माहू अब कैसे हैं? | खत्म | कम | वैसे ही*f | ज़्यादा*d\n"
                  "scale | छिड़काव कितना काम आया?"])
    i = _surveyed()
    hi = _llm.llm_items(i, 'hi-IN', n_items=3, source_items=en)
    assert [q['prompt'] for q in hi] == ['क्या आपने सरसों पर दवा छिड़की?', 'माहू अब कैसे हैं?', 'छिड़काव कितना काम आया?']
    shape = lambda items: [[(o['value'], o.get('follow_up')) for o in q.get('options', [])] for q in items]
    assert shape(hi) == shape(en) and hi[1]['options'][2]['label'] == 'वैसे ही' and hi[2]['follow_up_at_or_below'] == 2
    sent = rt.calls[0]
    assert 'Translate' in sent['system'][0]['text'] and 'Insight' not in sent['messages'][0]['content'][0]['text']
    assert _llm.lines_from(en) in sent['messages'][0]['content'][0]['text']
    assert sent['inferenceConfig']['maxTokens'] == _llm.MAX_WRITE_TOKENS
    bedrock(["confirm | क्या आपने दवा छिड़की? | हाँ | नहीं"])                       # one line for a two-line survey
    assert _llm.llm_items(i, 'hi-IN', n_items=2, source_items=en[:2]) is None


def test_read_conversation_fills_only_allowed_fields(bedrock):
    rt = bedrock(["asset: Goat\nconcern: livestock_health\nseverity: High\nadvice_type: escalate_to_expert\n"
                  "act_within_days: 1 day\ncheck_back: next_day\nquestions: 2\ncolour: blue"])
    got = _llm.read_conversation('My goat is not eating', 'Call the vet today.')
    assert got == {'asset': 'goat', 'concern': 'livestock_health', 'severity': 'high', 'advice_type': 'escalate_to_expert',
                   'act_within_days': 1, 'check_back': 'next_day', 'questions': 2}
    sent = rt.calls[0]
    assert sent['inferenceConfig']['maxTokens'] == 120 and 'My goat is not eating' in sent['messages'][0]['content'][0]['text']
    bedrock(["severity: urgent\nquestions: 7\nadvice_type: do_not_act"])
    assert _llm.read_conversation('x', 'y') == {'advice_type': 'do_not_act'}        # unknown values are dropped


def test_committed_replay_file_answers_without_bedrock(bedrock, tmp_path, monkeypatch):
    monkeypatch.setattr(_llm, '_replay', None)
    bedrock([COMPACT])
    i = _surveyed()
    first = _llm.llm_items(i, 'en-IN', n_items=3)
    replay = tmp_path / 'replay.jsonl'
    assert first is not None and _llm.export_cache(replay) == 1 and _llm.export_cache(replay) == 1   # idempotent
    monkeypatch.setattr(_llm, 'REPLAY', replay)
    monkeypatch.setenv('MEL_CACHE_DIR', str(tmp_path / 'empty'))                  # a laptop with no cache of its own
    boom = bedrock([], errors=[RuntimeError('no AWS here')])
    assert _llm.llm_items(i, 'en-IN', n_items=3) == first and boom.calls == []     # answered from the committed file
    assert _llm.client().last_usage['cached'] is True
