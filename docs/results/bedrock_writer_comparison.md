# Templates vs Bedrock writers (5 Nov 2026)

P4's contract asks for "templates vs Bedrock (both model sizes) on 50 surveys (guard pass rate, relevance, cost,
speed) in one table". P5 ran it with the AI judge added. Owners: P4 (writer), P5 (evaluation).

**Command:** `MEL_USE_LLM=1 MEL_BEDROCK_REGION=us-east-1 MEL_BEDROCK_WRITE_MODEL=us.anthropic.claude-sonnet-4-6
MEL_BEDROCK_CHECK_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0 MEL_JUDGE=1 MEL_JUDGE_MODEL=google.gemma-3-12b-it
python scripts/p4_compare.py`. That is 50 surveys from the full pack, English baseline, raw model output before any
template fallback.

## Results
| Writer | Pass the safety checks | P4 relevance (0–1) | AI judge relevance (1–5) | Avg question length | Cost per 1,000 surveys | Whole season (2,616) | Time per survey |
|---|---|---|---|---|---|---|---|
| Templates | 100% | 0.82 | 4.50 | 28 characters | $0 | $0 | under 1 ms |
| Claude Sonnet 4.6 (large) | 100% | 0.94 | **4.90** | 114 characters | $6.85 | about $18 | 2.8 s |
| Claude Haiku 4.5 (small) | 92% | 0.88 | 4.89 | 69 characters | $2.01 | about $5 | 1.3 s |

Notes on the columns:
- **AI judge relevance** is Gemma 3 12B (picked in `judge_calibration.md`), scored over the surveys that passed the
  safety checks.
- **Costs** use the AWS Price List prices in `bedrock_prices.json`: Sonnet $3 in / $15 out, Haiku $1 / $5 per 1M
  tokens. Writing only; the judge adds about $0.05 per 1,000 surveys.
- **Haiku's 4 failed surveys** fell back to templates in the real pipeline, so nothing unsafe would be sent:
  - 3 gave new advice;
  - 2 had a label over 20 characters;
  - 2 broke the survey schema.

## What it means
- **The models write questions the judge rates higher:** 4.9 vs 4.5 for templates.
- **But the questions are much longer, and the judge may be rewarding that.**
  - Sonnet's questions are 4 times longer than the templates'. Nearly half restate the advice ("You were advised
    not to irrigate your maize seedlings soon after rain. Did you follow this advice?").
  - Some assume the farmer acted ("How satisfied are you with the certified wheat seed you bought?").
  - The rubric rewards asking directly about the advice, and says "short, tap-to-answer", but Gemma barely
    penalises length.
  - On WhatsApp, SMS-style screens and voice calls, length matters. Hindi is longer still.
- **Haiku is nearly as relevant as Sonnet for under a third of the cost,** but fails the safety checks more often
  (92%). Templates stay the fallback either way.
- **Cost is small in absolute terms:** about $5 (Haiku) to $18 (Sonnet) for a whole season.

## Limits
- **The 50-survey sample is lopsided:** 39 "do this", 9 plans, 2 "don't act", and no wait-and-watch or
  call-an-expert surveys. P4's `sample_insights` takes every n-th survey in file order. A sample spread across
  advice types would be fairer (P4).
- **The judge was checked against people on template surveys only.** The blind sheet below checks it on
  model-written surveys.

## Blind spot-check (to do)
`docs/results/hand_scores_bedrock.csv` has 15 rows: 5 farmer conversations, each written by the templates, Sonnet
and Haiku, shuffled.
- Score each row 1–5 with the same guide (`hand_scoring_guide.md`), without knowing which writer made it.
- The key is in `hand_scores_bedrock_key.json`. Open it only after scoring.
- **What it tells us:** if people prefer the short template questions, the model surveys' higher judge score comes
  from the judge's taste, not from better surveys. Then the rubric needs a length rule (v2).

## Recommendation (for P4 to decide)
- **Hand-scores show templates are as good or better:** keep templates as the default. Use Bedrock only where no
  template fits, and say so in the demo.
- **Hand-scores agree with the judge:** use **Haiku 4.5 with template fallback**, with a prompt rule of one short
  question per line and no restating of the advice. Re-run this table.
