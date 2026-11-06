"""Checks on the Terraform setup (infra/terraform/) that need no AWS and no HCL library.

Full validation: `cd infra/terraform && terraform init -backend=false && terraform validate` (CI runs it).
"""

import re
from pathlib import Path

from mel.agent.aws import metric_data

TF = Path(__file__).resolve().parents[1] / "infra" / "terraform"
AGENT, UI, MAIN = ((TF / f).read_text(encoding="utf-8") for f in ("agent.tf", "ui.tf", "main.tf"))


def _sent_metrics() -> set[str]:
    sent = {d["MetricName"] for d in metric_data({"metrics": {}, "surveys": {"en-IN": {}}})}
    return sent | {d["MetricName"] for d in metric_data({"metrics": {}, "surveys": {}})}


def test_bucket_is_private_and_encrypted():
    for flag in ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"):
        assert re.search(rf"{flag}\s+= true", AGENT), flag
    assert 'sse_algorithm = "AES256"' in AGENT and '"aws:SecureTransport" = "false"' in AGENT  # HTTPS only


def test_only_hackathon_regions():
    assert MAIN.count('contains(["us-east-1", "us-west-2"]') == 2  # agent_region and ui_region


def test_agent_role_has_no_wildcard_actions():
    policy = AGENT.split('resource "aws_iam_role_policy" "agent"', 1)[1].split("\n}\n", 1)[0]
    actions = re.findall(r'"([a-z0-9-]+:[A-Za-z*]+)"', policy)
    assert actions and not [a for a in actions if "*" in a], actions
    assert '"Deny"' not in policy


def test_dashboard_matches_agent_metrics():
    charts = AGENT.split("charts = [", 1)[1].split("\n  ]\n", 1)[0]
    shown = set(re.findall(r'\["(\w+)", "[^"]+"\]', charts))
    assert shown and shown <= _sent_metrics(), shown - _sent_metrics()


def test_outputs_feed_the_agent_settings():
    env = AGENT.split('output "agentcore_launch_env"', 1)[1]
    for name in (
        "MEL_S3_INPUT",
        "MEL_S3_RESULTS",
        "MEL_GUARDRAIL_ID",
        "MEL_GUARDRAIL_VERSION",
        "MEL_METRICS_NAMESPACE",
    ):
        assert re.search(rf"^\s+{name}\s+=", env, flags=re.M), name


def test_ui_service_runs_one_task_and_checks_streamlit_health():
    assert "min_task_count = 1, max_task_count = 1" in UI  # Streamlit sessions live in one process
    assert 'health_check_path       = "/_stcore/health"' in UI and "container_port = 8501" in UI


def test_ui_task_role_only_invokes_the_agent_in_its_region():
    task = UI.split('resource "aws_iam_role_policy" "ui_task"', 1)[1].split("\n}\n", 1)[0]
    assert re.findall(r'Action\s+= "([^"]+)"', task) == ["bedrock-agentcore:InvokeAgentRuntime"]
    assert "var.agent_region" in task and "us-east-1" not in task  # one region: the agent's
    assert not re.findall(r'Action\s+= "[^"]*\*', UI)
