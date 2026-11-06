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

## Deploy (from a laptop with the event's AWS keys, about 20 minutes)
Two parts: **(1)** `terraform apply` (infrastructure-as-code) creates everything around the agent, then
**(2)** the AgentCore toolkit builds and runs the agent itself, using the Terraform outputs.

### 1. The resources: `infra/terraform/`
`agent.tf` creates, in us-west-2 (or us-east-1; other regions are refused):
- a **private, encrypted S3 bucket** for input and results (public access blocked, HTTPS only, results kept 30 days);
- the **AgentCore execution role** with only what the agent needs: the Claude, Gemma and Nova models, this
  guardrail, this bucket, metrics in `FasalPulse/Agent`, its own logs and container image;
- the **Bedrock Guardrail** for survey questions: no requests for personal information, PII
  and harmful-content filters;
- a **CloudWatch dashboard** `fasal-pulse-agent` (runs, spend, seconds, revisions, fallbacks, tokens);
- an optional **budget alert** (only if you give `budget_email`).

Nothing in it runs or costs money when idle. From a laptop with Terraform, or CloudShell (the `>_` icon in the
console top bar; it has the AWS CLI, install Terraform there first):
```
git clone https://github.com/michvinh-7/mel-agent-repo.git && cd mel-agent-repo/infra/terraform
terraform init
terraform apply
terraform output
```
(The same apply makes the UI's registry and build project; the UI service itself comes on a second apply with
`-var image_tag=<sha>`, see `infra/README.md`.)

Copy the insights to the bucket (required: `agentcore_launch_env` sets `MEL_S3_INPUT`, and the runtime then reads only
from S3). With `<bucket>` = `terraform output bucket_name`:
```
aws s3 cp mel-survey-agent-participant-pack/participant-pack/data/insights.jsonl s3://<bucket>/input/insights.jsonl
```

To remove everything: empty the bucket, then `terraform destroy`.

Check the setup before changing it: `terraform fmt -check` and `terraform validate` (CI runs both).
`tests/test_infra.py` checks the security settings.

### 2. The agent: AgentCore starter toolkit
If a flag differs in your version, check `agentcore configure --help`.
```
source .venv/bin/activate
pip install bedrock-agentcore bedrock-agentcore-starter-toolkit
mv Dockerfile /tmp/Dockerfile.api
agentcore configure --non-interactive --name fasal_pulse --entrypoint agentcore_app.py --requirements-file requirements-agentcore.txt --region us-west-2 --execution-role <execution_role_arn> --ecr auto --deployment-type container --disable-memory
agentcore launch --env MEL_USE_LLM=1 --env MEL_BEDROCK_REGION=us-west-2 --env MEL_BEDROCK_WRITE_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0 --env MEL_AGENT_JUDGE=1 --env MEL_JUDGE_MODEL=google.gemma-3-12b-it --env 'MEL_BEDROCK_PRICES={"anthropic.claude-haiku-4-5-20251001-v1:0":{"in":0.001,"out":0.005},"google.gemma-3-12b-it":{"in":0.00009,"out":0.00029}}' <agentcore_launch_env>
agentcore invoke '{"insight_id": "I-001253"}'
```
- **Move the REST API's `Dockerfile` aside first** (the `mv` above). With a `Dockerfile` at the repo root the toolkit
  builds that image (P1's API on port 8000) instead of generating its own, and every invoke fails with "Runtime health
  check failed"; `--non-interactive` skips the question that would catch it. Move it back after `launch`.
- **Why the extra `--env` lines:** the toolkit builds the image with its own ignore list, not our `.dockerignore`. It
  copies `out/` (so the laptop's model cache would answer every call: $0 and no real Bedrock call) and leaves out
  `docs/` (so the price file is missing and costs show $0). `agentcore_app.py` therefore sets `MEL_OUT_DIR=/tmp/mel_out` in the
  container (caches, call log, judge cache; the app folder is read-only there); `MEL_BEDROCK_PRICES` gives the two models' prices (USD per 1,000 tokens, from
  `docs/results/bedrock_prices.json`). The build recipe is `.bedrock_agentcore/fasal_pulse/Dockerfile`.
- `<execution_role_arn>` and `<agentcore_launch_env>` come from `terraform output`. `agentcore_launch_env` is a
  ready-made set of `--env` flags (bucket, guardrail id and version, metrics namespace).
- `--name fasal_pulse`: letters, numbers and underscores only (a `-` is refused). `--ecr auto` makes the repository
  `bedrock-agentcore-fasal_pulse`.
- The toolkit prints that it is "no longer supported" in favour of the npm AgentCore CLI. It still deploys;
  set `AGENTCORE_SUPPRESS_RECOMMENDATION=1` to hide the warning. We stay on it for this event.
- **`launch`** builds the container in the cloud (CodeBuild) and prints the runtime's ARN. To redeploy, add
  `--auto-update-on-conflict`.
- **`invoke`** should stream the steps and end with the result. Its metrics show on the dashboard within a few minutes.
- **The guardrail is new:** run the 40-survey pilot with `MEL_GUARDRAIL_ID` / `MEL_GUARDRAIL_VERSION` set once. If it
  blocks fair questions (they show as template fallbacks with a guardrail reason), loosen the topic wording in
  `infra/terraform/agent.tf` and apply again.

### Point the app at it
```
export MEL_AGENTCORE_ARN=<the ARN from agentcore launch>
streamlit run app/streamlit_app.py
```
"Run the agent" in Survey demo now runs on AgentCore and streams each step back.

Done 5 Nov in the event account: `terraform apply`, insights in the bucket, runtime `fasal_pulse` in us-west-2, and
the hosted UI's `MEL_AGENTCORE_ARN` set to it (`infra/README.md`).

## Record runs for the hosted app (no AWS keys there)
With the Bedrock settings in your terminal:
```
MEL_USE_LLM=1 MEL_BEDROCK_REGION=us-west-2 MEL_BEDROCK_WRITE_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0 MEL_AGENT_JUDGE=1 MEL_JUDGE_MODEL=google.gemma-3-12b-it python -m mel.agent --record
```
This records the five Survey demo picks into `docs/results/agent_runs/`. Commit them. Add `--remote <ARN>` to record
the runs from AgentCore instead.

## Fewer tokens (5 Nov, after the full run)
The full run spent about 340 output tokens per draft and made 1,776 revisions. Three changes in `mel/writer/llm.py`
cut that (P4's file; P4 to review):
- **One line per question.** The model writes `TYPE | QUESTION | ANSWER | ANSWER`; a star marks an answer that means
  failure (`*f` did not work, `*d` crop or animal damaged, `*i` could not get the input, `*e` could not reach the
  expert). Our code builds the schema items (ids, types, values, scale fields), so no output tokens go on JSON keys.
  `max_tokens` is 400. The older JSON answers still parse, so replayed caches keep working.
- **Hindi is a translation.** Once the English survey passes the Verifier, the model translates those lines instead
  of writing Hindi from the insight: a shorter request, the same questions in both languages, and none of the Hindi
  "less relevant than the template" rejections.
- **The limits are in the prompt** (questions under 100 characters, answers of 1 to 3 words under 20 characters), so
  fewer revisions.
- **One payment per distinct request.** Two farmers with the same advice get the same request; with 8 workers both
  used to be in flight at once and both were paid for. The second now waits for the first and takes its answer
  from the cache.

Measured 5 Nov (us-west-2, no guardrail): the 40-survey pilot cost $0.0014 per survey against pilot 2's $0.0039; the
full set cost **$2.61** for 2,616 surveys in both languages (the first run: $11.06), $0.00102 per survey, 14 minutes,
0 schema-invalid files, Bedrock-written English 97% and Hindi 96% (was 95% / 88%), 160 template fallbacks (was 442),
906 revisions (was 1,776), judge 4.93 (was 4.91), questions 54 characters on average (was 62). Write output tokens:
294k against 1.42M.

## Replay file: the same questions for $0
Every answer is cached on disk (`out/cache/bedrock/`, keyed by the request). `python -m mel.writer.llm export-cache`
adds them to `docs/results/bedrock_cache.jsonl`; commit it. `ModelClient` reads that file after the disk cache, so a
laptop without AWS keys, the hosted app and every rerun get the same questions without calling Bedrock. A changed
prompt is a new request, so a stale answer is never replayed. Bedrock's own prompt caching is not used: Haiku 4.5
caches only prefixes of 4,096 tokens or more, and ours are about 300.

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
export MEL_USE_LLM=1 MEL_BEDROCK_REGION=us-west-2 MEL_BEDROCK_WRITE_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
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
