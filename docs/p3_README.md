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

## Test status (this branch)
- Full suite: **524 passed**
- P3 group (frequency + schedule + simulator + broadcast + season): **all passing**
- `mel.cli validate`: 47 files checked, 0 invalid
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
- **P4:** none — the quality gate reads the `self_eval` block P4 already writes.
