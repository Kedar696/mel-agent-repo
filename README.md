# Fasal Pulse - MEL Survey Agent

Reads FarmerChat insights → decides survey / no survey → writes 1–3 tap questions (hi-IN + en-IN) →
builds the scheduler hand-off → simulates farmer answers across app, web, WhatsApp, Telegram and voice.
Built for the Digital Green MEL hackathon pack (synthetic data only).

## Quick start
Run these from the repo root. Python 3.12.
```bash
# Windows
py -3.12 -m venv .venv
# macOS / Linux
python3.12 -m venv .venv
```
Activate the virtual environment (pick your OS):
```bash
# Windows (PowerShell or cmd)
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```
```bash
pip install -e ".[dev]"
pytest -q
python -m mel.cli run --simulate --clean   # writes out/{surveys,handoffs,no_survey,responses} + run_summary.json + junk_report.csv
python -m mel.cli validate                 # schema-checks everything in out/ (fails if there is nothing to check)
python -m mel.cli eval                     # golden-set score
python -m mel.cli parity                   # Excel workbooks and JSON/CSV agree, config folders match the pack
streamlit run app/streamlit_app.py         # demo UI
```
The defaults use the small mock subset in `data/mock/`.

## Run on the full pack
The full participant pack is committed at `mel-survey-agent-participant-pack/participant-pack/`.
Point `MEL_DATA_DIR` at its `data` folder and `MEL_OUT_DIR` at a scratch folder **outside the repo**.

> **Keep output out of OneDrive** (and Dropbox, iCloud, Google Drive). Syncing locks and re-uploads thousands of small
> files and can stall or break a long run. Use a plain local folder such as `C:\mel_out` or `/tmp/mel_out`.

Windows (PowerShell):
```powershell
$env:MEL_DATA_DIR = "mel-survey-agent-participant-pack\participant-pack\data"
$env:MEL_OUT_DIR = "C:\mel_out"
python -m mel.cli run --simulate --clean
python -m mel.cli validate
python -m mel.cli eval
```
Windows (cmd):
```bat
set MEL_DATA_DIR=mel-survey-agent-participant-pack\participant-pack\data
set MEL_OUT_DIR=C:\mel_out
python -m mel.cli run --simulate --clean
```
macOS / Linux:
```bash
export MEL_DATA_DIR=mel-survey-agent-participant-pack/participant-pack/data
export MEL_OUT_DIR=/tmp/mel_out
python -m mel.cli run --simulate --clean
python -m mel.cli validate
python -m mel.cli eval
```
| Variable | Meaning | Default |
|---|---|---|
| `MEL_DATA_DIR` | folder with `insights.jsonl`, `golden_set.jsonl`, `farmers.csv`, `crop_calendar_bihar_rabi.csv` | `data/mock` |
| `MEL_OUT_DIR` | where `run` writes (and `validate` reads) | `./out` |

`validate` on the full pack checks about 12,500 files (a few seconds to a few minutes, depending on the machine).

## Weekly limit
The brief caps how often a farmer is surveyed: at most **one non-urgent survey per farmer per 7 days**, across
every channel, and an opted-out farmer gets nothing after that. High-priority (urgent) surveys are exempt but
still count toward the window for later ones.

`python -m mel.cli run` applies this. The pipeline plans a hand-off for each survey; then the weekly cap, the
opt-out list and the survey quality gate decide what actually goes out. A capped survey is **moved** to the next
free date inside its window, **merged** into an earlier survey to the same farmer if it cannot move, or **skipped**
if it can do neither. So on the full pack, `run` writes fewer hand-off, survey and response files than the number
of surveys the pipeline planned, while the R1–R8 decision counts are unchanged. `run_summary.json` records the
breakdown under `schedule` (`sent`, `moved`, `merged`, `skipped`, `opted_out`, `rejected`, and `cap_violations`,
which should be 0).

The full policy, with the exact move/merge/skip rules, is in [docs/cap_policy.md](docs/cap_policy.md).

## REST API
A thin FastAPI front in `mel/api/`. `POST /surveys` runs the same agent as the CLI and AgentCore
(`mel.agent.run_agent`: decide, write with Bedrock or the templates, verify, hand off) and admits the
result with P3's opt-out, quality and weekly-cap rules unchanged. Everything that must outlive a process
(surveys, hand-offs, answers, opt-outs) is in one database, so any number of replicas can run.

| Setting | Meaning | Default |
|---|---|---|
| `MEL_API_TOKEN` | the bearer token every call but `/healthz` must send. The API refuses to start without one. | none |
| `MEL_DATABASE_URL` | `postgresql://user:pass@host:5432/mel` (Amazon RDS for PostgreSQL, Digital Green's database) or `sqlite:///path` | `sqlite:///<MEL_OUT_DIR>/mel.sqlite3` |

```bash
pip install -e ".[api]"
MEL_API_TOKEN=change-me uvicorn --factory mel.api.app:create_app
```
It listens on `http://127.0.0.1:8000`. The interactive API reference is at `http://127.0.0.1:8000/docs`.

| Method & path | What it does |
|---|---|
| `GET /healthz` | liveness check for the container (no token) |
| `POST /surveys` | run one insight. A survey returns `201` and is admitted (opt-outs, the quality gate, then the weekly cap decided from that farmer's stored hand-offs); no survey returns `200`; junk input returns the R1 no-survey result (not an error); a body that is not a JSON object returns `422`. The same insight again returns its first admission and takes no second weekly slot. |
| `GET /surveys/due` | read-only list of the hand-offs a sender should send at an instant, each a full schema-valid `schedule_handoff`. Optional `at` (ISO 8601 with a timezone offset; default: now) and `limit`. |
| `GET /v1/surveys/{flow_id}` | the survey registered under a FarmerChat flow id (`farmerchat_flow.flow_id` on the hand-off). Static registration: the id is derived from the survey id, not requested from FarmerChat yet. |
| `POST /v1/surveys/{flow_id}/responses` | FarmerChat's answer path. One `response` record (checked against `response.schema.json`) in; `201` when new, `200` when the same `response_key` was seen before. A `farmer_opted_out` record puts the farmer on the opt-out list; `needs_follow_up` puts the record in the follow-up queue. |
| `GET /follow-ups` | answer records that need a person, oldest first. Optional `limit`. |

> **Windows PowerShell users:** `curl` is an alias for `Invoke-WebRequest` there, which takes
> different arguments. Type `curl.exe` instead to use the real curl shown below.

Health (no token):
```bash
curl http://127.0.0.1:8000/healthz
```
Submit an insight (here, the first mock insight; swap in your own JSON object):
```bash
curl -X POST http://127.0.0.1:8000/surveys \
  -H "authorization: Bearer $MEL_API_TOKEN" -H 'content-type: application/json' \
  -d "$(head -n 1 data/mock/insights.jsonl)"
```
List what is due at a given instant. A literal `+` in the offset works, as does the percent-encoded `%2B`:
```bash
curl -H "authorization: Bearer $MEL_API_TOKEN" "http://127.0.0.1:8000/surveys/due?at=2027-01-22T09:00:00+05:30"
```
Send an answer back (the flow id is `handoff.farmerchat_flow.flow_id` in the `POST /surveys` reply; the record is
one of the pack's answer records with the survey's ids):
```bash
curl -X POST "http://127.0.0.1:8000/v1/surveys/$FLOW_ID/responses" \
  -H "authorization: Bearer $MEL_API_TOKEN" -H 'content-type: application/json' -d @answer.json
curl -H "authorization: Bearer $MEL_API_TOKEN" http://127.0.0.1:8000/follow-ups
```

## Command reference
| Command | What it does |
|---|---|
| `run [--insights PATH] [--simulate] [--limit N] [--farmer ID] [--clean]` | decide, write, hand off every insight. `--limit` must be 0 or more. `--clean` empties only `surveys/`, `handoffs/`, `no_survey/`, `responses/` first. Also writes `run_summary.json` and `junk_report.csv` (see [docs/TEAM.md](docs/TEAM.md)). |
| `validate [--allow-empty]` | schema-check the output; exits non-zero when it finds no files, unless `--allow-empty` |
| `eval [--golden PATH]` | golden-set scores |
| `junk [--insights PATH] [--limit N] [--farmer ID]` | list input rows that get no survey, and why |
| `parity [--xlsx FILE] [--jsonl FILE] [--pack DIR]` | compare the four workbooks (insights, golden set, farmers, crop calendar) with their JSON/CSV, and `config/rules`, `config/schemas`, `data/mock/scenarios`, `data/mock/outcomes` with the pack. Prints each difference by row id and field (`I-000123 severity`) or file name; exits non-zero on any difference. |

## If a new golden set arrives
1. Save the new file outside the pack (for example `~/new/golden_set.jsonl`); do not overwrite the old one yet.
2. Compare: `python scripts/compare_golden.py mel-survey-agent-participant-pack/participant-pack/data/golden_set.jsonl ~/new/golden_set.jsonl`.
   It lists the golden ids added, removed and changed (and which fields), and the count per rule R1 to R8. It also reads `.xlsx`.
3. Replace `golden_set.jsonl` (and `golden_set.xlsx` if it came too) in the pack's `data/` and `spreadsheets/` folders, then run `python -m mel.cli parity`: the workbook and the JSON must agree.
4. Rebuild the mock subset: `python scripts/make_mock_data.py` (default `--pack` is the committed pack).
5. Re-score: `MEL_DATA_DIR=mel-survey-agent-participant-pack/participant-pack/data python -m mel.cli eval`, and `pytest -q`.
6. Tell P2 which ids changed, tell P5 to refresh the results section, and update the numbers in `docs/TEAM.md`.

## Pipeline
```
insight ─► decision (R1–R8) ─► timing (window, expiry) ─► writer (templates | Claude + guards)
                                                     └─► schedule hand-off (priority, channels, cap, flow ids)
                                                              └─► channels render ─► simulator ─► response records
                                                                                           └─► evaluation / Streamlit
```

## Layout (5-person team)
| Path | What | Owner |
|---|---|---|
| `mel/config.py`, `mel/data/`, `mel/pipeline.py`, `mel/cli.py`, `config/`, `scripts/`, `data/mock/` | paths, loaders, schema checks, glue, CLI, mock data | P1 Data & Integration |
| `mel/decision/`, `mel/timing/` | survey / no-survey rules R1–R8, send window, crop calendar | P2 Decision & Timing |
| `mel/schedule/`, `mel/channels/`, `mel/simulator/` | hand-off, weekly limit, opt-outs, channel messages, simulated answers | P3 Scheduler, Channels & Simulator |
| `mel/writer/` | question templates, Hindi/English, Claude writer, safety guards | P4 Survey Writing & Safety |
| `mel/evaluation/`, `app/` | golden scoring, Streamlit demo | P5 Evaluation & Demo |

The signed Team Contracts document is the source of truth. `docs/TEAM.md` is the short version;
`docs/h4_interface_decisions.md` lists the function names to settle at H+4; `docs/prompts/` holds reusable prompts.

## Results
Digital Green's brief and its answer key disagree on send times (brief: 07:00, after the farmer's action
window; answer key: 09:00, often before it). P2 built both; the brief is the default
(`MEL_TIMING_BASIS=brief`) and the answer-key rule is a setting (`MEL_TIMING_BASIS=answer_key`). Both are
scored below, and we have asked Digital Green which is right (see `mel/timing/README.md`).

<!-- results:start -->
**Answer key** (150 rows), under each send-time rule.

| Measure | Brief rules (default) | Answer-key setting |
|---|---|---|
| Decision (survey or not) | 99.3% | 100.0% |
| Rule (which of R1–R8) | 99.3% | 100.0% |
| First channel | 100.0% | 100.0% |
| Send window (exact match with answer key) | 0.0% | 100.0% |
| Item similarity (keyword overlap) | 0.99 | 0.99 |
| Misses | 1 | 0 |

**Every survey we write** (6,999 insights; Hindi + English files).

| Measure | Brief rules (default) | Answer-key setting |
|---|---|---|
| Surveys (files) | 2,616 (5,232) | 2,698 (5,396) |
| Format (schema, 1–3 tap items, right language) | 100.0% | 100.0% |
| Safety (no new advice, no personal info) | 100.0% | 100.0% |
| Timeliness (after the action window, 07:00–19:00, in season, before harvest) | 100.0% | 26.5% |
| Failing surveys handed to the scheduler | 0 | 0 |
| Relevance (P4's score, 0–1) | 0.81 | 0.81 |
| Relevance (AI judge on Bedrock, 1–5; see the rubric below) | 4.48 | 4.47 |
| Speed | 3.1 ms per survey · 8 s for all | 3.1 ms per survey · 8 s for all |

**Rules we changed** (each recorded run vs the last run under the same send-time rule)

| Run (vs) | What changed | Timing rule | Decision | Rule | Window match | Timeliness | Item sim | Relevance (P4) | Misses |
|---|---|---|---|---|---|---|---|---|---|
| 2 (vs 1) | R7 storage exception (P2): stored crops still get a survey | Brief rules (default) | 96.0% → 99.3% | 96.0% → 99.3% | 0.0% | — → 100.0% | 0.50 | — → 0.83 | 6 → 1 |
| 3 (vs 2) | Answer-key send-time setting (P2), off by default | Answer-key setting | 99.3% → 100.0% | 99.3% → 100.0% | 0.0% → 100.0% | 100.0% → 26.5% | 0.50 | 0.83 | 1 → 0 |
| 4 (vs 2) | P4 templates in answer-key wording (writer_style=golden) + stricter relevance v2 | Brief rules (default) | 99.3% | 99.3% | 0.0% | 100.0% | 0.50 → 0.99 | 0.83 → 0.69 | 1 |
| 5 (vs 3) | P4 templates in answer-key wording (writer_style=golden) + stricter relevance v2 | Answer-key setting | 100.0% | 100.0% | 100.0% | 26.5% | 0.50 → 0.99 | 0.83 → 0.69 | 0 |
| 6 (vs 4) | History rules H1-H4 on (P4's, moved into the team writer) | Brief rules (default) + history on | 99.3% | 99.3% | 0.0% | 100.0% | 0.99 → 0.93 | 0.69 → 0.73 | 1 |
| 7 (vs 5) | History rules H1-H4 on (P4's, moved into the team writer) | Answer-key setting + history on | 100.0% | 100.0% | 100.0% | 26.5% | 0.99 → 0.93 | 0.69 → 0.73 | 0 |
| 8 (vs 4) | Judge: best-value model; plan questions name the first step and crop; send bar 0.3 | Brief rules (default) | 99.3% | 99.3% | 0.0% | 100.0% | 0.99 | 0.69 → 0.81 | 1 |
| 9 (vs 5) | Judge: best-value model; plan questions name the first step and crop; send bar 0.3 | Answer-key setting | 100.0% | 100.0% | 100.0% | 26.5% | 0.99 | 0.69 → 0.81 | 0 |

Misses under brief rules (default): G-0145 (expected R8, got R6)

_Generated by `python scripts/readme_numbers.py --write`. Do not edit by hand._
<!-- results:end -->

## Relevance rubric (AI judge)
Digital Green asks for relevance to be scored by an AI judge. Ours runs a small model on Amazon Bedrock
(`mel/evaluation/judge.py`, off by default: `MEL_JUDGE=1`). It reads the conversation summary and our English
survey, and scores relevance 1–5 with this rubric (version `v1`):

```
Score how relevant this follow-up survey is to the advice this farmer actually received.

5 = Asks directly whether the farmer acted on this specific advice and whether it worked. Every question
    is about this farmer's crop or animal and problem. Short, tap-to-answer.
4 = Clearly about this advice, but one question is generic or slightly off the main action.
3 = About the right crop or problem, but does not check the specific action that was advised.
2 = Mostly generic: could be sent to any farmer; only loosely tied to this conversation.
1 = Irrelevant, gives new advice, contradicts the advice, or asks for personal information.

Built from Digital Green's design principles: one farmer, one context; ask about the advice given; never give
new advice; short and tappable. Replace with Digital Green's MEL rubric if they share one.
```

To check the judge, the team scores 20 surveys by hand in `docs/results/hand_scores.csv` (same rubric), then
`python -m mel.evaluation.judge --calibrate` reports how often the judge agrees (exact and within one point).
