# File ownership

Source of truth: `docs/TEAM.md` and `.github/CODEOWNERS`. Do not edit another owner's files without their OK;
write the change down as a request to that person and carry on.

| Owner | Files |
|---|---|
| P1 Data, Contracts & Integration | `mel/config.py`, `mel/data/`, `mel/pipeline.py`, `mel/cli.py`, `config/`, `scripts/`, `data/mock/`, `.github/`, `.kiro/`, `pyproject.toml`, `.env.example`, `tests/test_data.py` and P1's new `tests/test_*.py` (`test_cli.py`, `test_parity.py`) |
| P2 Decision & Timing | `mel/decision/`, `mel/timing/`, `tests/test_decision.py`, `tests/test_timing.py` |
| P3 Scheduler, Channels & Simulator | `mel/schedule/`, `mel/channels/`, `mel/simulator/`, `tests/test_schedule.py`, `tests/test_simulator.py` |
| P4 Survey Writing & Safety | `mel/writer/`, `tests/test_writer.py` |
| P5 Evaluation & Demo | `mel/evaluation/`, `app/`, `.streamlit/`, `tests/test_pipeline.py`, README results section |
| Shared P1 + P5 | `docs/`, `README.md`, `CLAUDE.md` |

## Read-only for everyone
- `mel-survey-agent-participant-pack/` is the organisers' pack. Never edit it.
- `config/schemas/` and `config/rules/` are copies of the pack's `json/schemas` and `json/rules`; `mel.cli parity` checks they
  still match. A schema change is a request to P1 plus a note to Digital Green, not a quiet edit.
- `data/mock/scenarios/` and `data/mock/outcomes/` are copies of the pack's `json/scenarios` and `json/outcomes`.

## Branches
Branch per task. Never push to `main` directly; PRs are reviewed by a downstream owner. P1's branch is `lucas-p1`.
Shared shapes (function signatures, schemas, the dependencies in `pyproject.toml`): post in chat first.
