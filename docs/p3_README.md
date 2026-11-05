# P3 scheduling & simulation — features on the `Semdon-P3` branch

This README documents the P3-owned work on this branch: a shared simulated clock, a
broadcaster with a manual per-step trigger, a configurable November–March season range, and
frequency-aware survey scheduling. It is a P3 companion to the repo's main `README.md`
(which is P1/P5-owned and not edited here).

Scope: P3 owns scheduling, channel handling, and simulated responses. None of this changes
P1's pipeline/data, P2's decision/timing/calendar rules, or P4's survey writing. Everything
reads only existing project inputs; delivery stays simulated (no real messaging).

---

## 1. Shared simulated clock — `mel/schedule/clock.py`

`SimClock` is a hand-driven, deterministic clock. Time moves only when you call `advance()`,
so a demo or a test reproduces exactly. It never reads the system clock.

- `now()` / `now_ist()` — current instant (tz-aware IST / string).
- `advance(days)` — move forward whole days; rejects negative, non-integer, and `bool`
  (so `advance(True)` can't mean 1). `advance(0)` is a valid no-op.
- `set(when)` — jump to a specific instant (used for season clamping / fast-forward).
- Rejects naive datetimes and offset-less strings (ambiguous).

`Season` defines the date range the demo walks — the rabi season, November to March —
inclusive IST bounds. Defaults come from config so the range and the window maths agree:
start = 1 November 07:00, end = `window_rules.season_end` (2027-03-31) 19:00. Either end is
configurable; `contains(dt)` is the membership test.

Tests: `tests/test_broadcast.py` (clock), `tests/test_season.py` (season range).

---

## 2. Broadcaster with a manual per-step trigger — `mel/schedule/broadcast.py`

`Broadcaster` holds a queue of hand-offs, ordered by **send-window start** (not insertion
order), and decides what goes out at the clock's instant. It is bound to a shared `SimClock`
(`Broadcaster(clock)`) and never acts on its own timer.

- `broadcast_due(relevance_threshold=...)` — the explicit manual trigger. Per hand-off it
  returns one of: `sent`, `waiting` (due but outside send hours), `pending` (window not
  open), `expired` (dropped), `rejected` (failed quality gate, dropped).
- `next_due(...)` / `due_now()` — read-only views of what would send / is due.
- `drop_expired_and_rejected(...)` — a non-sending sweep.

**Quality gate** (`quality_failures`): reads the survey's `self_eval` (`schema_valid`,
`relevance_score`, `gives_new_advice`, `asks_personal_info`). The relevance threshold is
**caller-supplied and explicit** — P3 invents no shared bar. A score equal to the threshold
is eligible.

Tests: `tests/test_broadcast.py`.

---

## 3. Season driver — `mel/schedule/season.py`

`SeasonScheduler` ties the scheduler and broadcaster to **one shared `SimClock`**
(`sched.clock is sched.broadcaster.clock`) so they can never disagree about "now", and adds
a manual per-step trigger so a demo can show progress one step at a time.

- `admit()` / `admit_all()` — gate hand-offs through the opt-out list and frequency cap, then
  queue the ones that are sent/moved/merged.
- `step()` — run exactly **one** due scheduled step (one channel attempt), returning a
  `StepResult` (`sent` / `nothing`). `run_due()` fires every currently-due step, one at a time.
- `advance(days)` — move the shared clock forward, **clamped at the season end** (a
  fast-forward can't run off past March). `advance_to_end()` jumps to the season's last
  instant. `in_season()` / `is_season_over()` report position.

Delivery is simulated: a step calls `mel.simulator.simulate()` at the clock's instant. The
demo UI (P5's Streamlit app) drives this via the API documented in
`docs/p3_season_screen_api.md`.

**Attempt timing** (shared by `step()` and `simulate_handoff`, rules in
`mel.simulator.next_step` / `earliest_send`):
- No answer (`window_expired`, or `push_not_opened` on app) on a channel that is not the last:
  try the next channel after that channel's `wait_hours` (6 h high, 24 h normal, 48 h low).
- Delivery failure (`fall_back_to_next_channel`): next channel after `retry_after_minutes`.
- `retry_same_channel`: same channel again after `retry_after_minutes`, at most two tries;
  each try is its own record (`delivery_attempt`, and `response_key` gets `-a<n>` from try 2,
  so first attempts keep the reference keys).
- The next attempt is moved into send hours. If it would land after the send window's
  `not_after`, the hand-off ends there. The broadcaster also drops any hand-off whose send
  window has closed (counted as `expired`, reason "send window closed"), so nothing is sent
  between `not_after` and `expires_at`.
- Until the wait has passed, `step()` returns "nothing" for that hand-off, however often it
  is triggered. `next_attempt_at(handoff_id)` shows when it becomes due.

**Quality gate:** besides `self_eval` and the P4 relevance threshold, the gate runs P4's
`check_survey()` and rejects any guard failure (for example `label_too_long` or
`duplicate_option_value`), which `self_eval` does not report.

Tests: `tests/test_season.py`.

---

## 4. Frequency-aware survey scheduling — `mel/schedule/frequency.py`

Watches how often farmers ask questions and uses that, with a survey's **existing** priority
and eligibility, to rank/time eligible hand-offs. Full design in
`docs/p3_frequency_scheduling.md`.

- `FrequencyMonitor` — groups question history by `(farmer, topic)` (topic = crop, else
  concern) over a configurable rolling window; flags a `FrequencyPeak` when recent volume
  runs above that pair's own baseline. PII-free (ids/timestamps only); duplicates counted
  once; out-of-order timestamps sorted; sparse history → no peak.
- `SeasonStageContext` — labels a crop's growth stage for a date from P2's crop calendar
  (read-only; does not redefine R7).
- `ClimateContext` — pluggable; **neutral fallback** because the repo ships no climate data.
  Results expose `climate_context_missing`; demo values are labelled `climate_synthetic`.
- `FrequencyScheduler` — `filter_eligible()` enforces the existing protections (opt-out,
  quality gate, send window/expiry, frequency cap) by calling them; `rank()` scores eligible
  hand-offs from priority + peak strength + season stage + optional climate, and explains each
  result. **A peak never bypasses any protection.**

Config: `mel/schedule/frequency_config.json` — every threshold and weight, with documented
defaults. Kept inside the package (not `config/rules/`) so P1's pack-parity check is untouched.

Tests: `tests/test_frequency.py`.

---

## 5. Batch scheduling and the weekly-limit policy — `mel/schedule/batch.py`

`run_batch(handoffs, *, relevance_threshold, simulate=False, persona, seed, cap, opt_out,
reachability, ranker)` is P3's scheduling path for a whole batch. It works on copies (the
caller's hand-offs are not changed) and returns a `BatchResult` (`items`, `handoffs_to_send`,
`responses`, `counts`). `SeasonScheduler.admit_all` uses the same admission code
(`schedule_in_send_order`), so the demo and the batch decide identically.

**The final policy is in `docs/cap_policy.md`** (one place, matches the code and tests). Short
version: opt-out first, then the P4 quality gate (a rejected survey never takes a weekly slot),
then at most one non-high-priority survey per farmer per 7 days: move (inside the survey's own
window and expiry, placed after anything that opens in between), else merge (all insight IDs on
the host, no duplicates, at most 5), else skip. High priority is exempt and still counts.

- **Opt-outs always win**, also when produced during a simulated send (fed back, so a later
  hand-off for that farmer is `opted_out`) and also for a survey already queued (the
  broadcaster checks the same opt-out list).
- With `simulate=True`, each hand-off that goes out is walked through its `channel_order`
  (`simulate_handoff`: fallback, waits, send hours, send window, reachability).
- `counts`: `sent`, `moved`, `merged`, `skipped`, `opted_out`, `rejected`, `duplicates`,
  `prevented` (= skipped + opted_out + rejected; **not** violations) and `cap_violations` (an
  independent audit of what goes out; full pack: 0). All from actual decisions.
- **Not yet called by `mel.cli run`** (P1's file): see `docs/p3_batch_wiring_request.md` for the
  exact patch.

Delivery stays simulated; the broadcaster's only target is `SimulatedApp`.

## 6. Farmer channel reachability — `mel/channels/reachability.py`
`FarmerReachability(load_farmers(), unreachable_by_farmer=...)` answers "can this farmer be
reached on this channel?". The farmers.csv has only `preferred_channel` and no per-channel
reachability column, so the documented rule is: preferred channel always reachable; every
other channel reachable by default (no data rules it out — we do **not** read
`preferred_channel` as "others unreachable"); explicit override marks gaps; an unknown
farmer falls back to all-reachable. `SeasonScheduler(reachability=...)` and
`run_batch(reachability=...)` skip unreachable channels while preserving `channel_order`.
**Input contract to add real data (request to P1):** a `reachable_channels` column on
farmers.csv (pipe-separated) or a provider; until then the fallback above applies.

## 7. Reference-grid comparison tool — `mel/simulator/reference_check.py`
`python -m mel.simulator.reference_check` regenerates each of the 183 reference records and
reports mismatches **by field**, exiting non-zero on any mismatch or if not all 183 are
present. Nothing is ignored by default (the simulator is fully deterministic, including
`response_key`); the `ignore_fields` hook is empty and documented for a future generated ID
only — never a non-ID field. The existing exact-match test
(`test_simulate_matches_all_183_reference_records`) stays as the gate; this is the
human-readable companion for when something drifts.

## 8. Advice-failed persona and follow-up tickets — `mel/simulator/`
- `PERSONAS["sometimes_fails"]`: answers on the first channel, but on about 25% of surveys
  (`advice_fails`) picks the survey's `advice_did_not_work` answer. Which surveys is fixed by
  `reports_advice_failure(persona, survey_id, seed)` (sha256 of seed and survey id), so a seed
  always gives the same failures. `advice_fails_for` lists survey ids that always fail. The other
  five personas are unchanged (tested record-for-record).
- `follow_up_tickets(records, surveys)` (`mel/simulator/follow_up.py`) turns records with
  `needs_follow_up` into one ticket each, with the same fields as P5's Follow-up tab. The tab can
  use it on real simulated records instead of forcing each survey's first flagged answer.
- `is_late(record, expires_at)` counts late answers with today's schema. How a stored record
  marks them is a P1 decision: `docs/h4_schema_change_request_late.md`.

## P5 metrics surfaced
- `SeasonScheduler.metrics()` -> `{"admitted": {...}, "steps": {...}, "dropped": {...}}`.
- `Broadcaster.counts()` -> `{"rejected", "expired", "opted_out"}`. `rejected` includes surveys
  rejected at admission, so the app's "Blocked by quality check" is unchanged in meaning.
- `run_batch(...).counts` -> see section 5. Use `cap_violations` for violations and
  `prevented` for what the gate held back.
- Heads-up for P5: the app's Overview replays the limit with plain `CapLedger.admit` in sort
  order. That replay places a moved survey immediately, so on the full pack it counts 9 moves
  that would land inside a high-priority survey's week. `SeasonScheduler.admit_all` /
  `run_batch` do not.

## Cross-owner requests (not done here, by design — ownership + parity)
- **Batch wiring into the CLI (P1):** `mel/cli.py cmd_run` can call `mel.schedule.run_batch`
  to apply the gate and report the counts (the "thin helper" option in
  `docs/p3_batch_wiring_request.md`). P3 did not edit P1's `cmd_run`/`pipeline.py`.
- **`late` schema field (P1 + Digital Green):** adding the optional boolean `late` to
  `config/schemas/response.schema.json` is P1's change (the schema is pack-parity-checked).
  The P3 side already computes `late` (gated by `MEL_RESPONSE_LATE_FIELD`); flipping that on
  is one constant once the field lands. See `docs/h4_schema_change_request_late.md`.

## Protections preserved across all of the above
Send windows, expiry, send hours, opt-outs, the 1-per-7-day frequency cap, and the survey
quality gate behave exactly as before. The new features orchestrate and rank around these
rules; none of them weaken, redefine, or bypass a protection.

## How to run
```
pytest -q                               # full suite
pytest -q tests/test_frequency.py tests/test_season.py tests/test_broadcast.py   # P3 feature tests
python -m mel.cli validate              # output is schema-valid
python -m mel.cli parity                # repo config still matches the pack
```

## Test status (this branch, 5 Nov)
- Full suite: **673 passed**; P3 test files: all passing (completion tests:
  `tests/test_p3_completion.py`)
- `python -m mel.simulator.reference_check`: 183/183 field-for-field, nothing ignored
- `mel.cli run --simulate` + `validate`: 0 invalid (mock 105 files, full pack 14,847)
- `mel.cli parity`: 0 differences

## Files (P3-owned)
| File | What |
|---|---|
| `mel/schedule/clock.py` | `SimClock`, `Season` |
| `mel/schedule/broadcast.py` | `Broadcaster`, quality gate, send-hours |
| `mel/schedule/season.py` | `SeasonScheduler`, per-step trigger, season clamp |
| `mel/schedule/frequency.py` | frequency monitor + ranking + season/climate context |
| `mel/schedule/frequency_config.json` | frequency thresholds/weights (documented) |
| `tests/test_broadcast.py`, `test_season.py`, `test_frequency.py` | focused tests |
| `docs/p3_season_screen_api.md` | Season-tab API for P5's demo UI |
| `docs/p3_frequency_scheduling.md` | frequency feature design + input contracts |

## Data needed from other owners
- **P1:** for real regional climate, a provider `provider(state, district, date) -> float|None`
  (stress factor in [0,1]); until then the neutral fallback applies. No schema change needed
  for the monitor.
- **P2:** optionally a direct "stage for crop+date" helper for `SeasonStageContext` to delegate
  to; currently it reads the calendar read-only.
- **P4:** publish the relevance threshold (one named value). P3 requires it explicitly and uses
  0.5 only as a labelled stand-in; at 0.5, 552 of 2,616 full-pack surveys are rejected, so the
  number matters. The gate also calls P4's `check_survey()`.
- **P1:** wire `run_batch` into `cmd_run` (`docs/p3_batch_wiring_request.md`); decide the `late`
  field (`docs/h4_schema_change_request_late.md`); add the weekly-limit policy to `README.md`
  (README is P1/P5-owned; the text to link is `docs/cap_policy.md`).
