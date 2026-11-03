"""Deterministic question templates per resolution_type, in en-IN and hi-IN. Owner: P5.

Each template returns survey `items` (survey.schema.json $defs/item). `follow_up` marks answers
that mean the advice failed or harm happened. Keep option values identical across languages.
TODO(P5): concern-specific variants (pest count, yellow leaves, seed availability) like the worked scenarios.
"""
from .i18n import asset_word

T = {
    "en-IN": {
        "yes": "Yes", "no": "No",
        "followed": "Did you follow the advice for your {a}?",
        "status": "How is your {a} now?",
        "better": "Better", "same": "Same as before", "worse": "Worse",
        "watched": "Did you keep checking your {a}?",
        "growing": "Is the problem growing?",
        "less": "Getting less", "same_p": "Same as before", "more": "Growing",
        "held": "Did you hold off as advised?",
        "plan": "How much of the plan have you done?",
        "all": "All steps", "some": "Some steps", "none": "Not started",
        "useful": "How useful was the plan? 1 means not useful, 5 means very useful.",
        "expert": "Did an expert see your {a}?",
    },
    "hi-IN": {
        "yes": "हाँ", "no": "नहीं",
        "followed": "क्या आपने अपनी {a} के लिए दी गई सलाह मानी?",
        "status": "आपकी {a} अब कैसी है?",
        "better": "पहले से बेहतर", "same": "पहले जैसी", "worse": "पहले से खराब",
        "watched": "क्या आप अपनी {a} की जाँच करते रहे?",
        "growing": "क्या समस्या बढ़ रही है?",
        "less": "कम हो रही है", "same_p": "पहले जैसी", "more": "बढ़ रही है",
        "held": "क्या आपने सलाह के अनुसार अभी कुछ नहीं किया?",
        "plan": "योजना का कितना काम आपने कर लिया?",
        "all": "सारे कदम", "some": "कुछ कदम", "none": "शुरू नहीं किया",
        "useful": "योजना कितनी काम की रही? 1 मतलब बिल्कुल नहीं, 5 मतलब बहुत काम की।",
        "expert": "क्या किसी विशेषज्ञ ने आपकी {a} को देखा?",
    },
}


def _opt(v, label, fu=None):
    o = {"value": v, "label": label}
    if fu:
        o["follow_up"] = fu
    return o


def _confirm(iid, prompt, t, no_follow_up=None):
    return {"item_id": iid, "type": "survey-confirm", "prompt": prompt,
            "options": [_opt("yes", t["yes"]), _opt("no", t["no"], no_follow_up)]}


def _status(iid, t, a):
    return {"item_id": iid, "type": "survey-single-select", "prompt": t["status"].format(a=a),
            "options": [_opt("better", t["better"]), _opt("same", t["same"], "advice_did_not_work"),
                        _opt("worse", t["worse"], "crop_or_animal_damaged")]}


def template_items(insight: dict, lang: str) -> list[dict]:
    t, a = T[lang], asset_word(insight, lang)
    res = insight["resolution_type"]
    if res == "direct_action":
        return [_confirm("q1", t["followed"].format(a=a), t), _status("q2", t, a)]
    if res == "wait_and_monitor":
        return [_confirm("q1", t["watched"].format(a=a), t),
                {"item_id": "q2", "type": "survey-single-select", "prompt": t["growing"],
                 "options": [_opt("less", t["less"]), _opt("same", t["same_p"]),
                             _opt("growing", t["more"], "crop_or_animal_damaged")]}]
    if res == "do_not_act":
        return [_confirm("q1", t["held"], t), _status("q2", t, a)]
    if res == "plan_created":
        return [{"item_id": "q1", "type": "survey-single-select", "prompt": t["plan"],
                 "options": [_opt("all", t["all"]), _opt("some", t["some"]), _opt("not_started", t["none"])]},
                {"item_id": "q2", "type": "survey-scale", "prompt": t["useful"], "scale_min": 1, "scale_max": 5,
                 "follow_up_at_or_below": 1, "follow_up_reason": "advice_did_not_work"}]
    if res == "escalate_to_expert":
        return [_confirm("q1", t["expert"].format(a=a), t, "could_not_reach_expert"), _status("q2", t, a)]
    raise ValueError(f"no template for resolution_type={res!r}")
