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

## Deploy (Terraform; from any machine with the account's credentials)
Everything is in `infra/terraform/` (steps in `infra/README.md`). `terraform apply` makes the bucket, the Guardrail,
the execution role, the dashboard, the agent's image registry and its ARM build project; then
```
aws codebuild start-build --project-name fasal-pulse-agent-build --region us-west-2
terraform apply -var agent_image_tag=<the SHA the build printed>
```
creates (or rolls) the runtime `fasal_pulse` from the `Dockerfile`'s `agent` target with the agent's settings
(`terraform output agent_env`: the bucket, guardrail id and version, models, prices, metrics namespace). The UI's
`MEL_AGENTCORE_ARN` follows `terraform output agentcore_arn` on its next apply, so "Run the agent" in the Survey demo
runs live. Try it from a laptop: `python -m mel.agent --remote $(terraform -chdir=infra/terraform output -raw agentcore_arn) I-001253`.

The AgentCore starter toolkit (`agentcore configure` / `launch`) is no longer used: the runtime it launched on 5 Nov
was imported into the Terraform state on 6 Nov, and the image now comes from the same build path as the UI's.
Inside the container `agentcore_app.py` sets `MEL_OUT_DIR=/tmp/mel_out` (the app folder is read-only) and the pack's
insights ride in the image, so a call needs no S3 unless `MEL_S3_INPUT` is set.

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
