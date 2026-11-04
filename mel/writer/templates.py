"""P4 - question templates (English + Hindi).

What the answer key tells us (golden_set v1, 40 direct_action surveys; this is why the rules below are what they are):
  * direct_action  : 3 questions when severity is medium/high (26 of 26), 2 questions when severity is low (14 of 14)
  * all other advice types: always 2 questions
  * wait_and_monitor first question is literally "Have you seen <X>?" where the advice says "wait and watch for <X>"
  * first question of direct_action is a short action question taken from the advice ("Did you apply zinc?")

Two outcome styles (setting `writer_style`):
  'golden'  : "How is your wheat now? Better / Same / Worse" (what the answer key uses)
  'concern' : outcome question specific to the concern (insect count, yellowing, drooping, seed availability, animal health ...)

Nothing here gives advice or asks for personal information. Every Hindi string is "pending native review".
"""
import re
from mel.writer import i18n

# ---------------------------------------------------------------- text templates (key -> (en, hi))
TEMPLATES = {
    'now': ('How is your {name} now?', 'अब {poss} {name_hi} {kaisa} है?'),
    'hold_off': ('Did you hold off as advised?', 'क्या आपने सलाह के अनुसार रुककर इंतज़ार किया?'),
    'barrier': ('If not, what stopped you?', 'अगर नहीं किया, तो क्या रुकावट थी?'),
    'watch_generic': ('Have you seen the problem get worse in your {name}?', 'क्या {ke} {name_hi} में समस्या बढ़ी?'),
    'help': ('Do you need more help?', 'क्या आपको और मदद चाहिए?'),
    'plan_progress': ('How much of the plan have you done?', 'आपने योजना का कितना काम किया?'),
    'plan_working': ('Is the plan working so far?', 'क्या योजना अब तक काम कर रही है?'),
    # Hindi avoids "मिले/गए" (verb would have to agree with the farmer's gender); "मुलाकात हो पाई" does not
    'expert_met_vet': ('Did you meet the veterinary doctor?', 'क्या पशु डॉक्टर से मुलाकात हो पाई?'),
    'expert_met_agri': ('Did you meet the agriculture expert?', 'क्या कृषि विशेषज्ञ से मुलाकात हो पाई?'),
    'expert_helped': ('Did their advice help?', 'क्या उनकी सलाह से फ़ायदा हुआ?'),
    # concern-specific outcome questions
    'out.pest_disease': ('How are the insects or spots on your {name} now?', '{name_hi} पर कीड़े या धब्बे अब कैसे हैं?'),
    'out.nutrient_deficiency': ('How do the leaves of your {name} look now?', '{name_hi} के पत्ते अब कैसे दिख रहे हैं?'),
    'out.water_stress': ('How do your {name} plants look now?', '{name_hi} के पौधे अब कैसे दिख रहे हैं?'),
    'out.weather_climate': ('Did the weather harm your {name}?', 'क्या मौसम से {name_hi} को नुकसान हुआ?'),
    'out.growth_issue': ('How is your {name} now?', 'अब {poss} {name_hi} {kaisa} है?'),
    'out.livestock_nutrition': ('Is your {name} eating well now?', 'क्या {poss} {name_hi} अब ठीक से खा {rahi} है?'),
    'out.storage_post_harvest': ('Is there still damage in your stored {name}?', 'क्या भंडार में रखे {name_hi} में अब भी नुकसान है?'),
    'out.livestock_health': ('How is your {name} now?', 'अब {poss} {name_hi} {kaisa} है?'),
    'out.variety_selection': ('Was it easy to get good seed?', 'क्या अच्छा बीज आसानी से मिल गया?'),
    'out.market_price': ('Did you sell as planned?', 'क्या आपने सोचे हुए तरीके से बेचा?'),
}


def render_template(key, slots, lang):
    en, hi = TEMPLATES[key]
    return (hi if lang.startswith('hi') else en).format(**slots)


# ---------------------------------------------------------------- options
def opt(value, label_key, fu=None):
    en, hi = i18n.LABELS[label_key]
    return {'value': value, 'en': en, 'hi': hi, **({'follow_up': fu} if fu else {})}

YNN = lambda: [opt('yes', 'yes'), opt('not_yet', 'not_yet'), opt('no', 'no')]
YN = lambda: [opt('yes', 'yes'), opt('no', 'no')]
NOW = lambda: [opt('better', 'better'), opt('same', 'same'), opt('worse', 'worse', 'advice_did_not_work')]
BARRIER = lambda: [opt('too_costly', 'too_costly'), opt('not_nearby', 'not_nearby'), opt('no_time', 'no_time'), opt('not_understood', 'not_understood', 'could_not_get_input')]

OUTCOME_OPTS = {   # concern -> options (follow_up marks the answers that mean "advice failed or harm happened")
    'pest_disease': lambda: [opt('almost_none', 'almost_none'), opt('fewer', 'fewer'), opt('same', 'same_as_before'), opt('more', 'more', 'problem_growing')],
    'nutrient_deficiency': lambda: [opt('green', 'green'), opt('some_yellow', 'some_yellow'), opt('many_yellow', 'many_yellow', 'crop_or_animal_damaged')],
    'water_stress': lambda: [opt('normal', 'normal'), opt('some_droop', 'some_droop'), opt('many_droop', 'many_droop', 'crop_or_animal_damaged')],
    'weather_climate': lambda: [opt('no_harm', 'no_harm'), opt('little_harm', 'little_harm'), opt('bad_harm', 'bad_harm', 'crop_or_animal_damaged')],
    'growth_issue': NOW,
    'livestock_nutrition': lambda: [opt('eating_well', 'eating_well'), opt('eating_less', 'eating_less'), opt('not_eating', 'not_eating', 'crop_or_animal_damaged')],
    'storage_post_harvest': lambda: [opt('no_damage', 'no_damage'), opt('less', 'less_damage'), opt('same', 'same_damage'), opt('more', 'more_damage', 'problem_growing')],
    'livestock_health': NOW,
    'variety_selection': lambda: [opt('easy', 'seed_easy'), opt('hard', 'seed_hard'), opt('not_found', 'seed_none', 'could_not_get_input')],
    'market_price': lambda: [opt('yes', 'sold'), opt('not_yet', 'not_yet'), opt('other', 'sold_differently')],
}
TOP10 = ['pest_disease', 'weather_climate', 'growth_issue', 'nutrient_deficiency', 'water_stress', 'livestock_nutrition',
         'storage_post_harvest', 'livestock_health', 'variety_selection', 'market_price']   # by count in the 6,999 run

# ---------------------------------------------------------------- first question of direct_action: short action question taken from the advice
# (regex on advice_summary, English question, Hindi question). First match wins, so specific rules come before generic ones.
ACTION_RULES = [
    (r'clean the store', 'Did you re-dry and use airtight bins?', 'क्या आपने उपज को फिर सुखाकर हवा-बंद डिब्बों में रखा?'),
    (r'stop irrigation on windy days', 'Did you avoid irrigation on windy days?', 'क्या आपने तेज़ हवा वाले दिनों में सिंचाई नहीं की?'),
    (r'postpone sprays and irrigation', 'Did you drain the standing water?', 'क्या आपने खेत में खड़ा पानी निकाला?'),
    (r'sulphur', 'Did you apply sulphur?', 'क्या आपने सल्फर खाद डाली?'),
    (r'check irrigation and drainage first', 'Did you fix water and top-dress?', 'क्या आपने पानी ठीक किया और खाद डाली?'),
    (r'top-dress urea', 'Did you top-dress urea?', 'क्या आपने ऊपर से यूरिया डाली?'),
    (r'light irrigation in the evening and keep the field moist', 'Did you give a light irrigation in the evening?', 'क्या आपने शाम को हल्की सिंचाई की?'),
    (r'light irrigation in the evening to protect grain', 'Did you irrigate lightly in the heat?', 'क्या आपने गर्मी में हल्की सिंचाई की?'),
    (r'\bzinc\b', 'Did you apply zinc?', 'क्या आपने ज़िंक डाला?'),
    (r'check the crop every two days', 'Did you check the crop for leaf spots?', 'क्या आपने पत्तों पर धब्बों की जाँच की?'),
    (r'soil insecticide', 'Did you treat the affected patches?', 'क्या आपने प्रभावित हिस्सों में इलाज किया?'),
    (r'feel if the soil below', 'Did you give a light irrigation?', 'क्या आपने हल्की सिंचाई की?'),
    (r'local forecast', 'Did you plan field work by the forecast?', 'क्या आपने मौसम देखकर खेत का काम किया?'),
    (r'open drains on the low side', 'Did you drain the field?', 'क्या आपने खेत से पानी निकाला?'),
    (r'whorl', 'Did you control fall armyworm?', 'क्या आपने फॉल आर्मीवर्म का नियंत्रण किया?'),
    (r'shake plants over a cloth', 'Did you control the painted bug?', 'क्या आपने पेंटेड बग का नियंत्रण किया?'),
    (r'neem oil', 'Did you spray neem oil?', 'क्या आपने नीम तेल का छिड़काव किया?'),
    (r'berseem or oats', 'Did you sow winter fodder?', 'क्या आपने सर्दी का चारा बोया?'),
    (r'fill the gaps', 'Did you fill the gaps in the field?', 'क्या आपने खेत की खाली जगहों में बीज या पौधे लगाए?'),
    (r'fungicide for rust', 'Did you spray for rust?', 'क्या आपने रतुआ रोग के लिए छिड़काव किया?'),
    (r'powdery mildew', 'Did you spray for powdery mildew?', 'क्या आपने चूर्णिल आसिता (सफ़ेद चूर्ण) के लिए छिड़काव किया?'),
    (r'late blight', 'Did you spray for late blight?', 'क्या आपने पछेती झुलसा के लिए छिड़काव किया?'),
    (r'warm water, a balanced feed', 'Did you give warm water and balanced feed?', 'क्या आपने गुनगुना पानी और संतुलित चारा दिया?'),
    (r'dry the produce in the sun', 'Did you dry the produce and store it in clean bags?', 'क्या आपने उपज सुखाकर साफ़ बोरों में रखी?'),
    (r'pull out wilted plants', 'Did you remove the wilted plants?', 'क्या आपने मुरझाए पौधे निकाले?'),
    (r'remove (badly affected plants|the worst leaves|lower affected leaves)', 'Did you remove the affected plants or leaves and spray?', 'क्या आपने खराब पौधे या पत्ते हटाकर छिड़काव किया?'),
    (r'remove (affected|dead|dried)', 'Did you remove the affected parts?', 'क्या आपने खराब या सूखे हिस्से हटाए?'),
    (r'bees are not active', 'Did you spray in the evening?', 'क्या आपने शाम को कीटनाशक छिड़का?'),
    (r'certified seed', 'Did you buy certified seed?', 'क्या आपने प्रमाणित बीज लिया?'),
    (r'variety suited to late sowing', 'Did you choose a late-sowing variety?', 'क्या आपने देर से बुवाई वाली किस्म चुनी?'),
    (r'rotten tubers', 'Did you sort out rotten tubers?', 'क्या आपने सड़े कंद अलग किए?'),
    (r'veterinary doctor today', 'Did you call the vet?', 'क्या आपने पशु डॉक्टर को बुलाया?'),
    (r'deworm', 'Did you deworm the animal?', 'क्या आपने पशु को कृमिनाशक दवा दी?'),
    (r'mineral mixture daily', 'Did you get the animal checked?', 'क्या आपने पशु की जाँच करवाई?'),
    (r'vaccination camp', 'Did you get the animal vaccinated?', 'क्या आपने पशु को टीका लगवाया?'),
    (r'\bAI worker', 'Did you call the AI worker?', 'क्या आपने कृत्रिम गर्भाधान (एआई) कार्यकर्ता को बुलाया?'),
    (r'covered shed', 'Did you keep the animal in a covered shed?', 'क्या आपने पशु को ढके हुए बाड़े में रखा?'),
    (r'herbicide for grassy weeds', 'Did you spray for grassy weeds?', 'क्या आपने घास वाले खरपतवार पर छिड़काव किया?'),
    (r'hand weeding', 'Did you weed the field?', 'क्या आपने खेत की निराई की?'),
    (r'sell part now', 'Did you sell part of the produce?', 'क्या आपने उपज का कुछ हिस्सा बेचा?'),
    (r'mandi prices', 'Did you compare mandi prices?', 'क्या आपने मंडी के भाव मिलाए?'),
    (r'weigh or judge the goats', 'Did you compare buyers?', 'क्या आपने कई खरीदारों से भाव पूछा?'),
    (r'dairy cooperative', 'Did you compare the milk rate?', 'क्या आपने दूध का भाव मिलाया?'),
    (r'pheromone traps', 'Did you set pheromone traps?', 'क्या आपने फेरोमोन ट्रैप लगाए?'),
    (r'break the crust', 'Did you break the soil crust?', 'क्या आपने मिट्टी की ऊपरी पपड़ी तोड़ी?'),
    (r'first irrigation at the critical stage', 'Did you give the first irrigation at the right stage?', 'क्या आपने सही समय पर पहली सिंचाई की?'),
    (r'drench the nursery', 'Did you treat the nursery bed?', 'क्या आपने नर्सरी की क्यारी का उपचार किया?'),
    (r'soil sample', 'Did you take a soil sample?', 'क्या आपने मिट्टी की जाँच के लिए नमूना दिया?'),
    (r'yellow sticky traps', 'Did you set yellow sticky traps?', 'क्या आपने पीले चिपचिपे ट्रैप लगाए?'),
    (r'keep soil moisture even', 'Did you keep the soil moisture even?', 'क्या आपने मिट्टी में नमी एक-सी रखी?'),
    (r'uproot curled plants', 'Did you uproot the curled plants?', 'क्या आपने मुड़े हुए पौधे उखाड़े?'),
    (r'pick damaged pods', 'Did you remove the damaged pods and spray?', 'क्या आपने खराब फलियाँ हटाकर छिड़काव किया?'),
    (r'fungicide', 'Did you spray the fungicide?', 'क्या आपने फफूंदनाशक का छिड़काव किया?'),
    (r'insecticide', 'Did you spray the insecticide?', 'क्या आपने कीटनाशक का छिड़काव किया?'),
    (r'light irrigation', 'Did you give a light irrigation?', 'क्या आपने हल्की सिंचाई की?'),
    (r'avoid sowing gram in the same field', 'Did you remove the dried plants?', 'क्या आपने सूखे पौधे हटाए?'),
]
_ACTION = [(re.compile(p, re.I), en, hi) for p, en, hi in ACTION_RULES]

# generic first question per concern, used when no rule above matches the advice text
ACTION_FALLBACK = {
    'pest_disease': ('Did you treat the pest or disease?', 'क्या आपने कीट या रोग का इलाज किया?'),
    'weather_climate': ('Did you follow the weather advice?', 'क्या आपने मौसम की सलाह मानी?'),
    'nutrient_deficiency': ('Did you give the fertiliser?', 'क्या आपने खाद दी?'),
    'growth_issue': ('Did you follow the advice?', 'क्या आपने सलाह मानी?'),
    'water_stress': ('Did you follow the watering advice?', 'क्या आपने पानी देने की सलाह मानी?'),
    'livestock_nutrition': ('Did you change the feed?', 'क्या आपने चारे में बदलाव किया?'),
    'storage_post_harvest': ('Did you follow the storage advice?', 'क्या आपने भंडारण की सलाह मानी?'),
    'livestock_health': ('Did you follow the treatment advice?', 'क्या आपने इलाज की सलाह मानी?'),
    'variety_selection': ('Did you follow the seed advice?', 'क्या आपने बीज की सलाह मानी?'),
    'market_price': ('Did you follow the selling advice?', 'क्या आपने बिक्री की सलाह मानी?'),
}
DEFAULT_ACTION = ('Did you follow the advice?', 'क्या आपने सलाह मानी?')

# ---------------------------------------------------------------- wait_and_monitor: "wait and watch for <X> over the next few days"
_WATCH = re.compile(r'watch for (.+?) over the next few days', re.I)
WATCH_HI = {   # X -> full Hindi question. The verb agrees with what is seen, never with the farmer.
    'insects in the bins': 'क्या आपको भंडारण के डिब्बों में कीड़े दिखे?',
    'new drying patches': 'क्या आपको सूखने के नए धब्बे दिखे?',
    'more plants falling over': 'क्या आपको और पौधे गिरते दिखे?',
    'new drooping plants': 'क्या आपको और पौधे मुरझाते दिखे?',
    'insect numbers on the ears': 'क्या बालियों पर कीड़े बढ़े हुए दिखे?',
    'fresh damage in the whorl': 'क्या पौधे के बीच के हिस्से (गोभ) में नया नुकसान दिखा?',
    'new yellow stripes on the upper leaves': 'क्या ऊपर के पत्तों पर नई पीली धारियाँ दिखीं?',
    'new blisters on young leaves': 'क्या नए पत्तों पर नए फफोले दिखे?',
    'more seedlings falling over': 'क्या आपको और नन्हे पौधे गिरते दिखे?',
    'insect clusters on the top shoots': 'क्या ऊपर की कोंपलों पर कीड़ों के झुंड दिखे?',
    'bugs on the seedlings': 'क्या नन्हे पौधों पर कीड़े दिखे?',
    'new drying plants': 'क्या आपको और पौधे सूखते दिखे?',
    'white powder on new leaves': 'क्या नए पत्तों पर सफ़ेद चूर्ण दिखा?',
    'burnt leaf tips after cold nights': 'क्या ठंडी रातों के बाद पत्तों के सिरे जले दिखे?',
    'new spots on the pods': 'क्या फलियों पर नए धब्बे दिखे?',
    'wilting the next afternoon': 'क्या अगली दोपहर पौधे मुरझाए दिखे?',
    'new holes in the leaves': 'क्या पत्तों में नए छेद दिखे?',
    'new dark patches after foggy days': 'क्या कोहरे के दिनों के बाद नए काले धब्बे दिखे?',
    'spots moving to upper leaves': 'क्या धब्बे ऊपर के पत्तों तक पहुँचे?',
    'caterpillars in the pods': 'क्या फलियों में इल्लियाँ दिखीं?',
    'caterpillars on the pods': 'क्या फलियों पर इल्लियाँ दिखीं?',
    'spots on new leaves': 'क्या नए पत्तों पर धब्बे दिखे?',
    'spots on upper leaves': 'क्या ऊपर के पत्तों पर धब्बे दिखे?',
    'more soft tubers in the heap': 'क्या ढेर में और नरम कंद दिखे?',
    'new curled plants': 'क्या आपको और मुड़े हुए पौधे दिखे?',
    'new bored fruits': 'क्या आपको और छेद वाले फल दिखे?',
    'new dead shoots': 'क्या आपको और सूखी टहनियाँ दिखीं?',
}


# concern style: when the advice text gives no "watch for X", ask about the concern itself instead of "the problem"
WATCH_BY_CONCERN = {
    'pest_disease': ('Have you seen more insects or spots on your {name}?', 'क्या {ke} {name_hi} में और कीड़े या धब्बे दिखे?'),
    'weather_climate': ('Has the weather harmed your {name}?', 'क्या मौसम से {ke} {name_hi} को नुकसान हुआ?'),
    'growth_issue': ('Has the growth of your {name} got worse?', 'क्या {ke} {name_hi} की बढ़वार और बिगड़ी?'),
    'nutrient_deficiency': ('Have more leaves of your {name} turned yellow?', 'क्या {ke} {name_hi} के और पत्ते पीले हुए?'),
    'water_stress': ('Have more plants of your {name} started wilting?', 'क्या {ke} {name_hi} के और पौधे मुरझाने लगे?'),
    'livestock_nutrition': ('Is your {name} eating less than before?', 'क्या {ke} {name_hi} पहले से कम खा रही है?'),
    'livestock_health': ('Has your {name} become more unwell?', 'क्या {ke} {name_hi} की तबीयत और बिगड़ी?'),
    'storage_post_harvest': ('Have you seen more damage in your stored {name}?', 'क्या भंडारित {name_hi} में और नुकसान दिखा?'),
}


def _q(typ, en, hi, opts): return (typ, en, hi, opts)


_FIRST_STEP = re.compile(r'first (.+?),? then', re.I)


def first_step_question(insight):
    """plan_created: the brief says to ask whether the farmer did the plan's FIRST step. Plan text is 'first <step>, then ...'."""
    m = _FIRST_STEP.search(insight.get('advice_summary') or '')
    if not m: return None
    for rx, en, hi in _ACTION:
        if rx.search(m.group(1)): return en, hi
    return None


def action_question(insight):
    adv = insight.get('advice_summary') or ''
    for rx, en, hi in _ACTION:
        if rx.search(adv): return en, hi
    return ACTION_FALLBACK.get(insight.get('concern'), DEFAULT_ACTION)


def watch_question(insight):
    m = _WATCH.search(insight.get('advice_summary') or '')
    if m:
        x = m.group(1).strip()
        if x in WATCH_HI: return f'Have you seen {x}?', WATCH_HI[x]
    return None


def question_count(insight):
    """2-vs-3 rule (from the answer key): direct_action gets 3 questions unless severity is low; every other type gets 2."""
    return 2 if (insight['resolution_type'] != 'direct_action' or insight.get('severity') == 'low') else 3


def build_items(insight, style='golden'):
    """-> list of (type, prompt_en, prompt_hi, options). Options are dicts with value, en, hi and optional follow_up."""
    i = insight; rt = i['resolution_type']; cn = i.get('concern') or 'growth_issue'
    S = i18n.slots(i['asset'].get('name')); live = i['asset'].get('category') == 'livestock'
    T = lambda k: (TEMPLATES[k][0].format(**S), TEMPLATES[k][1].format(**S))
    if style == 'concern' and cn in OUTCOME_OPTS:
        en, hi = T('out.' + cn); outcome = _q('survey-single-select', en, hi, OUTCOME_OPTS[cn]())
    else:
        en, hi = T('now'); outcome = _q('survey-single-select', en, hi, NOW())
    if rt == 'direct_action':
        en, hi = action_question(i)
        items = [_q('survey-single-select', en, hi, YNN()), outcome]
        if question_count(i) == 3:
            en, hi = T('barrier'); items.append(_q('survey-single-select', en, hi, BARRIER()))
        return items
    if rt == 'do_not_act':
        en, hi = T('hold_off'); return [_q('survey-confirm', en, hi, YN()), outcome]
    if rt == 'wait_and_monitor':
        w = watch_question(i)
        if w: en, hi = w
        elif style == 'concern' and cn in WATCH_BY_CONCERN: en, hi = (t.format(**S) for t in WATCH_BY_CONCERN[cn])
        else: en, hi = T('watch_generic')
        opts = [opt('yes', 'yes', 'problem_growing'), opt('no', 'no'), opt('not_checked', 'not_checked')]
        en2, hi2 = T('help')
        return [_q('survey-single-select', en, hi, opts), _q('survey-confirm', en2, hi2, [opt('yes', 'yes', 'needs_more_help'), opt('no', 'no')])]
    if rt == 'plan_created':
        a, b = T('plan_progress'), T('plan_working')
        step = first_step_question(i) if style == 'concern' else None
        if step:   # concern style: ask about the plan's first step, as the brief says
            return [_q('survey-single-select', step[0], step[1], YNN()), _q('survey-single-select', *b, [opt('yes', 'yes'), opt('too_early', 'too_early'), opt('no', 'no', 'advice_did_not_work')])]
        return [_q('survey-single-select', *a, [opt('all', 'all_steps'), opt('some', 'some_steps'), opt('none', 'not_started')]),
                _q('survey-single-select', *b, [opt('yes', 'yes'), opt('too_early', 'too_early'), opt('no', 'no', 'advice_did_not_work')])]
    if rt == 'escalate_to_expert':
        a = T('expert_met_vet' if live else 'expert_met_agri'); b = T('expert_helped')
        return [_q('survey-single-select', *a, [opt('yes', 'met_yes'), opt('not_yet', 'met_not_yet'), opt('unreachable', 'could_not_reach', 'could_not_reach_expert')]),
                _q('survey-single-select', *b, [opt('yes', 'yes'), opt('no', 'no', 'advice_did_not_work'), opt('not_met', 'not_met')])]
    raise ValueError(f'no survey template for resolution_type={rt}')


# ---------------------------------------------------------------- adapter: the shared repo's survey schema
STYLE = 'golden'          # 'golden' matches the answer key; 'concern' is more concern-specific (see docs/p4/P4_PLAN.md)
# survey.schema.json allows only four follow_up reasons. Our finer-grained ones map onto them.
FOLLOW_UP_MAP = {'problem_growing': 'crop_or_animal_damaged', 'needs_more_help': 'advice_did_not_work', 'problem_recurring': 'advice_did_not_work',
                 'input_not_available': 'could_not_get_input', 'cost_barrier': 'could_not_get_input'}


def template_items(insight, lang, style=None):
    """Survey `items` (survey.schema.json) for one insight in one language. Same call the shared compose.py used before."""
    k = 'hi' if str(lang).startswith('hi') else 'en'
    items = []
    for n, (typ, pen, phi, opts) in enumerate(build_items(insight, style or STYLE), 1):
        options = []
        for o in opts:
            d = {'value': o['value'], 'label': o[k]}
            if o.get('follow_up'): d['follow_up'] = FOLLOW_UP_MAP.get(o['follow_up'], o['follow_up'])
            options.append(d)
        if len(options) == 2 and {o['value'] for o in options} == {'yes', 'no'}: typ = 'survey-confirm'
        elif typ == 'confirm_later': typ = 'survey-single-select'
        items.append({'item_id': f'q{n}', 'type': typ, 'prompt': phi if k == 'hi' else pen, 'options': options})
    return items
