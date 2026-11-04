"""Claude survey writer (opt-in). Off unless ANTHROPIC_API_KEY is set and the `anthropic` package is installed.
Flow: build prompt from the insight + remembered history -> Claude returns JSON -> guards -> accept, else None (caller uses the template).
Never sends farmer ids, names or phone numbers. Responses are cached on disk by prompt hash."""
import os, json, time, hashlib, pathlib
from mel.writer import history

MODEL = os.environ.get('MEL_LLM_MODEL', 'claude-sonnet-5-5')
CACHE = pathlib.Path(os.environ.get('MEL_LLM_CACHE', '.cache/llm'))
FOLLOW_UPS = ['advice_did_not_work', 'could_not_reach_expert', 'crop_or_animal_damaged', 'could_not_get_input',
              'problem_growing', 'needs_more_help', 'problem_recurring', 'input_not_available', 'cost_barrier']
SYSTEM = """You write short follow-up surveys for smallholder farmers in Bihar, India, after they got advice from FarmerChat.
Rules you must follow:
- 1 to 3 questions. Each is answered by a tap: type survey-confirm (exactly 2 options), or survey-single-select (2 to 5 options).
- Write ONLY in the requested language, in simple spoken words a farmer with low literacy understands. Each answer label is at most 20 characters.
- Ask about the advice that was given: did they do it, did it work, what happened. NEVER give new advice, never suggest what to do, never ask for personal information (name, phone, address, income, ID).
- Use the history only to make questions more specific or shorter. Do not mention dates, ids or what other farmers did.
- If an answer means the advice failed or harm happened, set "follow_up" on that option to one of: """ + ', '.join(FOLLOW_UPS) + """.
- Return ONLY JSON: {"items":[{"type":"survey-confirm|survey-single-select","prompt":"...","options":[{"value":"snake_case","label":"...","follow_up":"optional"}]}]}"""

def build_prompt(insight, ctx, lang):
    return (f"Language: {'Hindi (Devanagari)' if lang.startswith('hi') else 'English'}\n"
            f"Crop or animal: {insight['asset'].get('name')} ({insight['asset'].get('growth_stage')})\n"
            f"Concern: {insight.get('concern')}\nWhat the farmer asked: {insight['query_summary']}\n"
            f"Advice given: {insight['advice_summary']}\nAdvice type: {insight['resolution_type']}\n"
            f"What we remember about this farmer:\n- " + '\n- '.join(history.summary_lines(ctx)))

def _to_survey_items(raw, lang):
    out = []
    for n, q in enumerate(raw['items'], 1):
        out.append({'item_id': f'q{n}', 'type': q['type'], 'prompt': q['prompt'],
                    'options': [{'value': o['value'], 'label': o['label'], **({'follow_up': o['follow_up']} if o.get('follow_up') else {})} for o in q['options']]})
    return out

def write_survey_llm(insight, mem, lang=None, client=None, retries=2):
    """Returns a validated list of survey items, or None (use the template). `client` can be injected for tests."""
    from mel import core
    from mel.writer import check_survey, relevance
    lang = lang or insight['conversation_language']
    if client is None:
        if not os.environ.get('ANTHROPIC_API_KEY'): return None
        try: import anthropic; client = anthropic.Anthropic()
        except ImportError: return None
    ctx = history.build_context(insight, mem); prompt = build_prompt(insight, ctx, lang)
    key = hashlib.sha256((MODEL + SYSTEM + prompt).encode()).hexdigest()[:24]; f = CACHE / f'{key}.json'
    raw = json.loads(f.read_text()) if f.exists() else None
    for a in range(0 if raw else retries + 1):
        try:
            t0 = time.time()
            r = client.messages.create(model=MODEL, max_tokens=900, system=SYSTEM, messages=[{'role': 'user', 'content': prompt}])
            txt = ''.join(b.text for b in r.content if getattr(b, 'text', None)); raw = json.loads(txt[txt.index('{'): txt.rindex('}') + 1])
            CACHE.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(raw, ensure_ascii=False))
            break
        except Exception:
            raw = None; time.sleep(min(2 ** a, 4) if client.__class__.__name__ == 'Anthropic' else 0)
    if not raw: return None
    try: items = _to_survey_items(raw, lang)
    except Exception: return None
    sv = core.build_survey(insight, lang)      # envelope (window, ids) from the template path
    sv = {**sv, 'items': items}
    g = check_survey(sv)
    if not g['ok'] or relevance(sv, insight) < 0.34: return None
    return items
