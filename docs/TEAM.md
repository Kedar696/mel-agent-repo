# Tech stack and team split (8 people)

## Tech stack
| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ (dev machine: 3.14), `.venv` | one language end to end, fast to iterate |
| Contracts | JSON Schema 2020-12 via `jsonschema` + `referencing` | the pack's schemas are the grading contract |
| Rules | `config/rules/rules.json`, `outcome_codes.json` | rules stay data, not hard-coded |
| Decision / timing / schedule | plain Python, deterministic | must reproduce golden set + worked scenarios exactly |
| Survey writing | templates (default) + Claude `claude-sonnet-5-5` via `anthropic` SDK (opt-in) | templates are safe and free; LLM for richer, concern-specific wording |
| Guardrails | regex + schema checks in `mel/writer/guards.py` | no new advice, no PII, ≤20-char labels |
| Simulation | seeded `random`, channel adapters | reproducible success/failure records |
| Data wrangling | `pandas`, `openpyxl` (spreadsheets/) | analysis, Excel exports |
| UI | Streamlit | the brief says Streamlit or CLI is enough |
| Tests | `pytest`, one file per owner | each owner keeps their own tests green |

## Interfaces (do not change without telling the owners downstream)
```python
mel.data.validate(kind, obj) / errors(kind, obj)            # P1
mel.decision.decide(insight) -> Decision(survey, rule, reason_code, send_window)   # P2
mel.timing.send_window(insight) -> {"not_before","not_after"} | None              # P3
mel.timing.expires_at(window) -> str                                              # P3
mel.writer.write_surveys(insight, window) -> {lang: survey}                       # P5/P6
mel.writer.check_survey(survey) -> list[str]                                      # P6
mel.schedule.build_handoff(insight, survey) -> handoff                            # P4
mel.channels.render(survey, channel) -> payload                                   # P7
mel.simulator.simulate(survey, channel, case, seed) -> response                   # P7
mel.evaluation.score_golden(golden) -> metrics                                    # P8
mel.pipeline.run_insight(insight) -> {...}                                        # P1
```
Downstream: P1 → P2/P3 → P4/P5/P6 → P7 → P8.

---

## P1 · Data, Contracts & Integration lead
**Owns:** `mel/config.py`, `mel/data/`, `mel/pipeline.py`, `mel/cli.py`, `config/`, `scripts/`, `data/mock/`, `tests/test_data.py`
- Keep loaders + schema validation the single source of truth; make junk-row detection report *why* a row is junk.
- Load spreadsheets/ (openpyxl) and confirm they match the JSON copies.
- Own `main` branch hygiene, merge order, CI-style `pytest -q` + `mel.cli validate` before demo.
- CLI: add `--limit`, `--farmer`, summary report (counts per rule, per channel, per language).
**Done when:** full 6,999 run + validate passes with 0 invalid files; every teammate can run the pipeline from README alone.

## P2 · Decision Engine
**Owns:** `mel/decision/`, `tests/test_decision.py`
- Reverse-engineer golden rules R1–R8 precisely (currently 96%). The 6 misses are all R7 false positives.
- Document every rule with evidence rows; add per-rule unit tests from golden ids.
- Handle null resolution, missing verification, critical + escalate interplay.
**Done when:** ≥99% decision and rule accuracy on the full golden set, no rule without a test.

## P3 · Timing & Season
**Owns:** `mel/timing/`, `tests/test_timing.py`
- **Open question (top priority):** golden R8 windows open at **09:00 on created + timing_start** and appear to ignore the action window; worked scenarios open at **07:00 after the action window**. Golden `seasonal` starts ~day 30, not 21. Figure out the real rule, keep both scenario and golden tests green (maybe two rule sets), and raise it with Digital Green if they truly conflict.
- R7 crop calendar: harvest-end per crop, fallback for crops not in the calendar (cauliflower, cabbage), stage-aware.
**Done when:** window_acc ≥95% on golden *and* all 5 scenario windows still exact.

## P4 · Scheduler Hand-off
**Owns:** `mel/schedule/`, `tests/test_schedule.py`
- Channel order, wait hours, priority, expiry, FarmerChat flow ids (already match all scenarios).
- `CapLedger`: simulate the 1-per-7-days cap across a farmer's many insights (choose: drop, defer, or merge insights into one survey via `source_insight_ids`).
- Skip channels a farmer can't be reached on (use farmers.csv preferred_channel / activity).
**Done when:** a batch run produces at most 1 non-high survey per farmer per 7 days, with a written policy.

## P5 · Survey Templates & Hindi/English content
**Owns:** `mel/writer/templates.py`, `mel/writer/i18n.py`, `mel/writer/compose.py`
- Concern-specific templates (pest count, yellowing, seed availability, animal health) modelled on the 5 worked surveys.
- Native-quality Hindi: gender agreement for asset nouns, consistent options across languages, ≤20 code points.
- Choose 2 vs 3 questions per case; rationale text per survey.
**Done when:** every resolution × top-10 concern has a template; Hindi reviewed by a speaker; guards pass on 100% of surveys.

## P6 · LLM Writer & Safety Guardrails
**Owns:** `mel/writer/llm.py`, `mel/writer/guards.py`, `tests/test_writer.py`
- Prompt + JSON parsing for Claude, retries, cost/latency logging, cache by (resolution, concern, asset, lang).
- Strengthen guards: new-advice detection (Hindi + English), PII, relevance score (does the question reference the advice?), fill `self_eval.relevance_score`.
- A/B: templates vs LLM on a 50-survey sample; human rubric.
**Done when:** LLM path on with 0 guard failures shipped (bad outputs fall back), and an eval table comparing both.

## P7 · Channels & Answer Simulator
**Owns:** `mel/channels/`, `mel/simulator/`, `tests/test_simulator.py`
- Renderers for bottom sheet, WhatsApp (buttons ≤3, list otherwise), Telegram, voice IVR, diffed against `data/mock/scenarios/*/render`.
- Simulator: match the 183 reference records field by field (raw_event strings, timestamps, sheet_outcome), multi-attempt retries and fall-back across `channel_order`.
- Farmer personas (responsive / busy / unreachable) to produce realistic mixes.
**Done when:** our grid reproduces `data/mock/outcomes/` exactly (except ids), and a channel-fallback simulation runs for a whole hand-off.

## P8 · Evaluation & Demo
**Owns:** `mel/evaluation/`, `app/`, `tests/test_pipeline.py`
- Eval report: decision/rule/channel/window accuracy, per-rule confusion, item similarity vs golden `items`, schema pass rate, follow-up rate.
- Streamlit: insight picker → decision → survey (hi/en) → hand-off → channel mock → simulate → follow-up queue; eval dashboard.
- Own the demo script and final presentation numbers.
**Done when:** a 3-minute demo runs from a clean checkout; eval numbers in README are regenerated, not typed.

---

## Extra items from the participant brief (added 2026-11-03)
We checked the scaffold against the organisers' brief (`participant-pack/index.html`). These items were missing.

**Already done (in the scaffold now):**
- P7: channel messages now match the pack's reference files exactly, including the "how it arrives" note and the extra spoken answers for voice ("हाँ / हां / जी हाँ / haan"). Test: `test_render_matches_reference_files`.
- P4: `OptOutList` remembers farmers who said "no more surveys" (STOP, /stop, 9 on a call, "Do not ask me again"). Test: `test_opt_out_blocks_future_surveys`.
- P6: every survey now gets a basic `relevance_score` (0 to 1): the share of questions that mention the crop/animal or the advice. Test: `test_relevance_score_in_range`.

**Still to do, by owner:**
| Owner | What | Why (from the brief) |
|---|---|---|
| P1 | Load the Excel files in `spreadsheets/` and check they match the JSON copies | The pack gives both; they must agree |
| P1 | Re-run everything when Digital Green sends a new golden set | "Version 1, which Digital Green may update during the event" |
| P2 | Write down that R1–R8 come from studying the golden set, not from the brief. Confirm R2 (critical → no survey, a person calls) with Digital Green | The brief only says critical = high priority |
| P3 | Follow the brief (07:00 start, after the action window). Send Digital Green 2–3 golden ids where windows start at 09:00 and ask which is right | The brief states the 07:00 rule in plain words |
| P4 | Use `OptOutList` in the batch run: no survey to a farmer who opted out | "Stop all future surveys to this farmer" |
| P4 | Decide what happens to capped surveys (drop / move to next free week / merge) | Brief sets the limit, not the policy |
| P7 | Late answers (after expiry) are kept but marked late | "Late answers are kept but marked late" |
| P7 | App/web answers are sent once, when the farmer finishes or closes the sheet | Brief, "Simulating farmer answers" |
| P6 | Replace the basic relevance score with a better one; compare templates vs Claude | `self_eval.relevance_score` is in the survey contract |
| P8 | Show any rule we changed on purpose, with the numbers that justify it | "Use them as the baseline, and improve on them if your evaluation shows a better choice" |

**Questions to send Digital Green (owner: P1 collects, P3/P2 write):**
1. Golden windows start at 09:00; the brief says 07:00. Which is right?
2. Critical cases: survey with high priority, or no survey and a human call?
3. Will there be a golden set version 2, and when?

---

## AWS, in plain English (optional, after the core work)
Nothing in the project needs AWS to run or to score well. Everything works on a laptop. Use AWS only for the
pieces below, and only once the core targets are met. One person sets up the account; nobody else needs AWS keys.

| Plain words | AWS name | What we'd use it for | Owner |
|---|---|---|---|
| A shared online folder | **S3** | Put the data pack and our `out/` files where the whole team can reach them | P1 |
| Claude through Amazon | **Bedrock** | Same Claude model, billed to the AWS account instead of an Anthropic key. Small change in `mel/writer/llm.py` | P6 |
| A web link for the demo | **App Runner** | Runs our Streamlit app so judges can open a link instead of our laptop | P8 (with P1) |
| A safe place for passwords | **Secrets Manager** | Holds the Claude/AWS keys so they never go in the code | P1 |
| Alarm clock and retry | **EventBridge Scheduler / Step Functions** | *Slide only*: how real sending at 07:00 and "try WhatsApp after 24h" would work | P4 (slide) |
| Phone calls | **Amazon Connect** | *Slide only*: how the voice survey would really call farmers | P7 (slide) |
| Shared ledger | **DynamoDB** | *Slide only*: where the weekly limit and opt-out list would live in production | P4 (slide) |

Ground rules: never put AWS keys in git or chat; set a budget alert (for example $20) on day one; use the
`ap-south-1` (Mumbai) region; delete what you created after the event.

---

## Words you'll hear
- **Insight**: one farmer conversation, summed up (what they asked, what advice they got).
- **Golden set**: the answer key. 150 insights where Digital Green wrote the right decision.
- **Hand-off**: the note we give the sending system: when, which channel first, how urgent.
- **Schema**: the required shape of a file. "Schema-valid" means the file has the right fields.
- **Guards / guardrails**: automatic checks that a survey gives no new advice and asks nothing personal.
- **Follow-up (⚑)**: an answer that means trouble, so FarmerChat should get back to the farmer.
- **Cap**: the limit of one survey per farmer per week.
- **Window**: the dates and hours a survey may be sent.

---

## Working agreements
- Branch per person: `p<N>-<topic>`; PRs need one reviewer from a downstream owner.
- Never edit another owner's package without a PR they approve (see `.github/CODEOWNERS`).
- Every PR: `pytest -q` green and `python -m mel.cli run && python -m mel.cli validate` = 0 invalid.
- Interface changes: post in team chat first, update this file.
