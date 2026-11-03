# Prompt: generate one contract per teammate

Produces 8 separate one-page contracts (P1–P8), each pre-loaded with that role's current baseline
and open work. For a single shared team contract, use `team_contract_prompt.md` instead.

Copy everything below the line into Claude (or any assistant). Fill in the bracketed parts first.
Update the "current state" lines if the baseline has moved (`python -m mel.cli eval`).

---

You are helping an 8-person hackathon team write one INDIVIDUAL contract per teammate for the
Digital Green "MEL Survey Agent" challenge. Produce 8 separate contracts (P1–P8), each one page,
each starting on its own "## P<N> · <Role> — <Name>" heading.

PROJECT
A Python agent that reads FarmerChat insights, decides survey vs no-survey (golden rules R1–R8),
writes 1–3 tap questions in Hindi + English (no new advice, no personal info, labels ≤20 chars),
computes a send window, builds a scheduler hand-off (priority, channel order app/web/WhatsApp/
Telegram/voice, 1-per-7-days cap, expiry), and simulates farmer answers incl. failures. Everything
is validated against JSON Schemas and scored on a 150-row golden set. Stack: Python 3.11+,
jsonschema, optional Claude API, Streamlit, pytest. Synthetic data only.

EVENT
Dates/duration: [ ]   Demo time: [ ]   Judging criteria: [ ]
Chat channel: [ ]     Repo: [ ]        Stand-up cadence: [e.g. every 4h, 5 min]

PEOPLE (name · GitHub handle · hours available · offline windows · strengths)
P1 [ ] · P2 [ ] · P3 [ ] · P4 [ ] · P5 [ ] · P6 [ ] · P7 [ ] · P8 [ ]

ROLES, CURRENT STATE, AND OPEN WORK
P1 Data, Contracts & Integration lead — owns mel/config.py, mel/data/, mel/pipeline.py, mel/cli.py,
   config/, scripts/, data/mock/, tests/test_data.py. Has: loaders, schema validation, CLI run/eval/
   validate. Todo: junk-row reasons, spreadsheet loader + JSON parity check, CLI --limit/--farmer/
   summary, git init + CI (pytest + validate), merge order. Done when: full 6,999-insight run
   validates with 0 invalid files; anyone can run from README alone.
P2 Decision Engine — owns mel/decision/, tests/test_decision.py. Baseline 96–97% decision/rule
   accuracy; all misses are R7 false positives. Todo: exact R1–R8 rules with evidence rows, null
   resolution, critical+escalate interplay, one test per rule. Done when: ≥99% decision and rule acc.
P3 Timing & Season — owns mel/timing/, tests/test_timing.py. Baseline: 5/5 scenario windows exact,
   golden window acc 0%. Todo (top priority): resolve golden (09:00, created+timing_start, ignores
   action window; seasonal starts ~day 30) vs scenarios (07:00, after action window); crop-calendar
   fallback for missing crops (cauliflower, cabbage); escalate to Digital Green if truly conflicting.
   Done when: window acc ≥95% AND scenarios still exact.
P4 Scheduler Hand-off — owns mel/schedule/, tests/test_schedule.py. Has: priority, channel order,
   expiry, flow ids matching scenarios, CapLedger class (not wired in). Todo: cap policy (drop /
   defer / merge via source_insight_ids), wire into batch run, skip unreachable channels using
   farmers.csv. Done when: ≤1 non-high survey per farmer per 7 days, with a written policy.
P5 Survey Templates & Hindi/English — owns mel/writer/templates.py, i18n.py, compose.py (shared w/ P6).
   Has: generic per-resolution templates. Todo: concern-specific templates (pest count, yellowing,
   seed availability, animal health), native-speaker Hindi review, gender agreement, 2-vs-3 question
   choice, rationale text. Done when: every resolution × top-10 concern has a template; 100% pass guards.
P6 LLM Writer & Safety Guardrails — owns mel/writer/llm.py, guards.py, tests/test_writer.py. Has:
   opt-in Claude writer with template fallback, regex guards. Todo: retries, cache, cost/latency
   logs, stronger Hindi+English advice/PII detection, relevance score, templates-vs-LLM eval on 50
   surveys. Done when: LLM path ships with 0 guard failures and a comparison table.
P7 Channels & Answer Simulator — owns mel/channels/, mel/simulator/, tests/test_simulator.py. Has:
   renderers for 5 channels, seeded simulator for every outcome code. Todo: match the 183 reference
   records field by field, multi-attempt fallback across channel_order, farmer personas. Done when:
   grid reproduces data/mock/outcomes/ exactly (except ids).
P8 Evaluation & Demo — owns mel/evaluation/, app/, tests/test_pipeline.py. Has: score_golden, 3-tab
   Streamlit app. Todo: item similarity vs golden items, per-rule confusion, follow-up queue in UI,
   regenerated README numbers, 3-minute demo script + slides. Done when: demo runs from clean checkout.

Dependencies: P1 → P2/P3 → P4/P5/P6 → P7 → P8.
Buddies (backup + reviewer): P2↔P3, P4↔P7, P5↔P6, P1↔P8.

EACH INDIVIDUAL CONTRACT MUST CONTAIN
1. Role in one sentence, and why it matters to the demo/judging.
2. Ownership: files/packages owned; files they must NOT edit without the owner's PR approval.
3. Starting point: what already works (from above) and the measured baseline.
4. Deliverables with checkpoints: H+4 interfaces frozen, H+12 baseline improved, H+24 feature
   complete, H+36 demo freeze. Give 1–3 concrete, checkable items per checkpoint for THIS person.
5. Definition of done: the measurable targets above, plus "pytest -q green" and
   "python -m mel.cli validate = 0 invalid".
6. Interfaces they provide (function signatures from mel.* they own) and the ones they consume,
   naming the teammate on the other side of each. Interface changes are announced in chat first.
7. Dependencies & risks: who blocks them, whom they block, the top 2 risks with a fallback plan
   (e.g. P6: if the LLM path is unstable, ship templates only).
8. Working agreements: branch p<N>-<topic>; PR reviewed by a downstream owner; stand-up updates;
   blockers raised within 30 minutes; response time in chat [ ].
9. Safety commitments relevant to the role: no real farmer data, no API keys in git, surveys never
   give new advice or ask for personal info, Hindi reviewed by a native speaker.
10. Availability (from PEOPLE) and buddy/backup.
11. Sign-off line: name, date, signature.

STYLE
Plain language, second person ("You own…"), tables for checkpoints, no filler. Keep each contract
to one page. After the 8 contracts, add a half-page "who to ask about what" cheat sheet and a
dependency checklist showing, for each checkpoint, which hand-offs must have happened.
