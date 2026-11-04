# P5 plan: Evaluation & Demo

Source of truth: the FINAL Team Contracts (4 Nov), which now include Digital Green's Vision and Technical
documents. Updated 4 Nov 2026.

## What P5 must deliver (FINAL contract)
- A scorecard covering Digital Green's five dimensions (relevance, timeliness, format, safety, speed), next
  to our decision and rule accuracy.
- Relevance scored by an **AI judge on Amazon Bedrock**, checked against 20 surveys the team scores by hand.
- A **run history**: every eval run saved, with a chart per dimension. At least one improvement shown.
- The 3-minute demo, including the simulated clock moving through the season. Slides, two clean-checkout
  rehearsals, a backup video.
- Bedrock is **required** for every model call (no longer optional). App Runner hosting stays optional.

## Where things stand (4 Nov)
| Contract item | Status |
|---|---|
| Per-rule confusion matrix, item similarity | Done |
| Format, safety, speed on all 6,999 insights | Done |
| Timeliness (after the action window, 07:00–19:00, in season, before harvest) | Done |
| Run history + chart with a dimension picker | Done: runs 1–3 recorded |
| At least one improvement run | Done: run 2 (R7 storage fix, 96.0% → 99.3%), run 3 (answer-key send-time setting) |
| "Rules we changed" list | Done: generated from the history (README, app, offline scorecard) |
| Both timing numbers shown | Done: README, app toggle, demo script |
| README numbers by script; offline scorecard | Done (`mel/evaluation/report.py`) |
| Follow-up queue page | Done; switch to P3's outcomes with late answers when they land |
| Every `mel.cli eval` appends to the history | **Waiting on P1** to call `run_eval()` from `cmd_eval` |
| AI judge on Bedrock + 20 hand-scored surveys | Not started: needs P1's Bedrock access |
| Season screen with the simulated clock | Not started: needs P3's `SimClock` and `broadcast_due` |
| Templates-vs-Bedrock table, token/cost/time totals | Waiting on P4 |
| Slides, rehearsals, backup video | H+36 |

**Finding worth showing:** the answer-key send-time setting matches the answer key 100%, but only 26.5% of
its send windows pass the timeliness check. 1,982 surveys would open before the farmer's action window ends.
The brief rules pass 100%. That is the evidence for keeping the brief as the default.

## Next steps
**Workstream B: AI judge (needs Bedrock access from P1)**
- `mel/evaluation/judge.py`. Rubric: Digital Green's if they have one (P1's question 4), otherwise ours from
  the Vision principles: one farmer, one context; asks about the advice given; no new advice; short and
  tappable. Scores 1–5 with a reason.
- Uses P4's `ModelClient` once merged, else a small Bedrock `converse` adapter. Small model, IAM role, no key.
  Off by default (`MEL_JUDGE=1`), cached on disk, tokens/cost/time logged. Runs on the 95 answer-key surveys.
- `docs/results/hand_scores.csv`: 20 surveys scored by the team; report how often the judge agrees.
- `boto3` in `requirements.txt` is a shared change: post in chat first.

**Workstream C: plug in teammates' work as it merges (P5 reviews P1 and P3 PRs)**
- P3: follow-up queue from their outcomes (late answers shown); cap / opt-out / skip-move-merge counts on
  Overview; "failing but scheduled" read from their gate; a Season screen with the clock.
- P4: read `self_eval` and `GuardResult.codes`; agree a relevance threshold; templates-vs-Bedrock table.
- P1: `RunResult` adapter for `score_golden`; one REST API example in the Q&A.

**Workstream D (H+36):** slides (one per changed rule; AWS slide with Bedrock built and the rest "not
built"), two clean-checkout rehearsals, backup video, freeze with P1.

## Messages to send
- **P1:** call `mel.evaluation.run_eval()` from `cmd_eval` (3 lines); Bedrock region/model + IAM access for the
  judge; Digital Green question 4 (relevance rubric).
- **P2:** runs 2 and 3 recorded from your merge. The contract still describes the R7 misses backwards. G-0145
  (one-day 31 March window) is the last miss under the brief rules.
- **P3:** your `simulate` changes touch the app's Simulate and Follow-up tabs; tell P5 before merging.
- **P4:** your branch conflicts with `main`; send the `self_eval` field names; agree the relevance threshold.

## How to record an improvement
```
python scripts/readme_numbers.py --write --record "what changed"
```
Add `--basis brief` or `--basis answer_key` to record only one send-time rule. Commit the README,
`docs/results/scorecard.md` and `docs/results/eval_history.jsonl` together with the change.
