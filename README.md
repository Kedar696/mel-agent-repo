# MEL Survey Agent

Reads FarmerChat insights → decides survey / no survey → writes 1–3 tap questions (hi-IN + en-IN) →
builds the scheduler hand-off → simulates farmer answers across app, web, WhatsApp, Telegram and voice.
Built for the Digital Green MEL hackathon pack (synthetic data only).

## Quick start
Run these from the repo root. Python 3.11 or newer.
```bash
python -m venv .venv
```
Activate the virtual environment (pick your OS):
```bash
# Windows (PowerShell or cmd)
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```
```bash
pip install -r requirements.txt
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

`validate` on the full pack checks about 14,650 files (a few seconds to a few minutes, depending on the machine).

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

## Baseline (scaffold, full pack)
decision 96.0% · rule 96.0% · channel 100% · window 0% (see open question in docs/TEAM.md, P2).
