# Team plan (5 people)

The signed **Team Contracts** document is the source of truth for who does what and when. This file is the
short version kept next to the code: owners, files, interfaces, open questions and plain-English notes.
If the two disagree, the contract wins; fix this file.

Changed 3 Nov: team went from 8 to 5 by merging buddy pairs (old P2+P3 → P2, old P4+P7 → P3,
old P5+P6 → P4, old P8 → P5). All commitments kept.

## Who owns what
| Person | Role | Owns (files) | Buddy / backup |
|---|---|---|---|
| **P1** | Data, Contracts & Integration | `mel/config.py`, `mel/data/`, `mel/pipeline.py`, `mel/cli.py`, `config/`, `scripts/`, `data/mock/`, `.github/`, `.kiro/`, `tests/test_data.py`, `tests/test_cli.py`, `tests/test_parity.py` | P5 |
| **P2** | Decision & Timing | `mel/decision/`, `mel/timing/`, `tests/test_decision.py`, `tests/test_timing.py` | P3 |
| **P3** | Scheduler, Channels & Simulator | `mel/schedule/`, `mel/channels/`, `mel/simulator/`, `tests/test_schedule.py`, `tests/test_simulator.py` | P2 (also backs up P4) |
| **P4** | Survey Writing & Safety | `mel/writer/` (templates, i18n, compose, llm, guards), `tests/test_writer.py` | P3 |
| **P5** | Evaluation & Demo | `mel/evaluation/`, `app/`, `.streamlit/`, `tests/test_pipeline.py`, README results, slides | P1 |

`docs/` is shared by P1 and P5. Code owners for review are in `.github/CODEOWNERS`.

**How work flows:** P1 → P2 → (P4 writes questions, P3 packages and sends) → P5 shows it to the judges.
P4's surveys go to P3. Everyone sends final numbers to P5.

## Tech stack
| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ (dev machine: 3.14), `.venv` | one language end to end |
| Contracts | JSON Schema 2020-12 via `jsonschema` | the pack's schemas are the grading contract |
| Rules | `config/rules/rules.json`, `outcome_codes.json` | rules stay data, not hard-coded |
| Decision / timing / schedule | plain Python, deterministic | must reproduce golden set + worked scenarios |
| Survey writing | templates (default) + Claude via `anthropic` SDK (opt-in) | templates are safe and free |
| Guardrails | patterns + schema checks in `mel/writer/guards.py` | no new advice, no personal info, ≤20-char labels |
| Simulation | seeded `random` (same seed, same answers) | reproducible |
| UI | Streamlit | the brief says Streamlit or CLI is enough |
| Tests | `pytest`, one file per owner | each owner keeps their own tests green |

## Interfaces as they are in the code today
The contract proposes some new names. Decide which to use at H+4: see
[h4_interface_decisions.md](h4_interface_decisions.md).
```python
mel.data.load_insights(path=None) / load_farmers(path=None) / load_golden(path=None) / load_crop_calendar(path=None)  # P1
mel.data.load_insights_xlsx(p) / load_golden_xlsx(p) / load_farmers_xlsx(p) / load_crop_calendar_xlsx(p)             # P1: same data as the JSON/CSV loaders
mel.data.errors(kind, obj) -> list[str]; validate(kind, obj); failed_fields(kind, obj) -> list[str]                  # P1
mel.data.why_junk(insight) -> list[str]; junk_row(insight) -> (category, detail) | None                              # P1
mel.data.check_all_parity(pack=None) -> list[str]   (empty = workbooks, rules, schemas, scenarios, outcomes all agree) # P1
mel.pipeline.run_insight(insight) -> {"decision", "surveys", "handoff"} | {"decision", "no_survey"}  # P1 (unchanged)
mel.pipeline.run_pipeline(insights, limit=None, farmer=None) -> PipelineResult                       # P1: filter + loop, writes nothing
#   PipelineResult.insights / .outputs (same order as the input) / .rows_processed / .counts()
mel.pipeline.select_insights(insights, limit=None, farmer=None) -> list                              # P1: the shared --limit / --farmer filter
mel.decision.decide(insight) -> Decision(survey, rule, reason_code, send_window)        # P2
mel.timing.send_window(insight) -> {"not_before", "not_after"} | None; expires_at(window) # P2
mel.timing.is_past_harvest(crop, date) -> bool                                           # P2
mel.writer.write_surveys(insight, window) -> {lang: survey}                              # P4
mel.writer.check_survey(survey) -> list[str]   (empty list = safe)                       # P4
mel.writer.guards.relevance_score(survey, insight) -> float 0..1                         # P4
mel.schedule.build_handoff(insight, survey) -> handoff                                   # P3
mel.schedule.CapLedger().allow(handoff) -> bool; OptOutList().record(resp) / .blocks(h)  # P3
mel.channels.render(survey, channel) -> payload                                          # P3
mel.simulator.simulate(survey, channel, case, seed) -> response                          # P3
mel.evaluation.score_golden(golden=None) -> metrics                                      # P5
```

## Where each person starts (3 Nov, mock data)
- **P1 (commit 5763855 plus this round):** all done: `run` / `eval` / `validate` / `junk` / `parity`; `--limit` (negative is an
  error), `--farmer`, `--clean`; `validate` fails when there is nothing to check (`--allow-empty` to override);
  `run_pipeline`; `run_summary.json` and `junk_report.csv` (below); Excel loaders for all four workbooks; `parity`
  with no arguments checks the four workbooks and `config/rules`, `config/schemas`, `data/mock/scenarios`,
  `data/mock/outcomes` against the committed pack; `scripts/compare_golden.py`; CI; Kiro steering and spec.
  Still open: real usernames in `.github/CODEOWNERS`; sending the questions to Digital Green
  ([questions_for_digital_green.md](questions_for_digital_green.md)); the P3 wiring request (see Merge order).
- **P2:** merged 4 Nov. Decision and rule accuracy 99.3% under the brief rules (one miss: G-0145, a one-day
  31 March window); 100% with 100% window match under the answer-key setting (`MEL_TIMING_BASIS=answer_key`).
  R7 now lets stored crops through. Details: `mel/timing/README.md`.
- **P3:** priority, channel order, expiry and flow ids match the scenarios. Channel messages match the
  pack's reference files exactly (tested). `OptOutList` and `CapLedger` exist but aren't used in the batch run.
  Not yet: two-in-a-week policy, late answers, app/web sent once, fallback across channels, the 183-record match.
- **P4:** generic templates in both languages pass the guards; opt-in Claude writer with template fallback;
  basic relevance score on every survey. Not yet: problem-specific templates, Hindi review, stronger guards,
  Claude retries/cache/logs, templates-vs-Claude table.
- **P5:** app (Overview, Survey Studio, Simulate, Follow-up queue, Evaluation), five-dimension scorecard on all
  6,999 insights (timeliness 100% brief / 26.5% answer-key), both send-time rules side by side, run history
  with improvement runs, generated "Rules we changed" table, README + offline scorecard by script, 3-minute
  script. Not yet: AI judge on Bedrock, Season screen, P3/P4 hook-ups, slides, rehearsals, video.
  Status table: `docs/p5_plan.md`.

**Channel order (P3), as the brief and code define it:** 1) the farmer's preferred channel, 2) the channel the
advice's check method names, if different, 3) WhatsApp, 4) voice, only for high priority. Wait 6 h (high),
24 h (normal) or 48 h (low) before trying the next one.

## Run outputs (for P5)
`python -m mel.cli run` writes these into `MEL_OUT_DIR` (default `./out`). Same input, same files, byte for byte.
- `surveys/`, `handoffs/`, `no_survey/`, `responses/` (with `--simulate`): one JSON per artifact. `--clean` empties
  only these four folders first; anything else in the output folder stays.
- `run_summary.json`: what this run did. Keys:
  - `input_path` (the insights file read), `rows_read`, `rows_processed` (after `--limit` / `--farmer`), `limit`, `farmer`
  - `surveys` and `no_survey` (they add up to `rows_processed`), `junk_rows`
  - `by_rule`: `R1` to `R8`, every key always present, counts every processed row (sums to `rows_processed`)
  - `by_language` (`hi-IN`, `en-IN`), `by_first_channel` (app, web, whatsapp, telegram, voice) and `by_priority`
    (`high`, `normal`, `low`): these describe the hand-offs, so they only count rows that got a survey and each sums to `surveys`
- `junk_report.csv`: columns `insight_id`, `category`, `detail`; one row per junk insight processed. Junk is what
  `why_junk` flags: labelled `quality_flag: junk`, or failing the insight schema. `schema_failure` rows list every
  failed field in `detail` (for example `query_summary`, `advice_summary`, `resolution_type`). Schema-valid junk is sorted by
  what the farmer said: `greeting`, `thanks`, `about_the_app`, `unclear_voice`, `unclear_text`, `acknowledgement`,
  `off_topic`, or `other_junk`. This is a report only: it never changes a survey decision.
Do not write output into a OneDrive/Dropbox folder: sync locks files and a long run can stall or fail.

## Merge order
As of 4 Nov, `origin/main` is 71ad499. It already contains `willF-p2` (P2) and
`p5-scorecard` (P5) through PRs #1 to #3. Not yet in main: `Semdon-P3` (9380a79), `kedar-p4` (8be9efe) and
`lucas-p1` (this work, based on 5763855). `main` can move again, so re-check with `git fetch origin main`.
Nothing was merged to produce this list; it comes from comparing each branch with its merge-base.

Order, and why:
1. **`lucas-p1` (P1) first, after merging `origin/main` into it.** Everyone else imports `mel.config`, `mel.data` and
   `mel.pipeline`, and none of the other branches touch `mel/cli.py` or `mel/data/`. Merge main into `lucas-p1`
   first so the one real conflict (below) is fixed on the branch, then open the PR.
2. **`Semdon-P3` (P3) second.** It only edits `mel/schedule/`, `mel/simulator/`, its tests and new docs, so it merges cleanly.
   Its request in `docs/p3_batch_wiring_request.md` asks to change `cmd_run`; that now has to go through `run_pipeline`
   and must not change the survey counts (see below). Also pending from P3: `docs/h4_schema_change_request_late.md`
   (optional `late` field in `response.schema.json`), which is a P1 decision.
3. **`kedar-p4` (P4) last.** It edits `mel/writer/` and its tests, plus `CLAUDE.md` and `docs/prompts/README.md`.
4. `willF-p2` and `p5-scorecard` need no action: already in main. If `main` is behind them, merge them before step 1.

Files likely to conflict with `lucas-p1` (checked by comparing each branch's changed files with mine):
| File | Who else changed it | What to do |
|---|---|---|
| `mel/config.py` | main (P2 / P5): added `PACK` and `PACK_DATA` after `FIXTURES` | I added the same two lines in the same place, so git should merge cleanly. Keep one copy. `app/` and `scripts/readme_numbers.py` import `PACK_DATA`, do not remove it. |
| `mel/cli.py` | nobody else edited it since the base, but P3 wants to change `cmd_run` | Keep my `cmd_run` (calls `run_pipeline`, writes the summary and junk report). Apply P3's cap / opt-out gating inside it only if the run counts stay the same (or are explained). |
| `mel/data/` (`__init__`, `excel`, `validate`, new `junk`) | nobody | No conflict. `mel/decision/rules.py` and `mel/timing/calendar.py` import `mel.data.validate.is_valid` and `mel.data.loader.load_crop_calendar`; both still exist. |
| `mel/pipeline.py` | nobody (P5's `mel/evaluation/` imports `run_insight` and `clean`) | `run_insight` and `clean` are unchanged. |
| `README.md`, `CLAUDE.md`, `docs/TEAM.md` | main / p5-scorecard (results section, status lines); `CLAUDE.md` also `kedar-p4` | Take both: my quick start / commands, their results and status lines. Leave the README results section to P5. |
| `docs/prompts/README.md` | `kedar-p4`, `p5-scorecard` | I did not edit it; no conflict with mine. |
| `tests/test_data.py` | nobody | My new tests are in `tests/test_cli.py` and `tests/test_parity.py`. |
After merging, run the proof set again (`pytest -q`, `run --simulate --clean`, `validate`, `eval`, `parity`). P2's changes
can move rule counts and eval scores, so the numbers in the brief of this round (R1 723 ... R8 2551, decision 96.0%)
are for the base code, not for the merged result.

## Questions to send Digital Green (P1 sends, P2 writes the examples)
Draft with real examples: [questions_for_digital_green.md](questions_for_digital_green.md).
1. The answer key opens windows at 09:00; the brief says 07:00. Which is right?
2. Critical cases: high-priority survey, or no survey and a human call?
3. Will there be a new answer key (golden set version 2), and when?
4. Is there an MEL rubric for judging relevance?
5. Does our survey JSON match your agent-to-UI format?
Also ask event staff which Bedrock models and region are enabled.

## AWS, in plain English
Bedrock is **required** for every model call (FINAL contract, 4 Nov); everything else comes after the core
targets. One Workshop Studio account, owned by P1, in the region where event staff enabled the Bedrock
models. Bedrock uses the account's IAM role, so there is no model key. Every resource we create is defined
in `infra/`; never put AWS keys in git or chat.

| Plain words | AWS name | Use | Owner |
|---|---|---|---|
| A shared online folder | **S3** | Data pack and our output files | P1 |
| A locked box for keys | **Secrets Manager** | Keep keys out of the code | P1 |
| Amazon's AI models | **Bedrock** | **Required**: the AI writer (P4) and the AI relevance judge (P5) | P4, P5 |
| A web link for the demo | **App Runner** | Judges open a link; laptop demo stays the main plan | P5 with P1 |
| Alarm clock and retry | **EventBridge / Step Functions** | *Slide only*: send at 07:00, retry on WhatsApp after 24 h | P3 notes → P5 slide |
| Digital Green's database | **RDS for PostgreSQL** | *Slide only*: weekly limit and opt-outs in real life | P3 notes → P5 slide |
| Automated phone calls | **Amazon Connect** | *Slide only*: real voice surveys | P3 notes → P5 slide |

## Words you'll hear
- **Insight**: one past FarmerChat conversation, summed up (crop or animal, problem, advice).
- **Golden set**: the answer key. 150 cases with the right decision. We're scored against it.
- **Hand-off**: the package for the sending system: when, which channel first, how urgent, when it expires.
- **Schema**: the required shape of a file. "Schema-valid" = the file has the right fields.
- **Guardrails**: automatic checks that stop a survey giving new advice or asking for personal info.
- **Follow-up (⚑)**: an answer that means trouble, so FarmerChat should get back to the farmer.
- **Cap**: the weekly limit, 1 non-urgent survey per farmer per 7 days.
- **Send window**: the dates and hours a survey may go out.
- **Opt-out**: STOP, /stop, pressing 9, or "Do not ask me again". That farmer gets nothing after that.

## Working agreements
- `main` always works. Branch per task: `p<N>-<topic>` (for example `p2-brief-rule`).
- PRs reviewed by a downstream owner, usually your buddy. Tests and `mel.cli validate` must pass.
- Never edit another owner's package without their OK (see `.github/CODEOWNERS`).
- Changing a shared shape (function signature, schema, `requirements.txt`): post in chat first.
- Every question for Digital Green goes through P1.
- Give teammates shell commands without trailing `# comments` (zsh passes them as arguments).
