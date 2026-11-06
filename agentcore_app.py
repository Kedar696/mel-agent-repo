"""Fasal Pulse agent on Amazon Bedrock AgentCore Runtime (the AWS associate's design). Owner: P5.

Local Streamlit UI --questions--> AgentCore Runtime [Evidence Extractor -> Analyst -> Verifier -> Synthesizer]
                   <--events + answer--                 |-> Amazon S3 (input + results)
                                                        |-> Amazon Bedrock (models + Guardrails)
                                                        |-> Amazon CloudWatch (metrics)

Payload: {"insight": {...}} or {"insight_id": "I-001253"}; optional "langs", "max_revisions".
Streams every step event (mel.agent.run_agent), then the result. Deployment steps: docs/agentcore.md.

Settings (environment of the runtime; credentials come from its IAM execution role, never a key):
  MEL_USE_LLM=1, MEL_BEDROCK_WRITE_MODEL, MEL_BEDROCK_CHECK_MODEL, MEL_BEDROCK_REGION   P4's Bedrock writer
  MEL_GUARDRAIL_ID [, MEL_GUARDRAIL_VERSION]   Bedrock Guardrails in the Verifier (optional)
  MEL_AGENT_JUDGE=1 with MEL_JUDGE_MODEL       the AI judge's score in the Verifier (optional)
  MEL_S3_INPUT=s3://bucket/key/insights.jsonl  where insight_id is looked up (else the pack in the image)
  MEL_S3_RESULTS=s3://bucket/prefix            every result is saved here as JSON (optional)
  MEL_METRICS_NAMESPACE (default FasalPulse/Agent)   CloudWatch metrics; MEL_METRICS=0 turns them off
"""
import os

# In the container the app folder is read-only and the AgentCore toolkit copies the laptop's out/ (model and judge
# caches) into the image. Work in /tmp instead, so every call is a real Bedrock call and every write succeeds.
# Set before importing mel, which reads MEL_OUT_DIR at import.
if os.environ.get("DOCKER_CONTAINER") == "1":
    os.environ.setdefault("MEL_OUT_DIR", "/tmp/mel_out")

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from mel.agent import run_agent, guardrail_from_env, judge_from_env, MAX_REVISIONS
from mel.agent.aws import load_insight, save_result, put_metrics

app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload):
    ins = payload.get("insight") or load_insight(payload.get("insight_id"))
    if not ins:
        yield {"step": "error", "status": "fail", "title": "No insight",
               "detail": "Send {'insight': {...}} or a known {'insight_id': ...}."}
        return
    guard, judge = guardrail_from_env(), judge_from_env()
    langs = tuple(payload.get("langs") or ("en-IN", "hi-IN"))
    for e in run_agent(ins, langs=langs, guardrail=guard, judge=judge,
                       max_revisions=int(payload.get("max_revisions", MAX_REVISIONS))):
        if e["step"] == "result":
            e["saved_to"] = save_result(e)
            put_metrics(e)
        yield e


if __name__ == "__main__":
    app.run()
