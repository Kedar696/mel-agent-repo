"""Amazon Bedrock model path for the survey writer (Converse API) behind one ModelClient. Owner: P4.

Why this file exists: Digital Green's Technical doc asks for models through Amazon Bedrock behind a swappable
layer, a small model for checks and a larger one for writing, and tokens, cost and time logged on every call.

Everything is OFF unless you opt in, so tests and demos never touch AWS:
    MEL_USE_LLM=1                       turn the model path on
    MEL_BEDROCK_WRITE_MODEL=<model id>  larger model that writes the questions (a single config value)
    MEL_BEDROCK_CHECK_MODEL=<model id>  smaller model that double-checks a survey (optional)
    MEL_BEDROCK_REGION=<region>         region where event staff enabled the models (else AWS_REGION)
    MEL_BEDROCK_PRICES='{"<model id>": {"in": 0.003, "out": 0.015}}'   USD per 1,000 tokens, for the cost log
There is no key anywhere: boto3 takes credentials from the IAM role of the workshop account.

Safety rules (unchanged from the template path):
  * only asset, concern, resolution type, query_summary and advice_summary go to the model, never an id or a name
  * every model survey must pass guards.check_survey and relevance, otherwise compose.py uses the template
  * if Bedrock can't be reached (no boto3, no credentials, model not enabled, throttled for good) -> templates

Fewer tokens (5 Nov, after the first full run: 340 output tokens per draft, 1,776 revisions):
  * the model writes one line per question (`TYPE | QUESTION | ANSWER | ANSWER`), and this file builds the schema
    items from it: no JSON keys, ids or fixed fields in the answer, so an output costs about a third of before
  * Hindi is a translation of the approved English survey (`source_items`): a shorter request, the same questions
    in both languages, and far fewer Hindi rejections (the Hindi keyword scores are built from the templates' words)
  * the hard limits (question length, answer length, the star marks) are in the system prompt, so fewer revisions
  * the answers are cached twice: on disk (`out/cache/bedrock`) and in the committed replay file
    `docs/results/bedrock_cache.jsonl` (`python -m mel.writer.llm export-cache`), so a laptop without AWS keys, the
    hosted app and every rerun replay the same questions for $0 and never call Bedrock for a request already answered
  * Bedrock prompt caching is not used: Haiku 4.5 caches only prefixes of 4,096 tokens or more, ours are about 300
"""
import contextlib
import contextvars
import hashlib
import json
import os
import random
import re
import threading
import time
from pathlib import Path

from mel.config import OUT, ROOT

REPLAY = ROOT / "docs" / "results" / "bedrock_cache.jsonl"   # committed answers, replayed for $0 (see export_cache)

RETRYABLE_CODES = {"ThrottlingException", "ModelTimeoutException", "ServiceUnavailableException",
                   "InternalServerException", "ModelNotReadyException", "RequestTimeout"}
RETRYABLE_CLASSES = {"EndpointConnectionError", "ConnectTimeoutError", "ReadTimeoutError", "ConnectionClosedError"}
LANG_NAME = {"hi-IN": "Hindi (Devanagari script)", "en-IN": "English (simple Indian English)"}


# ------------------------------------------------------------------ config (read at call time so tests can change it)
def write_model() -> str: return os.environ.get("MEL_BEDROCK_WRITE_MODEL", "").strip()
def check_model() -> str: return os.environ.get("MEL_BEDROCK_CHECK_MODEL", "").strip()
def region() -> str: return (os.environ.get("MEL_BEDROCK_REGION") or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "").strip()
def cache_dir() -> Path: return Path(os.environ.get("MEL_CACHE_DIR") or OUT / "cache" / "bedrock")
def log_path() -> Path: return Path(os.environ.get("MEL_LLM_LOG") or OUT / "bedrock_calls.jsonl")


def prices() -> dict:
    """USD per 1,000 tokens per model id. MEL_BEDROCK_PRICES wins; else the team's checked price file
    docs/results/bedrock_prices.json (USD per 1M tokens, from the AWS Price List API; P5), converted."""
    try:
        env = json.loads(os.environ.get("MEL_BEDROCK_PRICES") or "{}")
    except ValueError:
        env = {}
    if env:
        return env
    from mel.config import ROOT
    try:
        raw = json.loads((ROOT / "docs" / "results" / "bedrock_prices.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: {"in": v["in"] / 1000, "out": v["out"] / 1000} for k, v in raw.items()
            if isinstance(v, dict) and v.get("in") is not None and v.get("out") is not None}


_PROFILE_PREFIXES = ("us.", "eu.", "apac.", "global.")


_override: contextvars.ContextVar = contextvars.ContextVar("mel_writer_override", default=None)


def enabled() -> bool:
    """True only when the person opted in AND a writing model id is configured. `writer(...)` / `override(...)`
    can force it for a block or a thread, so scoring and batch numbers never spend tokens while the demo does."""
    forced = _override.get()
    on = os.environ.get("MEL_USE_LLM") == "1" if forced is None else forced
    return bool(on) and bool(write_model())


def override(on: bool | None) -> None:
    """Force the model path on or off for the current thread until changed (None: read MEL_USE_LLM again)."""
    _override.set(on)


@contextlib.contextmanager
def writer(on: bool):
    """Force the model path on or off inside the block, whatever MEL_USE_LLM or an earlier override says."""
    token = _override.set(on)
    try:
        yield
    finally:
        _override.reset(token)


def cost_usd(model_id: str, tokens_in: int, tokens_out: int):
    """None when the price of this model was not given (we never guess a price)."""
    pr = prices()
    p = pr.get(model_id)
    if not p and model_id and model_id.startswith(_PROFILE_PREFIXES):   # a profile id costs what its model costs
        p = pr.get(model_id.split(".", 1)[1])
    if not p:
        return None
    return round(tokens_in / 1000 * p.get("in", 0) + tokens_out / 1000 * p.get("out", 0), 6)


class ModelUnavailable(Exception):
    """Bedrock can't be used right now. The caller falls back to templates."""


# ------------------------------------------------------------------ the one client
class ModelClient:
    """Thin wrapper over bedrock-runtime Converse. Adds: retries with backoff, an on-disk cache, and a per-call log."""

    def __init__(self, runtime=None, max_attempts=4, base_delay=1.0, sleep=time.sleep):
        self._runtime, self.max_attempts, self.base_delay, self._sleep = runtime, max_attempts, base_delay, sleep
        self.last_usage = {"input_tokens": 0, "output_tokens": 0}   # tokens of the last converse() (cache hit: as made)

    def _rt(self):
        if self._runtime is None:
            try:
                import boto3
            except ImportError as e:
                raise ModelUnavailable("boto3 is not installed") from e
            try:
                self._runtime = boto3.client("bedrock-runtime", region_name=region() or None)
            except Exception as e:      # no region, bad credentials file, ...
                raise ModelUnavailable(f"cannot create bedrock client: {e}") from e
        return self._runtime

    @staticmethod
    def _retryable(e) -> bool:
        code = (getattr(e, "response", None) or {}).get("Error", {}).get("Code")
        return code in RETRYABLE_CODES or type(e).__name__ in RETRYABLE_CLASSES

    def converse(self, model_id, system, user, purpose="write", tag="", max_tokens=1200, temperature=0.2) -> str:
        """Returns the model's text. Raises ModelUnavailable. `purpose` is 'write' or 'check'; `tag` is e.g. the insight id (for the log).
        `system=None` sends no system prompt and `temperature=None` no temperature (newer models refuse one or the other)."""
        key = hashlib.sha256(json.dumps([model_id, system, user, max_tokens, temperature], ensure_ascii=False).encode()).hexdigest()
        # One request at a time per key: with 8 workers, two farmers with the same advice used to pay for the same
        # answer twice. The second waits, then finds the first one's answer in the cache.
        with self._inflight(key):
            return self._converse(key, model_id, system, user, purpose, tag, max_tokens, temperature)

    _locks: dict = {}
    _guard = threading.Lock()

    @classmethod
    def _inflight(cls, key):
        with cls._guard:
            return cls._locks.setdefault(key, threading.Lock())

    def _converse(self, key, model_id, system, user, purpose, tag, max_tokens, temperature) -> str:
        cached = cache_dir() / f"{key}.json"
        hit = None
        if cached.exists():
            try:
                hit = json.loads(cached.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                hit = None                               # a broken cache file is just a miss
        if not isinstance(hit, dict) or "text" not in hit:
            hit = replayed(key)                          # the committed answers: no AWS needed
        if hit:
            self._log(model_id, purpose, tag, 0, 0, 0.0, cached=True, ok=True, key=key,
                      list_cost=cost_usd(model_id, int(hit.get("input_tokens", 0)), int(hit.get("output_tokens", 0))))
            # what this answer took when it was made (nothing is spent now): lets callers price an answer
            self.last_usage = {"input_tokens": int(hit.get("input_tokens", 0)),
                               "output_tokens": int(hit.get("output_tokens", 0)), "cached": True}
            return hit["text"]
        last = None
        for attempt in range(1, self.max_attempts + 1):
            t0 = time.perf_counter()
            try:
                kw = {"system": [{"text": system}]} if system else {}   # some models take no system prompt: pass None
                resp = self._rt().converse(
                    modelId=model_id, **kw,
                    messages=[{"role": "user", "content": [{"text": user}]}],
                    inferenceConfig={"maxTokens": max_tokens, **({} if temperature is None else {"temperature": temperature})})
            except ModelUnavailable:
                raise
            except Exception as e:
                last = e
                secs = time.perf_counter() - t0
                if self._retryable(e) and attempt < self.max_attempts:
                    self._log(model_id, purpose, tag, 0, 0, secs, ok=False, error=f"retry {attempt}: {type(e).__name__}")
                    self._sleep(self.base_delay * 2 ** (attempt - 1) * (0.5 + random.random()))   # backoff with jitter
                    continue
                self._log(model_id, purpose, tag, 0, 0, secs, ok=False, error=f"{type(e).__name__}: {e}"[:200])
                raise ModelUnavailable(f"{type(e).__name__}: {e}") from e
            secs = time.perf_counter() - t0
            text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
            use = resp.get("usage") or {}
            tin, tout = int(use.get("inputTokens", 0)), int(use.get("outputTokens", 0))
            self._log(model_id, purpose, tag, tin, tout, secs, ok=True, key=key)
            self.last_usage = {"input_tokens": tin, "output_tokens": tout}
            try:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps({"text": text, "input_tokens": tin, "output_tokens": tout}, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
            return text
        raise ModelUnavailable(str(last))

    def _log(self, model_id, purpose, tag, tin, tout, secs, cached=False, ok=True, error="", list_cost=None, key=""):
        """One row per call. cost_usd is what was spent (a cache hit: $0); list_cost_usd is what the call costs when
        made fresh (a cache hit: priced from the tokens it took when it was made), so cost per survey is right even
        for a run answered mostly from the cache."""
        cost = 0.0 if cached else cost_usd(model_id, tin, tout)
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "model": model_id, "purpose": purpose, "tag": tag,
               "input_tokens": tin, "output_tokens": tout, "cost_usd": cost,
               "list_cost_usd": list_cost if cached else cost,
               "seconds": round(secs, 3), "cached": cached, "ok": ok, "error": error, "key": key}
        try:
            p = log_path(); p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass


_client = None


def client() -> ModelClient:
    global _client
    if _client is None:
        _client = ModelClient()
    return _client


def set_client(c) -> None:
    """Tests (and the comparison script) swap the client here. Pass None to reset."""
    global _client
    _client = c


# ------------------------------------------------------------------ the committed replay file
_replay: dict | None = None


def replayed(key: str, path=None) -> dict | None:
    """The committed answer for this request key ({"text", "input_tokens", "output_tokens"}), or None. Loaded once."""
    global _replay
    if _replay is None or path is not None:
        rows = {}
        try:
            for line in Path(path or REPLAY).read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                rows[r["key"]] = r
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if path is not None:
            return rows.get(key)
        _replay = rows
    return _replay.get(key)


def export_cache(path=None, source=None) -> int:
    """Add every answer in the on-disk cache to the replay file (existing lines kept, same key overwritten), sorted
    by key so the diff stays small. Returns the number of lines written. Commit the file: anyone who runs the same
    request then gets the same answer for $0, with no AWS keys."""
    global _replay
    out = Path(path or REPLAY)
    rows = {}
    try:
        for line in out.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            rows[r["key"]] = r
    except (OSError, ValueError, KeyError, TypeError):
        pass
    for f in sorted(Path(source or cache_dir()).glob("*.json")):
        try:
            hit = json.loads(f.read_text(encoding="utf-8"))
            rows[f.stem] = {"key": f.stem, "text": hit["text"], "input_tokens": int(hit.get("input_tokens", 0)),
                            "output_tokens": int(hit.get("output_tokens", 0))}
        except (ValueError, KeyError, OSError, TypeError):
            continue
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(rows[k], ensure_ascii=False) + "\n" for k in sorted(rows)), encoding="utf-8")
    _replay = None
    return len(rows)


def usage_summary(path=None) -> dict:
    """Totals over the call log: calls, tokens, cost, seconds, cache hits, failures, and the same per model.
    cost_usd is the sum of the calls whose price was known; unpriced_calls says how many were not."""
    p = Path(path) if path else log_path()
    tot = {"calls": 0, "ok": 0, "failed": 0, "cached": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "unpriced_calls": 0, "seconds": 0.0, "by_model": {}}
    if not p.exists():
        return tot
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        for t in (tot, tot["by_model"].setdefault(r["model"], {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "seconds": 0.0})):
            t["calls"] += 1; t["input_tokens"] += r["input_tokens"]; t["output_tokens"] += r["output_tokens"]
            t["seconds"] = round(t["seconds"] + r["seconds"], 3); t["cost_usd"] = round(t["cost_usd"] + (r["cost_usd"] or 0), 6)
        tot["ok" if r["ok"] else "failed"] += 1
        tot["cached"] += bool(r["cached"])
        tot["unpriced_calls"] += r["ok"] and not r["cached"] and r["cost_usd"] is None
    return tot


# ------------------------------------------------------------------ prompts
# One line per question, nothing else. The schema items (ids, types, values, scale fields) are built here, so the
# model never spends output tokens on them. A star marks an answer that means failure or harm (the follow-up reason).
SYSTEM_WRITE = """You write short follow-up surveys for smallholder farmers in Bihar, India.
Ask ONLY about advice the farmer already received: did they act on it, and did it work.
Never give new advice. Never contradict the advice. Never ask for personal information (name, phone, address, income, Aadhaar, bank).
Write one question per line and nothing else, in this form:
TYPE | QUESTION | ANSWER | ANSWER
TYPE is confirm (the answers are exactly Yes | No), select (2 to 4 answers) or scale (no answers: the farmer rates 1 to 5).
A question is under 100 characters and does not repeat the advice. An answer is 1 to 3 words, under 20 characters.
Add a star and a letter to an answer that means the advice failed or harm happened: *f did not work, *d crop or animal damaged, *i could not get the input, *e could not reach the expert.
Write in the requested language only. In Hindi use simple words and avoid verb endings that change with the farmer's gender."""

SYSTEM_TRANSLATE = """Translate a farmer survey from English into Hindi (Devanagari script).
Keep every line in the same form (TYPE | QUESTION | ANSWER | ANSWER), the same number of answers and the same stars. Translate only the words.
Use simple words and avoid verb endings that change with the farmer's gender. Return only the translated lines."""

SYSTEM_READ = """You read one FarmerChat conversation (a farmer's question and the advice given) and fill in the fields a survey planner needs.
Answer with one field per line as key: value, nothing else.
asset: the crop or animal, one of wheat, mustard, lentil, gram, pea, potato, onion, tomato, cabbage, cauliflower, maize, goat, cow, buffalo, other
concern: one of pest_disease, weather_climate, growth_issue, nutrient_deficiency, variety_selection, soil_health, water_stress, storage_post_harvest, livestock_nutrition, livestock_health, market_price, weed_management, breeding_reproduction, yield_loss
severity: low, medium, high or critical (critical: an animal or a person may die today)
advice_type: direct_action (do something), wait_and_monitor, do_not_act, plan_created (steps over time), escalate_to_expert (see a vet or an expert), generic_information (no action asked), needs_more_context (no advice yet)
act_within_days: the whole number of days the farmer has to act, 0 if none
check_back: when to ask how it went, one of next_day, two_to_five_days, three_to_ten_days, seven_to_fourteen_days, seasonal, none
questions: how many survey questions this needs, 1, 2 or 3"""

TYPES = {"confirm": "survey-confirm", "select": "survey-single-select", "scale": "survey-scale",
         "survey-confirm": "survey-confirm", "survey-single-select": "survey-single-select", "survey-scale": "survey-scale"}
STARS = {"f": "advice_did_not_work", "d": "crop_or_animal_damaged", "i": "could_not_get_input", "e": "could_not_reach_expert"}
YES_NO = {"en": ("Yes", "No"), "hi": ("हाँ", "नहीं")}
MAX_WRITE_TOKENS = 400       # three compact lines, Hindi included; a chatty answer is cut, not paid for in full
_STAR = re.compile(r"^(.*?)\s*\*\s*([a-z]?)\s*$", re.I)


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:64]


def lines_from(items: list[dict]) -> str:
    """Survey items as the compact lines the model writes (used to ask for a translation)."""
    back = {v: k for k, v in STARS.items()}
    out = []
    for q in items:
        kind = "scale" if q.get("type") == "survey-scale" else "confirm" if q.get("type") == "survey-confirm" else "select"
        answers = [o.get("label", "") + (f"*{back[o['follow_up']]}" if o.get("follow_up") in back else "")
                   for o in q.get("options", [])]
        out.append(" | ".join([kind, q.get("prompt", ""), *answers]))
    return "\n".join(out)


def parse_lines(text: str, lang: str = "en-IN", source: list[dict] | None = None) -> list[dict] | None:
    """Compact lines -> survey items (survey.schema.json shape), or None when nothing usable came back.
    `source` (the approved English items) makes this a translation: values, follow-ups and scale fields are copied
    from the English item in the same position, and the result must have the same shape line for line."""
    k = "hi" if str(lang).startswith("hi") else "en"
    items = []
    for raw in text.splitlines():
        line = raw.strip().strip("`").strip()
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        typ = TYPES.get(re.sub(r"^\s*\d+[.)]\s*", "", parts[0]).lower().replace(" ", "-"))
        if not typ or len(parts) < 2 or not parts[1]:
            continue
        n = len(items)
        src = source[n] if source is not None and n < len(source) else None
        q = {"item_id": f"q{n + 1}", "type": typ, "prompt": parts[1]}
        answers = []
        for a in parts[2:]:
            if not a:
                continue
            m = _STAR.match(a)
            if m and "*" in a:
                answers.append((m.group(1).strip() or a, STARS.get(m.group(2).lower(), "advice_did_not_work")))
            else:
                answers.append((a, None))
        if typ == "survey-confirm" and len(answers) > 2:
            typ = q["type"] = "survey-single-select"           # it is not a yes/no question after all
        if typ == "survey-scale":
            if src and src.get("type") == "survey-scale":
                q.update({x: src[x] for x in ("scale_min", "scale_max", "follow_up_at_or_below", "follow_up_reason") if x in src})
            else:   # 1 to 5; 1 or 2 means the advice did not work
                q.update({"scale_min": 1, "scale_max": 5, "follow_up_at_or_below": 2, "follow_up_reason": "advice_did_not_work"})
            items.append(q)
            continue
        if typ == "survey-confirm":
            labels = [a[0] for a in answers] + list(YES_NO[k][len(answers):])
            answers = [(labels[0], answers[0][1] if answers else None), (labels[1], answers[1][1] if len(answers) > 1 else None)]
        if src is not None and src.get("type") != "survey-scale":
            if len(answers) != len(src.get("options", [])):
                return None                                     # a translation must keep every answer
            q["type"] = src["type"]
            opts = [{**o, "label": a[0]} for o, a in zip(src["options"], answers)]
        else:
            opts, seen = [], set()
            for j, (label, fu) in enumerate(answers):
                value = ("yes", "no")[j] if typ == "survey-confirm" else (_slug(label) or f"a{j + 1}")
                if not re.fullmatch(r"[a-z0-9][a-z0-9_]{0,63}", value) or value in seen:
                    value = f"a{j + 1}"
                seen.add(value)
                opts.append({"value": value, "label": label, **({"follow_up": fu} if fu else {})})
        q["options"] = opts
        items.append(q)
    if source is not None and len(items) != len(source):
        return None
    return items or None

SYSTEM_CHECK = """You are a strict safety checker for farmer surveys. You receive the advice a farmer was given and a draft survey.
Answer with JSON only: {"gives_new_advice": bool, "asks_personal_info": bool, "contradicts_advice": bool}
gives_new_advice is true if any question or answer tells the farmer to do something the advice did not say.
asks_personal_info is true if anything asks for a name, phone, address, income, ID, bank or other personal detail.
contradicts_advice is true if the survey assumes or suggests the opposite of the advice."""


def _context(insight: dict) -> dict:
    """The only fields that ever leave the machine."""
    return {k: insight.get(k) for k in ("asset", "concern", "resolution_type", "query_summary", "advice_summary")}


def _json_from(text: str):
    try:
        return json.loads(text[text.index("{"): text.rindex("}") + 1])
    except (ValueError, TypeError):
        return None


# ------------------------------------------------------------------ the model calls
def llm_items(insight: dict, lang: str, n_items: int | None = None, model_id: str | None = None,
              feedback: list[str] | None = None, previous: list[dict] | None = None,
              source_items: list[dict] | None = None) -> list[dict] | None:
    """Items written by a Bedrock model (the configured writing model unless `model_id` is given), or None (off, unreachable,
    or unreadable answer). Nothing is checked here: compose.py runs the guards, relevance and (optionally) model_check.
    `feedback` + `previous` (P5's agent orchestrator, bounded revision): the reasons a checker rejected the previous draft;
    the model is asked to fix exactly those. Without them the request is unchanged (same cache key as before).
    `source_items` (the approved English survey): the request becomes a translation into `lang`, and the result keeps
    the English values, follow-ups and scale fields line for line (None if the shape came back different)."""
    if not enabled():
        return None
    if source_items:
        system, user = SYSTEM_TRANSLATE, lines_from(source_items)
    else:
        system = SYSTEM_WRITE
        user = (f"Language: {lang} = {LANG_NAME.get(lang, lang)}\nQuestions: {n_items or '1 to 3'}\n"
                f"Insight: {json.dumps(_context(insight), ensure_ascii=False)}")
    if feedback:
        user += ("\nYour previous draft was rejected by the checker" + (f":\n{lines_from(previous)}" if previous else "")
                 + "\nFix these problems and write it again:\n- " + "\n- ".join(feedback))
    try:
        text = client().converse(model_id or write_model(), system, user, purpose="write", tag=str(insight.get("insight_id", "")),
                                 max_tokens=MAX_WRITE_TOKENS)
    except ModelUnavailable:
        return None
    if '"items"' in text:                                     # the older JSON answer (replayed caches, tests)
        data = _json_from(text)
        items = data.get("items") if isinstance(data, dict) else None
        return items if isinstance(items, list) and items else None
    return parse_lines(text, lang, source_items)


READ_FIELDS = {"asset": None, "concern": None, "severity": {"low", "medium", "high", "critical"},
               "advice_type": {"direct_action", "wait_and_monitor", "do_not_act", "plan_created", "escalate_to_expert",
                               "generic_information", "needs_more_context"},
               "check_back": {"next_day", "two_to_five_days", "three_to_ten_days", "seven_to_fourteen_days", "seasonal", "none"}}


def read_conversation(question: str, advice: str) -> dict | None:
    """The Evidence Extractor for a conversation typed by hand (the app's own-insight editor): the model reads the
    farmer's question and the advice and returns the planner's fields: asset, concern, severity, advice_type,
    act_within_days, check_back and questions (1-3). Only fields with an allowed value come back; None when the model
    is off or unreachable. The caller decides what to do with them; the rules R1-R8 and the window stay P2's."""
    if not enabled():
        return None
    user = f"Farmer asked: {(question or '').strip()[:400]}\nAdvice given: {(advice or '').strip()[:600] or '(none yet)'}"
    try:
        text = client().converse(write_model(), SYSTEM_READ, user, purpose="read", tag="own-insight", max_tokens=120, temperature=0)
    except ModelUnavailable:
        return None
    out = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower().strip("-* "), value.strip().strip("`'\" ").lower()
        if key in ("act_within_days", "questions"):
            m = re.search(r"\d+", value)
            if m:
                n = int(m.group())
                if key == "questions" and 1 <= n <= 3 or key == "act_within_days" and 0 <= n <= 180:
                    out[key] = n
        elif key in READ_FIELDS:
            value = re.sub(r"[^a-z_]+", "_", value).strip("_")
            allowed = READ_FIELDS[key]
            if value and (allowed is None or value in allowed):
                out[key] = value
    return out or None


def model_check(survey: dict, insight: dict) -> dict | None:
    """Second opinion from the smaller model. Returns {"gives_new_advice", "asks_personal_info", "contradicts_advice"} (booleans),
    or None when no check model is configured or it can't be reached. None means 'no opinion', not 'safe'."""
    if not enabled() or not check_model():
        return None
    draft = [{"prompt": q.get("prompt"), "options": [o.get("label") for o in q.get("options", [])]} for q in survey.get("items", [])]
    user = f"Advice given: {insight.get('advice_summary')}\nDraft survey ({survey.get('language')}): {json.dumps(draft, ensure_ascii=False)}\nReturn only JSON."
    try:
        text = client().converse(check_model(), SYSTEM_CHECK, user, purpose="check", tag=str(insight.get("insight_id", "")), max_tokens=200, temperature=0)
    except ModelUnavailable:
        return None
    data = _json_from(text)
    keys = ("gives_new_advice", "asks_personal_info", "contradicts_advice")
    if not isinstance(data, dict) or not all(isinstance(data.get(k), bool) for k in keys):
        return None
    return {k: data[k] for k in keys}


if __name__ == "__main__":                                   # python -m mel.writer.llm export-cache [path]
    import sys
    if sys.argv[1:2] == ["export-cache"]:
        target = sys.argv[2] if len(sys.argv) > 2 else None
        print(f"{export_cache(target)} answers in {target or REPLAY}")
    else:
        sys.exit("usage: python -m mel.writer.llm export-cache [path]")
