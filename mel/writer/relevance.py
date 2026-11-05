"""P4 - relevance score v2 (0 to 1), same logic in Hindi and English. Owner: P4.

0.3 the crop or animal is named, 0.3 the concern's words appear, 0.4 the advice's key words appear.
Baseline in the shared repo was: share of questions that mention the asset or an advice word.
"""
from mel.writer import i18n

# The send bar: P3's quality check never schedules a survey whose relevance is below this (contract: P4 sets it,
# P3 enforces it). Agreed 4 Nov by P4 and P5 at 0.3: it blocks only surveys that name neither the crop, the concern
# nor the advice ("a missed survey is better than an irrelevant one"). At 0.5 it blocked 21% of surveys, including
# specific ones such as "Did you treat the nursery bed?", and P4's score agrees only weakly with people (r = 0.29 on
# the hand-scored sheet; the AI judge: 0.58). See docs/results/judge_calibration.md.
RELEVANCE_THRESHOLD = 0.3

# ---------------------------------------------------------------- relevance score v2 (0 to 1), same logic in both languages
# crop mention (0.3) + concern words (0.3) + advice words (0.4). Each table: (what to look for in the advice, English forms, Hindi forms in the survey)
CONCERN_WORDS = {
    'pest_disease': (['insect', 'bug', 'pest', 'spray', 'spot', 'treat', 'disease', 'blight', 'rust', 'caterpillar', 'seen', 'problem'], ['कीड़े', 'कीट', 'छिड़काव', 'धब्बे', 'रोग', 'इलाज', 'दिखे', 'दिखीं', 'दिखा', 'समस्या', 'नियंत्रण']),
    'weather_climate': (['weather', 'forecast', 'rain', 'harm', 'cold', 'heat', 'irrigat', 'drain', 'water', 'seen', 'problem'], ['मौसम', 'बारिश', 'नुकसान', 'सिंचाई', 'पानी', 'दिखे', 'दिखा', 'समस्या']),
    'growth_issue': (['grow', 'plant', 'now', 'advice', 'seen', 'problem', 'irrigat', 'water', 'fertil', 'top-dress'], ['पौधे', 'अब', 'सलाह', 'दिखे', 'समस्या', 'सिंचाई', 'पानी', 'खाद']),
    'nutrient_deficiency': (['fertil', 'sulphur', 'zinc', 'urea', 'leaves', 'yellow', 'nutrient', 'top-dress', 'now', 'seen'], ['खाद', 'सल्फर', 'ज़िंक', 'यूरिया', 'पत्ते', 'पत्तों', 'पीले', 'पीली', 'अब', 'दिखे']),
    'water_stress': (['water', 'irrigat', 'drain', 'drooping', 'wilt', 'moist', 'plants', 'now', 'seen'], ['पानी', 'सिंचाई', 'मुरझा', 'पौधे', 'नमी', 'अब', 'दिखे']),
    'livestock_nutrition': (['feed', 'fodder', 'eating', 'mineral', 'water', 'now'], ['चारा', 'चारे', 'खा', 'खनिज', 'पानी', 'अब']),
    'storage_post_harvest': (['store', 'stored', 'dry', 'bags', 'bins', 'damage', 'tuber', 'produce', 'seen'], ['भंडार', 'सुखा', 'बोरों', 'डिब्बों', 'नुकसान', 'कंद', 'उपज', 'दिखे']),
    'livestock_health': (['vet', 'animal', 'treat', 'now', 'checked', 'deworm', 'vaccin', 'seen'], ['डॉक्टर', 'पशु', 'इलाज', 'अब', 'जाँच', 'टीका', 'कृमि', 'दिखे']),
    'variety_selection': (['seed', 'variety', 'sow', 'now'], ['बीज', 'किस्म', 'बुवाई', 'बोया', 'अब']),
    'market_price': (['sell', 'sold', 'price', 'mandi', 'buyer', 'rate'], ['बेच', 'भाव', 'मंडी', 'खरीदार', 'दाम']),
}
ADVICE_KEYS = [   # (word in the advice text, English forms in the survey, Hindi forms in the survey)
    ('zinc', ['zinc'], ['ज़िंक', 'जिंक']), ('sulphur', ['sulphur'], ['सल्फर']), ('urea', ['urea', 'top-dress'], ['यूरिया', 'खाद']),
    ('drain', ['drain'], ['निकाल']), ('irrigat', ['irrigat', 'water'], ['सिंचाई', 'पानी']), ('neem', ['neem'], ['नीम']),
    ('fungicide', ['fungicide', 'spray'], ['फफूंद', 'छिड़काव']), ('insecticide', ['insecticide', 'spray', 'control', 'treat'], ['कीटनाशक', 'छिड़काव', 'नियंत्रण', 'इलाज']),
    ('herbicide', ['spray', 'weed'], ['छिड़काव', 'खरपतवार']), ('weeding', ['weed'], ['निराई']), ('seed', ['seed', 'variety'], ['बीज', 'किस्म']),
    ('vet', ['vet'], ['डॉक्टर']), ('veterinary', ['vet'], ['डॉक्टर']), ('mandi', ['mandi', 'price'], ['मंडी', 'भाव']), ('sell', ['sell', 'sold'], ['बेच']),
    ('trap', ['trap'], ['ट्रैप']), ('bins', ['bin', 'dry'], ['डिब्बों', 'सुखा']), ('tubers', ['tuber'], ['कंद']),
    ('insect', ['insect', 'bug'], ['कीड़े']), ('spots', ['spot'], ['धब्बे']), ('patches', ['patch'], ['धब्बे', 'हिस्सों']),
    ('drooping', ['droop', 'wilt'], ['मुरझा']), ('wilting', ['wilt'], ['मुरझा']), ('falling over', ['fall'], ['गिर']),
    ('caterpillar', ['caterpillar'], ['इल्ल']), ('stripes', ['stripe'], ['धारियाँ', 'धारियां']), ('blister', ['blister'], ['फफोले']),
    ('shed', ['shed'], ['बाड़े']), ('mineral', ['feed', 'animal', 'checked'], ['चारा', 'पशु', 'जाँच']), ('feed', ['feed'], ['चारा']), ('fodder', ['fodder'], ['चारा']),
]


def _text(sv): return ' '.join([q['prompt'] + ' ' + ' '.join(o['label'] for o in q.get('options', [])) for q in sv['items']])


def relevance(sv, insight):
    """0 to 1. 0.3 crop or animal is named, 0.3 the concern's words appear, 0.4 the advice's key words appear (works for hi-IN and en-IN)."""
    hi = str(sv.get('language', '')).startswith('hi')
    txt = _text(sv); low = txt.lower()
    name = insight['asset'].get('name') or ''
    crop = 1.0 if name and ((i18n.name_hi(name) in txt) if hi else (name.lower() in low)) else 0.0
    en_w, hi_w = CONCERN_WORDS.get(insight.get('concern'), ([], []))
    words = hi_w if hi else en_w
    concern = (1.0 if any(w.lower() in low for w in words) else 0.0) if words else 1.0
    adv = (insight.get('advice_summary') or '').lower() + ' ' + (insight.get('query_summary') or '').lower()
    needed = [(en, h) for k, en, h in ADVICE_KEYS if k in adv]
    if needed:
        hit = sum(any(f.lower() in low for f in (h if hi else en)) for en, h in needed)
        advice = hit / len(needed)
    else:
        advice = 1.0
    return round(0.3 * crop + 0.3 * concern + 0.4 * advice, 3)
