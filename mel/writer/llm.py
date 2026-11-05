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
"""
import hashlib
import json
import os
import random
import time
from pathlib import Path

from mel.config import OUT

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
    try:
        return json.loads(os.environ.get("MEL_BEDROCK_PRICES") or "{}")
    except ValueError:
        return {}


def enabled() -> bool:
    """True only when the person opted in AND a writing model id is configured."""
    return os.environ.get("MEL_USE_LLM") == "1" and bool(write_model())


def cost_usd(model_id: str, tokens_in: int, tokens_out: int):
    """None when the price of this model was not given (we never guess a price)."""
    p = prices().get(model_id)
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
        cached = cache_dir() / f"{key}.json"
        if cached.exists():
            try:
                hit = json.loads(cached.read_text(encoding="utf-8"))
                self._log(model_id, purpose, tag, 0, 0, 0.0, cached=True, ok=True)
                # what this answer took when it was made (nothing is spent now): lets callers price an answer
                self.last_usage = {"input_tokens": int(hit.get("input_tokens", 0)),
                                   "output_tokens": int(hit.get("output_tokens", 0)), "cached": True}
                return hit["text"]
            except (ValueError, KeyError, OSError):
                pass                                     # a broken cache file is just a miss
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
            self._log(model_id, purpose, tag, tin, tout, secs, ok=True)
            self.last_usage = {"input_tokens": tin, "output_tokens": tout}
            try:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps({"text": text, "input_tokens": tin, "output_tokens": tout}, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
            return text
        raise ModelUnavailable(str(last))

    def _log(self, model_id, purpose, tag, tin, tout, secs, cached=False, ok=True, error=""):
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "model": model_id, "purpose": purpose, "tag": tag,
               "input_tokens": tin, "output_tokens": tout, "cost_usd": 0.0 if cached else cost_usd(model_id, tin, tout),
               "seconds": round(secs, 3), "cached": cached, "ok": ok, "error": error}
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
SYSTEM_WRITE = """You write short follow-up surveys for smallholder farmers in Bihar, India.
Ask ONLY about advice the farmer already received: did they act on it, and did it work.
Never give new advice. Never contradict the advice. Never ask for personal information (name, phone, address, income, Aadhaar, bank).
Return JSON: {"items": [...]} with exactly the number of items you are asked for, following this shape:
  {"item_id":"q1","type":"survey-confirm"|"survey-single-select","prompt":"...",
   "options":[{"value":"snake_case","label":"<=20 chars","follow_up":"advice_did_not_work|crop_or_animal_damaged|could_not_get_input|could_not_reach_expert"(optional)}]}
  or {"item_id":"q2","type":"survey-scale","prompt":"...","scale_min":1,"scale_max":5,
   "follow_up_at_or_below":1,"follow_up_reason":"advice_did_not_work"}
survey-confirm has exactly the options yes/no. Mark follow_up on any answer that means failure or harm.
Write prompts and labels in the requested language only. Option values are English snake_case.
In Hindi use simple words and avoid verb endings that change with the farmer's gender."""

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


# ------------------------------------------------------------------ the two calls
def llm_items(insight: dict, lang: str, n_items: int | None = None, model_id: str | None = None) -> list[dict] | None:
    """Items written by a Bedrock model (the configured writing model unless `model_id` is given), or None (off, unreachable,
    or unreadable answer). Nothing is checked here: compose.py runs the guards, relevance and (optionally) model_check."""
    if not enabled():
        return None
    ask = f"Number of questions: {n_items}\n" if n_items else ""
    user = f"Language: {lang} = {LANG_NAME.get(lang, lang)}\n{ask}Insight: {json.dumps(_context(insight), ensure_ascii=False)}\nReturn only JSON."
    try:
        text = client().converse(model_id or write_model(), SYSTEM_WRITE, user, purpose="write", tag=str(insight.get("insight_id", "")))
    except ModelUnavailable:
        return None
    data = _json_from(text)
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) and items else None


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
