# Is the AI relevance judge trustworthy? (calibration, 4–5 Nov 2026)

Digital Green scores relevance with an "LLM-as-judge". Before we use the judge's score for all surveys, we check
it against people, and we pick the model that agrees with people best for the money. Owner: P5.

## What we did
- **Sample:** 20 of the 94 golden-set surveys, 4 for each advice type (`docs/results/hand_scores.csv`).
- **People:** 5 team members (Kedar, Lucas, Michael, Semdon, Will) scored all 20 surveys, 1 to 5, each on their
  own, using `docs/results/hand_scoring_guide.md`. That gives 100 scores.
- **Judge:** rubric v1 (in `mel/evaluation/judge.py`), on Amazon Bedrock through P4's `ModelClient`. The judge
  scores the exact question text people saw (`survey_from_text`), not newer versions of the surveys.
- **Which model:** every text model our account can call judged the same 20 surveys
  (`python -m mel.evaluation.judge_models --run`; results in `docs/results/judge_models.json`, shown on the
  Dashboard). The pick is the **cheapest model whose quality is close to the best**: ranking match within 0.10 and
  average gap within 0.15 of the most accurate model. Token prices come from the AWS Price List API
  (`docs/results/bedrock_prices.json`).
- **Commands:** `MEL_JUDGE=1 MEL_JUDGE_MODEL=google.gemma-3-12b-it python -m mel.evaluation.judge --calibrate`,
  then `--run`.

## Which model (88 text models listed in us-east-1, 70 ranked)
| Close to the best | Ranking match (r) | Within 1 point | Average gap | Cost per 1,000 surveys |
|---|---|---|---|---|
| **Gemma 3 12B (Google), the pick** | **0.72** | **97%** | **0.54** | **$0.05** |
| Claude Opus 4.8 | 0.71 | 91% | 0.58 | $4.63 |
| Claude Opus 4.7 | 0.68 | 96% | 0.56 | $4.46 |
| Claude Haiku 5.5 | 0.64 | 90% | 0.64 | $0.25 |
| GPT-6 Luna | 0.62 | 91% | 0.58 | price unknown |

- **Others for comparison:**
  - Claude Sonnet 4.6 ties Gemma on r (0.72) but has a larger gap (0.73), at $1.99.
  - Claude Haiku 4.5, our first judge, scores r 0.58, gap 0.63, at $0.74.
- **11 models gave every survey a 5** (for example Mistral Large 3, GLM 5, Llama 4 Maverick). They come last: a judge
  that cannot tell surveys apart is no use.
- **Three thinking models answered only 9 to 13 of the 20 surveys** (Grok 4.6 and 4.7, Kimi K2 Thinking). They are
  listed but not ranked.
- **8 models could not run, for reasons outside our code:**
  - Claude Fable 5 and 5.1 need a data-retention setting the account lacks.
  - GLM 5.3 and GPT-6.1 Terra are not enabled for the account.
  - Four are not chat models.
- **Caveat:** with 70 models on 20 surveys, part of the top spot is luck. Gemma leads on all three quality measures,
  at a fraction of the cost of the models it ties with, so it is a safe pick. Still say "on 20 hand-scored surveys".

## Results with the pick (Gemma 3 12B)
| | Same score | Within 1 point | Average gap | Follows the group's ranking (r) |
|---|---|---|---|---|
| **AI vs each person** | 50% | **97%** | **0.54** | **0.72** |
| Person vs person (all 200 pairs) | 37% | 83% | 0.82 | 0.00 to 0.49 (each person vs the other four) |
| "Always say 5" | 44% | 79% | 0.79 | n/a |
| "Always say 4" | 35% | 99% | 0.67 | n/a |

The r column is a correlation over the 20 surveys, from 0 (no link) to 1 (same ranking). It shows whether a scorer
rates surveys higher and lower in the same places as the team's average does.

## What it means
- **The AI agrees with people more closely than people agree with each other.** Its average gap from a person
  (0.54) is smaller than the gap between two people (0.82).
- **It tells better and weaker surveys apart.** It used 3, 4 and 5. It follows the team's average ranking
  (r = 0.72) more closely than any single person does (0.00 to 0.49).
- **Lead with the ranking result, not "97% within 1 point".** People scored mostly 4s and 5s, so even "always say
  4" lands within 1 point 99% of the time.
- **It costs almost nothing:** about $0.05 per 1,000 surveys, about 13 cents for a whole season of 2,616 surveys.

## Limits (say these out loud)
- **The sample is small:** 20 surveys, all written from P4's templates.
- **The cauliflower case (G-0129).** The advice talks about "grain for eating". Gemma gave the survey a 4. People
  averaged 3.4, and one reviewer gave it a 1 because of the data error. The case is on the list of questions for
  Digital Green. (The first judge, Haiku 4.5, gave it a 5.)

## What people's scores say about the surveys
- The average is 4.2 out of 5.
- Lowest: plans (3.85) and "do this" advice (3.95). Their questions didn't name the actual step. That led to the
  plan-question change below.
- Highest: "call an expert" (4.8).

## All 94 golden-set surveys (current templates, 5 Nov)
`MEL_JUDGE=1 MEL_JUDGE_MODEL=google.gemma-3-12b-it python -m mel.evaluation.judge --run`. Per-survey results are in
`out/judge_results.jsonl`, not in git. The summary is in `docs/results/judge_summary.json`.

- **Average AI relevance: 4.48 out of 5.** 48 surveys got a 5, 43 a 4 and 3 a 3. Gemma is stricter than Haiku,
  which gave 4.82.
- **By advice type:**
  - call an expert 5.00
  - don't act 4.92
  - plan 4.75
  - do this 4.28
  - wait and watch 3.75
- **Cost and time:** 94 calls, 35,635 input tokens and 4,707 output tokens, 66 seconds.
- **Weakest: wait-and-watch surveys.** Their second question, "Do you need more help?", is generic. P4: ask whether
  the problem grew instead.
- The judge's 1 to 5 score sits beside P4's rule-based relevance (0 to 1, now 0.81). They aren't on the same scale.
  Keep them side by side rather than turning one into the other.

## Decision: the send bar and plan questions (4 Nov, P4 + P5)
- **Send bar = 0.3** (`mel.writer.RELEVANCE_THRESHOLD`; P3's quality check enforces it).
  - P4's relevance score agrees only weakly with people: r = 0.29 on 18 hand-scored surveys, against the AI judge's
    0.58 (Haiku) and 0.72 (Gemma).
  - At 0.5, it blocked 552 of 2,616 surveys (21%), including specific ones such as "Did you treat the nursery bed?".
  - At 0.3, it blocks only surveys that name neither the crop, the problem nor the advice.
- **Plan surveys ask about the plan's first step and name the crop.** For example: "Did you apply zinc?", then "Is
  the plan working for your mustard so far?". Before, they asked the generic "How much of the plan have you done?",
  which people scored lowest (3.85). The answer key's wording is kept as the fallback.
  - On all 6,999 insights: P4's relevance went from 0.69 to 0.81 on the scorecard. Surveys below 0.3 went from 80
    to 0.
  - Item similarity with the answer key stays 0.99, and the safety checks still have 0 failures.
  - Recorded as runs 8 and 9 in `docs/results/eval_history.jsonl`.
  - Season walk, after P3's PR #24: 2,050 sends, 0 blocked by the quality check.

## Next
- Possible rubric v2: tell the judge to give a 3 to any question that doesn't name the advised action.
- More hand-scored surveys would make the model choice firmer. Twenty is enough to rule out the "always 5" judges,
  not to separate models that are within 0.05 of each other.
