# The Streamlit UI (app/streamlit_app.py) on Amazon ECS Express Mode: the image
# registry, a CodeBuild project that builds the Dockerfile's ui target straight from GitHub, the three ECS roles, a cluster and the
# Express service (Fargate behind an HTTPS load balancer, one task).

# ---- The image registry and the build that fills it ---------------------------------------------
resource "aws_ecr_repository" "ui" {
  region = var.ui_region
  name   = var.ui_name
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "ui" {
  region     = var.ui_region
  repository = aws_ecr_repository.ui.name
  policy = jsonencode({ rules = [{
    rulePriority = 1
    description  = "Keep only the last 10 images"
    selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
    action       = { type = "expire" }
  }] })
}

resource "aws_iam_role" "ui_build" {
  name               = "${var.ui_name}-codebuild"
  assume_role_policy = jsonencode(local.trust["codebuild"])
}

resource "aws_iam_role_policy" "ui_build" {
  name = "build-and-push"
  role = aws_iam_role.ui_build.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${local.arn}:logs:${var.ui_region}:${local.account}:log-group:/aws/codebuild/${var.ui_name}*"
      },
      { Effect = "Allow", Action = "ecr:GetAuthorizationToken", Resource = "*" }, # ECR accepts no narrower resource
      {
        Effect = "Allow"
        Action = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
        Resource = aws_ecr_repository.ui.arn
      },
    ]
  })
}

resource "aws_codebuild_project" "ui" {
  region        = var.ui_region
  name          = "${var.ui_name}-build"
  description   = "Builds the Dockerfile's ui target from GitHub and pushes it to the UI registry (no Docker needed on a laptop)."
  service_role  = aws_iam_role.ui_build.arn
  build_timeout = 30

  artifacts {
    type = "NO_ARTIFACTS"
  }

  logs_config {
    cloudwatch_logs {
      status     = "ENABLED"
      group_name = "/aws/codebuild/${var.ui_name}"
    }
  }

  environment {
    type            = "LINUX_CONTAINER"
    compute_type    = "BUILD_GENERAL1_MEDIUM"
    image           = "aws/codebuild/amazonlinux-x86_64-standard:5.0"
    privileged_mode = true # docker build
    environment_variable {
      name  = "REPO_URL"
      value = var.repo_url
    }
    environment_variable {
      name  = "GIT_REF"
      value = var.git_ref
    }
    environment_variable {
      name  = "ECR_URI"
      value = aws_ecr_repository.ui.repository_url
    }
  }

  source {
    type      = "NO_SOURCE"
    buildspec = <<-EOT
      version: 0.2
      phases:
        pre_build:
          commands:
            - git clone --depth 1 --branch "$GIT_REF" "$REPO_URL" src
            - aws ecr get-login-password | docker login --username AWS --password-stdin "$${ECR_URI%%/*}"
        build:
          commands:
            - cd src && TAG=$(git rev-parse --short HEAD) && docker build --target ui -t "$ECR_URI:$TAG" -t "$ECR_URI:latest" . && docker push "$ECR_URI:$TAG" && docker push "$ECR_URI:latest" && echo "PUSHED $ECR_URI:$TAG"
    EOT
  }
}

# ---- The three roles Express Mode needs ---------------------------------------------------------
resource "aws_iam_role" "ui_execution" { # lets ECS pull the image and write logs
  name               = "${var.ui_name}-execution"
  assume_role_policy = jsonencode(local.trust["ecs-tasks"])
}

resource "aws_iam_role_policy_attachment" "ui_execution" {
  role       = aws_iam_role.ui_execution.name
  policy_arn = "${local.arn}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "ui_infrastructure" { # lets ECS create the load balancer, target groups, security groups, scaling
  name               = "${var.ui_name}-infrastructure"
  assume_role_policy = jsonencode(local.trust["ecs"])
}

resource "aws_iam_role_policy_attachment" "ui_infrastructure" {
  role       = aws_iam_role.ui_infrastructure.name
  policy_arn = "${local.arn}:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"
}

resource "aws_iam_role" "ui_task" { # what the running app may call: only invoke the AgentCore runtime (no keys in the app)
  name               = "${var.ui_name}-task"
  assume_role_policy = jsonencode(local.trust["ecs-tasks"])
}

resource "aws_iam_role_policy" "ui_task" {
  name = "invoke-agentcore"
  role = aws_iam_role.ui_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "bedrock-agentcore:InvokeAgentRuntime"
      # The agent's region (us-west-2), whichever region this UI runs in.
      Resource = "${local.arn}:bedrock-agentcore:${var.agent_region}:${local.account}:runtime/*"
    }]
  })
}

# ---- The service --------------------------------------------------------------------------------
resource "aws_ecs_cluster" "ui" {
  region = var.ui_region
  name   = var.ui_name
}

resource "aws_ecs_express_gateway_service" "ui" {
  count                   = var.image_tag == "" ? 0 : 1
  region                  = var.ui_region
  service_name            = var.ui_name
  cluster                 = aws_ecs_cluster.ui.name
  execution_role_arn      = aws_iam_role.ui_execution.arn
  infrastructure_role_arn = aws_iam_role.ui_infrastructure.arn
  task_role_arn           = aws_iam_role.ui_task.arn
  health_check_path       = "/_stcore/health"

  primary_container {
    image          = "${aws_ecr_repository.ui.repository_url}:${var.image_tag}"
    container_port = 8501
    dynamic "environment" {
      for_each = var.agentcore_arn == "" ? [] : [var.agentcore_arn]
      content {
        name  = "MEL_AGENTCORE_ARN"
        value = environment.value
      }
    }
  }

  # One task only: Streamlit keeps each visitor's session inside the process.
  scaling_target = [{ min_task_count = 1, max_task_count = 1, auto_scaling_metric = null, auto_scaling_target_value = null }]

  depends_on = [aws_iam_role_policy_attachment.ui_execution, aws_iam_role_policy_attachment.ui_infrastructure]
}

output "ui_repository_url" {
  value = aws_ecr_repository.ui.repository_url
}

output "ui_build_project" {
  description = "Run `aws codebuild start-build --project-name <this> --region <ui_region>` to build and push the image."
  value       = aws_codebuild_project.ui.name
}

output "ui_url" {
  description = "The app (after the second apply). Its DNS name can take about 10 minutes to resolve after the service is ACTIVE."
  value       = try(aws_ecs_express_gateway_service.ui[0].ingress_paths[0].endpoint, null)
}
