# Fasal Pulse - MEL Survey Agent: project status for Claude

Read this first in every new session. Update the **Status** and **Open items** sections whenever work lands
(and the date below), so the next session starts from the truth.

_Last updated: 2026-11-05 (lucas-p1: weekly cap in `mel.cli run`, REST API, Docker/infra, Py 3.12, DG questions)_

## What this is
Hackathon project for Digital Green (MEL = monitoring, evaluation, learning). Python tool that reads FarmerChat
"insights" (farmer conversations), decides survey / no survey (rules R1–R8), writes 1–3 tap questions in hi-IN +
en-IN, builds a scheduler hand-off, renders per channel (app, web, WhatsApp, Telegram, voice), and simulates
answers. Scored against a 150-row golden set. Synthetic data only. Real delivery is out of scope.

- Repo: https://github.com/michvinh-7/mel-agent-repo (branch `main`)
- Organisers' brief: `mel-survey-agent-participant-pack/participant-pack/index.html`. The full pack is committed in
  the repo at `mel-survey-agent-participant-pack/participant-pack/` (read-only reference). Mock subset: `data/mock/`.
- Team plan, owners P1–P8, interfaces, brief gaps, AWS notes, glossary: `docs/TEAM.md`
- Reusable prompts: `docs/prompts/` (team contract, individual contracts, update contracts, v0 sketch, update status)

## How to run (give users commands WITHOUT trailing `# comments`: their zsh treats `#` as an argument)
```
source .venv/bin/activate
pytest -q
python -m mel.cli run --simulate --clean
python -m mel.cli validate
python -m mel.cli eval
python -m mel.cli parity
streamlit run app/streamlit_app.py
```
Activity attention (off by default): `python -m mel.cli run --simulate --clean --attention`; before/after numbers:
`MEL_DATA_DIR=mel-survey-agent-participant-pack/participant-pack/data python scripts/activity_report.py`.
Full pack: `MEL_DATA_DIR=mel-survey-agent-participant-pack/participant-pack/data python -m mel.cli eval`.
Write output outside the repo, and outside OneDrive on Windows, with `MEL_OUT_DIR=...`.
`run` also writes `run_summary.json` and `junk_report.csv` into the output folder (described in `docs/TEAM.md`).

## Status (mock data)
- On `main` (4 Nov): PRs #1–#2 (P5), #3 (P2), #4 `p5-eval-v2`, #5 `p5-judge`, plus P1 (`lucas-p1`) and P4
  (`kedar-p4`), P3 (`Semdon-P3`), P2 send time (#6, #7). Open: P5 `p5-full-data` (pushed, PR to open);
  P4 `kedar-p4` one-line fix for their hosted demo; **P1 `lucas-p1`** (5 Nov; merged origin/main in, pushed, PR to
  open) — weekly cap in `mel.cli run`, REST API + Docker + infra/, Apache-2.0, Py 3.12, CODEOWNERS, DG questions.
- **801 tests pass on `lucas-p1`** (Py 3.12 VM, ~2.5 min); 462 on `main`. `validate`: 0 invalid files. Mock: 57
  insights → 16 surveys, 41 no-survey. CI (`.github/workflows/ci.yml`, Python 3.12) runs pytest, `run --simulate`,
  `validate`, `eval`, `parity`, and now builds the API image + smoke-tests `/healthz` on every PR.
- Golden eval, full pack (150 rows), two send-time rules (P2's `MEL_TIMING_BASIS`):
  brief (default) decision 99.3%, rule 99.3%, channel 100%, window match 0%, 1 miss (G-0145);
  answer_key 100% / 100% / 100% / 100%, 0 misses. Item similarity **0.99** (P4's templates copy the answer
  key's wording on purpose, `templates.STYLE='golden'`, so this is an in-sample match, not independent proof).
- Batch scorecard on all 6,999 insights (`mel/evaluation/scorecard.py`): brief → 2,616 surveys, format 100%,
  safety 100%, **timeliness 100%**, 0 failing-but-scheduled, relevance 0.69 (P4's stricter v2 score; was 0.83
  under v1), ~3.1 ms/survey (~8 s total). Under answer_key, timeliness is **26.5%** (key windows open before
  the farmer's action window ends): the case for brief. Only 19 of 94 answer-key windows are themselves timely.
- Run history `docs/results/eval_history.jsonl`: 1 baseline (96.0%), 2 R7 storage fix (99.3%), 3 answer-key
  setting, 4–5 P4 templates (item sim 0.50 → 0.99) under each rule. "Rules we changed" compares each run with
  the last run under the same send-time rule. `python scripts/readme_numbers.py --write [--record "label"]
  [--basis ...]` (logic in `mel/evaluation/report.py`) regenerates README block + `docs/results/scorecard.md`.
- AI relevance judge `mel/evaluation/judge.py` (Bedrock Converse, off unless `MEL_JUDGE=1`, cached, logs
  tokens/cost/time; rubric v1 in README). **Ran on Bedrock 4 Nov** (Claude Haiku 4.5, inference profile
  `us.anthropic.claude-haiku-4-5-20251001-v1:0`, us-east-1; plain `anthropic.` id fails "on-demand throughput").
  Hand scores: 5 people x 20 surveys = 100 rows in `docs/results/hand_scores.csv`. Calibration (judge scores the
  sheet's exact question text via `survey_from_text`): AI vs person within 1 point 95%, gap 0.63, r=0.58 with the
  team average; person vs person 83%, 0.82, r 0.00-0.49; "always 5" 79%, 0.79. AI used only 4/5 and is a bit
  lenient. Write-up: `docs/results/judge_calibration.md` (PR `p5-hand-scores`). `--run` on all 94 rows: AI relevance
  **4.82/5** (78x5, 15x4, 1x3; lost points = generic 2nd question), 65 s, ~44k tokens. Both commands now also write `docs/results/judge_summary.json`
  (committed; incl. `rank_r`); the app's Evaluation tab shows "Can we trust the AI judge?" from it, never calling
  Bedrock. Next: switch to P4's `ModelClient`. Bedrock from a laptop needs the event's temporary AWS keys pasted into
  the terminal (never chat/git) and `AWS_DEFAULT_REGION=us-east-1`.
- Channel renders match every reference file in `data/mock/scenarios/*/render` exactly (test enforces it).
- Streamlit app loads the full pack (6,999) by default, mock sample only if the pack is missing or
  `MEL_DATA_DIR` is set; first load ~25 s, clicks ~0.1 s. UI/UX redesign (branch `willF-uiux`, 4 Nov, not yet
  merged): a compact masthead, then 3 tabs. **Dashboard** (default; below). **Survey demo**: a toolbar with the Demo picks list (four
  demo picks: High goat, Medium lentil, Low stored mustard, no-survey critical cow, then Browse with filters) and
  the primary **Add your own insight** button (own-insight mode replaces the picker with a "Source: Your insight" label and
  shows the **Edit insight / Hide editor** toggle and **Back to the demos**; **Your insight** returns from demo mode;
  the editor draft, result and last demo pick survive hiding and switches), a
  report title line ("Your insight" / "Demo insight"), a settings bar (channel; language with **English default**, Hindi one tap away; an icon-only
  **Restart** that resets the phone only; pretend history), then the green insight card | the interactive
  channel preview (`app/channel_preview.py`, one 378x700 phone for all channels, restart/show_restart API) |
  the scheduler hand-off, survey checks and the answer record; JSON in collapsed developer details. History
  rules H1-H5 are always on in the app (the old toggle is gone; H5 = low severity turned high, demo pick I-001996). **Your own insight** (`app/custom_context.py`): the editor (farmer's question, advice, Details for crop/problem/severity/advice
  type/timing/channel/language/district) runs once through `run_insight` on submit and then collapses; ids `I-9000NN`, real IST
  `created_at`, session only, never in the batch or the numbers; empty advice = "No advice given yet." and R4;
  tests in `tests/test_custom_context.py`. **Dashboard**: P3's weekly-limit decisions (full data:
  1,614 sent, 452 moved, 442 merged, 108 skipped), then the send-time rule toggle, five-dimension scorecard,
  brief-vs-answer-key comparison, rules-we-changed table and run-history chart; its metrics count up and the rule
  bars grow in on first view (`COUNT_UP_JS`, ported from the Success Metrics site; none under reduced motion).
  **Follow-up queue**: reason and channel filters with counts, a pick-one list (oldest answer first) and the open
  ticket beside it: next step, conversation log (insight summaries, then the survey Q&A), record JSON.
  The Simulate answers tab, the static all-questions panel and the data caption are gone. Theme: `app/theme.py`
  + `.streamlit/config.toml` (Mukta, ivory/green/marigold, see `docs/uiux-design.md`). Dates and times on screen are
  Eastern Time, MM/DD/YYYY, 12-hour via `app/display_time.py`; stored timestamps and JSON stay ISO/IST.
  Voice channel: the speaker beside Restart (tap = read the call aloud / mute, chevron = volume) plays the IVR lines through ElevenLabs (`app/tts.py`, needs `ELEVENLABS_API_KEY`
  in `.env`; see `.env.example`); off and silent without a key.
  **Restart Streamlit after every `git pull` / stash pop / branch switch** (old `mel/` stays loaded otherwise).
- **One demo, named "Fasal Pulse - MEL Survey Agent"** (decided 4 Nov). P4's standalone demo
  (`demo/p4_standalone/`, hosted at https://fasal-pulse.streamlit.app/) is folded into the team app: Survey demo
  shows "What the agent remembers", a "pretend survey history" demo and generic vs
  adapted questions, and the integrated interactive channel preview (`app/channel_preview.py`; real taps on all 5
  channels: finish, close, opt out, free text, hang up; answer record built by P3's simulator from the actual taps); Overview has "How it fits
  FarmerChat". P3's `simulate_sheet` gained an optional `answers=` (real taps; P3 to review). The app/web
  sheet has a Skip button (P3's `simulate_sheet` keeps the answers around a skipped step); opt-out is STOP, /stop or 9. History rules H1–H5 now live in
  `mel/writer/history.py` (P4 owns; P5 moved them, P4 reviews): `run_pipeline(..., history=True)`,
  `run_insight(..., memory=)`, `compose_survey(..., memory=)`. Default: **on in the app, off for scoring and the
  CLI**. On full data they change 1,343 of 2,616 surveys (H1 964, H4 458; H2/H3 need earlier answers). Runs 6–7
  score history on: item sim 0.99 → 0.93, P4 relevance 0.69 → 0.73, format/safety/timeliness still 100%.
  Tests: `tests/test_history.py`. Our app can be hosted next to P4's on Streamlit Cloud as a backup link.

- **Activity attention (4 Nov, new):** focuses survey attention on positive *change* in a farmer's activity, at
  the beneficiary's representative's request (named in the demo per the "show deliberate changes with numbers"
  rule). New P1 module `mel/data/activity.py` labels each insight `surge` / `steady_high` / `neutral` from the
  farmer's own history (distinct conversations, no leakage, junk-excluded, Poisson jump test vs a per-farmer
  baseline — not a plain "doubled" ratio). The tier rides on `Decision.attention` (schemas forbid extra fields,
  so it goes on the Decision like `send_time`) and adjusts priority (P3), question count (P4) and send time
  (P2) only — never the survey/no-survey decision, the rule or the window. **Off by default** in scoring and
  the CLI (`run --attention` turns it on), **on in the app** (matching the H1–H4 decision). Turning attention off
  adds nothing to a run: at the same revision, `run` with and without `--attention` differ only where attention
  re-prioritises / re-times (the summary's `by_tier`/`by_reason` appear only when on). Note the CLI output baseline
  itself changed on `lucas-p1` when `mel.cli run` started applying the weekly cap through `run_batch` (fewer
  hand-off/survey/response files; see "Weekly limit" below), so "today's output" is the post-cap output, not the
  pre-cap checkout. Full pack with attention on: surge 130, steady_high
  173, neutral 2313 (502 insufficient_history); golden decision/rule/channel and scorecard
  format/safety/timeliness unchanged (99.3% / 99.3% / 100% and 100/100/100), but golden **item similarity dips
  0.991 → 0.977** with attention on, because steady_high surveys trim to 2 questions so one expected golden item
  loses its match (scored with each golden row's real history from the full pack). The app runs history + attention
  together: avg questions/survey heavy 2.56, regular 2.69, light 2.09. Settings in
  `config/activity_attention.json` (outside the parity-checked folders, so `parity` still passes). Report:
  `docs/results/activity_attention.{md,json}` + Evaluation tab. Tests: `tests/test_activity.py` (23). Spec:
  `.kiro/specs/activity-attention/`; cross-owner changes (P2/P3/P4/P5) agreed, written in
  `docs/activity_attention_request.md`. **Uncommitted** on `lucas-p1` pending review.

## Team (5 people since 3 Nov; signed "Team Contracts" doc is the source of truth)
P1 Data & Integration · P2 Decision & Timing · P3 Scheduler, Channels & Simulator · P4 Survey Writing & Safety ·
P5 Evaluation & Demo. Old 8-person numbers (P6–P8) no longer exist; map old P2+P3→P2, P4+P7→P3, P5+P6→P4, P8→P5.
Owners/files: `docs/TEAM.md`, `.github/CODEOWNERS` (usernames still `@p1..@p5` placeholders).
Function-name choices pending for H+4: `docs/h4_interface_decisions.md` (recommendation: keep code names, add
`run_pipeline`, `CapLedger.admit`, `simulate_handoff`, `item_similarity`).

## Open items (owner)
- P2: merged (PR #3): R7 storage exception, answer-key timing behind `MEL_TIMING_BASIS`, crop fallback;
  see `mel/timing/README.md`. 5 Nov (`willF-p2-open-items`): `now=` on `send_window()` / `decide()` reads P3's
  simulated clock (window never opens before it; R6 `window_passed` when < 2 days left; `now=None` = unchanged).
  Nobody passes `now` yet: P1's `run_insight` / P3's scheduler can pass `sched.clock.now()`. `MEL_CRITICAL_POLICY`
  = `human_call` (default, answer key, R2) or `survey` (brief). G-0145 (kept R6 under the brief), G-0129/G-0136
  (no change) and R2 are decided in `mel/timing/README.md` "Open cases, decided". Suggestion from P5 (not yet sent): open at 09:00 within the
  brief rule (+14 exact matches, still 100% timely), or "answer-key window when timely, else brief"
  (window match ~20%, timeliness ~99%).
- P2: send time added 11-04 (`mel/timing/send_time.py`, `Decision.send_time`, rules in `mel/timing/README.md`).
  Wired: `run_pipeline(..., farmers=)` passes profile + chat history; CLI and app simulate at `send_at`; app
  hand-off strip shows it. Hand-off JSON unchanged (organisers' schema forbids extra fields; `parity` checks it).
- P3: merged into main 4 Nov (`Semdon-P3`): `CapLedger.admit` (sent/moved/merged/skipped/opted_out),
  `simulate_handoff`, personas, `late` flag (off until P1 adds it to the response schema). Not started: SimClock,
  `broadcast_due`, self_eval gate in the scheduler, 183-record match; batch wiring request to P1; a persona that
  sometimes reports failure (so the follow-up queue can use real P3 outcomes).
- P4: (4 Nov) relevance threshold agreed at 0.3 with P5; plan templates changed by P5 on `p5-season-speed` (review).
  DONE: concern templates (top-10 x 5 types), Hindi gender, guards + schema check, relevance v2, Bedrock `ModelClient` (retries, cache, per-call token/cost/time log, template fallback, small-model check incl. contradiction), `compose_survey(decision, insight, lang)` with hi-IN/en-IN (English = baseline), self_eval on every survey, `scripts/p4_compare.py` (see `docs/p4/P4_PLAN.md`).
  TODO: native Hindi review (`docs/p4/hindi_review_sheet.csv`), run the Bedrock path and the comparison against real Bedrock (only tested with a fake client so far), `boto3` in requirements (P1), agree relevance threshold with P5/P3, history-aware questions.
- **Judge model sweep (P5, 4 Nov, `p5-season-speed`):** `python -m mel.evaluation.judge_models --list | --run [--only x,y]
  [--full]` finds every active text model in the region (on-demand id, else a us./global. inference profile), has each
  judge the 20 hand-scored surveys, ranks by r with the team then gap; writes `docs/results/judge_models.json`
  (committed) for the Dashboard's "Which model makes the best judge?". **Cost counts:** `--prices` fetches token prices
  (AWS Price List API, best effort) into `docs/results/bedrock_prices.json` for a person to check; cost per survey =
  price x tokens the model really used (from the judge's saved answers, so re-runs price the same). Pick = "best value":
  the cheapest priced model within 0.10 r and 0.15 gap of the most accurate. **Ran 5 Nov: 88 listed, 70 ranked; pick =
  Gemma 3 12B** (`google.gemma-3-12b-it`, on-demand): r 0.72, within 1 pt 97%, gap 0.54, ~$0.05 per 1,000 surveys;
  now the main judge (judge_summary.json; 94-row relevance 4.48). `ModelClient.converse` accepts `system=None` and
  `temperature=None` (newer models refuse them; P4 to review).
- **P4 comparison + AI judge (P5, 5 Nov; P4 to review):** `mel.writer.compare.compare(..., judge=)` adds a
  `judge_relevance` column (1-5, the AI judge, over surveys that passed the guards; warns if a writer is also the
  judge). `scripts/p4_compare.py`: `MEL_JUDGE=1 MEL_JUDGE_MODEL=...` turns it on; samples 50 from the full pack.
- **Templates vs Bedrock, run 5 Nov (P5 ran it for P4):** `docs/results/bedrock_writer_comparison.md`. 50 surveys:
  templates 100% pass / judge 4.50 / 28-char questions / $0; Sonnet 4.6 100% / 4.90 / 114 chars / $6.85 per 1,000;
  Haiku 4.5 92% / 4.89 / 69 chars / $2.01. Judge may reward long questions that restate the advice; blind sheet
  `docs/results/hand_scores_bedrock.csv` (15 rows, key in `hand_scores_bedrock_key.json`) is unscored. P4's sample
  has no wait-and-watch or expert surveys. `llm.prices()` now falls back to `bedrock_prices.json`.
- **Send bar 0.3 + plan questions (4 Nov, P4 + P5 agreed; P4 to review the code):** `mel.writer.RELEVANCE_THRESHOLD = 0.3`
  (app Season tab reads it). Plan surveys (both styles) ask the plan's first step + "Is the plan working for your
  {crop} so far?" (new Hindi rows appended to the review sheet); fallback = answer-key wording. Full data: P4
  relevance 0.72 -> 0.82, 0 surveys below 0.3 (was 80), season 2,050 sends / 0 blocked (after P3 #24). README/scorecard
  regenerated: runs 8-9 (P4 relevance 0.69 -> 0.81). Write-up: `docs/results/judge_calibration.md`.
- **Agent on AgentCore (P5, 5 Nov, `p5-agent-orchestrator`), the AWS associate's design:** `mel/agent/` = Evidence
  Extractor -> Analyst -> Verifier -> Synthesizer with bounded revision (max 2, then template), streaming JSON events.
  Verifier: P4 guards, relevance >= 0.3, prompts <= 120 chars, P4 small-model check, Bedrock Guardrails
  (`MEL_GUARDRAIL_ID`), judge score. `llm_items(feedback=, previous=)` added (P4 to review). AgentCore wrapper
  `agentcore_app.py` (+ `mel/agent/aws.py` S3 results / CloudWatch metrics, `mel/agent/remote.py` invoke stream),
  `requirements-agentcore.txt`, `.dockerignore`; deploy steps `docs/agentcore.md` (not yet deployed). App: Survey demo
  expander "How the agent wrote this survey" (recorded run from `docs/results/agent_runs/` or live; AgentCore when
  `MEL_AGENTCORE_ARN`). CLI `python -m mel.agent [--record] [--remote ARN] ids`. Without Bedrock it matches the
  pipeline exactly (test).
- **Cost tracking + full run (P5, 5 Nov, `p5-agent-orchestrator`):** `mel/evaluation/costs.py` (CostMeter reads
  `out/bedrock_calls.jsonl` from its start offset; ledger `docs/results/cost_history.jsonl`; projection x 2,616 surveys).
  `python -m mel.agent.batch [--sample N | --limit N] [--workers 8] [--max-usd 40] [--judge]`: thread pool, budget cap,
  free resume via cache, files to `out/agent_batch/`, summary `docs/results/full_bedrock_run.json`. Dashboard "What it
  costs". Decided: Haiku 4.5, hi+en, history off, cap $40. **Pilot and full run not yet run** (need AWS keys).
- **IaC + demo-day plan (P5, 5 Nov, `p5-agent-orchestrator`):** `infra/fasal-pulse.yaml` (CloudFormation; rules restrict to us-east-1/us-west-2): private SSE S3 bucket (HTTPS only, results expire 30 d), least-privilege AgentCore execution role, Bedrock Guardrail + version (deny personal-info requests, PII + content filters, no violence filter; v1 also denied "new agronomic advice" but it blocked "Did you follow the advice?", so v2 drops it), CloudWatch dashboard (SEARCH over `FasalPulse/Agent`), optional budget. Outputs incl. ready `--env` flags for `agentcore launch`. cfn-lint clean; `tests/test_infra.py`. Steps in `docs/agentcore.md`. Hackathon rules check, stack and order of work: `docs/demo_day_plan.md`. Repo is public but has **no LICENSE** (team to pick MIT-0 or Apache-2.0). No AWS CLI on Michael's laptop: deploy via console upload or CloudShell. **Stack deployed 5 Nov in us-west-2** (team chose Oregon; all AgentCore/Bedrock settings now use `MEL_BEDROCK_REGION=us-west-2`); guardrail `dh15hs1wc6uw` (use v2 after the stack update). Batch runner now test-calls the guardrail before spending (and stops if it blocks a harmless question). Pilot 1 (40 surveys, us-west-2, guardrail v2): $0.22, projected full $15.41, judge 4.87, but hi-IN fell back to templates 15/40: 43 of 44 Hindi rejections were "less relevant than the template" (P4 keyword lists are the templates' own words). Fix: that comparison is now English-only (`mel/agent/orchestrator.py verify`); Hindi keeps the 0.3 send bar. P4 to review. Pilot 2: hi-IN bedrock 39/40, judge 4.90. Cost per survey now = full price of every distinct request in the run (cache hits priced from the tokens they took; `list_cost_usd` + `key` in out/bedrock_calls.jsonl, `full_price_usd` + `projection_basis` in ledger rows), so a cached re-run projects like a fresh one; pilot 2 replay: $0.0039/survey, ~$10.3 full (+ judge ~$0.25; guardrail ApplyGuardrail charges are not in the ledger). Mis-priced pilot 2 ledger row removed.
- **REMINDER for P5 (deferred 5 Nov):** score the blind Bedrock sheet `docs/results/hand_scores_bedrock.csv` before
  claiming model-written surveys beat templates (judge 4.9 vs 4.5 may just reward longer questions).
- P5 (4 Nov, `p5-season-speed`): season walk 2-5x faster (quality-check results cached on survey content in
  `mel/schedule/broadcast.py`, P3 to review): to end of March 10 -> 5 s responsive, 38 -> 8 s never-answers, same
  counts. Judge's `BedrockClient` now wraps P4's `ModelClient` (purpose "judge" in out/bedrock_calls.jsonl);
  `ModelClient.last_usage` added (P4 to review).
- P5 (4 Nov, `p5-season`): **Season tab** (third tab) drives P3's `SeasonScheduler` (shared SimClock, +1 day /
  +1 week / to end of March, "Send next step" manual trigger, persona picker, relevance-bar slider at provisional
  now 0.3; personas incl. P3's `sometimes_fails` (523 answers need a person); full data ~2,050 sends, ~5 s). Shows India
  time first (Eastern alongside). Test: `tests/test_season_tab.py`. Demo script Part 2b (optional).
- P5 (4 Nov, `p5-merge-all`): merged Semdon-P3, kedar-p4, lucas-p1 and the auto-reload fix onto Will's
  redesign; `boto3` added to requirements; demo script speed now "under 4 ms, ~10 s". Ask the team: app shows
  Eastern Time (Will's `display_time.py`) while farmers/DG use IST. P3 broadcaster still ignores `not_after`.
- P5: plan + checklist status `docs/p5_plan.md`; demo script `docs/demo_script.md`; slide text
  `docs/slides_draft.md`. Next: open the `p5-full-data` PR; post Scorecard fields + 3-part storyline in chat;
  send the hand-scoring sheet; decide with P4 on one demo / one name / H1–H4; host our app next to P4's as a
  backup link; judge calibrated on Bedrock (done 4 Nov); judge now uses P4's `ModelClient`;
  window-overlap measure; real deck; two clean-checkout rehearsals; backup video.
  Follow-up queue still forces each survey's trouble answer: P3's personas never report failure and `late` is
  not in the response schema, so P3's outcomes would give an empty queue.
- P1 (5 Nov, `lucas-p1`, pushed; not yet merged to main): **DONE** — P3's batch-wiring request: `mel.cli run`
  now applies the weekly cap + opt-outs + P4 quality gate via `run_batch` (threshold `mel.writer.RELEVANCE_THRESHOLD`
  = 0.3), writes `schedule` into `run_summary.json`; full pack 2,616 planned → 2,038 out (1,613 sent, 425 moved,
  480 merged, 98 skipped, 0 rejected, **0 cap_violations**), R1–R8 / no_survey / eval unchanged; hand-off, survey
  and response file counts drop (explain in the PR). **REST API** `mel/api` (`POST /surveys`, `GET /surveys/due`,
  `/healthz`; FastAPI; one in-memory `SeasonScheduler` per process, state lost on restart; `tests/test_api.py`).
  **Dockerfile** + `.dockerignore` (built, run, three endpoints exercised, HEALTHCHECK healthy). **`infra/`**
  (CFN: ECR + App Runner + Bedrock-only instance role; k8s Deployment/Service replicas 1; README; definition only,
  cfn-lint + kubeconform clean). **LICENSE** (Apache-2.0) + **NOTICE** (excludes the pack / pack-derived data).
  **Python 3.12** across README/pyproject/steering/TEAM. **CODEOWNERS** real usernames (P3 temp = @WestphalianFresco
  until Semdon's username). **CI** builds the image + smoke-tests `/healthz`. `requirements.txt` changed
  (`-r requirements-api.txt` + httpx) — post in chat. Still open: call `mel.evaluation.run_eval()` from `cmd_eval`
  (history on every eval); `late` in the response schema (P3 request, decision pending, see
  `docs/h4_schema_change_request_late.md`); open the PR to main; create the freeze tag (`docs/release_checklist.md`).
- Questions owed to Digital Green (P1 sends them): `docs/questions_for_digital_green.md` is **rewritten and ready
  to send** — the 3 originals refreshed (99.3% at commit 343742f), the 2 missing ones added (MEL rubric; survey
  JSON vs agent-to-UI format), plus Bedrock models/region, late answers, reachability, licence and an AWS-design
  section. P1 still has to actually send it; whether an earlier version was sent is unknown.
- FINAL contract (4 Nov) also adds: REST API + Dockerfile + infra/ + LICENSE + public repo (P1); SimClock +
  broadcaster stub + self_eval gate (P3); Bedrock `ModelClient`, BCP 47 `lang`, self_eval (P4). Its P2 section
  still describes the R7 misses backwards (we said no-survey, key said survey); tell P2.

## Decisions already made (don't re-litigate)
- Streamlit stays the real UI. `v0-sketch/` (git-ignored) is a design reference only.
- Bedrock is **required** for every model call (FINAL contract, 4 Nov), via the account's IAM role, no key.
  Everything else on AWS is after core targets; App Runner optional; EventBridge/RDS/Connect are slide-only.
- Rules follow the brief as the baseline; deliberate changes must be shown with numbers in the demo.

## How the user likes to work
- Plain English; most teammates are new to this and to AWS. Explain technical terms the first time.
- Prompts and team-facing docs go in `docs/prompts/` or `docs/`, and get listed in `docs/prompts/README.md`.
- Commit/push only when asked. Never commit `.env`, keys, `.venv/`, `out/`, `v0-sketch/`.

## Environment notes
- macOS, zsh, Python 3.14 in `.venv`. No `gh` CLI. The full pack is committed in the repo (see the pack location above).
- P1 works on an **Amazon Linux 2023 VM** (Linux, bash, Python 3.12 in `.venv`, Docker available). The project
  requires Python 3.12 (`pyproject.toml`, CI). On the AL2023 VM, `python3.12 -m venv .venv` creates the venv; the
  Windows form is `py -3.12 -m venv .venv` (not testable from the VM).

## Blockers for teammates (from P3, 2026-11-04)
Checked against `Semdon-P3` and `origin/main` (9239abe) on 4 Nov; none of these is fixed on either. Each is the
owner's call; P3 has not edited their files. The "P3:" line under Open items above is out of date: SimClock,
`broadcast_due`, the self_eval gate and the 183-record match are done on `Semdon-P3` (see `docs/p3_README.md`).

**P1 (Data, Contracts & Integration)**
- **`mel.cli run` ignores the weekly limit and opt-outs.** `cmd_run` writes and simulates every hand-off.
  On the full pack that is 2,616 hand-offs; with the limit applied it would be 1,614 sent, 452 moved, 442 merged,
  108 skipped, so 1,002 go out against the 1-per-7-days rule. The app already applies it; the CLI does not.
  Fix: call `mel.schedule.run_batch(handoffs, relevance_threshold=..., simulate=...)` from `cmd_run` and write its
  `counts` into `run_summary.json` (`docs/p3_batch_wiring_request.md`). Rule counts R1-R8 do not change; the number
  of hand-off and response files does, so explain it in the PR (`docs/TEAM.md` asks for that).
- **No `late` field in `config/schemas/response.schema.json`.** Answers after expiry cannot be marked late in a
  valid record. Adding it breaks `mel.cli parity`, because `config/schemas/` must match the organisers' pack, so
  it needs a decision: Digital Green ships the field, or P1 documents a parity exception
  (`docs/h4_schema_change_request_late.md`). P3 then turns on `MEL_RESPONSE_LATE_FIELD` (one line).
- **`farmers.csv` has no channel-reachability data** (only `preferred_channel`). P3's `FarmerReachability`
  treats every channel as reachable, so it skips nothing on real data. Ask: add a `reachable_channels` column
  (pipe-separated, like `crops`), or confirm the all-reachable fallback is fine.
- `.github/CODEOWNERS` still uses `@p1`..`@p5`, so GitHub requests no reviewer on PRs.
- `boto3` is still missing from `requirements.txt` (needed by P4's Bedrock client and P5's judge).
- OK needed (P1 + P5): a short weekly-limit policy section in `README.md`, and a thin
  `scripts/compare_outcomes.py` that calls `mel.simulator.reference_check` (both folders are yours).
- Unknown whether the questions to Digital Green were sent (`docs/questions_for_digital_green.md`).

**P2 (Decision & Timing)**
- Done 5 Nov (`willF-p2-open-items`): `send_window(insight, now=)` / `decide(insight, now=)` read P3's clock;
  G-0145, G-0129 and R2 decided (see Open items above).

**P4 (Survey Writing & Safety)**
- **No relevance threshold is published** (nothing in `mel/writer/` or `config/`). P3's gate needs it and must not
  invent one; tests and the demo use 0.5 as a stand-in. Ask: one named value P3 can import, agreed with P5.
- Heads-up, not a blocker: `self_eval` only reflects 3 of your guards (schema, advice, personal info). P3's gate
  now also calls your `check_survey()` and rejects any failure (0 of 2,616 full-pack surveys affected).

**P5 (Evaluation & Demo)**
- The Season screen is not built (no `SeasonScheduler` in `app/`). API and a sketch: `docs/p3_season_screen_api.md`.
- Heads-up on P3 changes that touch your numbers (on `Semdon-P3`, not yet in `main`):
  `Broadcaster.counts()["expired"]` now also counts hand-offs dropped because their send window closed (nothing
  is sent between `not_after` and `expires_at`); a retry on the same channel gets its own record and a
  `response_key` ending `-a2`; fallback waits each channel's `wait_hours` (6/24/48 h); the `never_answers`
  persona reports `push_not_opened` on app. New P5 counts: `run_batch(...).counts`, `SeasonScheduler.metrics()`,
  `Broadcaster.counts()`.

**Before P3's next PR:** `Semdon-P3` is 9 commits behind `main`; merge `origin/main` first and rerun
`pytest -q`, `run --simulate`, `validate`, `parity`.

## To-do for teammates from P3 (2026-11-05)
Replaces the 4 Nov list above where they differ. P3's code for each item is done on `Semdon-P3`;
each step below is in the owner's own files. Numbers are from the full pack (6,999 insights).

**P1 (Data, Contracts & Integration)**
1. **Run the batch through P3's scheduler.** In `mel/cli.py` `cmd_run`, replace the loop over
   `result.outputs` with the patch in `docs/p3_batch_wiring_request.md` (calls
   `mel.schedule.run_batch`, writes only `batch.handoffs_to_send`, `batch.responses`, and the
   surveys of hand-offs that go out). Add `"schedule": batch.counts` to `run_summary.json`.
   Expected on the full pack at threshold 0.5: 1,372 sent, 316 moved, 324 merged, 52 skipped,
   552 rejected, `cap_violations` 0. P3 tested the patch on a scratch copy: `validate` 0 invalid.
   Say in the PR that hand-off/survey/response file counts drop (R1-R8 counts do not change).
2. **Decide how late answers are recorded** (`docs/h4_schema_change_request_late.md`):
   - Option A: add `"late": {"type": "boolean"}` to `properties` (not `required`) in
     `config/schemas/response.schema.json`, and either get Digital Green to add it to the pack or
     add a one-property exception to `check_all_parity`. Then tell P3 to turn on
     `MEL_RESPONSE_LATE_FIELD`.
   - Option B: no schema change; write a late count into `run_summary.json` using
     `mel.simulator.is_late(record, handoff["expires_at"])`.
   Write the choice into `docs/h4_interface_decisions.md` so it is on record.
3. **Ask Digital Green** (add to `docs/questions_for_digital_green.md`): a chat tap after expiry
   is dropped in the pack (`survey_closed`, answers `{}`), but the brief says late answers are
   kept. Which wins for WhatsApp/Telegram?
4. **Channel reachability:** add a `reachable_channels` column to `data/mock/farmers.csv`
   (pipe-separated, like `crops`), or write in `docs/TEAM.md` that "every channel is reachable"
   is the agreed default. Today P3 skips nothing because the data says nothing.
5. **README:** add a short "Weekly limit" section to `README.md` linking `docs/cap_policy.md`
   (P5 co-owns README; agree the wording with them).
6. Still open from before: real usernames in `.github/CODEOWNERS` (still `@p1`..`@p5`, so no
   reviewer is requested), and send the questions in `docs/questions_for_digital_green.md`.

**P4 (Survey Writing & Safety)**
1. **Publish the relevance threshold** as one named value P3 and P5 import, for example
   `RELEVANCE_THRESHOLD` in `mel/writer/guards.py`, agreed with P5. Today P3's gate and the app's
   `SEASON_THRESHOLD` use a stand-in 0.5, which rejects 552 of 2,616 full-pack surveys, so the
   number decides how many surveys go out. Tell P3 when it lands; P3 switches `run_batch`
   callers and tests to it.
2. Nothing to change in `self_eval`: P3's gate now also calls your `check_survey()`.

**P5 (Evaluation & Demo)**
1. **Follow-up queue from real answers:** in `app/streamlit_app.py` `_follow_queue`, instead of
   forcing each survey's first flagged answer, simulate with
   `simulate_handoff(h, "sometimes_fails", seed=0)` and build tickets with
   `mel.simulator.follow_up_tickets(records, surveys)` (same ticket fields you use now:
   response_key, farmer_id, survey_id, channel, recorded_at, reason, item_id, rec; add the
   label and insight lookups you already have). Full pack: 429 advice-failed answers → 429 tickets.
2. **Add the persona to the Season tab:** add `"sometimes_fails": "Sometimes says the advice did
   not work"` to `PERSONA_LABEL`, and count `negative_outcome` as "Needs a person" in
   `STATUS_LABEL`.
3. **Weekly-limit numbers on the Dashboard:** `batch()` replays the cap with plain
   `CapLedger.admit`, which places a moved survey at once (9 moves land inside a high-priority
   survey's week). Use `SeasonScheduler(relevance_threshold=...).admit_all(copies)` or
   `run_batch(...).counts` instead, and show `cap_violations` (should be 0) and `prevented`
   separately. Do not label skipped/merged surveys as violations.
4. The Season tab's "Blocked by quality check" (`broadcaster.counts()["rejected"]`) now includes
   surveys rejected before they are queued; `counts()` also has a new `opted_out` key.

**P2 (Decision & Timing)**: no new asks from P3. The 4 Nov items (P3's clock, G-0145, G-0129, R2) are
done on `willF-p2-open-items` (5 Nov).

**P3 itself:** commit the 5 Nov work on `Semdon-P3`, merge `origin/main` (24 commits ahead),
rerun `pytest -q`, `run --simulate --clean`, `validate`, `parity`, then open the PR. P1's
activity-attention request (`docs/activity_attention_request.md`: `adjust_priority`,
`HighPromotionBudget`) waits until P1's `mel/data/activity.py` is merged.
