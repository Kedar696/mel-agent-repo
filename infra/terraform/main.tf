# Terraform version of the two deployed CloudFormation templates, in one apply:
#   agent.tf = infra/fasal-pulse.yaml (S3, Guardrail, AgentCore execution role, dashboard, budget)
#   ui.tf    = infra/ui-express.yaml  (ECR, CodeBuild, ECS roles, cluster, Express Mode service)
# Same resources, names and permissions. No account IDs or credentials here; state is local and git-ignored.
# Steps: infra/README.md, "Terraform".

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.72" # aws_ecs_express_gateway_service and per-resource `region`
    }
  }
}

provider "aws" {
  region = var.agent_region # ui.tf sets `region = var.ui_region` on its regional resources
  default_tags {
    tags = { project = var.project_name }
  }
}

data "aws_caller_identity" "me" {}
data "aws_partition" "this" {}

locals {
  account = data.aws_caller_identity.me.account_id
  arn     = "arn:${data.aws_partition.this.partition}"
  region  = var.agent_region
  trust = { for s in ["bedrock-agentcore", "codebuild", "ecs", "ecs-tasks"] : s => {
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "${s}.amazonaws.com" }, Action = "sts:AssumeRole" }]
  } }
}

# ---- Agent (agent.tf) ---------------------------------------------------------------------------
variable "project_name" {
  description = "Lowercase prefix for the agent's resource names."
  type        = string
  default     = "fasal-pulse"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.project_name))
    error_message = "Lowercase letters, digits and dashes, 3 to 31 characters."
  }
}

variable "agent_region" {
  description = "Region of the AgentCore runtime and the resources around it."
  type        = string
  default     = "us-west-2"
  validation {
    condition     = contains(["us-east-1", "us-west-2"], var.agent_region)
    error_message = "The hackathon account supports only us-east-1 and us-west-2."
  }
}

variable "metrics_namespace" {
  description = "CloudWatch namespace the agent writes to (MEL_METRICS_NAMESPACE)."
  type        = string
  default     = "FasalPulse/Agent"
}

variable "results_retention_days" {
  description = "Days to keep saved results in S3 before they are deleted."
  type        = number
  default     = 30
  validation {
    condition     = var.results_retention_days >= 1
    error_message = "At least 1 day."
  }
}

variable "budget_email" {
  description = "Email for a monthly budget alert. Leave empty to skip the budget (some event accounts block it)."
  type        = string
  default     = ""
}

variable "budget_limit_usd" {
  description = "Budget alert threshold in US dollars (alerts at 80% actual and 100% forecast)."
  type        = number
  default     = 40
}

# ---- UI (ui.tf) ---------------------------------------------------------------------------------
variable "ui_name" {
  description = "Name of the UI's ECR repository, cluster and service (lowercase; ECR requires it)."
  type        = string
  default     = "fasal-pulse-ui"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*$", var.ui_name))
    error_message = "Lowercase letters, digits and dashes."
  }
}

variable "ui_region" {
  description = "Region of the Streamlit UI on ECS Express Mode."
  type        = string
  default     = "us-east-1"
  validation {
    condition     = contains(["us-east-1", "us-west-2"], var.ui_region)
    error_message = "The hackathon account supports only us-east-1 and us-west-2."
  }
}

variable "repo_url" {
  description = "Public Git repository CodeBuild clones."
  type        = string
  default     = "https://github.com/michvinh-7/mel-agent-repo.git"
}

variable "git_ref" {
  description = "Branch or tag CodeBuild builds."
  type        = string
  default     = "main"
}

variable "image_tag" {
  description = "Leave empty on the first apply (registry and build project only), run the build, then apply again with the short commit SHA it printed to create the service. A new SHA rolls the service."
  type        = string
  default     = ""
}

variable "agentcore_arn" {
  description = "Optional ARN of the Bedrock AgentCore runtime. When set, \"Run the agent\" in the app runs live on it."
  type        = string
  default     = ""
}
