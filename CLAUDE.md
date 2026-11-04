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
- Organisers' brief: `participant-pack/index.html` (full pack lives in ~/Downloads, which macOS blocks for Claude;
  the user must move files into the project). Mock subset: `data/mock/`.
- Team plan, owners P1–P8, interfaces, brief gaps, AWS notes, glossary: `docs/TEAM.md`
- Reusable prompts: `docs/prompts/` (team contract, individual contracts, update contracts, v0 sketch)

## How to run (give users commands WITHOUT trailing `# comments`: their zsh treats `#` as an argument)
```
source .venv/bin/activate
pytest -q
python -m mel.cli run --simulate
python -m mel.cli validate
python -m mel.cli eval
streamlit run app/streamlit_app.py
```
Full pack: `MEL_DATA_DIR=<pack>/data python -m mel.cli eval`. Write scratch output with `MEL_OUT_DIR=...`.

## Status (mock data)
- 16 tests pass. `validate`: 0 invalid files. 57 insights → 16 surveys, 41 no-survey.
- Golden eval (35 rows): decision 97.1%, rule 97.1%, channel 100%, **window 0%**.
- Channel renders match every reference file in `data/mock/scenarios/*/render` exactly (test enforces it).
- Streamlit app: Overview, Survey Studio (insight card, bilingual question cards, phone preview, hand-off strip),
  Simulate answers, Evaluation. Theme in `.streamlit/config.toml` (light only). All numbers come from the pipeline.
- Added beyond the scaffold: `OptOutList` (mel/schedule), basic `relevance_score` (mel/writer/guards.py).

## Team (5 people since 3 Nov; signed "Team Contracts" doc is the source of truth)
P1 Data & Integration · P2 Decision & Timing · P3 Scheduler, Channels & Simulator · P4 Survey Writing & Safety ·
P5 Evaluation & Demo. Old 8-person numbers (P6–P8) no longer exist; map old P2+P3→P2, P4+P7→P3, P5+P6→P4, P8→P5.
Owners/files: `docs/TEAM.md`, `.github/CODEOWNERS` (usernames still `@p1..@p5` placeholders).
Function-name choices pending for H+4: `docs/h4_interface_decisions.md` (recommendation: keep code names, add
`run_pipeline`, `CapLedger.admit`, `simulate_handoff`, `item_similarity`).

## Open items (owner)
- P2: window accuracy 0%. Golden opens 09:00; brief + scenarios say 07:00 after action window. Plan: brief rule
  default, answer-key rule behind a setting, ask Digital Green. Missing-crop fallback in `mel/timing/calendar.py`.
  One decision miss (G-0131, expected R8, got R7). R1–R8 are inferred from golden, not the brief; confirm R2.
- P3: wire `OptOutList` + `CapLedger` into batch run; two-in-a-week policy (skip/move/merge); late answers;
  app/web sent once; channel fallback; reproduce the 183 reference answer records.
- P4: DONE: concern templates (top-10 x 5 types), Hindi gender, guards + schema check, relevance v2, Bedrock `ModelClient` (retries, cache, per-call token/cost/time log, template fallback, small-model check incl. contradiction), `compose_survey(decision, insight, lang)` with hi-IN/en-IN (English = baseline), self_eval on every survey, `scripts/p4_compare.py` (see `docs/p4/P4_PLAN.md`).
  TODO: native Hindi review (`docs/p4/hindi_review_sheet.csv`), run the Bedrock path and the comparison against real Bedrock (only tested with a fake client so far), `boto3` in requirements (P1), agree relevance threshold with P5/P3, history-aware questions.
- P5: follow-up queue page, per-rule confusion, item similarity, README numbers by script, demo script.
- P1: Excel loader + parity check; `--limit`/`--farmer`; junk-row reasons; CI; real usernames in CODEOWNERS.
- Questions owed to Digital Green: 09:00 vs 07:00; critical → survey or human call; golden set v2 timing.

## Decisions already made (don't re-litigate)
- Streamlit stays the real UI. `v0-sketch/` (git-ignored) is a design reference only.
- AWS is optional polish after core targets: S3, Bedrock, App Runner, Secrets Manager; the rest is slides only.
- Rules follow the brief as the baseline; deliberate changes must be shown with numbers in the demo.

## How the user likes to work
- Plain English; most teammates are new to this and to AWS. Explain technical terms the first time.
- Prompts and team-facing docs go in `docs/prompts/` or `docs/`, and get listed in `docs/prompts/README.md`.
- Commit/push only when asked. Never commit `.env`, keys, `.venv/`, `out/`, `v0-sketch/`.

## Environment notes
- macOS, zsh, Python 3.14 in `.venv`. No `gh` CLI. `~/Downloads` is not readable from Claude's shell.
