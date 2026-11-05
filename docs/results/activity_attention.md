# Activity attention: before / after

**Why this change:** the beneficiary's representative asked us to focus survey attention on positive CHANGE in a farmer's activity, not on high activity itself. Per `CLAUDE.md`, a deliberate change to the brief is shown with numbers. Attention is OFF by default (scoring and the CLI) and ON in the app.

Full pack: **6,999 insights**.

## Tiers and reasons (attention on)

### Tier totals

| tier | count |
|---|---|
| neutral | 2313 |
| steady_high | 173 |
| surge | 130 |

### Reason totals

| reason | count |
|---|---|
| activity_jump | 44 |
| declining | 83 |
| insufficient_history | 502 |
| none | 1901 |
| quiet_then_high_weight | 86 |

### Tier by activity_level (attention on)

| activity_level | surge | neutral | steady_high |
|---|---|---|---|
| heavy | 11 | 674 | 169 |
| light | 51 | 407 | 0 |
| regular | 68 | 1232 | 4 |

### Priority counts

| | off | on |
|---|---|---|
| high | 286 | 310 |
| normal | 1905 | 1755 |
| low | 425 | 551 |

### Weekly cap (sent / moved / merged / skipped / opted_out)

| | off | on |
|---|---|---|
| sent | 1614 | 1631 |
| moved | 452 | 442 |
| merged | 442 | 440 |
| skipped | 108 | 103 |
| opted_out | 0 | 0 |

### Average questions per survey, by activity_level

`on + history` is how the app runs (both history rules and attention on); compare it with `off + history`, since history alone changes the question counts.

| activity_level | off | on | off + history | on + history |
|---|---|---|---|---|
| heavy | 2.495 | 2.4 | 2.713 | 2.557 |
| light | 2.489 | 2.489 | 2.0 | 2.092 |
| regular | 2.502 | 2.501 | 2.693 | 2.692 |

### Golden set (decision / rule / channel / item similarity)

| metric | off | on |
|---|---|---|
| decision_acc | 99.3% | 99.3% |
| rule_acc | 99.3% | 99.3% |
| channel_acc | 100.0% | 100.0% |
| item_similarity_avg | 0.991 | 0.977 |

### Scorecard (format / safety / timeliness must stay 100%)

| metric | off | on |
|---|---|---|
| format_pass | 100.0% | 100.0% |
| safety_pass | 100.0% | 100.0% |
| timeliness_pass | 100.0% | 100.0% |
| failed_but_scheduled | 0 | 0 |

## Notes

- Decision, rule and send window are identical off vs on (asserted in this script and in `tests/test_activity.py`): attention only moves priority, question count and the send moment.
- A prototype on raw data flagged far more (≈109 quiet_then_high_weight, ≈63 activity_jump, ≈303 steady_high); those did not go through the real pipeline (which drops junk, counts distinct conversations, and respects the 28-day/dataset-start rule), so the real counts are lower. The thresholds in `config/activity_attention.json` are starting values to adjust with this evidence.
