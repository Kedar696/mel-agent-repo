# Request to P1: add an optional `late` field to response.schema.json

From: P3 (Scheduler, Channels & Simulator)
To: P1 (Data, Contracts & Integration — owner of `config/schemas/`)
Status: **proposed, not applied.** P3 has not edited the shared schema.

## Why
The brief says, for app/web surveys:

> Answers that arrive after `expires_at` are kept but marked **late**.
> (`schedule_handoff.schema.json`: "late answers are kept but marked late".)

Today `response.schema.json` has `"additionalProperties": false` and no `late` field, so a
record cannot express lateness without being invalid. P3 will not silently edit a shared
schema or emit invalid records, so the late flag is currently computed internally and only
written when the environment variable `MEL_RESPONSE_LATE_FIELD=1` is set. By default every
record P3 emits stays valid against today's schema.

## The change (one optional boolean)
Add to `config/schemas/response.schema.json` `properties` (NOT to `required`, so existing
records stay valid):

```json
"late": {
  "type": "boolean",
  "description": "True when the answer arrived after expires_at. The answer is kept but flagged; FarmerChat treats it as late, not fresh. Absent means not late."
}
```

Leave `additionalProperties: false` as-is; adding the property to the schema is what makes
it allowed.

## What flips on the P3 side when this lands
1. P1 adds the property above and re-runs `python -m mel.cli validate` (still 0 invalid).
2. P3 flips the default of `MEL_RESPONSE_LATE_FIELD` on in `mel/simulator/simulate.py`
   (one constant), so `simulate()` / `simulate_sheet()` start emitting `late`.
3. The 183 reference records in the pack do not contain `late`; they remain valid because
   the field is optional and absent means not late. P3's reference-match test keeps the
   flag off, so it continues to pass.

## Scope note
This only affects the answer record (`response`). No change to `survey`,
`schedule_handoff`, `bottom_sheet`, `insight`, or `no_survey`.
