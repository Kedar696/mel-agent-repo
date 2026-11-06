# Prompt: update the team contracts

Use this after the contracts already exist, when the plan has changed. Paste everything below the line into
Claude, then paste your current contracts where it says so. Fill in the brackets.

---

You are helping an 8-person hackathon team update their **existing team contracts** for the Digital Green
"MEL Survey Agent" challenge. For most of the team this is their first project of this kind and their first
time near AWS, so write in plain English. Use short sentences. If you must use a technical word, explain it
in brackets the first time, for example "S3 (a shared online folder on Amazon's cloud)".

## What the project is (one paragraph, for context)
FarmerChat gives farmers in Bihar crop and animal advice. Our tool reads each past conversation, decides
whether to check back with the farmer, writes 1–3 tap-to-answer questions in Hindi and English, plans when
and on which channel to send them (app, web, WhatsApp, Telegram, voice call), and simulates how farmers
answer, including failures. Everything runs in Python on a laptop. It is scored against an answer key of
150 cases (the "golden set"). All data is made up.

## The current contracts
[PASTE THE CURRENT CONTRACTS HERE — the team one and/or the 8 individual ones]

## What changed since they were written
Apply every item below to the right person's contract. Do not drop anything that is still true.

**Already finished — move these to "done" and remove them from to-do lists:**
- P7: channel messages now match the organisers' reference files exactly (including the voice answers
  "हाँ / हां / जी हाँ / haan"). There is a test that checks this.
- P4: there is now an opt-out list. A farmer who says STOP, /stop, presses 9, or taps "Do not ask me again"
  is remembered. It is not yet used in the batch run.
- P6: every survey now gets a basic relevance score from 0 to 1 (how many questions mention the crop or the
  advice). It is a first version and should be improved.
- P8: the demo app now has Overview and Survey Studio pages with a phone preview, using real results.

**New work, from the organisers' brief:**
- P1: load the Excel copies of the data and check they match the JSON files. Re-run everything if Digital
  Green sends a new answer key ("golden set version 2"). Collect our questions for Digital Green and send them.
- P2: write down that rules R1–R8 were worked out from the answer key, not given in the brief. Confirm with
  Digital Green whether critical cases get a high-priority survey or no survey and a phone call instead.
- P3: follow the brief's timing rule (window opens 07:00, after the farmer's action window). Send Digital Green
  2–3 examples where the answer key says 09:00 and ask which is right. This is still the top priority:
  timing accuracy is 0%.
- P4: use the opt-out list in the batch run so opted-out farmers get nothing. Decide and write down what
  happens when a farmer would get two surveys in one week (skip it, move it to the next week, or merge them).
- P6: replace the basic relevance score with a better one, and compare template questions vs Claude-written ones.
- P7: answers that arrive after the survey expired are kept but marked late. App and web answers are sent once,
  when the farmer finishes or closes the sheet.
- P8: any rule we change on purpose must appear in the demo with the numbers that justify it.

**Questions we owe Digital Green (P1 sends them):**
1. The answer key opens windows at 09:00; the brief says 07:00. Which is right?
2. Critical cases: high-priority survey, or no survey and a human call?
3. Will there be a new answer key, and when?

**AWS (optional, only after the core targets are met):**
Nothing needs AWS to run or to score well. If the team uses it, keep it to these, with one account owner (P1):
- S3 (a shared online folder): store the data pack and our output files. Owner P1.
- Bedrock (Claude through Amazon): same Claude model, billed to AWS instead of an Anthropic key. Owner P6.
- App Runner (runs a website for us): host the Streamlit demo so judges get a link. Owner P8 with P1.
- Secrets Manager (a locked box for passwords): keep keys out of the code. Owner P1.
- Slide only, not built: EventBridge/Step Functions (an alarm clock that sends at 07:00 and retries on
  WhatsApp after 24 hours) for P4, Amazon Connect (automated phone calls) for P7, DynamoDB (a shared table
  for the weekly limit and opt-outs) for P4.
- Rules for everyone: never put AWS keys in git or chat; set a budget alert (about $20) on day one; use the
  Mumbai region (ap-south-1); delete what we created after the event.

Event details if they changed: Dates [ ] · Demo time [ ] · Chat channel [ ] · Repo [ ]

## How to write the update
1. Keep each contract's existing structure and headings. Change only what the list above changes.
2. For each person, add a short **"What changed"** box at the top (3 bullets at most).
3. Mark finished work as done; never silently delete a commitment someone signed.
4. If a new item has no clear owner, give it to the buddy pair (P2↔P3, P4↔P7, P5↔P6, P1↔P8) and say so.
5. Put AWS items in a separate "Optional: AWS" part of each affected contract, so nobody thinks they are required.
6. Add or update a "Words you'll hear" list at the end of the team contract: insight, golden set, hand-off,
   schema, guardrails, follow-up, cap, send window, S3, Bedrock, App Runner, Secrets Manager.
7. Leave the sign-off lines blank again for anyone whose contract changed, so they re-sign.
8. At the very end, list every change you made as a table: person, what changed, why.
