# P2: decisions, timing and crop harvest

Existing interfaces remain unchanged:

```python
from mel.decision import decide
from mel.timing import send_window, expires_at, is_past_harvest

decision = decide(insight)
window = decision.send_window  # {not_before, not_after}, or None
```

## Decision order

| Rule | Result | Trigger |
|---|---|---|
| R1 | No survey | Junk, invalid schema, or impossible timestamp |
| R2 | No survey; human call required | Critical severity, as specified by the v1 answer key |
| R3 | No survey | General information without actionable advice |
| R4 | No survey | Waiting for more details |
| R5 | No survey | Verification not needed |
| R6 | No survey | No usable send window remains before season end |
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

## Harvest checks

Only rows whose `growth_stage` is `harvest` determine the standing-crop cutoff.
Post-harvest storage rows do not extend that cutoff. The last harvest day is still
allowed; the following day is past harvest. Crop keys are normalized, with aliases
for chickpea/gram and peas/pea. Named crops missing from the calendar fall back to
the configured season end; a missing name remains unknown.

R7 exempts insights explicitly marked `post_harvest` or `storage_post_harvest`:
stored produce may still need follow-up after the field crop has been harvested.
It does not infer a storage stage from free text. The reference's cauliflower R7
row lacks a structured storage marker, even though its text mentions storage;
that ambiguity needs organizer clarification before changing this rule further.

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

The brief mismatch is G-0145: the answer key accepts a one-day 31 March window,
while the brief requires two days. Its 0% exact-window score follows from the
documented policy differences, not a claim that worked-example timing failed.
Critical-case handling also differs between the brief's high-priority rule and
the answer key's human-call rule. R2 currently preserves the existing answer-key
cascade; organizer confirmation is still needed for real use.
