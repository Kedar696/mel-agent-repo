"""Call the agent on Amazon Bedrock AgentCore Runtime and read its events as they stream back. Owner: P5.

    from mel.agent.remote import invoke
    for event in invoke("arn:aws:bedrock-agentcore:us-east-1:...:runtime/fasal_pulse-...", {"insight_id": "I-001253"}):
        ...

The runtime (agentcore_app.py) streams one JSON event per line ("data: {...}", server-sent events) and ends with the
"result" event. A non-streaming JSON answer is also accepted. Credentials come from the AWS account (IAM), no key.
"""
import json
import os
import uuid


def _client():
    import boto3
    region = os.environ.get("MEL_BEDROCK_REGION") or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    return boto3.client("bedrock-agentcore", region_name=region or "us-east-1")


def parse_stream(lines):
    """Events from server-sent-event lines (bytes or str). Ignores blank lines and keep-alive comments."""
    for raw in lines:
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, str):          # some runtimes double-encode each event
            try:
                e = json.loads(e)
            except ValueError:
                continue
        if isinstance(e, dict):
            yield e


def invoke(arn: str, payload: dict, client=None, session_id: str | None = None):
    """Yield the agent's events from AgentCore. `session_id` must be at least 33 characters (AgentCore's rule)."""
    c = client or _client()
    r = c.invoke_agent_runtime(agentRuntimeArn=arn, qualifier=os.environ.get("MEL_AGENTCORE_QUALIFIER", "DEFAULT"),
                               runtimeSessionId=session_id or f"fasal-pulse-{uuid.uuid4().hex}",
                               payload=json.dumps(payload).encode("utf-8"))
    body = r["response"]
    if "text/event-stream" in (r.get("contentType") or ""):
        yield from parse_stream(body.iter_lines())
        return
    data = json.loads(body.read())
    for e in (data if isinstance(data, list) else data.get("events", [data])):
        yield e
