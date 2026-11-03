# MEL Survey Agent

Reads FarmerChat insights → decides survey / no survey → writes 1–3 tap questions (hi-IN + en-IN) →
builds the scheduler hand-off → simulates farmer answers across app, web, WhatsApp, Telegram and voice.
Built for the Digital Green MEL hackathon pack (synthetic data only).

## Quick start
```bash
cd ~/mel-agent
source .venv/bin/activate          # or: python3 -m venv .venv && pip install -r requirements.txt
pytest -q                          # 13 tests, all green on the scaffold
python -m mel.cli run --simulate   # writes out/{surveys,handoffs,no_survey,responses}
python -m mel.cli validate         # schema-checks everything in out/
python -m mel.cli eval             # golden-set score
streamlit run app/streamlit_app.py # demo UI
```
Use the full pack instead of the mock subset:
`MEL_DATA_DIR=~/Downloads/participant-pack/data python -m mel.cli eval`

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
