# Fasal Pulse - MEL Survey Agent: project status for Claude

Read this first in every new session. Update the **Status** and **Open items** sections whenever work lands
(and the date below), so the next session starts from the truth.

_Last updated: 2026-11-04 (judge calibrated)_

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
Full pack: `MEL_DATA_DIR=mel-survey-agent-participant-pack/participant-pack/data python -m mel.cli eval`.
Write output outside the repo, and outside OneDrive on Windows, with `MEL_OUT_DIR=...`.
`run` also writes `run_summary.json` and `junk_report.csv` into the output folder (described in `docs/TEAM.md`).

## Status (mock data)
- On `main` (4 Nov): PRs #1–#2 (P5), #3 (P2), #4 `p5-eval-v2`, #5 `p5-judge`, plus P1 (`lucas-p1`) and P4
  (`kedar-p4`), P3 (`Semdon-P3`), P2 send time (#6, #7). Open: P5 `p5-full-data` (pushed, PR to open);
  P4 `kedar-p4` one-line fix for their hosted demo.
- 462 tests pass on `main` (~19 s), 463 on `p5-full-data`. `validate`: 0 invalid files. 57 insights → 16 surveys, 41 no-survey (mock).
  CI (`.github/workflows/ci.yml`, Python 3.12) runs pytest, `run --simulate`, `validate`, `eval` on every PR.
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
  **4.82/5** (78x5, 15x4, 1x3; lost points = generic 2nd question), 65 s, ~44k tokens. Next: switch to P4's `ModelClient`. Bedrock from a laptop needs the event's temporary AWS keys pasted into
  the terminal (never chat/git) and `AWS_DEFAULT_REGION=us-east-1`.
- Channel renders match every reference file in `data/mock/scenarios/*/render` exactly (test enforces it).
- Streamlit app (5 tabs) loads the full pack (6,999) by default, mock sample only if the pack is missing or
  `MEL_DATA_DIR` is set; first load ~25 s, clicks ~0.1 s. Overview shows P3's weekly-limit decisions (full data:
  1,614 sent, 452 moved, 442 merged, 108 skipped); Survey Studio has demo picks + filters; Evaluation has the
  send-time rule toggle, five-dimension scorecard, brief-vs-answer-key comparison, rules-we-changed table and
  run-history chart. (Full-data app is on `p5-full-data`; `main` still shows the 57-row sample.)
  **Restart Streamlit after every `git pull` / stash pop / branch switch** (old `mel/` stays loaded otherwise).
- **One demo, named "Fasal Pulse - MEL Survey Agent"** (decided 4 Nov). P4's standalone demo
  (`demo/p4_standalone/`, hosted at https://fasal-pulse.streamlit.app/) is folded into the team app: Survey Studio
  shows "What the agent remembers", a history on/off switch, a "pretend survey history" demo and generic vs
  adapted questions, and "Answer as the farmer" (real tap-through on all 5 channels: finish, close, opt out,
  free text, hang up; answer record built by P3's simulator from the actual taps); Overview has "How it fits
  FarmerChat". P3's `simulate_sheet` gained an optional `answers=` (real taps; P3 to review). Known P3 limit:
  skipping a middle sheet question drops later answers, so the tap-through has no Skip button. History rules H1–H4 now live in
  `mel/writer/history.py` (P4 owns; P5 moved them, P4 reviews): `run_pipeline(..., history=True)`,
  `run_insight(..., memory=)`, `compose_survey(..., memory=)`. Default: **on in the app, off for scoring and the
  CLI**. On full data they change 1,343 of 2,616 surveys (H1 964, H4 458; H2/H3 need earlier answers). Runs 6–7
  score history on: item sim 0.99 → 0.93, P4 relevance 0.69 → 0.73, format/safety/timeliness still 100%.
  Tests: `tests/test_history.py`. Our app can be hosted next to P4's on Streamlit Cloud as a backup link.

## Team (5 people since 3 Nov; signed "Team Contracts" doc is the source of truth)
P1 Data & Integration · P2 Decision & Timing · P3 Scheduler, Channels & Simulator · P4 Survey Writing & Safety ·
P5 Evaluation & Demo. Old 8-person numbers (P6–P8) no longer exist; map old P2+P3→P2, P4+P7→P3, P5+P6→P4, P8→P5.
Owners/files: `docs/TEAM.md`, `.github/CODEOWNERS` (usernames still `@p1..@p5` placeholders).
Function-name choices pending for H+4: `docs/h4_interface_decisions.md` (recommendation: keep code names, add
`run_pipeline`, `CapLedger.admit`, `simulate_handoff`, `item_similarity`).

## Open items (owner)
- P2: merged (PR #3): R7 storage exception, answer-key timing behind `MEL_TIMING_BASIS`, crop fallback;
  see `mel/timing/README.md`. Left: G-0145 (one-day 31 March window), cauliflower G-0129 needs DG, confirm R2;
  `compute_window()` must read P3's simulated clock. Suggestion from P5 (not yet sent): open at 09:00 within the
  brief rule (+14 exact matches, still 100% timely), or "answer-key window when timely, else brief"
  (window match ~20%, timeliness ~99%).
- P2: send time added 11-04 (`mel/timing/send_time.py`, `Decision.send_time`, rules in `mel/timing/README.md`).
  Wired: `run_pipeline(..., farmers=)` passes profile + chat history; CLI and app simulate at `send_at`; app
  hand-off strip shows it. Hand-off JSON unchanged (organisers' schema forbids extra fields; `parity` checks it).
- P3: merged into main 4 Nov (`Semdon-P3`): `CapLedger.admit` (sent/moved/merged/skipped/opted_out),
  `simulate_handoff`, personas, `late` flag (off until P1 adds it to the response schema). Not started: SimClock,
  `broadcast_due`, self_eval gate in the scheduler, 183-record match; batch wiring request to P1; a persona that
  sometimes reports failure (so the follow-up queue can use real P3 outcomes).
- P4: DONE: concern templates (top-10 x 5 types), Hindi gender, guards + schema check, relevance v2, Bedrock `ModelClient` (retries, cache, per-call token/cost/time log, template fallback, small-model check incl. contradiction), `compose_survey(decision, insight, lang)` with hi-IN/en-IN (English = baseline), self_eval on every survey, `scripts/p4_compare.py` (see `docs/p4/P4_PLAN.md`).
  TODO: native Hindi review (`docs/p4/hindi_review_sheet.csv`), run the Bedrock path and the comparison against real Bedrock (only tested with a fake client so far), `boto3` in requirements (P1), agree relevance threshold with P5/P3, history-aware questions.
- P5: plan + checklist status `docs/p5_plan.md`; demo script `docs/demo_script.md`; slide text
  `docs/slides_draft.md`. Next: open the `p5-full-data` PR; post Scorecard fields + 3-part storyline in chat;
  send the hand-scoring sheet; decide with P4 on one demo / one name / H1–H4; host our app next to P4's as a
  backup link; judge calibrated on Bedrock (done 4 Nov); left: switch to P4's `ModelClient`;
  window-overlap measure; real deck; two clean-checkout rehearsals; backup video.
  Follow-up queue still forces each survey's trouble answer: P3's personas never report failure and `late` is
  not in the response schema, so P3's outcomes would give an empty queue.
- P1: merged: batch runner, `run_pipeline()`/`PipelineResult`, `--limit`/`--farmer`, junk report, Excel parity,
  CI. Open: call `mel.evaluation.run_eval()` from `cmd_eval` (history on every eval); REST API + Dockerfile;
  `infra/` + LICENSE + public repo; Bedrock account access (region/models) for P4 and P5; `boto3` in
  requirements; `late` in the response schema (P3 request); P3's batch-wiring request (weekly limit and
  opt-outs are applied in the app but not in `mel.cli run`); real usernames in
  CODEOWNERS (still `@p1..@p5`).
- Questions owed to Digital Green (P1 sends 5): 09:00 vs 07:00; critical → survey or human call; golden set v2;
  MEL relevance rubric?; does our survey JSON match their agent-to-UI format? Plus: which Bedrock models/region.
  `docs/questions_for_digital_green.md` drafts only the first 3; whether they were sent is unknown.
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
