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

## Next
- Run the judge on all 94 survey rows (`MEL_JUDGE=1 python -m mel.evaluation.judge --run`). This gives an AI
  relevance score to put beside P4's rule-based relevance (0.69).
  - The judge's score is on a 1 to 5 scale, and P4's relevance is 0 to 1.
- Possible rubric v2: tell the judge to give a 3 to any question that doesn't name the advised action.
- Switch the judge to P4's `ModelClient`.
