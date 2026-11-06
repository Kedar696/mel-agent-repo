# Prompt: P4 Survey Writing & Safety — what was built and how to continue

Use this to brief Claude (or a teammate) on the P4 work, then ask for the next piece. Copy everything below
the `---` line into Claude. Fill the bracketed parts. Numbers come from `python scripts/writer_report.py`
and `python -m pytest -q`; refresh them if the code moves.

---

You are helping me (P4, Survey Writing & Safety) on the Digital Green "MEL Survey Agent" hackathon project
(5-person team: P1 Data, P2 Decision & Timing, P3 Scheduler/Channels/Simulator, P4 Survey Writing & Safety,
P5 Evaluation & Demo). My files are `mel/writer/` and `tests/test_writer.py`. Synthetic data only.

## My job
Write 1 to 3 tap-answer survey questions in Hindi (hi-IN) and English (en-IN) about the advice the farmer
received. Surveys check what happened; they never give advice or ask for personal information. A survey that
fails any guard is never shown; the plain template is used instead. The model path is Amazon Bedrock (Converse API), optional and off by default.

## What I built (prompted step by step with Claude)
1. **Templates** (`templates.py`, `i18n.py`): every resolution type (direct_action, wait_and_monitor,
   do_not_act, plan_created, escalate_to_expert) x top-10 concerns (pest_disease, weather_climate,
   growth_issue, nutrient_deficiency, water_stress, livestock_nutrition, storage_post_harvest,
   livestock_health, variety_selection, market_price). Order: did you do it, did it work, what stopped you.
2. **2-vs-3 rule** (found in the golden set): direct_action gets 3 questions if severity is medium or high,
   2 if low. Every other type gets 2.
3. **Advice-specific first question**: "Did you apply zinc?", "Did you call the vet?", "Have you seen insects
   in the bins?" taken from the advice text, so generic action questions are 0%.
4. **Hindi gender agreement**: feminine crops/animals (सरसों, मसूर, फूलगोभी, पत्तागोभी, गाय, भैंस, बकरी) get
   आपकी/कैसी/रही; others आपका/कैसा/रहा. Questions avoid verbs that agree with the farmer's own gender.
5. **Labels** at most 20 characters (WhatsApp button limit), glossary in `i18n.LABELS`.
6. **Guards** (`guards.py`, `check_survey`): bad_item_count, bad_option_count (2 to 10 answers, so scale
   at most 10), confirm_needs_two, prompt_too_long (400), label_too_long (20), empty_text,
   duplicate_option_value, duplicate_item_id, wrong_language (Devanagari check), gives_new_advice,
   asks_personal_info, unknown_follow_up (allowed: advice_did_not_work, could_not_reach_expert,
   crop_or_animal_damaged, could_not_get_input, problem_growing, needs_more_help, problem_recurring,
   input_not_available, cost_barrier), and schema_invalid (runs only when `config/schemas/survey.json`
   exists). An allow-list exists; every entry needs its own test.
7. **Relevance score v2** (`compose.relevance`): 0.3 crop named + 0.3 concern words + 0.4 advice key words,
   same logic in both languages. Each survey carries it in `self_eval`.
8. **History-aware questions** (`history.py`): H1 repeat problem within 45 days, H2 earlier survey said
   not_nearby / too_costly, H3 survey fatigue, H4 light user (at most 2 questions). Only data earlier than the
   insight is used (no leakage).
9. **Bedrock writer** (`llm.py`, `compose.py`): one `ModelClient` over the Amazon Bedrock Converse API (model ids in config, off by
   default), retries with backoff, disk cache, per-call token/cost/time log, template fallback, no farmer ids in the prompt.
   A model survey is used only if it has the right question count, passes every guard, is at least as relevant as the template,
   and (when a check model is set) the small model finds no new advice, no personal info and no contradiction of the advice.
   `compose_survey(decision, insight, lang)` takes hi-IN or en-IN (English is the evaluation baseline) and every survey
   carries `self_eval`. Tested with a fake client only; not run against real Bedrock. Two styles via `SETTINGS['writer_style']`:
   `golden` (default, matches the answer key) and `concern` (more concern-specific).
10. **Concern-style wait_and_monitor fallback**: when the advice names nothing to watch for, ask about the
    concern ("Have more leaves of your wheat turned yellow?") instead of "the problem".
11. **Language switch** in the survey tab (in my standalone app; the shared app already has one).
12. **Hindi review sheet** (`docs/p4/hindi_review_sheet.csv`, 438 rows) for a native reviewer, and `docs/p4/P4_PLAN.md`
    (checkpoints H+4 to H+36).

## Bugs the tests found (good demo stories)
- Substring check flagged the Hindi word "आया" as income ("आय"); fixed with whole-word Devanagari tokens.
- Hindi advice like "छिड़कनी चाहिए" got through the advice guard; fixed with an infinitive + चाहिए/होगा pattern,
  while "क्या आपको और मदद चाहिए?" stays allowed.
- Bare "चाहिए" and English "contact the vet" caused false positives; patterns narrowed.

## Numbers (answer key = golden set, 94 surveys)
- Tests: 298 pass in the shared repo. `python -m mel.cli validate`: 0 invalid surveys.
- `golden` style: question-count match 1.0, q1 word overlap 0.957, q1 exact 0.883, labels identical 1.0,
  relevance mean 0.706, guard pass 1.0.
- `concern` style: q1 overlap 0.766, labels identical 0.701, relevance mean 0.847, guard pass 1.0.
- ~17.8% of wait_and_monitor questions still use the generic fallback.

## What the two Digital Green documents changed
- Safety tenet: no personal information, no new advice, and a survey must not contradict the advice
  received. **Contradiction guard is not built yet.** A "did not work" or "crop damaged" answer is routed back
  for follow-up (our `follow_up` flags).
- Required provider is Amazon Bedrock; log tokens, estimated cost and time per survey. **Not built yet.**
- Open for Digital Green (via P1): survey JSON format (`single_choice` with `{id,label}` options vs our
  `survey-confirm` with `value`), resolution names (`indirect_action / wait_and_watch` vs the golden set's
  five), 07:00 vs 09:00 window, critical cases.

## How it was merged into the shared repo (branch `kedar-p4`)
- `mel/writer/` keeps the shared API: `write_surveys(insight, send_window, langs)`, `check_survey(survey) -> list[str]`,
  `template_items(insight, lang)`, `self_eval`, `relevance_score`. New: `check_survey_result`, `relevance` (relevance.py),
  `templates.STYLE`.
- The guard now also runs `survey.schema.json` through `mel.data.validate`. The schema allows only four follow-up
  reasons, so finer ones map onto them (`templates.FOLLOW_UP_MAP`).
- Result: 298 tests pass; full pack = 5,102 surveys with 0 failures, relevance mean 0.711; `mel.cli validate` 0 invalid.
- The Streamlit app already had a language switch (segmented control), so `app/` was not touched.
- Not merged yet: history-aware questions.
- Branch `kedar-p4`, small commits, `git pull --rebase origin main`, pull request reviewed by P3 (and P5/P2). CI is
  `pytest -q` and `python -m mel.cli validate`. Never commit `.env` or keys.

## Still to do (in cut order if late: comparison, model path)
1. Native Hindi review applied to `templates.py` and `i18n.LABELS`.
2. Run the Bedrock path and `python scripts/p4_compare.py` against real Bedrock once models are enabled (templates vs
   the large and small model on up to 50 surveys: guard pass rate, relevance, cost, speed). Only tested with a fake client so far.
3. Add `boto3` to requirements (P1 owns that file) and agree the relevance threshold for the scheduler gate with P5 and P3.
4. Post the top-10 concerns and guard codes to the team; give P5 the style numbers for "Rules we changed".

## What I want from you now
[Pick one: write the contradiction guard / merge my writer into the shared repo without breaking
`check_survey` callers / write the Bedrock wrapper / draft the demo script for P4 / other: ____ ]
Answer in plain English, give exact terminal commands for macOS zsh without trailing `# comments`,
and add a test for every new rule.
