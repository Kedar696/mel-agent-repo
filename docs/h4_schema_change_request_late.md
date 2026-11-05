# Request to P1: how a late answer is recorded

From: P3 (Scheduler, Channels & Simulator)
To: P1 (Data, Contracts & Integration, owner of `config/schemas/`)
Status: **needs a P1 decision.** Checked 5 Nov on `Semdon-P3`, `main` and `lucas-p1`: no decision
recorded, `response.schema.json` has no `late` field. P3 has not edited the schema.

## What the brief requires
`schedule_handoff.schema.json` → `expires_at`: "After this the survey is dropped, sent or not,
and late answers are kept but marked late."

## What P3 does today (no shared format invented)
- A late answer is **kept**: `simulate_sheet(..., submit_at=after_expiry)` stores the answers.
- It is **counted** without a new field: `mel.simulator.is_late(record, handoff["expires_at"])`
  (answer time strictly after expiry; exactly at expiry is not late).
- It is **marked** `late: true` only when `MEL_RESPONSE_LATE_FIELD=1`. Never `late: false`, so
  normal records stay identical to the 183 reference records. Off by default, because today's
  schema (`additionalProperties: false`) rejects the field and `validate` would fail.

## The decision P1 needs to make (pick one)
**Option A (recommended): optional boolean `late` in `response.schema.json`.**
```json
"late": {"type": "boolean", "description": "True when the answer arrived after expires_at. Kept, not fresh. Absent means not late."}
```
In `properties`, not `required`. Catch: `config/schemas/` must match the organisers' pack, so
`mel.cli parity` fails unless either Digital Green adds the field to the pack, or P1 adds a
documented parity exception for this one property. P1 chooses which.
Then P3 turns on `MEL_RESPONSE_LATE_FIELD` (one line). `tests/test_p3_completion.py` already
proves a late record validates against the schema plus this field.

**Option B: no schema change.** The stored record stays as today. Lateness is derived with
`is_late()` from `timestamps.answered` and the hand-off's `expires_at`, and P1 writes a late
count (or a list of late `response_key`s) into `run_summary.json`. Nothing in the record says
"late", so this meets "kept" but only meets "marked" through the summary.

## Second point to confirm
The pack's reference record `survey_closed` (a chat tap after expiry) is `stale`, answers `{}`
("dropped before it reaches FarmerChat"). That contradicts "late answers are kept" for chat
channels. P3 keeps the reference behaviour (all 183 records must match) and keeps late answers
for the app/web sheet, which stores answers and submits them later. Please confirm with Digital
Green that this split is what they want.
