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

## Layout
| Path | What | Owner |
|---|---|---|
| `mel/config.py`, `mel/data/`, `mel/pipeline.py`, `mel/cli.py`, `config/` | paths, loaders, schema validation, glue, CLI | P1 |
| `mel/decision/` | survey / no-survey cascade R1–R8 | P2 |
| `mel/timing/` | send window, expiry, season + crop calendar | P3 |
| `mel/schedule/` | hand-off: priority, channel order, cap, flow ids | P4 |
| `mel/writer/templates.py`, `i18n.py`, `compose.py` | question templates, Hindi/English | P5 |
| `mel/writer/llm.py`, `guards.py` | Claude writer, safety + format guardrails | P6 |
| `mel/channels/`, `mel/simulator/` | channel payloads, answer simulator | P7 |
| `mel/evaluation/`, `app/` | golden scoring, Streamlit demo | P8 |
| `data/mock/` | sampled insights/golden/farmers + worked scenarios + outcome grid | P1 (regenerate with `scripts/make_mock_data.py`) |

See `docs/TEAM.md` for the full breakdown and `docs/prompts/` for the team and individual contract prompts.

## Baseline (scaffold, full pack)
decision 96.0% · rule 96.0% · channel 100% · window 0% (see open question in docs/TEAM.md, P3).
