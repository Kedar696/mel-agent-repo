# Frequency-cap policy: two surveys in one week (P3)

Owner: P3 (`mel/schedule/handoff.py` `CapLedger`, `mel/schedule/batch.py` `run_batch`).
This is the deterministic policy every P3 scheduling path applies: the batch (`run_batch`), the
season demo (`SeasonScheduler.admit_all`) and the tests. Last checked against the code 5 Nov.

## The rule (from the brief)
- At most **1 non-high-priority survey per farmer per 7 days**, across every survey and channel.
- **High priority is exempt**: it is sent even when the cap is full, and it **still counts**
  toward the window for later surveys.
- An opted-out farmer gets nothing, ever.

## Order of checks for each hand-off
1. **Opt-out** → `opted_out`. Checked again by the broadcaster at send time, so a farmer who opts
   out while another of their surveys is queued never gets it.
2. **Quality gate** → `rejected`: `self_eval.schema_valid` is not true, any P4 guard fails
   (`check_survey`), or the relevance score is below the threshold P4 supplies (equal passes).
   A rejected survey never reaches the cap, so it cannot take the farmer's weekly slot.
3. **Weekly cap** → one of:

| decision | when | what happens |
|---|---|---|
| `sent` | within the cap, or high priority | scheduled as-is; counts toward the window |
| `moved` | capped, and a later start at least 7 days after every blocking send is still `<= not_after` | the window now opens on that day (same clock time, 07:00); `not_after` and `expires_at` stay exactly as they were |
| `merged` | capped, cannot move, and an earlier survey to the same farmer is still open on this survey's first day, with room for its insight IDs | the host survey goes out once; **all** contributing `source_insight_ids` are recorded on it (order kept, no duplicates, at most 5 = `survey.schema.json` maxItems) |
| `skipped` | capped, cannot move, no eligible host | dropped |

"7 days" is exact: 6 days 23:59 apart is capped, exactly 7 days is eligible, in either order.

## Send order (and why a move is placed late)
Hand-offs are decided in send-window-start order. Ties at the same instant are broken by the
optional frequency rank (higher first), then created time, farmer and `handoff_id`; a rank never
moves a survey ahead of one that opens earlier. A **moved** survey is put back in that order at
its new start and decided again when its turn comes. Otherwise a high-priority survey opening in
between would be missed and the moved survey could land inside its week (9 cases on the full
pack before this was fixed).

## Repeats
Admitting the same `handoff_id` again returns the first decision and counts nothing.

## Counts for P5 (`run_batch(...).counts`, all from actual decisions)
`sent`, `moved`, `merged`, `skipped`, `opted_out`, `rejected`, `duplicates`,
`prevented` = skipped + opted_out + rejected (the gate working: **not** violations), and
`cap_violations` = an independent audit of what goes out: non-high-priority sends less than 7
days after another send to the same farmer. It should be 0 (full pack: 0).

## Evidence
`tests/test_p3_completion.py` (boundary, both orders, exemption, move window, move after a high,
merge limit, duplicates, rejected-before-cap, opt-out after queuing), `tests/test_batch.py`,
`tests/test_schedule.py`.
