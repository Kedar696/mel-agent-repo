# The whole AWS setup, in one apply:
#   agent.tf = S3, Guardrail, execution role, dashboard, budget, the agent's registry + build, the AgentCore runtime (us-west-2)
#   ui.tf    = ECR, CodeBuild, ECS roles, cluster, Express Mode service (us-east-1)
# Both images are built by CodeBuild from GitHub (no Docker on a laptop) from the one Dockerfile's `ui` and `agent`
# targets, and both services are rolled with `terraform apply -var image_tag=<sha> -var agent_image_tag=<sha>`.
# No account IDs or credentials here; state is local and git-ignored. Steps: infra/README.md.

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
  # One build recipe for both images: clone the branch, build one Dockerfile target, push the short commit SHA and
  # `latest`. The build's log ends with `PUSHED <registry>:<sha>`; that SHA is the image_tag / agent_image_tag to apply.
  buildspec = <<-EOT
    version: 0.2
    phases:
      pre_build:
        commands:
          - git clone --depth 1 --branch "$GIT_REF" "$REPO_URL" src
          - aws ecr get-login-password | docker login --username AWS --password-stdin "$${ECR_URI%%/*}"
      build:
        commands:
          - cd src && TAG=$(git rev-parse --short HEAD) && docker build --target "$TARGET" -t "$ECR_URI:$TAG" -t "$ECR_URI:latest" . && docker push "$ECR_URI:$TAG" && docker push "$ECR_URI:latest" && echo "PUSHED $ECR_URI:$TAG"
  EOT
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

variable "agent_image_tag" {
  description = "Leave empty until the agent's build project has pushed an image, then the short commit SHA it printed: the AgentCore runtime is created (or rolled) with it."
  type        = string
  default     = ""
}

variable "agent_image" {
  description = "A full image URI for the runtime instead of agent_image_tag (used once to import a runtime that still runs an image from the AgentCore toolkit's registry)."
  type        = string
  default     = ""
}

variable "write_model" {
  description = "Bedrock model id (or inference profile) the agent writes questions with (MEL_BEDROCK_WRITE_MODEL)."
  type        = string
  default     = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "judge_model" {
  description = "Bedrock model id the agent's AI judge scores with (MEL_JUDGE_MODEL)."
  type        = string
  default     = "google.gemma-3-12b-it"
}

variable "bedrock_prices" {
  description = "MEL_BEDROCK_PRICES for the runtime: USD per 1,000 tokens per model id (the image carries no price file)."
  type        = string
  default     = "{\"anthropic.claude-haiku-4-5-20251001-v1:0\":{\"in\":0.001,\"out\":0.005},\"google.gemma-3-12b-it\":{\"in\":0.00009,\"out\":0.00029}}"
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
  description = "ARN of a runtime the UI should call instead of the one agent.tf manages (empty: the managed runtime, if any)."
  type        = string
  default     = ""
}

# The UI's execution and infrastructure roles and its cluster were first made by hand with these names, and IAM role
# and ECS cluster names cannot change in place; a fresh account can use any names.
variable "execution_role_name" {
  description = "Name of the ECS task execution role (pulls the image, writes logs)."
  type        = string
  default     = "ecsTaskExecutionRole"
}

variable "infrastructure_role_name" {
  description = "Name of the ECS infrastructure role (makes the load balancer, target groups, security groups, scaling)."
  type        = string
  default     = "ecsInfrastructureRoleForExpressServices"
}

variable "cluster_name" {
  description = "Name of the ECS cluster the Express service runs in."
  type        = string
  default     = "default"
}
