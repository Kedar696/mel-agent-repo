"""Turn a survey into a channel payload (mirrors data/mock/scenarios/*/render). Owner: P3.
Payloads are simulation-only; real delivery is out of scope."""

UI = {
    "hi-IN": {
        "title": "आपको मिली सलाह पर एक छोटा सवाल",
        "skip": "छोड़ें",
        "close": "बंद करें",
        "thanks": "धन्यवाद। आपके जवाब से हम और अच्छी सलाह दे पाएँगे।",
        "invite": "आपको मिली सलाह के बारे में FarmerChat से एक छोटा सवाल। बस एक मिनट लगेगा।",
        "start": "शुरू करें",
        "later": "अभी नहीं",
        "choose": "चुनें",
        "pick_one": "एक चुनें",
        "of": "{n} में से {i}",
        "press": "{label} के लिए {k} दबाएँ।",
        "scale": "{lo} से {hi} के बीच कोई अंक दबाएँ या बोलें।",
        "hello": "नमस्ते, यह FarmerChat की ओर से कॉल है। आपको मिली सलाह के बारे में {n} छोटे सवाल हैं। आप बटन दबाकर या बोलकर जवाब दे सकते हैं।",
        "nums": {1: "एक", 2: "दो", 3: "तीन"},
        "closing_fu": "धन्यवाद। हमने यह नोट कर लिया है। FarmerChat आपसे इस बारे में फिर बात करेगा।",
    },
    "en-IN": {
        "title": "A quick question about the advice you got",
        "skip": "Skip",
        "close": "Close",
        "thanks": "Thank you. Your answers help us give better advice.",
        "invite": "A short question from FarmerChat about the advice you got. It takes one minute.",
        "start": "Start",
        "later": "Not now",
        "choose": "Choose",
        "pick_one": "Choose one",
        "of": "{i} of {n}",
        "press": "For {label}, press {k}.",
        "scale": "Press or say a number from {lo} to {hi}.",
        "hello": "Hello, this is a call from FarmerChat. We have {n} short questions about the advice you got. You can press a key or say your answer.",
        "nums": {1: "one", 2: "two", 3: "three"},
        "closing_fu": "Thank you. We have noted this. FarmerChat will contact you again about it.",
    },
}

# Extra words a voice system should accept, copied from the pack's reference renders.
SPEECH_YES_NO = {
    "hi-IN": {"yes": ["हाँ", "हाँ", "हां", "जी हाँ", "haan"], "no": ["नहीं", "नहीं", "नही", "nahin"]},
    "en-IN": {"yes": ["Yes", "yes", "yes I did"], "no": ["No", "no", "not yet"]},
}
NUMBER_WORDS = {
    "hi-IN": ["एक", "दो", "तीन", "चार", "पाँच", "छह", "सात", "आठ", "नौ", "दस"],
    "en-IN": ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"],
}

# How each channel reaches the farmer (English, for reviewers; same text in every language file).
HOW_IT_ARRIVES = {
    "app": "A notification tells the farmer there is a short question. Tapping it opens the app with the sheet. "
    "If they open the app another way inside the send window, the sheet opens then. It never covers an answer "
    "that is still arriving, a message being typed, or a call.",
    "web": "Web chat has no notifications. The sheet opens the next time the farmer visits inside the send window, "
    "once the answer on screen has finished arriving.",
    "whatsapp": "Days after the chat, so outside WhatsApp's 24-hour reply window. The first message must be an "
    "approved template; the questions follow once the farmer taps Start.",
    "telegram": "The bot can message a farmer who has started it at any time. Scale numbers share one row; "
    "other choices get one row each.",
    "voice": "An outbound call from FarmerChat's number inside send hours. Two silent prompts in a row end the call "
    "and the answers so far are saved as partial.",
}


def _speech(item: dict, lang: str) -> dict:
    """What the voice system should accept as each answer when the farmer speaks."""
    if item["type"] == "survey-confirm":
        return {str(v): list(SPEECH_YES_NO[lang][v]) if v in SPEECH_YES_NO[lang] else [l] for l, v in choices(item)}
    if item["type"] == "survey-scale":
        words = NUMBER_WORDS[lang]
        return {str(v): [str(v)] + ([words[v - 1]] if 1 <= v <= len(words) else []) for _, v in choices(item)}
    return {str(v): [l] for l, v in choices(item)}


def choices(item: dict) -> list[tuple[str, object]]:
    """[(label, value)] for any item type; scale values are ints."""
    if item["type"] == "survey-scale":
        return [(str(v), v) for v in range(item["scale_min"], item["scale_max"] + 1)]
    return [(o["label"], o["value"]) for o in item["options"]]


def _sheet(s, channel):
    u, n = UI[s["language"]], len(s["items"])
    return {
        "channel": channel,
        "presentation": {
            "type": "bottom_sheet",
            "opens_when": ["push_tapped", "next_app_open"] if channel == "app" else ["next_web_visit"],
            "waits_for": ["answer_finished_streaming", "no_typing_for_5_seconds", "no_call_in_progress"],
            "one_question_per_step": True,
            "steps_total": n,
            "can_skip": True,
            "can_close": True,
            "swipe_down_closes": True,
        },
        "sheet": {
            "title": u["title"],
            "skip_label": u["skip"],
            "close_label": u["close"],
            "thank_you": u["thanks"],
            "steps": [
                {
                    "step": i,
                    "step_label": u["of"].format(i=i, n=n),
                    "item_id": it["item_id"],
                    "question_type": it["type"],
                    "question": it["prompt"],
                    "options": [{"label": l, "answer": v} for l, v in choices(it)],
                }
                for i, it in enumerate(s["items"], 1)
            ],
        },
    }


def _whatsapp(s):
    u, sid = UI[s["language"]], s["survey_id"]
    msgs = []
    for it in s["items"]:
        ch = choices(it)
        body = {"text": it["prompt"]}
        if len(ch) <= 3:
            inter = {
                "type": "button",
                "body": body,
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": f"{sid}|{it['item_id']}|{v}", "title": l}} for l, v in ch
                    ]
                },
            }
        else:
            inter = {
                "type": "list",
                "body": body,
                "action": {
                    "button": u["choose"],
                    "sections": [
                        {
                            "title": u["pick_one"],
                            "rows": [{"id": f"{sid}|{it['item_id']}|{v}", "title": l} for l, v in ch],
                        }
                    ],
                },
            }
        msgs.append(
            {
                "messaging_product": "whatsapp",
                "to": "<farmer WhatsApp number>",
                "type": "interactive",
                "interactive": inter,
            }
        )
    return {
        "channel": "whatsapp",
        "opening_template": {
            "messaging_product": "whatsapp",
            "to": "<farmer WhatsApp number>",
            "type": "template",
            "template": {
                "name": "mel_survey_invite",
                "language": {"code": s["language"][:2]},
                "components": [
                    {
                        "type": "button",
                        "sub_type": "quick_reply",
                        "index": str(i),
                        "parameters": [{"type": "payload", "payload": f"{sid}|{p}"}],
                    }
                    for i, p in enumerate(["start", "later"])
                ],
            },
        },
        "template_text_for_approval": {"body": u["invite"], "quick_replies": [u["start"], u["later"]]},
        "messages": msgs,
    }


def _telegram(s):
    u, sid = UI[s["language"]], s["survey_id"]
    msgs = [{"method": "sendMessage", "chat_id": "<telegram chat id>", "text": u["invite"]}]
    for it in s["items"]:
        btn = [{"text": l, "callback_data": f"mel|{sid}|{it['item_id']}|{v}"} for l, v in choices(it)]
        kb = [btn] if it["type"] == "survey-scale" else [[b] for b in btn]
        msgs.append(
            {
                "method": "sendMessage",
                "chat_id": "<telegram chat id>",
                "text": it["prompt"],
                "reply_markup": {"inline_keyboard": kb},
            }
        )
    return {"channel": "telegram", "messages": msgs}


def _voice(s):
    u = UI[s["language"]]
    items = []
    for it in s["items"]:
        ch = choices(it)
        if it["type"] == "survey-scale":
            say = f"{it['prompt']} {u['scale'].format(lo=it['scale_min'], hi=it['scale_max'])}"
        else:
            say = " ".join([it["prompt"]] + [u["press"].format(label=l, k=k) for k, (l, _) in enumerate(ch, 1)])
        items.append(
            {
                "item_id": it["item_id"],
                "say": say,
                "keypad": {str(k): v for k, (_, v) in enumerate(ch, 1)},
                "speech": _speech(it, s["language"]),
                "timeout_seconds": 8,
                "repeat_if_no_input": 1,
            }
        )
    n = len(s["items"])
    return {
        "channel": "voice",
        "opening": u["hello"].format(n=u["nums"].get(n, n)),
        "items": items,
        "closing": u["thanks"],
        "closing_if_follow_up": u["closing_fu"],
    }


RENDERERS = {
    "app": lambda s: _sheet(s, "app"),
    "web": lambda s: _sheet(s, "web"),
    "whatsapp": _whatsapp,
    "telegram": _telegram,
    "voice": _voice,
}


def render(survey: dict, channel: str) -> dict:
    payload = RENDERERS[channel](survey)
    return {"channel": payload.pop("channel"), "how_it_arrives": HOW_IT_ARRIVES[channel], **payload}
