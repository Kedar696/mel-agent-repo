# P2: decisions, timing and crop harvest

Existing interfaces remain unchanged:

```python
from mel.decision import decide
from mel.timing import send_window, expires_at, is_past_harvest

decision = decide(insight)
window = decision.send_window  # {not_before, not_after}, or None

decision = decide(insight, now=sched.clock.now())  # with P3's simulated clock
window = send_window(insight, now=sched.clock.now())
```

## Decision order

| Rule | Result | Trigger |
|---|---|---|
| R1 | No survey | Junk, invalid schema, or impossible timestamp |
| R2 | No survey; human call required | Critical severity, as specified by the v1 answer key (`MEL_CRITICAL_POLICY=survey` turns R2 off) |
| R3 | No survey | General information without actionable advice |
| R4 | No survey | Waiting for more details |
| R5 | No survey | Verification not needed |
| R6 | No survey | No usable send window remains before season end; with `now`, too little of the window is left (`window_passed`) |
| R7 | No survey | Standing-crop advice would arrive after the harvest period |
| R8 | Survey | All preceding checks pass |

R1 has precedence over R2, and so on. No-survey records keep the original schema's
two reason-code values, with the precise rule and reason in the `reason` text.
Invalid or absent IDs become `unknown` so rejected inputs still produce valid records.
R2 reports the need for a person to call; P2 does not place or queue a real call.

## Two timing policies

`MEL_TIMING_BASIS=brief` is the default. It reproduces the five worked scenarios:

- Count days from the insight's date in IST, not elapsed 24-hour periods.
- Use the configured timing offsets and wait until the action window ends.
- Treat a null action window as the configured two days; preserve an explicit zero.
- Open no earlier than the next day at 07:00 and close at 19:00.
- Require at least two days between the start and end dates.
- Clip to 31 March 2027. Reject a window if clipping leaves it too short.
- Expire two days after the final window close.

`MEL_TIMING_BASIS=answer_key` reproduces the incompatible v1 reference convention:

- Ordinary windows open at 09:00 using timing offsets without the action deadline.
- Seasonal windows start at day 30 and end at day 45.
- Same-day windows start four hours after creation and last four hours. A start at
  or after 19:00 moves to 09:00 the next day; a start before 09:00 moves to 09:00.
- Season-end clipping may leave a window shorter than two days.
- Some reference same-day windows end after 19:00. This mode retains those bounds
  for evaluation; the separate scheduler `send_hours` must still be enforced.

No code reads expected results, golden IDs or scenario IDs to make decisions.
The compatibility policy is inferred from v1 examples, not independently validated
agronomic scheduling guidance. Keep brief mode as the delivery baseline until the
organizer resolves the conflict. Unknown policy names raise a configuration error.

## Simulated clock (`now`)

`send_window(insight, now=...)` and `decide(insight, now=...)` take the simulated clock's
instant (P3's `SeasonScheduler.clock.now()`, tz-aware; a naive datetime is an error). P2
never reads the system clock. With `now=None` (the default) nothing changes: the window
is planned from the insight's own date, so scoring, the CLI and the app are unaffected.

- Clock before the planned opening: the window is unchanged.
- Clock past the opening: the window opens at the next send hour (now if between 07:00
  and 19:00, else 07:00 that morning or the next) and keeps its planned end.
- Fewer than the brief's two days left (the same rule as the season-end clip): no window,
  so `decide` returns R6 with reason `window_passed`. Answer-key mode, which allows
  shorter windows, only needs some time left.
- R7 then checks the harvest against the moved opening day.

## Harvest checks

Only rows whose `growth_stage` is `harvest` determine the standing-crop cutoff.
Post-harvest storage rows do not extend that cutoff. The last harvest day is still
allowed; the following day is past harvest. Crop keys are normalized, with aliases
for chickpea/gram and peas/pea. Named crops missing from the calendar fall back to
the configured season end; a missing name remains unknown.

R7 exempts insights explicitly marked `post_harvest` or `storage_post_harvest`:
stored produce may still need follow-up after the field crop has been harvested.
It does not infer a storage stage from free text, and the answer key agrees: G-0129
and G-0136 both say "stored cauliflower", but only G-0129 sets `growth_stage:
post_harvest`, and the key expects R8 for G-0129 and R7 for G-0136. Both match today.

## Send time

For surveys, `decision.send_time` picks one moment inside the window:
`{send_at, slot, rule, assumption, reason}`. `decide(insight, farmer=None, history_hours=())`
keeps the old call working; the optional farmers.csv row and `chat_hours(...)` history
only refine the time, never the decision. Rules, first match wins:

| Rule | When | Send at |
|---|---|---|
| `high_severity` | severity high or critical | window opens |
| `advice_evening` | advice text says "evening" | next morning, 07:00-10:00 |
| `usual_time` | call or light user, and past chats cluster in one slot (binomial test, p < 0.01) | that slot |
| `async_channel` | app, web, WhatsApp, Telegram | window opens |
| `harvest_busy` * | call during the crop's harvest period | 16:00-19:00 |
| `livestock_chores` * | call, farmer keeps livestock | 13:00-16:00 |
| `call_default` * | any other call | 16:00-19:00 |

\* Domain assumptions, flagged `assumption: true`; no data supports them. The pack's chat
times are spread evenly over the day, so `usual_time` rarely fires on it.

Downstream: `run_pipeline(insights, farmers=load_farmers())` passes each farmer's profile
and earlier chats, and the senders use the result. `mel.cli run --simulate` and the
Streamlit app call `simulate(..., send_at=decision.send_time["send_at"])` for the first
channel, and the app's hand-off strip shows the recommended time with its reason. The
hand-off JSON itself is unchanged: `schedule_handoff.schema.json` is the organisers' file
(`parity` checks it) and forbids extra fields, so a real scheduler reads the time from
the decision.

## Reproduce validation

From the repository root, activate an environment with the project dependencies:

```sh
MEL_USE_LLM=0 python -m pytest -q
MEL_DATA_DIR=mel-survey-agent-participant-pack/participant-pack/data MEL_TIMING_BASIS=brief MEL_USE_LLM=0 python -m mel.cli eval
MEL_DATA_DIR=mel-survey-agent-participant-pack/participant-pack/data MEL_TIMING_BASIS=answer_key MEL_USE_LLM=0 python -m mel.cli eval
MEL_TIMING_BASIS=brief MEL_USE_LLM=0 python -m mel.cli run --simulate
python -m mel.cli validate
```

On the 150-row bundled golden set:

| Policy | Decision | Rule | Channel | Exact window |
|---|---:|---:|---:|---:|
| Brief | 149/150 (99.3%) | 149/150 (99.3%) | 100% | 0% |
| Answer key | 150/150 (100%) | 150/150 (100%) | 100% | 95/95 (100%) |

Verification: all 64 tests pass. Both policies process all 6,999 bundled insights
without exceptions; no-survey records pass the shared schema. Default-mode windows
meet the action deadline, next-day, minimum-width and season-end constraints.
The mock end-to-end runs, including simulated responses, report zero invalid files
under both policies. These checks cover P2 behavior, not question-writing quality.

The 0% exact-window score follows from the documented policy differences, not a
claim that worked-example timing failed.

## Open cases, decided (5 Nov)

| Case | Decision | Why |
|---|---|---|
| G-0145 (maize, 28 March) | Keep R6 under the brief; answer-key mode gives the key's R8 | The brief says a window "is at least two days wide, and nothing is sent after 31 March". Only 31 March is left, so the brief allows no window. This is the one brief-mode miss (149/150). |
| G-0129 / G-0136 (stored cauliflower) | No change | Storage is read from `growth_stage` / `concern`, never from the text. The key labels both rows that way (above). |
| R2 (critical severity) | Answer key by default; `MEL_CRITICAL_POLICY=survey` gives the brief's reading | The key wants no survey and a human call for all 6 critical rows. The brief only lists critical as high priority. The contract says: until Digital Green answers, keep both behind a setting, default = answer key. |

Any of these changes only if Digital Green answers otherwise or ships a new golden set.

## Weather-dependent advice (written down 5 Nov, not modelled)

Some advice depends on the weather. The brief's mustard example says "spray within 2 days if no rain is
forecast", and the Vision doc asks how the send window should be set then. Today these windows are planned
like any other, from `action_window_days` and the verification timing. The pack has no weather data (P3 found
the same, `docs/p3_frequency_scheduling.md`), and no field says that advice depends on the weather. Only the
free text says it (1,169 of 6,999 full-pack advice summaries mention rain, fog, frost, the forecast or the
weather), and P2 never reads free text.

How we would handle it, once an insight carries a structured condition (say `weather_condition: "no_rain"`)
and FarmerChat passes in the district forecast (it already has weather data through AgMCP):

- Only days that meet the condition count toward the action window. If rain is forecast on one of the two
  days, the farmer has until day 3 to spray, so the window opens a day later. The rest of the brief rule
  stays: 07:00 to 19:00, at least two days wide, nothing after 31 March, and R6 when no room is left.
- The shift is capped (for example at 5 days), so a long wet spell can't push the survey past the point where
  the farmer still remembers the advice.
- Only the window moves. The survey or no-survey decision (R1–R8) never depends on the weather. Without a
  forecast, the window stays as it is today. No weather is invented.

This is question 10 in `docs/questions_for_digital_green.md`.
