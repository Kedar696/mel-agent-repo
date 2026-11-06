# Fasal Pulse - MEL Survey Agent: project notes for Claude

Read this first in every new session. Update **Status**, **Live stack** and **Open items** whenever work lands (and the
date below), so the next session starts from the truth.

_Last updated: 2026-11-06 (cleanup series after the hackathon: one generator path, one Dockerfile, one config, one
Bedrock client, correctness pass, app split by tab, repo hygiene; Terraform import of the live UI is next)_

## What this is
Built at the AWS "Breaking Barriers" hackathon (3-5 Nov 2026) for Digital Green (MEL = monitoring, evaluation,
learning), now kept by one person (Will, P2 at the event). A Python agent reads FarmerChat "insights" (farmer
conversations), decides survey / no survey (rules R1-R8), writes 1-3 tap questions in hi-IN + en-IN (Bedrock, or
checked templates), builds a scheduler hand-off, renders per channel (app, web, WhatsApp, Telegram, voice) and
simulates answers. Scored against a 150-row golden set. Synthetic data only (the participant pack); real delivery is
out of scope.

- Repo: https://github.com/michvinh-7/mel-agent-repo (branch `main`; Will has write access, no branch protection).
- Organisers' brief and the full pack: `mel-survey-agent-participant-pack/participant-pack/` (read-only reference,
  committed). Mock subset: `data/mock/`. Team-time notes (plan, glossary, AWS notes): `docs/TEAM.md`;
  hackathon process documents: `docs/archive/`.

## How to run (give the user commands WITHOUT trailing `# comments`: zsh treats `#` as an argument)
```
source .venv/bin/activate
pytest -q
python -m mel.cli run --simulate --clean
python -m mel.cli validate
python -m mel.cli eval
python -m mel.cli parity
streamlit run app/streamlit_app.py
```
Full pack: `MEL_DATA_DIR=mel-survey-agent-participant-pack/participant-pack/data python -m mel.cli eval` (and `run`).
Write output outside the repo with `MEL_OUT_DIR=...`. `run` also writes `run_summary.json` and `junk_report.csv`.
Activity attention (off by default): `run ... --attention`. The agent alone: `python -m mel.agent I-001253`
(`--record` saves the demo picks to `docs/results/agent_runs/`, `--remote ARN` runs it on AgentCore).
**Restart Streamlit after every `git pull` / branch switch** (the app reloads `mel/` and `app/` itself, but not always).

## Layout
- `mel/config.py`: paths, constants and **every setting**: `env(name, default)` reads the environment, then the
  repo's `.env` (copy `.env.example`), then the default; `flag()`, `bedrock_region()`, `full_pack()`. Nothing else
  reads `os.environ` for a `MEL_*` name.
- `mel/data/`: loaders, JSON Schema validation, Excel parity with the pack, junk report, activity attention.
- `mel/decision/rules.py` (R1-R8) and `mel/timing/` (send window, send time, crop calendar; `mel/timing/README.md`).
- `mel/writer/`: templates (hi/en), guards (safety and format), relevance score + `RELEVANCE_THRESHOLD` (0.3),
  history rules H1-H5, `llm.py` = the one Bedrock client (`ModelClient`: retries, on-disk cache, committed replay
  file `docs/results/bedrock_cache.jsonl`, per-call log `out/bedrock_calls.jsonl`, prices).
- `mel/agent/`: the agent (Evidence Extractor -> Analyst -> Verifier -> Synthesizer, bounded revision, streaming
  events). `run_agent_to_end` is the one generator the CLI, the API, the evaluation and AgentCore all use
  (`mel/pipeline.run_insight` wraps it). `batch.py` writes many with cost tracking; `aws.py` S3 + CloudWatch;
  `remote.py` invokes the runtime; `payload_options` validates an AgentCore payload.
- `mel/schedule/`: hand-off, priority, weekly cap (`CapLedger`: sent / moved / merged / skipped / opted_out),
  `schedule_in_send_order` + `run_batch` (the one scheduling path: opt-out, quality gate, cap with deferred moves),
  broadcaster, simulated clock, season driver, frequency ranker. `mel/channels/`: renders, reachability.
  `mel/simulator/`: answer records (byte-for-byte the pack's reference grid), personas, hand-off walk.
- `mel/evaluation/`: golden scoring, scorecard, AI judge (`judge.py`), judge model sweep, costs, run history,
  README results block (`scripts/readme_numbers.py --write`).
- `mel/api/app.py`: FastAPI, bearer token `MEL_API_TOKEN`, state in `mel/store.py` (SQLite, `MEL_DATABASE_URL`);
  `uvicorn --factory mel.api.app:create_app`. `agentcore_app.py`: the AgentCore entrypoint.
- `app/`: `streamlit_app.py` is the shell (reload guard, the batch, two tabs); `dashboard.py`; `survey_demo.py`
  (agent terminal, phone = `channel_preview.py` + `preview_state.py`, own insight = `custom_context.py`, voice =
  `tts.py`); `common.py` shared labels and display helpers; `display_time.py`; `theme.py`.
- `infra/terraform/`: the one IaC (`agent.tf` us-west-2: S3, Guardrail, AgentCore role, dashboard, budget; `ui.tf`
  us-east-1: ECR, CodeBuild, ECS roles, cluster, Express Mode service). Steps: `infra/README.md`, `docs/agentcore.md`.
- One multi-stage `Dockerfile` (targets `api` / `ui` / `agent`); `pyproject.toml` extras `api` / `agent` / `ui` / `dev`.
- CI (`.github/workflows/ci.yml`, Python 3.12): `ruff check`, `ruff format --check`, pytest, `run --simulate`,
  `validate`, `eval`, `parity`, both images built and smoke-tested, `terraform fmt -check` + `validate`.

## Settings (all through `mel.config.env`; see `.env.example`)
`MEL_USE_LLM=1` + `MEL_BEDROCK_WRITE_MODEL` (+ optional `MEL_BEDROCK_CHECK_MODEL`) turn the Bedrock writer on;
`MEL_BEDROCK_REGION` (us-west-2 for this account); `MEL_BEDROCK_PRICES` or `docs/results/bedrock_prices.json` price
every call; `MEL_JUDGE_MODEL` + `MEL_JUDGE=1` (evaluation) or `MEL_AGENT_JUDGE=1` (agent) turn the AI judge on;
`MEL_GUARDRAIL_ID` / `MEL_GUARDRAIL_VERSION` add Bedrock Guardrails; `MEL_AGENTCORE_ARN` makes the app's
"Run the agent" call the runtime; `MEL_TIMING_BASIS` brief (default) or answer_key; `MEL_CRITICAL_POLICY`;
`MEL_DATA_DIR`, `MEL_OUT_DIR`, `MEL_CACHE_DIR`, `MEL_LLM_LOG`; `MEL_API_TOKEN`, `MEL_DATABASE_URL`;
`ELEVENLABS_API_KEY` for the voice read-out. AWS credentials come from `~/.aws` or the task role, never from a file here.

## Status (6 Nov, after the cleanup series)
- **874 tests pass** (`pytest -q`, about 3 min). `validate`: 12,535 full-pack output files, 0 invalid.
- Golden, full pack (150 rows): brief decision 99.3%, rule 99.3%, channel 100%, window match 0%, one miss
  (G-0145, kept R6 on purpose: `mel/timing/README.md`); answer_key 100% / 100% / 100% / 100%. Item similarity 0.99
  (templates copy the key's wording, so in-sample).
- Scorecard, all 6,999 insights: 2,616 surveys, format 100%, safety 100%, timeliness 100%, 0 failing-but-scheduled,
  P4 relevance 0.81. Schedule (`run --simulate`): sent 1,613, moved 425, merged 480, skipped 98, rejected 0,
  **cap_violations 0**. The app's Dashboard runs the same gate as the CLI (6 Nov), so its numbers match.
- Bedrock full run (ledger run 5, Haiku 4.5 writer, Gemma 3 12B judge, us-west-2): 2,616 surveys for $2.61
  ($0.00102 per survey, both languages), Bedrock wrote en 97% / hi 96%, 160 template fallbacks, judge 4.93.
  Every pack survey replays for $0 from `docs/results/bedrock_cache.jsonl`. Judge calibration vs 5 people x 20
  surveys: within 1 point 97%, r 0.72 (`docs/results/judge_calibration.md`, `judge_models.json`).
- Cleanup series (6 Nov): #49 one generator path + one Dockerfile + SQLite store (no RDS); #50 one config
  (`mel.config.env`); #51 one bedrock-runtime client; #52 correctness (cap moves clear every prior send, API off
  the event loop, app on the CLI's scheduling path, AgentCore payload checked); #53 app split by tab; then this
  hygiene PR (`ruff format` at 120 columns, process docs to `docs/archive/`, CODEOWNERS gone); next: Terraform
  import of the hand-made UI resources and a relaunch of the runtime from the new `main`.

## Live stack (Will's Workshop Studio sandbox account; temporary credentials from the event page, a few hours each)
- UI: ECS Express Mode service `fasal-pulse-ui`, us-east-1, 1 vCPU / 2 GB, one task:
  https://fa-bb1bdead4fb64190b7a68b8d8eae6ff2.ecs.us-east-1.on.aws/ (image tag = short commit SHA of `main`; roll it with
  `aws codebuild start-build --project-name fasal-pulse-ui-build` then `terraform apply -var image_tag=<sha>` once the
  UI is imported into the state, or `aws ecs update-express-gateway-service` until then; `infra/README.md`).
- Agent: AgentCore runtime `fasal_pulse` (`arn:aws:bedrock-agentcore:us-west-2:<account>:runtime/fasal_pulse-asfyZYEUQm`),
  launched with the AgentCore toolkit (`docs/agentcore.md`; move the repo `Dockerfile` aside first). The UI's task
  has `MEL_AGENTCORE_ARN` set, so "Run the agent" runs live. Guardrail `fasal-pulse-survey-guardrail` and the
  data bucket come from `terraform apply` on `agent.tf` (in the state); the UI resources were made by hand under the
  Terraform names and are not in the state yet.
- Cost: about $2 a day while the UI runs (Fargate + load balancer); Bedrock calls are cents. The account is wiped
  when the event closes: everything is re-creatable from `infra/terraform/` + one `agentcore launch`.

## Decisions already made (don't re-litigate)
- Streamlit stays the UI (split by tab, not replaced). Bedrock is the model path, via the account's IAM role, no key.
- One AWS account, one IaC (`infra/terraform/`), one Bedrock region (us-west-2) for models and agent, one runtime,
  one hosted link. No RDS: the API's state is a SQLite file. EventBridge / Connect / RDS are slide-only.
- Rules follow the brief as the baseline; deliberate changes are shown with numbers (`docs/results/`).
- Everything goes through `mel.agent.run_agent` (generation) and `schedule_in_send_order` / `run_batch` (scheduling);
  no second path for the app, the API or the evaluation.
- Code layout is `ruff format` at 120 columns; lint rules are pyflakes + bugbear (`pyproject.toml`).

## Open items
- Terraform: import the 13 hand-made UI resources (`ui.tf`) so `terraform plan` is clean; relaunch the runtime from
  the new `main`; check whether the AWS provider now has `aws_bedrockagentcore_agent_runtime` (then the runtime moves
  into Terraform too).
- Hindi native review: 0 of 441 lines in `docs/p4/hindi_review_sheet.csv` checked; the app labels Hindi "pending
  review" until every row has a Y/N. Blind sheet `docs/results/blind_sheet.csv` (Bedrock vs templates) is unscored.
- `mel/writer/history.py personalize`: after an H3/H4 trim drops the personalised H1/H2 question, the H1/H2 note (and
  the rationale) still claims it; kept for byte-stable output, worth fixing with the next template change.
- Questions for Digital Green (`docs/questions_for_digital_green.md`) were never sent.

## How the user likes to work
- Plain English; conclusion first. Commit/push only when asked; PRs to `main`, the user merges.
  Never commit `.env`, keys, `.venv/`, `out/`, `v0-sketch/`.
- Regression bar for any change: `pytest -q`, golden 99.3 / 99.3 / 100 unchanged, full-pack schedule counts
  unchanged, `validate` 0 invalid, CI green.

## Environment notes
- macOS, zsh, Python 3.13 in `.venv` (the project requires 3.12+; CI runs 3.12). `gh` is authenticated. Use
  `.venv/bin/python` explicitly: a bare `python` can resolve to the Xcode Python 3.9.
- No Docker or Terraform on this Mac: image builds run in CI / CodeBuild; Terraform runs in CloudShell or CI.
