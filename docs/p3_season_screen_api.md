# Season screen: the P3 API for the demo's simulated-clock walk

From: P3 (Scheduler, Channels & Simulator)
To: P5 (Evaluation & Demo — owner of `app/streamlit_app.py`)
Status: **P3 API ready and tested. UI not yet wired.** P3 has not edited `app/`.

`docs/p5_plan.md` lists the Season screen as "Not started: needs P3's SimClock and
`broadcast_due`." Those now exist, plus a season driver that ties the scheduler and
broadcaster to one shared clock and exposes a manual per-step trigger. This note is the
integration point: the callable P3 API P5 drives from the Streamlit tab, so the UI change
stays small and lives entirely in P5's file.

## What P3 provides (all in `mel.schedule`, tested in `tests/test_season.py`)
```python
from mel.schedule import SeasonScheduler, Season

sched = SeasonScheduler(relevance_threshold=0.5)   # starts at the rabi season's 1 November
sched.admit_all(handoffs)                           # cap + opt-out gate; queues sent/moved/merged
```

The scheduler and broadcaster read time from **one shared `SimClock`**
(`sched.clock is sched.broadcaster.clock`); nothing reads the system clock, so the walk is
deterministic.

### Driving the clock (requirement 2: move through Nov–March quickly)
| Call | What it does |
|---|---|
| `sched.now_ist()` | current simulated instant, e.g. `"2026-11-01T07:00:00+05:30"` |
| `sched.advance(days)` | move the shared clock forward whole days; **clamps at the season end** |
| `sched.advance_to_end()` | jump to the season's last instant (fast-forward to end of March) |
| `sched.in_season()` / `sched.is_season_over()` | where the clock sits relative to the range |
| `sched.season.start_ist` / `sched.season.end_ist` | the configured range bounds |

The season range is configurable: `SeasonScheduler(relevance_threshold=..., season=Season(
start="2026-11-15T07:00:00+05:30", end="2027-02-28T19:00:00+05:30"))`. The default is the
rabi season from config: 1 November 07:00 to `window_rules.season_end` (2027-03-31) 19:00.

### The manual trigger (requirement 3: one step per click)
| Call | What it does |
|---|---|
| `sched.step()` | run exactly **one** due scheduled step (one channel attempt), return a `StepResult` |
| `sched.run_due()` | fire every step due at the current instant, one `step()` at a time |
| `sched.pending` | hand-offs still queued, in send-window order |

`StepResult` fields: `kind` (`"sent"` or `"nothing"`), `handoff_id`, `channel`, `record`
(the simulated `response` record for a sent step, schema-valid), and `reason`.

## Suggested Season tab (sketch — P5 writes this in `app/streamlit_app.py`)
```python
# One scheduler per session, built from the pipeline's hand-offs.
if "season" not in st.session_state:
    sched = SeasonScheduler(relevance_threshold=THRESHOLD)   # THRESHOLD agreed with P4/P5
    sched.admit_all([o["handoff"] for _, o in rows if "handoff" in o])
    st.session_state.season = sched
sched = st.session_state.season

st.metric("Simulated date", sched.now_ist())
c1, c2, c3 = st.columns(3)
if c1.button("Advance 1 day"):   sched.advance(1);  st.rerun()
if c2.button("Advance 1 week"):  sched.advance(7);  st.rerun()
if c3.button("Fast-forward to March"): sched.advance_to_end(); st.rerun()

if st.button("Trigger next due step", disabled=sched.is_season_over()):
    r = sched.step()
    if r.kind == "sent":
        st.success(f"Sent {r.handoff_id} on {r.channel} — status {r.record['status']}")
    else:
        st.info(r.reason)

st.caption(f"{len(sched.pending)} hand-off(s) still queued · "
           f"{'season over' if sched.is_season_over() else 'in season'}")
```

Notes for P5:
- `relevance_threshold` must be the number the team agreed (P4/P5 decision, see
  `docs/p5_plan.md` "agree a relevance threshold"). P3 invents none.
- Delivery stays simulated: `step()` calls `mel.simulator.simulate()`. No real messaging.
- Each `step()` returns one record, so the tab can show progress one farmer/channel at a
  time rather than processing the whole queue silently.
- Persona is selectable: `SeasonScheduler(..., persona="app_push_dead")` etc., reusing the
  simulator's existing personas, to demo fall-back and opt-out.

## Scope
This adds a Season tab to P5's app and reads the P3 API above. It does not change any
existing P3 behaviour (schedule window, send hours, expiry, cap, opt-out, quality gate, and
the simulator are all unchanged) and adds no external messaging.
