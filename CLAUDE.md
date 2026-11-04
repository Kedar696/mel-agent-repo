# MEL Survey Agent: project status for Claude

Read this first in every new session. Update the **Status** and **Open items** sections whenever work lands
(and the date below), so the next session starts from the truth.

_Last updated: 2026-11-04_

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
- 71 tests pass. `validate`: 0 invalid files. 57 insights → 16 surveys, 41 no-survey (mock).
- Golden eval, full pack (150 rows), two send-time rules (P2's `MEL_TIMING_BASIS`):
  brief (default) decision 99.3%, rule 99.3%, channel 100%, window match 0%, 1 miss (G-0145);
  answer_key 100% / 100% / 100% / 100%, 0 misses. Item similarity 0.50.
- Batch scorecard on all 6,999 insights (`mel/evaluation/scorecard.py`): brief → 2,616 surveys, format 100%,
  safety 100%, **timeliness 100%**, 0 failing-but-scheduled, ~2.4 ms/survey (~6 s total). Under answer_key,
  timeliness is **26.5%** (1,982 windows open before the farmer's action window ends): the case for brief.
- Run history `docs/results/eval_history.jsonl`: run 1 baseline (96.0%), run 2 R7 storage fix (99.3%),
  run 3 answer-key setting. `python scripts/readme_numbers.py --write [--record "label"] [--basis ...]`
  (logic in `mel/evaluation/report.py`) regenerates the README results block, the generated "Rules we changed"
  table and `docs/results/scorecard.md` (offline backup). Never type numbers.
- Channel renders match every reference file in `data/mock/scenarios/*/render` exactly (test enforces it).
- Streamlit app: Overview, Survey Studio (insight card, bilingual question cards, phone preview, hand-off strip),
  Simulate answers, Follow-up queue, Evaluation (send-time rule toggle, five-dimension scorecard, brief-vs-
  answer-key comparison, rules-we-changed table, run-history chart with dimension picker). Theme in `.streamlit/config.toml` (light only). All numbers come from the pipeline.
- Added beyond the scaffold: `OptOutList` (mel/schedule), basic `relevance_score` (mel/writer/guards.py).

## Team (5 people since 3 Nov; signed "Team Contracts" doc is the source of truth)
P1 Data & Integration · P2 Decision & Timing · P3 Scheduler, Channels & Simulator · P4 Survey Writing & Safety ·
P5 Evaluation & Demo. Old 8-person numbers (P6–P8) no longer exist; map old P2+P3→P2, P4+P7→P3, P5+P6→P4, P8→P5.
Owners/files: `docs/TEAM.md`, `.github/CODEOWNERS` (usernames still `@p1..@p5` placeholders).
Function-name choices pending for H+4: `docs/h4_interface_decisions.md` (recommendation: keep code names, add
`run_pipeline`, `CapLedger.admit`, `simulate_handoff`, `item_similarity`).

## Open items (owner)
- P2: merged (PR #3): R7 storage exception, answer-key timing behind `MEL_TIMING_BASIS`, crop fallback;
  see `mel/timing/README.md`. Left: G-0145 (one-day 31 March window), cauliflower G-0129 needs DG, confirm R2.
  `compute_window()` must read P3's simulated clock (FINAL contract).
- P3: wire `OptOutList` + `CapLedger` into batch run; two-in-a-week policy (skip/move/merge); late answers;
  app/web sent once; channel fallback; reproduce the 183 reference answer records.
- P4: DONE: concern templates (top-10 x 5 types), Hindi gender, guards + schema check, relevance v2, Bedrock `ModelClient` (retries, cache, per-call token/cost/time log, template fallback, small-model check incl. contradiction), `compose_survey(decision, insight, lang)` with hi-IN/en-IN (English = baseline), self_eval on every survey, `scripts/p4_compare.py` (see `docs/p4/P4_PLAN.md`).
  TODO: native Hindi review (`docs/p4/hindi_review_sheet.csv`), run the Bedrock path and the comparison against real Bedrock (only tested with a fake client so far), `boto3` in requirements (P1), agree relevance threshold with P5/P3, history-aware questions.
- P5: plan + status table in `docs/p5_plan.md`. Next: AI judge on Bedrock + 20 hand-scored surveys (needs
  P1's Bedrock access); P1 to call `mel.evaluation.run_eval()` from `cmd_eval`; plug in P3 (outcomes with late,
  cap counts, Season tab with SimClock) and P4 (`self_eval`, templates-vs-Bedrock table); slides, rehearsals, video.
  The `self_eval` gate (never schedule a failing survey) is P4 sets / P3 enforces; P5 only counts.
- P1: Excel loader + parity check; `--limit`/`--farmer`; junk-row reasons; CI; real usernames in CODEOWNERS.
- Questions owed to Digital Green (P1 sends 5): 09:00 vs 07:00; critical → survey or human call; golden set v2;
  MEL relevance rubric?; does our survey JSON match their agent-to-UI format? Plus: which Bedrock models/region.
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
