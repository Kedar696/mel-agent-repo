# The AWS resources around the AgentCore agent (same as infra/fasal-pulse.yaml). Nothing here runs or costs
# money when idle. The runtime itself is still built with `agentcore launch` (docs/agentcore.md), using the
# outputs below.

# ---- S3: input + results (private, encrypted, HTTPS only) ---------------------------------------
resource "aws_s3_bucket" "data" {
  bucket_prefix = "${var.project_name}-data-"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    id     = "ExpireResults"
    status = "Enabled"
    filter {
      prefix = "results/"
    }
    expiration {
      days = var.results_retention_days
    }
  }
}

resource "aws_s3_bucket_policy" "data" {
  bucket = aws_s3_bucket.data.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.data.arn, "${aws_s3_bucket.data.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.data] # S3 rejects the two calls when they race
}

# ---- Bedrock Guardrail (Verifier check) ---------------------------------------------------------
# Applied to the survey text with source=OUTPUT (mel/agent/orchestrator.py bedrock_guardrail).
# No "new agronomic advice" topic: in v1 it blocked "Did you follow the advice?" (every survey asks about advice the
# farmer already got). P4's guards (gives_new_advice) cover that case instead. Violence is left out so pest words
# ("kill the aphids") are not blocked.
resource "aws_bedrock_guardrail" "survey" {
  name                      = "${var.project_name}-survey-guardrail"
  description               = "Blocks requests for personal information and harmful content in survey questions."
  blocked_input_messaging   = "This survey request was blocked by the Fasal Pulse guardrail."
  blocked_outputs_messaging = "This survey question was blocked by the Fasal Pulse guardrail."

  topic_policy_config {
    topics_config {
      name       = "Personal information request"
      type       = "DENY"
      definition = "Asking the farmer for identity, contact, financial or government identity details such as phone, address, bank account or Aadhaar number."
      examples   = ["What is your Aadhaar number?", "Please share your bank account details.", "What is your home address?"]
    }
  }

  sensitive_information_policy_config {
    dynamic "pii_entities_config" {
      for_each = ["PHONE", "EMAIL", "ADDRESS", "CREDIT_DEBIT_CARD_NUMBER", "INTERNATIONAL_BANK_ACCOUNT_NUMBER"]
      content {
        type   = pii_entities_config.value
        action = "BLOCK"
      }
    }
  }

  content_policy_config {
    dynamic "filters_config" {
      for_each = ["HATE", "INSULTS", "SEXUAL", "MISCONDUCT"]
      content {
        type            = filters_config.value
        input_strength  = "MEDIUM"
        output_strength = "MEDIUM"
      }
    }
  }
}

resource "aws_bedrock_guardrail_version" "survey" {
  guardrail_arn = aws_bedrock_guardrail.survey.guardrail_arn
  description   = "v2: personal-information topic, PII and content filters (no advice topic)."
  skip_destroy  = true # a running agent keeps its pinned version until it is relaunched
  lifecycle {
    replace_triggered_by = [aws_bedrock_guardrail.survey] # any guardrail change publishes a new version
  }
}

# ---- AgentCore execution role (least privilege) -------------------------------------------------
resource "aws_iam_role" "agent" {
  name        = "${var.project_name}-agentcore-${local.region}"
  description = "Execution role for the Fasal Pulse agent on Bedrock AgentCore Runtime."
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [merge(local.trust["bedrock-agentcore"].Statement[0], {
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account }
        ArnLike      = { "aws:SourceArn" = "${local.arn}:bedrock-agentcore:${local.region}:${local.account}:*" }
      }
    })]
  })
}

resource "aws_iam_role_policy" "agent" {
  name = "fasal-pulse-agent"
  role = aws_iam_role.agent.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockModels"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        # The us.* inference profiles route to models in several US regions, hence the * region.
        Resource = [
          "${local.arn}:bedrock:*::foundation-model/anthropic.claude-*",
          "${local.arn}:bedrock:*::foundation-model/google.gemma-*",
          "${local.arn}:bedrock:*::foundation-model/amazon.nova-*",
          "${local.arn}:bedrock:${local.region}:${local.account}:inference-profile/*",
        ]
      },
      { Sid = "BedrockGuardrail", Effect = "Allow", Action = "bedrock:ApplyGuardrail", Resource = aws_bedrock_guardrail.survey.guardrail_arn },
      { Sid = "DataBucketList", Effect = "Allow", Action = "s3:ListBucket", Resource = aws_s3_bucket.data.arn },
      { Sid = "DataBucketObjects", Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.data.arn}/*" },
      {
        Sid       = "AgentMetrics"
        Effect    = "Allow"
        Action    = "cloudwatch:PutMetricData"
        Resource  = "*" # PutMetricData has no resource ARN; the namespace condition limits it.
        Condition = { StringEquals = { "cloudwatch:namespace" = [var.metrics_namespace, "bedrock-agentcore"] } }
      },
      {
        Sid      = "RuntimeLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
        Resource = "${local.arn}:logs:${local.region}:${local.account}:log-group:/aws/bedrock-agentcore/runtimes/*"
      },
      { Sid = "RuntimeLogGroups", Effect = "Allow", Action = "logs:DescribeLogGroups", Resource = "${local.arn}:logs:${local.region}:${local.account}:log-group:*" },
      {
        Sid      = "ContainerImagePull"
        Effect   = "Allow"
        Action   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
        Resource = "${local.arn}:ecr:${local.region}:${local.account}:repository/bedrock-agentcore-*"
      },
      { Sid = "ContainerRegistryToken", Effect = "Allow", Action = "ecr:GetAuthorizationToken", Resource = "*" }, # no resource ARN
      {
        Sid      = "Tracing"
        Effect   = "Allow"
        Action   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
        Resource = "*" # X-Ray tracing actions have no resource ARN
      },
      {
        Sid    = "WorkloadIdentity"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:GetWorkloadAccessToken",
          "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
          "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
        ]
        Resource = [
          "${local.arn}:bedrock-agentcore:${local.region}:${local.account}:workload-identity-directory/default",
          "${local.arn}:bedrock-agentcore:${local.region}:${local.account}:workload-identity-directory/default/workload-identity/*",
        ]
      },
    ]
  })
}

# ---- CloudWatch dashboard -----------------------------------------------------------------------
# SEARCH picks up every Writer dimension the agent sends (one line per model, plus "templates").
locals {
  charts = [
    { title = "Runs: surveys vs no survey", x = 0, y = 2, w = 8, stat = "Sum", lines = [["Surveys", "Surveys"], ["NoSurvey", "No survey"]] },
    { title = "Model spend (USD)", x = 8, y = 2, w = 8, stat = "Sum", lines = [["CostUSD", "Cost"]] },
    { title = "Seconds per run (average)", x = 16, y = 2, w = 8, stat = "Average", lines = [["Seconds", "Seconds"]] },
    { title = "Verifier: revisions and template fallbacks", x = 0, y = 8, w = 12, stat = "Sum", lines = [["Revisions", "Revisions"], ["TemplateFallbacks", "Fallbacks"]] },
    { title = "Tokens", x = 12, y = 8, w = 12, stat = "Sum", lines = [["InputTokens", "Input"], ["OutputTokens", "Output"]] },
  ]
}

resource "aws_cloudwatch_dashboard" "agent" {
  dashboard_name = "${var.project_name}-agent"
  dashboard_body = jsonencode({
    widgets = concat(
      [{
        type       = "text", x = 0, y = 0, width = 24, height = 2
        properties = { markdown = "## Fasal Pulse agent\nEvery AgentCore run sends these (namespace `${var.metrics_namespace}`). Cost is the model spend the agent measured, in US dollars." }
      }],
      [for c in local.charts : {
        type = "metric", x = c.x, y = c.y, width = c.w, height = 6
        properties = {
          title = c.title, region = local.region, stat = c.stat, period = 300, view = "timeSeries"
          metrics = [for i, l in c.lines : [{
            expression = "SEARCH('{${var.metrics_namespace},Writer} MetricName=\"${l[0]}\"', '${c.stat}', 300)"
            id         = "m${i}"
            label      = l[1]
          }]]
        }
      }]
    )
  })
}

# ---- Optional budget alert ----------------------------------------------------------------------
resource "aws_budgets_budget" "spend" {
  count        = var.budget_email == "" ? 0 : 1
  name         = "${var.project_name}-monthly"
  budget_type  = "COST"
  time_unit    = "MONTHLY"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"

  dynamic "notification" {
    for_each = [["ACTUAL", 80], ["FORECASTED", 100]]
    content {
      notification_type          = notification.value[0]
      threshold                  = notification.value[1]
      threshold_type             = "PERCENTAGE"
      comparison_operator        = "GREATER_THAN"
      subscriber_email_addresses = [var.budget_email]
    }
  }
}

# ---- Outputs (the same names as the CloudFormation stack's) -------------------------------------
output "bucket_name" {
  value = aws_s3_bucket.data.id
}

output "s3_input_url" {
  description = "Upload the pack's insights.jsonl here (MEL_S3_INPUT). Optional; the image also carries the pack."
  value       = "s3://${aws_s3_bucket.data.id}/input/insights.jsonl"
}

output "s3_results_url" {
  description = "MEL_S3_RESULTS. Results under it expire after results_retention_days."
  value       = "s3://${aws_s3_bucket.data.id}/results"
}

output "guardrail_id" {
  value = aws_bedrock_guardrail.survey.guardrail_id
}

output "guardrail_version" {
  value = aws_bedrock_guardrail_version.survey.version
}

output "execution_role_arn" {
  description = "Pass to `agentcore configure --execution-role`."
  value       = aws_iam_role.agent.arn
}

output "dashboard_url" {
  value = "https://${local.region}.console.aws.amazon.com/cloudwatch/home?region=${local.region}#dashboards/dashboard/${aws_cloudwatch_dashboard.agent.dashboard_name}"
}

output "agentcore_launch_env" {
  description = "Paste after `agentcore launch` (add the model settings from docs/agentcore.md)."
  value = join(" ", [for k, v in {
    MEL_S3_INPUT          = "s3://${aws_s3_bucket.data.id}/input/insights.jsonl"
    MEL_S3_RESULTS        = "s3://${aws_s3_bucket.data.id}/results"
    MEL_GUARDRAIL_ID      = aws_bedrock_guardrail.survey.guardrail_id
    MEL_GUARDRAIL_VERSION = aws_bedrock_guardrail_version.survey.version
    MEL_METRICS_NAMESPACE = var.metrics_namespace
  } : "--env ${k}=${v}"])
}
