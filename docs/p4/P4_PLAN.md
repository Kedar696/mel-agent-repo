# P4 plan: Survey Writing & Safety
Branch: `kedar-p4` · Reviewer: P3 (also P5/P2) · CI: `pytest -q` + `python -m mel.cli validate`

| Checkpoint | Goal | Status |
|---|---|---|
| H+4 | Post top-10 concerns and guard failure codes to team (below) | ready to post |
| H+12 | Templates for top-10 concerns x 5 resolution types, EN+HI, labels <=20 chars | done |
| H+24 | Guards (advice, PII, language, structure, follow-up allow-list) with tests; relevance v2 | done, 298 tests pass |
| H+36 | Hindi native review applied (`hindi_review_sheet.csv`); Claude writer vs templates comparison | Hindi review PENDING; comparison needs API key; cost/speed logging not yet added |

Top-10 concerns: pest_disease 2058, weather_climate 1648, growth_issue 722, nutrient_deficiency 520, water_stress 307, livestock_nutrition 197, storage_post_harvest 173, livestock_health 138, variety_selection 132, market_price 131.

Guard codes: bad_item_count, bad_option_count, confirm_needs_two, prompt_too_long, label_too_long, empty_text, duplicate_option_value, wrong_language, gives_new_advice, asks_personal_info, unknown_follow_up.

Numbers (for P5 "Rules we changed"): default style `golden` = q1 word overlap 0.957, labels identical 1.0, relevance 0.706; style `concern` = 0.766 / 0.701 / 0.847. Guard pass 100% both.

Cut order if late: AWS -> Claude path -> personas -> Excel loader -> follow-up queue. Never cut guards, Hindi review, weekly limit.

## Merged into the shared repo (3 Nov)
- `check_survey(survey)` still returns `list[str]` (empty = safe), so callers did not change. `check_survey_result(survey)` returns `.ok/.failures/.codes`.
- Schema validation now runs inside the guard (`mel.data.validate`, `survey.schema.json`).
- `survey.schema.json` allows only four follow-up reasons (advice_did_not_work, crop_or_animal_damaged, could_not_get_input, could_not_reach_expert). Finer reasons in our templates map onto them (`templates.FOLLOW_UP_MAP`).
- Result on the full pack (2,551 surveys x 2 languages = 5,102): 0 guard or schema failures, relevance mean 0.711.
- Not merged yet: history-aware questions (H1 to H4), Claude writer cache/retries, Bedrock + cost logging, contradiction guard.
- Writer style default is `golden` (`templates.STYLE`); `concern` is more concern-specific.
