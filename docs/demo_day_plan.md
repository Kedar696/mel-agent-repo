# Demo-day plan: Fasal Pulse on AWS (written 5 Nov, for the 6 Nov presentation)

Owner: P5. This checks our approach against the AWS hackathon rules, lists the technical stack, and gives the order
of work for tonight and tomorrow morning.

## 1. Is our approach right? Yes, with two gaps
The design follows the AWS associate's diagram: AgentCore Runtime → Evidence Extractor → Analyst → Verifier →
Synthesizer, with Bedrock, S3 and CloudWatch. It is cheap, because Haiku 4.5 writes and Gemma 3 12B judges. It is
safe, because a rejected draft gets at most 2 revisions and then the template, which always passes. It is
measured, through the golden set, the five-dimension scorecard, the AI judge checked against hand scores, and the
cost ledger. Keep it.

| Gap | Why it matters | Fix |
|---|---|---|
| **No infrastructure-as-code (IaC).** Today's AWS setup is console clicks plus the `agentcore` command line. | The rules say solutions "should be written as IaC when applicable". The account is wiped after the event, so nobody could rebuild it. | One CloudFormation template, `infra/fasal-pulse.yaml`, sets everything up in one deploy (list below). |
| **No licence file.** The repo is public but has no `LICENSE`. | Without a licence it isn't open source, and the rules ask for an open-source sample. | Add `LICENSE`: MIT-0, the licence most `aws-samples` repos use, or Apache-2.0. **The team decides which.** |
| Nothing is deployed in AWS yet. | The rules' best practices: "a deployed hello world that touches all your services is more valuable than a perfect but unfinished component". | Deploy AgentCore tonight. We have admin access, so this doesn't need to wait for P1. |

What the template creates (all private, encrypted, on-demand, nothing running when idle):
- an S3 bucket for input and results, with public access blocked and server-side encryption (SSE-S3);
- the AgentCore execution role, with only the permissions it needs (least privilege): Bedrock invoke and
  ApplyGuardrail, CloudWatch PutMetricData, and read/write on that one bucket;
- the Bedrock Guardrail: denied topics "agronomic advice" and "asking for personal information", plus filters for
  personal information;
- a CloudWatch dashboard for the `FasalPulse/Agent` metrics: runs, seconds, calls, tokens, cost, revisions,
  fallbacks;
- an AWS Budgets alert at $40, as a second safety net besides the batch runner's own cap.

The AgentCore runtime itself stays on `agentcore launch` (the toolkit builds the container image with CodeBuild and
stores it in ECR, AWS's container registry). We pass the template's role, bucket and guardrail to it.
`docs/agentcore.md` says this is the one step that isn't in the template.

## 2. Hackathon requirements: where we stand
| Requirement (Workshop Studio) | Status |
|---|---|
| Use only `us-east-1` or `us-west-2` | ✅ everything runs in `us-east-1`. The console opens in us-west-2 by default, so switch it to N. Virginia. |
| Keep total spend under $500 | ✅ the full run is capped at $40 (expected about $5–10; the pilot gives the real figure). The AI judge costs about $0.05 per 1,000 surveys. AgentCore is billed by use. |
| No public S3 buckets, no weakened security | ✅ the bucket is private and encrypted. No AWS keys in git (`.env` and `out/` are git-ignored). The event's temporary keys are pasted only into the terminal. |
| IaC when applicable | ⬜ `infra/fasal-pulse.yaml` (above) |
| Public GitHub repo, open-source sample | 🟡 public ✅, licence ⬜, README already lets a stranger run everything |
| Least-privilege IAM, encryption at rest | ⬜ comes with the template |
| Serverless, managed, on-demand | ✅ AgentCore Runtime, Bedrock, S3, CloudWatch; no servers we manage |
| Account wiped after the event | ✅ once committed: recorded agent runs (`docs/results/agent_runs/`), the cost ledger, the full-run summary, eval history. The demo runs with no AWS at all. |

## 3. Technical stack
| Layer | What we use | Notes |
|---|---|---|
| Language | Python 3.11+ (3.14 on Michael's laptop, 3.12 in CI) | |
| Core pipeline | `mel/` package: decision rules R1–R8 (P2), timing, writer + safety guards (P4), scheduler, channels, simulator (P3), data loading + validation (P1), evaluation (P5) | No model needed. Under 4 ms per survey. |
| Agent | `mel/agent/`: Evidence Extractor → Analyst → Verifier → Synthesizer, bounded revision (max 2) | Streams step events as JSON |
| Writer model | **Claude Haiku 4.5** on Amazon Bedrock, inference profile `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Picked from the 50-survey comparison: about the same quality as Sonnet at under a third of the cost |
| Judge model | **Gemma 3 12B** on Bedrock (`google.gemma-3-12b-it`) | A different model family from the writer, so it doesn't grade its own writing |
| Safety | P4 guards + relevance ≥ 0.3 + 120-character limit + P4's small-model check + **Bedrock Guardrails** | |
| Model access | Bedrock Converse API through `boto3`, with an on-disk cache, retries with backoff, and a per-call log (`out/bedrock_calls.jsonl`) | The cache makes re-runs free |
| Agent hosting | **Amazon Bedrock AgentCore Runtime**, entry point `agentcore_app.py` | Built by CodeBuild, image in ECR |
| Storage | **Amazon S3** (input `insights.jsonl`, per-survey results) | |
| Monitoring | **Amazon CloudWatch** metrics, namespace `FasalPulse/Agent` | Plus the cost ledger in git |
| IaC | **AWS CloudFormation** (`infra/fasal-pulse.yaml`) | To build |
| UI | **Streamlit** (`app/streamlit_app.py`): Dashboard, Survey demo, Season, Follow-up queue | Runs locally. Backup link on Streamlit Community Cloud. |
| Tests / CI | pytest (794 tests), GitHub Actions (`.github/workflows/ci.yml`) | |
| Data | Organisers' synthetic pack: 6,999 insights → 2,616 surveys, 150-row golden set | Synthetic only |

## 4. Getting the best surveys out of the full run
1. **Run the pilot first** (`--sample 40`). Read three numbers from it:
   - **Revisions by language.** Python counts Hindi characters as Unicode code points, so a vowel mark (matra)
     counts as its own character. The same question can look 20–40% longer in Hindi than it reads. If the pilot
     shows Hindi failing the 120-character check far more often than English, raise the Hindi limit (for example
     to 160) or count visible characters instead. Don't make Haiku shorten good Hindi. The brief allows 400.
   - **Fallback reasons.** If `bedrock_error` or throttling shows up, re-run the same command (only successful calls
     are cached, so failures are retried for free) or use `--workers 4`.
   - **Projected full cost.** If it's under $40, go ahead.
2. **Run the full set** while the AgentCore deploy happens in a second terminal.
3. **After the run,** check `docs/results/full_bedrock_run.json`:
   - `schema_invalid_files` should be 0;
   - fallbacks should be under about 5%;
   - the judge average by advice type should be similar across types. Note the lowest type for the Q&A.
4. **Score the blind sheet** (`docs/results/hand_scores_bedrock.csv`, 15 rows, about 10 minutes, any two people).
   Until it's scored, **don't claim** Bedrock surveys beat the templates: the judge's 4.9 vs 4.5 may just reward
   longer questions. Say instead: "the agent writes fresh wording for each farmer, and every draft passes the same
   safety checks as the templates".

## 5. Order of work
**Tonight**
| # | Step | Who | Time |
|---|---|---|---|
| 1 | Commit and push the cost tracking + batch runner code | P5 | 5 min |
| 2 | Paste fresh Workshop Studio keys; run the pilot; read the three numbers above | P5 | 15 min |
| 3 | Full run (background) **and**, in parallel, `agentcore configure` / `launch` / `invoke` | P5 (+P1 to watch the account) | 25 min |
| 4 | Record the five demo picks **from AgentCore**: `python -m mel.agent --record --remote <ARN>`; commit them | P5 | 5 min |
| 5 | Write `infra/fasal-pulse.yaml` + `LICENSE`; deploy the template once to prove it works; update `docs/agentcore.md` | Claude + P1 | 30 min |
| 6 | Commit results: `cost_history.jsonl`, `full_bedrock_run.json`, `agent_runs/`; regenerate README numbers (`python scripts/readme_numbers.py --write`) | P5 | 10 min |
| 7 | Score the blind Bedrock sheet (15 rows) | any 2 people | 10 min |
| 8 | Slides: add **Architecture** (diagram with real service names) and **Cost** (cost per survey, full run actual, projection per 1,000 farmers); update demo numbers | P5 | 30 min |
| 9 | Two rehearsals from a fresh clone, following only the README; record the backup video | P5 + presenter | 30 min |

**Tomorrow morning (30 minutes before)**
- Paste fresh AWS keys (yesterday's will have expired). Run `agentcore invoke '{"insight_id": "I-001253"}'` once,
  so the first live call isn't a cold start in front of the judges.
- Start Streamlit and open the Dashboard once (its numbers animate the first time).
- Open in browser tabs: the CloudWatch dashboard, the AgentCore runtime page, the GitHub repo.
- If AWS fails: the app shows the recorded runs, so the demo still works offline. Say "this is a recording from
  AgentCore last night".

## 6. Changes to the 3-minute demo
Keep the three parts (Digital Green's user stories). Make room for AWS by trimming Part 2's scorecard walkthrough by
about 25 seconds.
- **Part 1** (the farmer's survey): open **"How the agent wrote this survey"**. Show one step where the Verifier
  rejected a draft and the Analyst fixed it ("the agent checks its own work").
- **Part 2** (quality): add **"What it costs"**: about $X per survey, all 2,616 surveys for $Y, every one checked.
  One sentence on the judge: "a different AI model grades relevance; we checked it against people's scores".
- **Close:** "It runs on Bedrock AgentCore in the event account, the whole setup is one CloudFormation template,
  and the repo is open source". Show the architecture slide.

Fill in $X and $Y from `full_bedrock_run.json` after step 3. Never use estimates on stage.

## 7. Skip for this event
- App Runner or another hosted copy of the UI on AWS. The laptop demo plus the Streamlit Cloud backup is enough.
- Amazon Quick, Kiro, and the bigger starter templates (FAST and similar): rebuilding on them now costs more than
  it gains.
- Bedrock batch inference (half price). At about $5–10 for the full run, the saving isn't worth the extra setup.
