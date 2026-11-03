# Decisions for the H+4 meeting: function names and shapes

At H+4 we freeze every shared function and data shape. The contract proposes some names that differ from
the code we already have. For each row, pick **Keep** (use today's code name, change the contract) or
**Rename** (change the code to match the contract). Tick one box per row, then post the result in chat.

**Recommendation:** keep today's names wherever the contract only renames something, and add the genuinely
new pieces (marked *new*). Renaming costs time and breaks tests for no gain in the score.

| # | Owner | Contract says | Code has today | Recommendation | Decision |
|---|---|---|---|---|---|
| 1 | P1 | `load_insights(path) -> list[Insight]` | same (returns plain dicts) | Keep. "Insight" = the dict shape in `config/schemas/insight.schema.json` | ☐ Keep ☐ Rename |
| 2 | P1 | `validate(obj, schema_name) -> list[Error]` | `errors(kind, obj) -> list[str]` (arguments the other way round) | Keep `errors()`; the contract name can be an alias | ☐ Keep ☐ Rename |
| 3 | P1 | `run_pipeline(insights, limit=None, farmer=None) -> RunResult` | `run_insight(insight)` (one at a time); the batch loop lives in `cli.py` | *New:* add `run_pipeline()` that wraps the CLI loop; keep `run_insight()` | ☐ Add ☐ Skip |
| 4 | P2 | `decide(insight) -> Decision(survey, rule_id, reason, escalate)` | `decide(insight) -> Decision(survey, rule, reason_code, send_window)` | Keep field names; add `escalate` only if Digital Green's answer needs it | ☐ Keep ☐ Rename |
| 5 | P2 | `compute_window(insight, decision, now) -> Window(start, end, timezone, basis)` | `send_window(insight) -> {"not_before", "not_after"}` | Keep. The schema calls them `not_before`/`not_after`, so renaming would fight the grader. Add a `basis` setting ("brief" or "answer_key") for the 07:00 vs 09:00 switch | ☐ Keep ☐ Rename |
| 6 | P2 | `crop_season(crop, date) -> Season \| None` | `is_past_harvest(crop, date) -> bool` | Keep; extend it with the missing-crop fallback | ☐ Keep ☐ Rename |
| 7 | P4 | `compose_survey(decision, insight, lang="both") -> Survey` | `write_surveys(insight, window) -> {lang: survey}` | Keep | ☐ Keep ☐ Rename |
| 8 | P4 | `check_survey(survey) -> GuardResult(ok, failures)` | `check_survey(survey) -> list[str]` (empty = ok) | Keep; "ok" is just "list is empty" | ☐ Keep ☐ Rename |
| 9 | P4 | `relevance(survey, insight) -> float` | `relevance_score(survey, insight) -> float` | Keep | ☐ Keep ☐ Rename |
| 10 | P4 | `write_survey_llm(decision, insight) -> Survey \| None` | `llm_items(insight, lang) -> items \| None` | Keep | ☐ Keep ☐ Rename |
| 11 | P3 | `build_handoff(survey, decision, window, farmer) -> Handoff` | `build_handoff(insight, survey)` (window comes from the survey) | Keep; add an optional `farmer` argument when unreachable-channel skipping is built | ☐ Keep ☐ Rename |
| 12 | P3 | `CapLedger.admit(handoff) -> Admit` (sent / moved / merged / skipped / opted_out) | `CapLedger.allow(handoff) -> bool` | *New:* add `admit()` returning one of the five words; `allow()` can stay underneath | ☐ Add ☐ Skip |
| 13 | P3 | `is_opted_out(farmer_id) -> bool` | `OptOutList().blocks(farmer_id_or_handoff)` | Keep `blocks()`; `admit()` returns `opted_out` for these | ☐ Keep ☐ Rename |
| 14 | P3 | `render(survey, channel, lang) -> RenderedMessage` | `render(survey, channel)` (language is inside the survey) | Keep; a `lang` argument would duplicate what the survey already says | ☐ Keep ☐ Rename |
| 15 | P3 | `simulate(handoff, persona, seed) -> list[Outcome]` (with `late`) | `simulate(survey, channel, case, seed) -> one response` | *New:* add `simulate_handoff(handoff, persona, seed) -> list[response]` that tries each channel in order; keep `simulate()` for single records. `late` goes on each record | ☐ Add ☐ Skip |
| 16 | P5 | `score_golden(results, golden_path) -> Scorecard` | `score_golden(golden=None) -> dict` (runs the pipeline itself) | Keep; add `confusion` and `item_similarity` keys to the dict | ☐ Keep ☐ Rename |
| 17 | P5 | `item_similarity(survey, golden_items) -> float` | doesn't exist | *New:* add it | ☐ Add ☐ Skip |

**Also fix in the contract** (P3's "Where you start"): channel order is not "app → web → WhatsApp → Telegram
→ voice". It is: preferred channel, then the channel the check method names, then WhatsApp, then voice for
high priority only (see `docs/TEAM.md`).

Once decided: the owner updates their code (if renaming/adding), P1 updates `docs/TEAM.md` → "Interfaces",
and the contract's "What you hand over" lines are edited to match.
