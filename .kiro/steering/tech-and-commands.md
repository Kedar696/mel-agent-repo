# Tech stack and commands

## Stack
- Python 3.11+ (CI uses 3.12), virtualenv in `.venv`. `pytest` for tests. Streamlit for the UI.
- Contracts: JSON Schema 2020-12 in `config/schemas/` via `jsonschema`. Rules as data in `config/rules/`.
- Decision, timing and schedule are plain deterministic Python. The LLM writer is opt-in and off by default.
- `openpyxl` is imported only inside the functions that read Excel (`mel/data/excel.py`). Do not import it at module top.
- Every text file is read and written with `encoding="utf-8"`. JSON with Hindi uses `ensure_ascii=False`.
- No API keys or credentials in any file. `.env` is never committed. No AWS resources are created by the code.

## Commands (no trailing `# comments` when giving them to teammates; zsh treats `#` as an argument)
```
pytest -q
python -m mel.cli run --simulate --clean
python -m mel.cli validate
python -m mel.cli eval
python -m mel.cli parity
python -m mel.cli junk
python scripts/compare_golden.py OLD NEW
```
- `run` flags: `--insights PATH`, `--simulate`, `--limit N` (0 or more), `--farmer ID`, `--clean`.
  It writes `surveys/ handoffs/ no_survey/ responses/`, `run_summary.json` and `junk_report.csv`.
- `validate` exits non-zero when it finds no files; `--allow-empty` overrides that.
- `parity` needs no arguments: it compares the four workbooks and the config folders with the committed pack.

## Environment variables
| Variable | Use |
|---|---|
| `MEL_DATA_DIR` | data folder; full pack: `mel-survey-agent-participant-pack/participant-pack/data` |
| `MEL_OUT_DIR` | output folder; keep it outside the repo and outside OneDrive |
| `MEL_TIMING_BASIS` | `brief` (default) or `answer_key` (P2) |
| `MEL_USE_LLM`, `ANTHROPIC_API_KEY`, `MEL_MODEL` | opt-in Claude writer (P4) |

## Full-pack reference numbers (base code, commit 5763855)
Rule counts R1 723, R2 25, R3 1287, R4 875, R5 1312, R6 111, R7 115, R8 2551. Files: surveys 5102, handoffs 2551,
no_survey 4448, responses 2551. Scores: decision 96.0%, rule 96.0%, channel 100%, window 0%.
Mock: decision 97.1%, rule 97.1%, channel 100%, window 0%.
