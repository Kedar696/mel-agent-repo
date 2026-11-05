# Running the Fasal Pulse agent on Amazon Bedrock AgentCore

This follows the design the AWS associate suggested at the hackathon (5 Nov). Owner: P5. Account and IaC: P1.

```
Local Streamlit UI --questions-->  AgentCore Runtime                                   --> Amazon S3 (input + results)
                   <--events + answer--  Orchestrator:                                 --> Amazon Bedrock (models + Guardrails)
                                         Evidence Extractor -> Analyst -> Verifier -> Synthesizer
                                                                  ^---------|          --> Amazon CloudWatch (metrics)
                                                            bounded Analyst revision
```

## What each step does (`mel/agent/orchestrator.py`)
| Step | Our code |
|---|---|
| Evidence Extractor | the insight, the farmer's profile and chat hours (P1), the farmer's memory H1–H4 (P4), activity attention (P1) |
| Analyst | `decide()` survey or not and the window (P2), then a draft: Bedrock (P4's writer) or P4's templates |
| Verifier | P4's safety and format checks, relevance at the 0.3 send bar, questions of 120 characters or less, P4's small-model check, **Bedrock Guardrails** (when `MEL_GUARDRAIL_ID` is set), the AI judge's score (P5) |
| Bounded revision | a rejected Bedrock draft goes back to the Analyst with the reasons, at most 2 times, then the template, which always passes |
| Synthesizer | both language files, P3's hand-off, the farmer's channel renders, schema checks, metrics |

## The same agent in three places
1. **On a laptop:** `python -m mel.agent I-001253` prints each step. With `MEL_USE_LLM=1` and the model settings, the
   Analyst writes with Bedrock.
2. **In the app:** Survey demo → "How the agent wrote this survey". It shows a recorded Bedrock run
   (`docs/results/agent_runs/`, made with `python -m mel.agent --record`), or runs the agent live. The hosted app has
   no AWS keys, so there a live run uses the templates.
3. **On AgentCore:** `agentcore_app.py` wraps the same orchestrator. It streams the step events, writes the result
   to S3 and sends metrics to CloudWatch. The app calls it when `MEL_AGENTCORE_ARN` is set.

## Deploy to AgentCore (from a laptop with the event's AWS keys, about 15 minutes)
These are the AgentCore starter toolkit's commands. If a flag differs in your version, check `agentcore --help`.

```
source .venv/bin/activate
pip install bedrock-agentcore bedrock-agentcore-starter-toolkit
agentcore configure --entrypoint agentcore_app.py --requirements-file requirements-agentcore.txt --region us-east-1
agentcore launch --env MEL_USE_LLM=1 --env MEL_BEDROCK_REGION=us-east-1 --env MEL_BEDROCK_WRITE_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0 --env MEL_AGENT_JUDGE=1 --env MEL_JUDGE_MODEL=google.gemma-3-12b-it
agentcore invoke '{"insight_id": "I-001253"}'
```

- **`configure`** asks for an execution role and an ECR repository. Accept the auto-created ones if the account
  allows it.
  - The role needs Bedrock (`bedrock:InvokeModel`, `bedrock:ApplyGuardrail`), CloudWatch (`cloudwatch:PutMetricData`),
    and S3 access to the buckets below.
- **`launch`** builds the container in the cloud and prints the runtime's ARN.
- **`invoke`** should stream the steps and end with the result.

### Optional: S3 and Guardrails
- **Input and results buckets:**
  - `aws s3 mb s3://fasal-pulse-<team>` (in CloudShell or with the AWS CLI)
  - Copy the pack's `insights.jsonl` there.
  - Add `--env MEL_S3_INPUT=s3://fasal-pulse-<team>/input/insights.jsonl --env MEL_S3_RESULTS=s3://fasal-pulse-<team>/results`.
- **Guardrails:** create a guardrail in the Bedrock console. Add denied topics such as "giving agronomic advice" and
  "asking for personal information", and personal-information filters. Then add `--env MEL_GUARDRAIL_ID=<id>`.
- **Metrics** go to CloudWatch, namespace `FasalPulse/Agent`: runs, seconds, model calls, tokens, cost, revisions,
  template fallbacks. Set `MEL_METRICS=0` to turn them off.

### Point the app at it
```
export MEL_AGENTCORE_ARN=<the ARN from agentcore launch>
streamlit run app/streamlit_app.py
```
"Run the agent" in Survey demo now runs on AgentCore and streams each step back.

## Record runs for the hosted app (no AWS keys there)
With the Bedrock settings in your terminal:
```
MEL_USE_LLM=1 MEL_BEDROCK_REGION=us-east-1 MEL_BEDROCK_WRITE_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0 MEL_AGENT_JUDGE=1 MEL_JUDGE_MODEL=google.gemma-3-12b-it python -m mel.agent --record
```
This records the five Survey demo picks into `docs/results/agent_runs/`. Commit them. Add `--remote <ARN>` to record
the runs from AgentCore instead.

## Why Haiku 4.5 as the writer
In the 50-survey comparison (`docs/results/bedrock_writer_comparison.md`), Haiku scored 4.89 against Sonnet's 4.90 at
under a third of the cost. Haiku failed the safety checks on 8% of drafts. The Verifier's revision loop and the
template fallback deal with exactly that case. Gemma 3 12B is the judge, a different model family, so it does not
grade its own writing.

## Cost tracking and the full run
Every run that writes surveys with Bedrock adds a row to `docs/results/cost_history.jsonl`.
- **What a row records:** the models used, the number of surveys, tokens and dollars split into writing, checking
  and judging, revisions, template fallbacks, cost per survey, and the projected cost for the whole dataset
  (2,616 surveys in Hindi and English).
- **Which runs add one:** the batch runner, `python -m mel.agent`, and a live "Run the agent" in the local app.
- **On AgentCore,** the same numbers go to CloudWatch instead.
- **On the Dashboard,** the "What it costs" section shows them.

```
export MEL_USE_LLM=1 MEL_BEDROCK_REGION=us-east-1 MEL_BEDROCK_WRITE_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
export MEL_JUDGE_MODEL=google.gemma-3-12b-it
python -m mel.agent.batch --sample 40 --judge --label "pilot: Haiku 4.5, hi+en"
python -m mel.agent.batch --max-usd 40 --judge --label "full set: Haiku 4.5, hi+en"
```
1. **The pilot** writes 40 surveys spread across advice types. It prints the cost per survey and the projected
   full cost.
2. **The full run** writes every survey in both languages with 8 parallel workers. It stops sending new requests
   at `--max-usd`.
   - It writes the files to `out/agent_batch/<time>/` and the summary to `docs/results/full_bedrock_run.json`.
   - If it stops (budget cap, or your AWS keys expire), run the same command again. Everything already written
     comes from the cache for $0.
3. **Commit** `docs/results/cost_history.jsonl` and `docs/results/full_bedrock_run.json`.
