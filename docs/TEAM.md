# Team plan (5 people)

The signed **Team Contracts** document is the source of truth for who does what and when. This file is the
short version kept next to the code: owners, files, interfaces, open questions and plain-English notes.
If the two disagree, the contract wins; fix this file.

Changed 3 Nov: team went from 8 to 5 by merging buddy pairs (old P2+P3 → P2, old P4+P7 → P3,
old P5+P6 → P4, old P8 → P5). All commitments kept.

## Who owns what
| Person | Role | Owns (files) | Buddy / backup |
|---|---|---|---|
| **P1** | Data, Contracts & Integration | `mel/config.py`, `mel/data/`, `mel/pipeline.py`, `mel/cli.py`, `config/`, `scripts/`, `data/mock/`, `.github/`, `tests/test_data.py` | P5 |
| **P2** | Decision & Timing | `mel/decision/`, `mel/timing/`, `tests/test_decision.py`, `tests/test_timing.py` | P3 |
| **P3** | Scheduler, Channels & Simulator | `mel/schedule/`, `mel/channels/`, `mel/simulator/`, `tests/test_schedule.py`, `tests/test_simulator.py` | P2 (also backs up P4) |
| **P4** | Survey Writing & Safety | `mel/writer/` (templates, i18n, compose, llm, guards), `tests/test_writer.py` | P3 |
| **P5** | Evaluation & Demo | `mel/evaluation/`, `app/`, `.streamlit/`, `tests/test_pipeline.py`, README results, slides | P1 |

`docs/` is shared by P1 and P5. Code owners for review are in `.github/CODEOWNERS`.

**How work flows:** P1 → P2 → (P4 writes questions, P3 packages and sends) → P5 shows it to the judges.
P4's surveys go to P3. Everyone sends final numbers to P5.

## Tech stack
| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ (dev machine: 3.14), `.venv` | one language end to end |
| Contracts | JSON Schema 2020-12 via `jsonschema` | the pack's schemas are the grading contract |
| Rules | `config/rules/rules.json`, `outcome_codes.json` | rules stay data, not hard-coded |
| Decision / timing / schedule | plain Python, deterministic | must reproduce golden set + worked scenarios |
| Survey writing | templates (default) + Claude via `anthropic` SDK (opt-in) | templates are safe and free |
| Guardrails | patterns + schema checks in `mel/writer/guards.py` | no new advice, no personal info, ≤20-char labels |
| Simulation | seeded `random` (same seed, same answers) | reproducible |
| UI | Streamlit | the brief says Streamlit or CLI is enough |
| Tests | `pytest`, one file per owner | each owner keeps their own tests green |

## Interfaces as they are in the code today
The contract proposes some new names. Decide which to use at H+4: see
[h4_interface_decisions.md](h4_interface_decisions.md).
```python
mel.data.load_insights(path=None) / load_farmers(path=None) / load_golden(path=None)    # P1
mel.data.errors(kind, obj) -> list[str]; validate(kind, obj)                             # P1
mel.pipeline.run_insight(insight) -> {"decision", "surveys", "handoff"} | {"decision", "no_survey"}  # P1
mel.decision.decide(insight) -> Decision(survey, rule, reason_code, send_window)        # P2
mel.timing.send_window(insight) -> {"not_before", "not_after"} | None; expires_at(window) # P2
mel.timing.is_past_harvest(crop, date) -> bool                                           # P2
mel.writer.write_surveys(insight, window) -> {lang: survey}                              # P4
mel.writer.check_survey(survey) -> list[str]   (empty list = safe)                       # P4
mel.writer.guards.relevance_score(survey, insight) -> float 0..1                         # P4
mel.schedule.build_handoff(insight, survey) -> handoff                                   # P3
mel.schedule.CapLedger().allow(handoff) -> bool; OptOutList().record(resp) / .blocks(h)  # P3
mel.channels.render(survey, channel) -> payload                                          # P3
mel.simulator.simulate(survey, channel, case, seed) -> response                          # P3
mel.evaluation.score_golden(golden=None) -> metrics                                      # P5
```

## Where each person starts (3 Nov, mock data)
- **P1:** loaders, schema checks, CLI `run` / `eval` / `validate` work. Not yet: junk-row reasons, Excel
  loader, `--limit` / `--farmer`, CI. CODEOWNERS still has `@p1..@p5` placeholders.
- **P2:** decision and rule accuracy 97.1% (one miss: G-0131, R7 fired, answer key says R8).
  **Window accuracy 0%** (top priority). The brief and the 5 worked scenarios open at 07:00 after the
  action window; the answer key opens at 09:00 on created + timing start and seasonal starts ~day 30.
  Plan: brief rule as default, answer-key rule behind a setting, ask Digital Green.
  Crops missing from the calendar (cauliflower, cabbage) need a fallback (`mel/timing/calendar.py`).
- **P3:** priority, channel order, expiry and flow ids match the scenarios. Channel messages match the
  pack's reference files exactly (tested). `OptOutList` and `CapLedger` exist but aren't used in the batch run.
  Not yet: two-in-a-week policy, late answers, app/web sent once, fallback across channels, the 183-record match.
- **P4:** generic templates in both languages pass the guards; opt-in Claude writer with template fallback;
  basic relevance score on every survey. Not yet: problem-specific templates, Hindi review, stronger guards,
  Claude retries/cache/logs, templates-vs-Claude table.
- **P5:** Streamlit app with Overview, Survey Studio (phone preview), Simulate, Follow-up queue, Evaluation; all
  numbers from the pipeline. Done: per-rule confusion matrix, item similarity, README numbers by script,
  follow-up queue (per-reason counts, filters, suggested action), demo script (`docs/demo_script.md`). Not yet: slides, backup screenshots.

**Channel order (P3), as the brief and code define it:** 1) the farmer's preferred channel, 2) the channel the
advice's check method names, if different, 3) WhatsApp, 4) voice, only for high priority. Wait 6 h (high),
24 h (normal) or 48 h (low) before trying the next one.

## Questions to send Digital Green (P1 sends, P2 writes the examples)
1. The answer key opens windows at 09:00; the brief says 07:00. Which is right?
2. Critical cases: high-priority survey, or no survey and a human call?
3. Will there be a new answer key (golden set version 2), and when?

## AWS, in plain English (optional, only after the core targets)
Nothing needs AWS to run or to score well. One account, owned by P1. Budget alert ~$20 on day one,
Mumbai region (`ap-south-1`), delete everything after the event, never put AWS keys in git or chat.

| Plain words | AWS name | Use | Owner |
|---|---|---|---|
| A shared online folder | **S3** | Data pack and our output files | P1 |
| A locked box for keys | **Secrets Manager** | Keep keys out of the code | P1 |
| Claude through Amazon | **Bedrock** | Third writer option behind a setting | P4 |
| A web link for the demo | **App Runner** | Judges open a link; laptop demo stays the main plan | P5 with P1 |
| Alarm clock and retry | **EventBridge / Step Functions** | *Slide only*: send at 07:00, retry on WhatsApp after 24 h | P3 notes → P5 slide |
| Shared online table | **DynamoDB** | *Slide only*: weekly limit and opt-outs in real life | P3 notes → P5 slide |
| Automated phone calls | **Amazon Connect** | *Slide only*: real voice surveys | P3 notes → P5 slide |

## Words you'll hear
- **Insight**: one past FarmerChat conversation, summed up (crop or animal, problem, advice).
- **Golden set**: the answer key. 150 cases with the right decision. We're scored against it.
- **Hand-off**: the package for the sending system: when, which channel first, how urgent, when it expires.
- **Schema**: the required shape of a file. "Schema-valid" = the file has the right fields.
- **Guardrails**: automatic checks that stop a survey giving new advice or asking for personal info.
- **Follow-up (⚑)**: an answer that means trouble, so FarmerChat should get back to the farmer.
- **Cap**: the weekly limit, 1 non-urgent survey per farmer per 7 days.
- **Send window**: the dates and hours a survey may go out.
- **Opt-out**: STOP, /stop, pressing 9, or "Do not ask me again". That farmer gets nothing after that.

## Working agreements
- `main` always works. Branch per task: `p<N>-<topic>` (for example `p2-brief-rule`).
- PRs reviewed by a downstream owner, usually your buddy. Tests and `mel.cli validate` must pass.
- Never edit another owner's package without their OK (see `.github/CODEOWNERS`).
- Changing a shared shape (function signature, schema, `requirements.txt`): post in chat first.
- Every question for Digital Green goes through P1.
- Give teammates shell commands without trailing `# comments` (zsh passes them as arguments).
