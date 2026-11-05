"""Checks on the CloudFormation template (infra/fasal-pulse.yaml) that need no AWS and no YAML library.

Full validation: `pip install cfn-lint` then `cfn-lint --regions us-east-1 us-west-2 -- infra/fasal-pulse.yaml`.
"""
import json
import re
from pathlib import Path

from mel.agent.aws import metric_data

TEMPLATE = Path(__file__).resolve().parents[1] / "infra" / "fasal-pulse.yaml"
TEXT = TEMPLATE.read_text(encoding="utf-8")


def _dashboard_json() -> dict:
    block = TEXT.split("DashboardBody: !Sub |", 1)[1].split("\n  # ----", 1)[0]
    body = re.sub(r"\$\{[^}]+\}", "X", block)          # stand-ins for the !Sub variables
    return json.loads(body)


def test_bucket_is_private_and_encrypted():
    for flag in ("BlockPublicAcls", "BlockPublicPolicy", "IgnorePublicAcls", "RestrictPublicBuckets"):
        assert f"{flag}: true" in TEXT
    assert "SSEAlgorithm: AES256" in TEXT
    assert "aws:SecureTransport" in TEXT                 # HTTPS only


def test_only_hackathon_regions():
    assert "us-east-1" in TEXT and "us-west-2" in TEXT and "HackathonRegions" in TEXT


def test_agent_role_has_no_wildcard_actions():
    role = TEXT.split("  AgentExecutionRole:", 1)[1].split("\n  AgentDashboard:", 1)[0]
    assert "Effect: Deny" not in role and "Effect: Allow" in role
    actions = re.findall(r"Action:\s*(\S+)", role) + re.findall(r"^\s+- ([a-z0-9-]+:[A-Za-z*]+)\s*$", role, flags=re.M)
    assert actions and not [a for a in actions if "*" in a], actions


def test_dashboard_is_valid_json_and_matches_agent_metrics():
    widgets = _dashboard_json()["widgets"]
    shown = set(re.findall(r'MetricName=\\?"(\w+)', json.dumps(widgets)))
    sent = {d["MetricName"] for d in metric_data({"metrics": {}, "surveys": {"en-IN": {}}})}
    sent |= {d["MetricName"] for d in metric_data({"metrics": {}, "surveys": {}})}
    assert shown and shown <= sent, shown - sent


def test_outputs_feed_the_agent_settings():
    for env in ("MEL_S3_INPUT", "MEL_S3_RESULTS", "MEL_GUARDRAIL_ID", "MEL_GUARDRAIL_VERSION", "MEL_METRICS_NAMESPACE"):
        assert f"--env {env}=" in TEXT
