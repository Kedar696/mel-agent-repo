# P4 plan: Survey Writing & Safety
Branch: `kedar-p4` · Reviewer: P3 (also P5/P2) · CI: `pytest -q` + `python -m mel.cli validate`

| Checkpoint | Goal | Status |
|---|---|---|
| H+4 | Post top-10 concerns and guard failure codes to team (below) | ready to post |
| H+12 | Templates for top-10 concerns x 5 resolution types, EN+HI, labels <=20 chars | done |
| H+24 | Guards (advice, PII, language, structure, follow-up allow-list) with tests; relevance v2 | done, 298 tests pass |
| H+36 | Hindi native review applied (`hindi_review_sheet.csv`); templates vs Bedrock comparison | Hindi review PENDING; Bedrock path built and tested with a fake client, NOT yet run against real Bedrock; comparison script ready (prints `not run` until Bedrock is on) |

Top-10 concerns: pest_disease 2058, weather_climate 1648, growth_issue 722, nutrient_deficiency 520, water_stress 307, livestock_nutrition 197, storage_post_harvest 173, livestock_health 138, variety_selection 132, market_price 131.

Guard codes: bad_item_count, bad_option_count, confirm_needs_two, prompt_too_long, label_too_long, empty_text, duplicate_option_value, wrong_language, gives_new_advice, asks_personal_info, unknown_follow_up.

Numbers (for P5 "Rules we changed"): default style `golden` = q1 word overlap 0.957, labels identical 1.0, relevance 0.706; style `concern` = 0.766 / 0.701 / 0.847. Guard pass 100% both.

Cut order if late: AWS -> Claude path -> personas -> Excel loader -> follow-up queue. Never cut guards, Hindi review, weekly limit.

## Merged into the shared repo (3 Nov)
- `check_survey(survey)` still returns `list[str]` (empty = safe), so callers did not change. `check_survey_result(survey)` returns `.ok/.failures/.codes`.
- Schema validation now runs inside the guard (`mel.data.validate`, `survey.schema.json`).
- `survey.schema.json` allows only four follow-up reasons (advice_did_not_work, crop_or_animal_damaged, could_not_get_input, could_not_reach_expert). Finer reasons in our templates map onto them (`templates.FOLLOW_UP_MAP`).
- Result on the full pack (2,551 surveys x 2 languages = 5,102): 0 guard or schema failures, relevance mean 0.711.
- Not merged yet: history-aware questions (H1 to H4).
- Writer style default is `golden` (`templates.STYLE`); `concern` is more concern-specific.

## Bedrock path (4 Nov, from the updated Team Contracts)
The Anthropic key is gone. `mel/writer/llm.py` now has one `ModelClient` over the Amazon Bedrock Converse API.
- **Off by default.** Turn on with `MEL_USE_LLM=1` and `MEL_BEDROCK_WRITE_MODEL=<model id>` (larger model, writes). Optional `MEL_BEDROCK_CHECK_MODEL=<model id>` (smaller model, double-checks), `MEL_BEDROCK_REGION`, and `MEL_BEDROCK_PRICES='{"<id>": {"in": 0.003, "out": 0.015}}'` (USD per 1,000 tokens, for the cost column). Model ids are config values, not code. No key anywhere: boto3 uses the IAM role of the workshop account. `boto3` comes with `pip install -e ".[agent]"` (or `.[dev]`).
- **Retries with backoff** on throttling, timeouts and connection errors; **no retry** when access is denied or the model is not enabled. After the last retry the survey falls back to the template.
- **On-disk cache** (`out/cache/bedrock`, same request = no second call) and a **per-call log** (`out/bedrock_calls.jsonl`: model, tokens in/out, cost, seconds, cached, ok, error). `llm.usage_summary()` sums a run. A call with no configured price logs `cost_usd: null` and is counted under `unpriced_calls`; we never guess a price.
- **A model survey is used only if all of these pass**, otherwise the template is sent and `_fallback_reason` says why: right number of questions (2-vs-3 rule), every guard, relevance at least as good as the template for the same insight, and (if a check model is set) the small model says no new advice, no personal info and no contradiction of the advice.
- **Language** is a BCP 47 code: `compose_survey(decision, insight, lang)` takes `hi-IN` or `en-IN` (`hi`, `en` also work; anything else raises). English (`en-IN`) is the evaluation baseline and the default; Hindi comes from the same code when passed `hi-IN`.
- **`self_eval` on every survey**: `schema_valid`, `relevance_score`, `gives_new_advice`, `asks_personal_info`, computed on the survey that is actually sent (after any fallback). P3 never schedules one that fails it.
- **What goes to the model**: asset, concern, resolution type, query summary and advice summary only. A test checks that farmer and conversation ids are never sent.
- **Comparison**: `python scripts/p4_compare.py` writes `out/p4_compare.md` (templates vs the large and small model on up to 50 English surveys: guard pass rate, relevance, tokens, cost, seconds). With Bedrock off it prints `not run`. On the 57-insight mock data it can only sample 16 surveys; the full pack gives 50.
- **Tests**: 335 pass in total with a fake `bedrock-runtime` object (retries, cache, log, fallbacks, language, privacy, comparison). Nothing has called real AWS yet.
- Open with P3/P5: the relevance threshold for the scheduler gate. About 20% of today's template surveys score below 0.5, so a fixed threshold would drop good template surveys; pick it with P5 from the numbers.
