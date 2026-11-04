# Hand-scoring 20 surveys (about 15 minutes)

**Why:** Digital Green wants survey relevance scored by an AI judge. To show the judge can be trusted, we
score 20 surveys ourselves and check how often it agrees with us. The team contract makes this a P5 task
that needs everyone's help.

**What to open:** `docs/results/hand_scores.csv` (Excel, Numbers and Google Sheets all open it).

Each row is one farmer conversation and the survey we wrote for it:
- `farmer_asked`: what the farmer asked FarmerChat
- `advice_given`: what FarmerChat told them
- `questions`: the survey we would send, with its answer buttons in brackets

**What to fill in:**
- `score_1_to_5`: your score (see below)
- `scorer`: your initials
- `notes`: optional, one line on why

Score on your own, without looking at what others gave. If more than one person scores the same row, add
a new row with the same `golden_id` instead of overwriting theirs.

## The scale
| Score | Meaning |
|---|---|
| **5** | Asks directly whether the farmer did *this* advice and whether it worked. Every question fits this farmer's crop or animal and problem. Short, tap-to-answer. |
| **4** | Clearly about this advice, but one question is generic or slightly off. |
| **3** | Right crop or problem, but doesn't check the specific thing that was advised. |
| **2** | Mostly generic: could be sent to any farmer. |
| **1** | Irrelevant, gives new advice, contradicts the advice, or asks for personal information. |

Example: the advice was "don't spray the same insecticide again yet", and the survey asks *"Did you hold
off as advised?"* and *"How is your cabbage now?"* That's a **4 or 5**: it checks the exact action (holding
off) and the outcome.

## When you're done
Save the file (keep it as CSV) and commit it on a `p5-` branch, or send it to P5. P5 then runs
`python -m mel.evaluation.judge --calibrate` once Bedrock access is set up.

The same rubric is in the README under "Relevance rubric (AI judge)". If Digital Green sends their own MEL
rubric, P5 swaps it in and we rescore.
