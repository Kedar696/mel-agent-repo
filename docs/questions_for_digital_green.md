# Questions for Digital Green

Draft from P1. P1 sends them; nobody else contacts the organisers. Every number below comes from the pack
(`mel-survey-agent-participant-pack/participant-pack/`) or from running our code at commit 5763855 on 4 Nov.
Our code applies the brief's rule: that is why "ours" differs from the answer key in the examples.

## 1. Do survey windows open at 09:00 or at 07:00?

The brief and the five worked scenarios open the window at 07:00 on a later day. The golden set (the answer key)
opens it at 09:00, and on different days. Our window score against the answer key is 0%, so we need to know
which one you want.

What the brief says (`rules.json` `window_rules`): earliest start day 1, never before the action window ends,
`not_before_time` 07:00, `not_after_time` 19:00. The worked scenarios follow it:

| Scenario | Insight created | Action window | Window in the brief |
|---|---|---|---|
| 1 mustard aphid spray | 2026-12-04 09:12 | 2 days | 2026-12-06 07:00 to 2026-12-09 19:00 |
| 2 wheat irrigation timing | 2026-12-08 18:40 | 5 days | 2026-12-13 07:00 to 2026-12-18 19:00 |
| 4 cow vet escalation | 2026-12-15 07:30 | 1 day | 2026-12-16 07:00 to 2026-12-18 19:00 |

What the golden set says, with the same fields:

| Golden id | Insight created | Action window | Answer key window | Our window (brief rule) |
|---|---|---|---|---|
| G-0002 (wheat, plan created, `seven_to_fourteen_days`) | 2026-11-06 06:06 | 8 days | 2026-11-13 09:00 to 2026-11-20 19:00 | 2026-11-14 07:00 to 2026-11-20 19:00 |
| G-0003 (cabbage, do not act, `three_to_ten_days`) | 2026-11-12 09:40 | 10 days | 2026-11-15 09:00 to 2026-11-22 19:00 | 2026-11-22 07:00 to 2026-11-24 19:00 |

Take G-0002. The answer key opens the window 7 days after the insight, which is before the 8-day action window
ends. The brief says a survey should not go out before the action window ends. So in G-0002 the two documents
disagree on the time (09:00 vs 07:00) and on the day.

Questions:
- Is 07:00 (brief) or 09:00 (golden set) the correct opening time?
- Can a survey open before the action window ends, as in G-0002 and G-0003? Or does the brief rule win?
- Which one will you score us against in the final judging?

## 2. Critical cases: a survey, or a human call?

The golden set has 6 rows with `severity: critical` (G-0016, G-0030, G-0076, G-0078, G-0108, G-0138). All six
expect no survey: rule R2, reason code `critical_needs_human_call`. But `rules.json` lists `critical` under
`priority.high_if_severity`, which reads as "send a high-priority survey".

Examples from the answer key:
- G-0030: buffalo not eating and feeling hot. The advice was to call the nearest vet today. Expected: no survey.
- G-0016: pea leaves with white winding lines. The advice was to remove leaves and spray neem oil. Expected: no survey.
- G-0076: aphids on wheat. The advice asked for more details first. Expected: no survey.

Questions:
- For `critical` insights, do you want (a) a high-priority survey, or (b) no survey and a person calls the farmer?
- If (b), where do we record the call request? We only write a no-survey record with the reason text today.
- G-0016 and G-0076 are not obviously emergencies. Is the severity label the only trigger, as we assume?

## 3. Is a new golden set coming?

Our scores are measured on the 150 rows we have (decision 96.0%, rule 96.0%, channel 100%, window 0% on the
full pack with our code at that commit). We have a script that compares an old and a new golden file
(`scripts/compare_golden.py`) and a short checklist to re-run everything.

Questions:
- Will there be a second version of the golden set (v2)? If yes, when, and in the same format?
- If the windows in v2 change (question 1), should we expect other columns to change too?
- Is the current answer key final for the rule ids R1 to R8? The rule ids are not in the brief; we inferred them
  from the golden rows.
