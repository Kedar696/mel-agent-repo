"""P4 - safety guards. A survey that fails any guard is never shown: the caller falls back to the template.

Failure codes (posted to the team at H+4):
  bad_item_count          not 1 to 3 questions
  bad_option_count        a question without 2 to 10 answers
  confirm_needs_two       survey-confirm without exactly 2 answers
  prompt_too_long         prompt of 400 characters or more
  label_too_long          answer label over 20 characters (Unicode code points)
  empty_text              empty prompt or label
  duplicate_option_value  two answers with the same value
  wrong_language          Hindi survey without Devanagari, or English survey with Devanagari
  gives_new_advice        the question tells the farmer what to do
  asks_personal_info      name, phone, address, income, Aadhaar, bank, age, caste, religion, OTP, password
  unknown_follow_up       follow_up reason not in the agreed list
  duplicate_item_id       two questions share an item_id
  schema_invalid          fails config/schemas/survey.json (only checked when that file exists)
"""
import re
from dataclasses import dataclass, field

ALLOWED_FOLLOW_UP = {'advice_did_not_work', 'could_not_reach_expert', 'crop_or_animal_damaged', 'could_not_get_input', 'problem_growing',
                     'needs_more_help', 'problem_recurring', 'input_not_available', 'cost_barrier'}

# ---- advice: the question itself must not be an instruction
ADVICE_EN = [
    r"\b(you should|you must|you need to|you have to|you ought to|we recommend|we suggest|i recommend|i suggest|i advise|we advise|make sure (to|that)|be sure to|don'?t forget to)\b",
    r"\bplease (spray|apply|use|give|add|mix|water|irrigate|remove|sow|buy|call|keep|stop|avoid|take|check)\b",
    r"^\s*(spray|apply|use|give|add|mix|irrigate|water|remove|sow|buy|call|keep|stop|avoid|take|put|drain|dry|sell|plant|treat)\b",   # imperative sentence
    r"\bit is (better|best|advisable) to\b", r"\btry (to )?(spray|apply|use|add|give)\b",
]
ADVICE_HI = [
    r"[ऀ-ॿ]+(ना|नी|ने)\s+(चाहिए|चाहिये|होगा|होगी|पड़ेगा|पड़ेगी)", r"चाहिए कि", r"कीजिए|कीजिये|करिए|करिये",
    r"(छिड़कें|छिड़कना चाहिए|डालें|मिलाएँ|मिलाएं|लगाएँ|लगाएं|हटाएँ|हटाएं|रखें|दें|लें|बोएँ|बोएं|बेचें|खरीदें|सुखाएँ|सुखाएं|निकालें|उखाड़ें)\s*[?।.!]?\s*$",   # sentence ends in an imperative
    r"(ज़रूर|जरूर|तुरंत|फ़ौरन|फौरन) (करें|डालें|छिड़कें|दें|लें)",
    r"सलाह (है|देते हैं|दी जाती है)",
]
_ADV = [re.compile(p, re.I) for p in ADVICE_EN] + [re.compile(p) for p in ADVICE_HI]

# ---- personal information
PII_EN = re.compile(r"\b(name|phone|telephone|mobile|contact (number|no|details)|address|income|salary|earnings?|aadhaar|aadhar|bank|account|ifsc|otp|password|pin code|pincode|age|caste|religion|surname)\b", re.I)
PII_HI = {'नाम', 'फ़ोन', 'फोन', 'मोबाइल', 'नंबर', 'नम्बर', 'पता', 'पते', 'आय', 'आमदनी', 'कमाई', 'वेतन', 'आधार', 'बैंक', 'खाता', 'खाते', 'उम्र', 'आयु',
          'जाति', 'धर्म', 'पासवर्ड', 'ओटीपी', 'पिनकोड', 'सरनेम'}
_PATA_OK_NEXT = {'नहीं', 'है', 'चला', 'चली', 'लगा', 'लगी', 'लगाया', 'था', 'थी'}   # "पता नहीं" = "do not know", not "address"

# ---- allow-list: a (code, exact text) pair that is known to be fine. Every entry must come with a test in tests/test_writer.py.
ALLOW = set()

_DEV = re.compile(r'[ऀ-ॿ]')


@dataclass
class GuardResult:
    ok: bool
    failures: list = field(default_factory=list)      # ["q1: gives_new_advice", ...]
    codes: set = field(default_factory=set)
    def __getitem__(self, k): return getattr(self, k)   # lets old code use result['ok']
    def __bool__(self): return self.ok


def _tokens(text): return re.findall(r'[ऀ-ॿ]+', text)


def asks_personal_info(text):
    if PII_EN.search(text): return True
    t = _tokens(text)
    for n, w in enumerate(t):
        if w in PII_HI:
            if w in ('पता', 'पते') and n + 1 < len(t) and t[n + 1] in _PATA_OK_NEXT: continue
            if w in ('पता', 'पते') and n > 0 and t[n - 1] in ('मुझे', 'हमें', 'आपको'): continue
            return True
    return False


def gives_advice(text): return any(r.search(text) for r in _ADV)


def _schema_errors(sv):
    """Validate against Digital Green's JSON Schema once it is placed at config/schemas/survey.json. No file -> no check."""
    import json, os
    path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'schemas', 'survey.json')
    if not os.path.exists(path): return []
    try:
        import jsonschema
        return [e.message[:80] for e in jsonschema.Draft202012Validator(json.load(open(path, encoding='utf-8'))).iter_errors(sv)]
    except ImportError:
        return []


def check_survey(sv, insight=None):
    """-> GuardResult. `sv` is a survey dict (items with prompt + options). Pure function: no network, no randomness."""
    fails = []
    def f(item, code, detail=''): fails.append((item, code, detail))
    items = sv.get('items') or []
    hi = str(sv.get('language', '')).startswith('hi')
    if not 1 <= len(items) <= 3: f('survey', 'bad_item_count', str(len(items)))
    ids = [q.get('item_id') for q in items]
    if len(ids) != len(set(ids)): f('survey', 'duplicate_item_id', str(ids))
    for msg in _schema_errors(sv): f('survey', 'schema_invalid', msg)
    for q in items:
        qid = q.get('item_id', '?'); prompt = q.get('prompt') or ''; opts = q.get('options') or []
        if not prompt.strip(): f(qid, 'empty_text', 'prompt')
        if len(prompt) >= 400: f(qid, 'prompt_too_long', str(len(prompt)))
        if not 2 <= len(opts) <= 10: f(qid, 'bad_option_count', str(len(opts)))
        if q.get('type') == 'survey-confirm' and len(opts) != 2: f(qid, 'confirm_needs_two')
        vals = [o.get('value') for o in opts]
        if len(vals) != len(set(vals)): f(qid, 'duplicate_option_value')
        texts = [prompt] + [o.get('label', '') for o in opts]
        for o in opts:
            lab = o.get('label') or ''
            if not lab.strip(): f(qid, 'empty_text', 'label')
            if len(lab) > 20: f(qid, 'label_too_long', lab)
            if o.get('follow_up') and o['follow_up'] not in ALLOWED_FOLLOW_UP: f(qid, 'unknown_follow_up', o['follow_up'])
        for t in texts:
            if (('gives_new_advice', t) in ALLOW) or (('asks_personal_info', t) in ALLOW): continue
            if t is prompt and gives_advice(t): f(qid, 'gives_new_advice', t[:60])
            if asks_personal_info(t): f(qid, 'asks_personal_info', t[:60])
            if t.strip() and not t.strip().isdigit():
                if hi and not _DEV.search(t): f(qid, 'wrong_language', t[:40])
                if not hi and _DEV.search(t): f(qid, 'wrong_language', t[:40])
    codes = {c for _, c, _ in fails}
    return GuardResult(ok=not fails, failures=[f"{i}: {c}" + (f" ({d})" if d else '') for i, c, d in fails], codes=codes)
