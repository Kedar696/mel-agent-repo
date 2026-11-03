# Prompt: generate the team contract

Copy everything below the line into Claude (or any assistant). Fill in the bracketed parts first.

---

You are helping an 8-person hackathon team write a **team contract** for the Digital Green "MEL Survey Agent" challenge.

**Project.** We are building an agent that reads FarmerChat insights (what a farmer asked and was advised), decides whether a follow-up survey is needed (golden rules R1–R8), writes 1–3 tap-answer questions in Hindi and English with no new advice and no personal information, computes a send window, builds a scheduler hand-off (priority, channel order app/web/WhatsApp/Telegram/voice, 1-per-7-days frequency cap, expiry), and simulates farmer answers including failures (undelivered, declined, invalid input, stale, duplicate). Everything is validated against the pack's JSON Schemas and scored against a 150-row golden set. Stack: Python, jsonschema, optional Claude API for question wording, Streamlit demo, pytest.

**Event details.** Dates/duration: [e.g. 2026-11-07 to 2026-11-09, 48h]. Demo time: [ ]. Judging criteria: [paste]. Communication channel: [Slack/Discord/WhatsApp group]. Repo: [GitHub URL].

**Roles (one owner each):**
1. **P1 · Data, Contracts & Integration lead ([name])**: `mel/data`, `mel/config.py`, `mel/pipeline.py`, `mel/cli.py`, mock data, merge order. Done when the full 6,999-insight run validates with 0 invalid files and anyone can run it from the README.
2. **P2 · Decision Engine ([name])**: `mel/decision`. Done when golden-set decision and rule accuracy reach ≥99%, with a test per rule.
3. **P3 · Timing & Season ([name])**: `mel/timing`. Resolve the conflict between the golden windows (09:00, ignore the action window) and the worked scenarios (07:00, after the action window); crop-calendar harvest check. Done when window accuracy is ≥95% and the scenarios still match exactly.
4. **P4 · Scheduler Hand-off ([name])**: `mel/schedule`. Frequency-cap policy across a batch, channel reachability. Done when no farmer gets more than one non-high survey per 7 days.
5. **P5 · Survey Templates & Hindi/English ([name])**: `mel/writer/templates.py`, `i18n.py`. Templates per concern, Hindi reviewed by a native speaker. Done when 100% of surveys pass the guards.
6. **P6 · LLM Writer & Safety ([name])**: `mel/writer/llm.py`, `guards.py`. Claude prompt, fallback, no-advice/PII detection, relevance score, templates-vs-LLM comparison.
7. **P7 · Channels & Simulator ([name])**: `mel/channels`, `mel/simulator`. Reproduce the 183 reference answer records; simulate multi-channel fallback.
8. **P8 · Evaluation & Demo ([name])**: `mel/evaluation`, `app/`. Eval report, Streamlit demo, presentation.

Downstream dependencies: P1 → P2/P3 → P4/P5/P6 → P7 → P8.

**Write a team contract with these sections:**
1. Purpose and shared goal (one paragraph, plus the measurable success targets above).
2. Roles and responsibilities: a table with owner, files owned, deliverables, "done when" criteria, the backup person, and the downstream teammates who depend on them.
3. Deliverables timeline: checkpoints by hour/day (e.g. H+4 interfaces frozen, H+12 baseline eval, H+24 feature complete, H+36 demo freeze), with owners per checkpoint.
4. Interfaces and code ownership: no edits to another owner's package without their PR approval; interface changes are announced first. Every PR needs `pytest -q` green and `mel.cli validate` with 0 invalid files.
5. Communication: channel, stand-up cadence (e.g. every 4h, 5 minutes), response-time expectations, how to flag blockers.
6. Decision-making: who breaks ties (integration lead P1 for code, P8 for demo scope), and how scope cuts happen.
7. Quality and safety commitments: no real farmer data, no API keys in git, survey content must never give new advice or ask for personal info, and Hindi is reviewed.
8. Availability: a table for each person's hours and offline windows (leave blanks to fill in).
9. Conflict and underperformance: early check-in, reassignment, and a buddy system (pair P2↔P3, P4↔P7, P5↔P6, P1↔P8).
10. Sign-off: name, role, date, signature line for all 8.

Keep it practical and under two pages. Write it in plain language and use tables where they help. End with a one-page "who to ask about what" cheat sheet.
