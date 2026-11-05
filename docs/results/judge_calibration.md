# Is the AI relevance judge trustworthy? (calibration, 4 Nov 2026)

Digital Green scores relevance with an "LLM-as-judge". Before we use the judge's score for all surveys,
we check it against people. Owner: P5.

## What we did
- **Sample:** 20 of the 94 golden-set surveys, 4 for each advice type (`docs/results/hand_scores.csv`).
- **People:** 5 team members (Kedar, Lucas, Michael, Semdon, Will) scored all 20 surveys, 1 to 5, each
  on their own, using `docs/results/hand_scoring_guide.md`. That gives 100 scores.
- **Judge:** Claude Haiku 4.5 on Amazon Bedrock (`us.anthropic.claude-haiku-4-5-20251001-v1:0`, us-east-1),
  rubric v1 (in `mel/evaluation/judge.py`). The judge scores the exact question text people saw
  (`survey_from_text`). The live templates have improved since the sheet was made, so it must not score
  the newer surveys instead.
- **Command:** `MEL_JUDGE=1 python -m mel.evaluation.judge --calibrate`

## Results
| | Same score | Within 1 point | Average gap | Follows the group's ranking (r) |
|---|---|---|---|---|
| **AI vs each person** | 44% | **95%** | **0.63** | **0.58** |
| Person vs person (all 200 pairs) | 37% | 83% | 0.82 | 0.00 to 0.49 (each person vs the other four) |
| "Always say 5" | 44% | 79% | 0.79 | n/a |
| "Always say 4" | 35% | 99% | 0.67 | n/a |

The r column is a correlation over the 20 surveys, from 0 (no link) to 1 (same ranking). It shows whether a
scorer rates surveys higher and lower in the same places as the team's average does.

## What it means
- **The AI agrees with people at least as well as people agree with each other.** Its average gap from a person
  (0.63) is smaller than the gap between two people (0.82).
- **The AI tells better and weaker surveys apart.** It gave 8 surveys a 4 (people averaged 3.9 on those) and 12
  surveys a 5 (people averaged 4.4). It follows the team's average ranking (r = 0.58) more closely than any
  single person does (0.00 to 0.49).
- **Lead with the ranking result, not "95% within 1 point".** People scored mostly 4s and 5s, so even
  "always say 4" lands within 1 point 99% of the time.

## Limits (say these out loud)
- The sample is small: 20 surveys, all written from P4's templates. The AI used only 4 and 5.
- **The AI is a little lenient.** It gave the generic "Did you follow the advice for your mustard?" a 4, where
  the rubric says 3 ("does not check the specific action").
- **The AI missed a data error that a person caught.** For G-0129 (cauliflower), the advice talks about "grain
  for eating". The AI gave it a 5; one reviewer gave it a 1 (people's average 3.4). This case is already on
  the list of questions for Digital Green.

## What people's scores say about the surveys
- The average is 4.2 out of 5.
- Lowest: plans (3.85) and "do this" advice (3.95). Their questions didn't name the actual step. P4's newer
  templates do (for example, "Did you top-dress urea?").
- Highest: "call an expert" (4.8).

## All 94 golden-set surveys (current templates, 4 Nov)
`MEL_JUDGE=1 python -m mel.evaluation.judge --run`. Results are in `out/judge_results.jsonl`, which is not in git.

- **Average AI relevance: 4.82 out of 5.** 78 surveys got a 5, 15 got a 4, 1 got a 3. No survey scored 1 or 2.
- **By advice type:**
  - plan 5.00
  - don't act 4.92
  - call an expert 4.91
  - do this 4.72
  - wait and watch 4.67
- **Cost and time:** 94 calls, 37,635 input tokens and 6,684 output tokens, 65 seconds in total.
- **Why surveys lost a point:** almost always the second question was generic.
  - In most cases this was "How is your goat now?" or "Do you need more help?" after a specific first question.
  - The one 3 was G-0090 (cabbage): "Did you compare mandi prices?" followed by "How is your cabbage now?". A
    price check doesn't change how the crop is doing.
  - Ideas for P4: make the outcome question match the concern (the templates already have a `concern` style),
    and make the wait-and-watch second question about whether the problem grew, not "Do you need more help?".
- The judge's 1 to 5 score sits beside P4's rule-based relevance (0 to 1, 0.69). They aren't on the same scale.
  Keep them side by side rather than turning one into the other.

## Decision: the send bar and plan questions (4 Nov, P4 + P5)
- **Send bar = 0.3** (`mel.writer.RELEVANCE_THRESHOLD`; P3's quality check enforces it). P4's relevance score
  agrees only weakly with people (r = 0.29 on 18 hand-scored surveys; the AI judge: 0.58). At 0.5, it blocked 552
  of 2,616 surveys (21%), including specific ones such as "Did you treat the nursery bed?". At 0.3, it blocks only
  surveys that name neither the crop, the problem nor the advice.
- **Plan surveys ask about the plan's first step and name the crop.** For example: "Did you apply zinc?", then
  "Is the plan working for your mustard so far?". Before, they asked the generic "How much of the plan have you
  done?", which people scored lowest (3.85). The answer key's wording is kept as the fallback.
  - On all 6,999 insights: P4's relevance went from 0.72 to 0.82 on average, and surveys below 0.3 went from 80
    to 0.
  - Item similarity with the answer key stays 0.99, and the safety checks still have 0 failures.
  - Season walk: 2,066 sends, 0 blocked (before: 1,711 sends, 355 blocked at 0.5).

## Next
- Possible rubric v2: tell the judge to give a 3 to any question that doesn't name the advised action. It is
  a little lenient now.
- Switch the judge to P4's `ModelClient`.
