# Frequency-cap policy: two surveys in one week (P3)

Owner: P3 (`mel/schedule/handoff.py`, `CapLedger`). This documents the deterministic
decision the cap ledger makes when more than one survey would go to the same farmer
inside the 7-day window. It implements the brief's rule and the H+4 decision to add
`CapLedger.admit()` (`docs/h4_interface_decisions.md`, row 12).

## The rule (from the brief)
- At most **1 non-high-priority survey per farmer per 7 days**, counted across every
  survey and every channel.
- **High priority is exempt**: it is sent even when the cap is full, and it still counts
  toward the window for later surveys.
- An opted-out farmer gets nothing, ever.

## The decision: `CapLedger.admit(handoff, opt_out=None) -> Admit`
`Admit.decision` is one of five words:

| decision | when | what happens |
|---|---|---|
| `sent` | within the cap, or high-priority (exempt) | scheduled as-is; counts toward the window |
| `opted_out` | the farmer is on the opt-out list | nothing is sent |
| `moved` | capped, but a later day still inside this survey's `[not_before, expires_at]` is free | rescheduled to that day (07:00 kept); window width and expiry recomputed |
| `merged` | capped, cannot move, and an earlier survey to the same farmer is still open on this survey's open day | questions ride along with that earlier survey; **both** surveys' `source_insight_ids` are preserved |
| `skipped` | capped, cannot move, and no open survey covers this day | dropped |

## Why move-before-skip, and why merge is narrow
The task says: *prefer moving a capped survey to the next eligible date only if it stays
inside its send window and expiry; otherwise skip.* So:

1. **Move first.** The earliest day at least `window_days` (7) after the blocking send,
   that is still `<= not_after`, keeping the 07:00 start. If that day exists, move there.
   This respects the brief's send window and expiry: a survey is never pushed past the
   point where its answer would still be fresh.
2. **Merge only when it is genuinely one conversation.** If the survey cannot move but an
   earlier survey to the same farmer is *still open on this day* (its window covers this
   survey's `not_before`), the two are folded into one so the farmer answers once. Source
   insight IDs from both are kept (order preserved, de-duplicated) so provenance is not
   lost. Merge is deliberately narrow: it never hides a drop behind a survey whose window
   has already closed.
3. **Skip otherwise.** If it can neither move nor merge, it is dropped — the farmer is at
   their weekly limit and there is nothing to attach to.

## Determinism
No randomness. Given the same hand-offs in the same order, `admit()` always returns the
same decisions. `CapLedger.allow()` (the original yes/no gate) is unchanged and still used
by the Streamlit replay; `admit()` is layered on top of the same bookkeeping.

## Evidence / tests
`tests/test_schedule.py`:
`test_admit_first_survey_is_sent`, `test_admit_opted_out_blocks`,
`test_admit_high_priority_is_exempt_but_counts`,
`test_admit_second_normal_in_same_window_merges_and_preserves_insight_ids`,
`test_admit_moves_when_a_later_date_fits_the_window`,
`test_admit_skips_when_cannot_move_or_merge`, `test_allow_still_works_as_before`.
