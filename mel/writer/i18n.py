"""P4 - names, Hindi grammar helpers and the short answer-label glossary.

Hindi agreement (gender) is the thing native readers notice first:
  masculine: आपका गेहूँ कैसा है?      feminine: आपकी सरसों कैसी है?
Gender below is from standard usage and still needs the native-reviewer sign-off (see P4_PLAN.md).
Rule of thumb used in templates: put a possessive (आपका/आपकी) only directly before the crop or animal;
elsewhere write "<crop> के पत्ते" so no agreement is needed.
"""

# name -> (hindi, gender)
ASSETS = {
    'wheat': ('गेहूँ', 'm'), 'lentil': ('मसूर', 'f'), 'gram': ('चना', 'm'), 'mustard': ('सरसों', 'f'),
    'maize': ('मक्का', 'm'), 'potato': ('आलू', 'm'), 'pea': ('मटर', 'm'), 'onion': ('प्याज़', 'm'),
    'tomato': ('टमाटर', 'm'), 'cauliflower': ('फूलगोभी', 'f'), 'cabbage': ('पत्तागोभी', 'f'),
    'goat': ('बकरी', 'f'), 'cow': ('गाय', 'f'), 'buffalo': ('भैंस', 'f'), 'chickpea': ('चना', 'm'),
}
CROP_HI = {k: v[0] for k, v in ASSETS.items()}


def name_hi(n): return ASSETS.get(n, (n, 'm'))[0]
def gender(n): return ASSETS.get(n, (n, 'm'))[1]


def slots(asset_name):
    """Everything a template can ask for about the crop or animal, in both languages."""
    n = asset_name or 'crop'
    f = gender(n) == 'f'
    return {
        'name': n, 'name_hi': name_hi(n),
        'poss': 'आपकी' if f else 'आपका',        # आपका गेहूँ / आपकी सरसों
        'ke': 'आपकी' if f else 'आपके',          # आपके गेहूँ में / आपकी सरसों में (oblique form, before 'में')
        'kaisa': 'कैसी' if f else 'कैसा',        # कैसा / कैसी
        'rahi': 'रही' if f else 'रहा',           # खा रही है / खा रहा है
    }


# Short answer labels. Hard limit 20 characters (Unicode code points) so a WhatsApp reply button shows them whole.
# key -> (english, hindi)
LABELS = {
    'yes': ('Yes', 'हाँ'), 'no': ('No', 'नहीं'), 'not_yet': ('Not yet', 'अभी नहीं'), 'not_checked': ('Did not check', 'देखा नहीं'),
    'better': ('Better', 'पहले से अच्छा'), 'same': ('Same', 'वैसा ही'), 'worse': ('Worse', 'पहले से खराब'),
    'too_costly': ('Too costly', 'बहुत महँगा'), 'not_nearby': ('Not available nearby', 'पास में नहीं मिला'),
    'no_time': ('No time', 'समय नहीं मिला'), 'not_understood': ('Did not understand', 'समझ नहीं आया'),
    'almost_none': ('Almost none', 'लगभग नहीं'), 'fewer': ('Fewer than before', 'पहले से कम'),
    'same_as_before': ('Same as before', 'पहले जितने'), 'more': ('More than before', 'पहले से ज़्यादा'),
    'green': ('Green and healthy', 'हरे और स्वस्थ'), 'some_yellow': ('Some yellow leaves', 'कुछ पत्ते पीले'), 'many_yellow': ('Many yellow leaves', 'बहुत पत्ते पीले'),
    'normal': ('Looks normal', 'सामान्य'), 'some_droop': ('Some drooping', 'कुछ मुरझाए'), 'many_droop': ('Many drooping', 'बहुत मुरझाए'),
    'no_harm': ('No harm', 'कोई नुकसान नहीं'), 'little_harm': ('A little harm', 'थोड़ा नुकसान'), 'bad_harm': ('Yes, badly', 'हाँ, काफ़ी'),
    'eating_well': ('Yes, eating well', 'हाँ, ठीक खा रही'), 'eating_less': ('Eating a little', 'थोड़ा खा रही'), 'not_eating': ('Not eating', 'नहीं खा रही'),
    'no_damage': ('No damage now', 'अब नुकसान नहीं'), 'less_damage': ('Less damage', 'पहले से कम'), 'same_damage': ('Same damage', 'पहले जितना'), 'more_damage': ('More damage', 'पहले से ज़्यादा'),
    'seed_easy': ('Yes, easily', 'हाँ, आसानी से'), 'seed_hard': ('Yes, with difficulty', 'हाँ, मुश्किल से'), 'seed_none': ('Could not get it', 'नहीं मिला'),
    'sold': ('Yes, sold', 'हाँ, बेच दिया'), 'sold_differently': ('Sold differently', 'दूसरे तरीके से बेचा'),
    'all_steps': ('All steps', 'सारे काम'), 'some_steps': ('Some steps', 'कुछ काम'), 'not_started': ('Not started', 'शुरू नहीं किया'),
    'too_early': ('Too early to say', 'अभी जल्दी है'),
    'met_yes': ('Yes', 'हाँ'), 'met_not_yet': ('Not yet', 'अभी नहीं'), 'could_not_reach': ('Could not reach', 'मिल नहीं पाए'), 'not_met': ('Not met yet', 'अभी मिले नहीं'),
    'same_again': ('Yes, same problem', 'हाँ, वही समस्या'), 'different': ('No, a different one', 'नहीं, दूसरी समस्या'), 'none_now': ('No problem now', 'अब कोई समस्या नहीं'),
}


def label(key, lang):
    en, hi = LABELS[key]
    return hi if lang.startswith('hi') else en


# ---- kept from the shared repo (other packages and tests import these)
ASSET_HI = CROP_HI
GENERIC = {"en-IN": {"crop": "crop", "livestock": "animal", None: "crop"},
           "hi-IN": {"crop": "फसल", "livestock": "पशु", None: "फसल"}}


def asset_word(insight: dict, lang: str) -> str:
    a = insight.get("asset") or {}
    name = a.get("name")
    if name:
        return ASSET_HI.get(name, name) if lang == "hi-IN" else name
    return GENERIC[lang].get(a.get("category"), GENERIC[lang][None])
