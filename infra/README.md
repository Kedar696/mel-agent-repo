# Infrastructure

One AWS account (the event's Workshop Studio sandbox), one infrastructure-as-code setup (`terraform/`), one
Bedrock region for the models and the agent (us-west-2), one AgentCore runtime (made by `agentcore launch`,
`docs/agentcore.md`) and one hosted link for the UI. Nothing is deployed by this repo's build or CI, and no AWS
command that creates or changes a resource runs as part of them. There are no account IDs, access keys or
secrets in any file.

| Piece | Where | Status |
|---|---|---|
| Around the **agent on Bedrock AgentCore**: private S3 bucket, least-privilege execution role, Bedrock Guardrail, CloudWatch dashboard, optional budget | `terraform/agent.tf` (us-west-2) | Definition, checked in CI (`terraform fmt -check`, `terraform validate`); apply it before `agentcore launch` |
| The **Streamlit UI** (`app/streamlit_app.py`) on **Amazon ECS Express Mode**: ECR repository, a CodeBuild project that builds `ui.Dockerfile` from GitHub, the three ECS roles, a cluster and the Express service | `terraform/ui.tf` (us-east-1) | **Live** since 5 Nov at https://fa-bb1bdead4fb64190b7a68b8d8eae6ff2.ecs.us-east-1.on.aws/ , created with the CLI commands in "The Streamlit UI on ECS Express Mode" below (the Terraform holds the same settings) |
| The **agent itself** on AgentCore Runtime | `agentcore_app.py`, built and launched by the AgentCore toolkit | Steps in `docs/agentcore.md`. Set its ARN on the UI (`MEL_AGENTCORE_ARN`) and "Run the agent" runs live; until then the app shows the recorded runs |

## Terraform (`terraform/`)
- `main.tf`: the provider and the variables. One AWS provider covers both regions, because provider 6 lets each
  resource set its own `region`.
- `agent.tf`: private S3 bucket, Bedrock Guardrail and version, AgentCore execution role, CloudWatch dashboard,
  optional budget. Outputs: `execution_role_arn` for `agentcore configure`, `agentcore_launch_env` for
  `agentcore launch` (docs/agentcore.md).
- `ui.tf`: ECR repository, CodeBuild project, the three ECS roles, cluster and the Express Mode service. Its task
  role may only call `bedrock-agentcore:InvokeAgentRuntime` on this account's runtimes in the agent's region.

```bash
cd infra/terraform
terraform init
terraform apply
aws codebuild start-build --project-name fasal-pulse-ui-build --region us-east-1
terraform apply -var image_tag=<sha>
```
The first apply makes everything except the UI service. The build's log ends with `PUSHED ...:<sha>`; the
second apply, with that SHA, creates the service, and `terraform output ui_url` prints its address. Add
`-var agentcore_arn=<runtime arn>` to make "Run the agent" call the runtime live, and
`-var budget_email=<address>` for the budget alert. To stop paying: empty the bucket and the registry, then
`terraform destroy`.

**In this account the UI already exists by hand** under the same names (repository, roles, cluster and service
`fasal-pulse-ui`, see below), so either `terraform import` those or apply with another name
(`-var ui_name=fp-tf-ui`). State stays in a local `terraform.tfstate` (git-ignored: it holds the account ID and
ARNs); a team sharing one setup would add an S3 backend.

## The Streamlit UI on ECS Express Mode (live since 5 Nov)
`ui.Dockerfile` at the repo root packages `app/streamlit_app.py` with the participant pack and the
recorded agent runs; `ui.Dockerfile.dockerignore` next to it decides what is copied in (Docker uses
`<Dockerfile>.dockerignore` when it exists; `.dockerignore` belongs to the API image). CI builds the
image and checks `/_stcore/health`. `terraform/ui.tf` is the same setup as infrastructure-as-code.

Why Express Mode: App Runner stopped taking new customers on 30 April 2026, and Express Mode is the
replacement AWS points to. One container image in; ECS creates the Fargate service, the HTTPS load
balancer, the logs and the URL. The service runs **one task** (`MinTaskCount` = `MaxTaskCount` = 1)
because Streamlit keeps each visitor's session inside the process. The task role may only call
`bedrock-agentcore:InvokeAgentRuntime`, so the app needs no keys: once `MEL_AGENTCORE_ARN` is set,
"Run the agent" in the Survey demo runs live on AgentCore; until then it shows the recorded runs.

**Made by hand on 5 Nov** with the AWS CLI and the event's temporary credentials:
1. `aws ecr create-repository --repository-name fasal-pulse-ui`
2. Roles: `ecsTaskExecutionRole` (trust `ecs-tasks.amazonaws.com`, managed policy
   `AmazonECSTaskExecutionRolePolicy`), `ecsInfrastructureRoleForExpressServices` (trust
   `ecs.amazonaws.com`, managed policy `AmazonECSInfrastructureRoleforExpressGatewayServices`),
   `fasal-pulse-ui-task` and `fasal-pulse-ui-codebuild` (inline policies = `ui_task` and `ui_build`
   in `terraform/ui.tf`).
3. CodeBuild project `fasal-pulse-ui-build` with the same buildspec, then
   `aws codebuild start-build --project-name fasal-pulse-ui-build`: it clones GitHub, builds
   `ui.Dockerfile` on AWS (no Docker needed on a laptop) and pushes the short commit SHA and `latest`.
4. `aws ecs create-cluster --cluster-name default`, then
   ```bash
   aws ecs create-express-gateway-service --service-name fasal-pulse-ui \
     --execution-role-arn <ecsTaskExecutionRole arn> \
     --infrastructure-role-arn <ecsInfrastructureRoleForExpressServices arn> \
     --task-role-arn <fasal-pulse-ui-task arn> \
     --primary-container '{"image":"<account>.dkr.ecr.us-east-1.amazonaws.com/fasal-pulse-ui:<sha>","containerPort":8501}' \
     --health-check-path /_stcore/health --scaling-target '{"minTaskCount":1,"maxTaskCount":1}'
   ```
   The URL is `activeConfigurations[0].ingressPaths[0].endpoint` in
   `aws ecs describe-express-gateway-service --service-arn <arn>`. The service was ACTIVE after about
   5 minutes; its DNS name resolved about 10 minutes later.

**After a merge to main:** `start-build` again, then roll the service to the new SHA:
`aws ecs update-express-gateway-service --service-arn <arn> --primary-container '{"image":"...:<new sha>","containerPort":8501}'`.
**Point it at AgentCore:** add `"environment":[{"name":"MEL_AGENTCORE_ARN","value":"<runtime arn>"}]`
to that primary container. The app calls the runtime in the ARN's own region (`mel/agent/remote.py`): the agent
runs in us-west-2 while this UI runs in us-east-1. The hand-made task role must allow `InvokeAgentRuntime` on
`arn:aws:bedrock-agentcore:us-west-2:<account>:runtime/*`; if it only lists us-east-1, the button shows an
AccessDenied error and the recorded runs are still there.

To stop paying: `aws ecs delete-express-gateway-service --service-arn <arn>` (and empty the registry).
Cost while running: one 1 vCPU / 2 GB Fargate task plus a load balancer, about US$2 a day.

### Why one copy only
The REST API (`mel/api`, `Dockerfile`) and the UI keep their scheduler state (the weekly-cap ledger, the opt-out
list and the queue of hand-offs) **in memory**. Two copies would each hold a different, out-of-step state and
would disagree about what is due, so the service runs a single task. Running more than one needs a shared store
(see "Production design" below); that is not built.

### IAM action names (so no one copies the wrong ones)
The agent's execution role allows exactly `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream`,
scoped to the model families it uses and the inference profiles in its region. There is **no** `bedrock:Converse`
IAM action: the Converse and ConverseStream APIs are authorised by `InvokeModel` and
`InvokeModelWithResponseStream` respectively (AWS docs, "Inference using the Converse API"). Those two actions
therefore cover both the Invoke-style and the Converse-style calls P4's writer and P5's judge make.

## Production design only (NOT built)
The team's AWS notes (`docs/TEAM.md`) list three services that belong to a real production
system, not this hackathon build. They are **slide-only**; there is no code or template for them
here:
- **EventBridge / Step Functions** — the real "alarm clock": send at the right time, retry on
  WhatsApp after 24 h. In this project the simulated clock does that deterministically.
- **RDS for PostgreSQL** — the shared database that would hold the weekly limit and opt-outs
  across restarts and across more than one instance. Here that state is in memory.
- **Amazon Connect** — real automated phone calls for voice surveys. Here voice is simulated.

## What we could and could not validate here
- `terraform/`: `terraform fmt -check` and `terraform validate` pass (Terraform 1.17.1, AWS provider 6.72; CI
  runs both). An offline apply against a mocked AWS provider ran clean. `tests/test_infra.py` checks the bucket,
  the roles' actions, the dashboard metrics, the launch outputs and the one-task settings. Not yet applied to the
  account: the UI there was made by hand as described above, and the agent's resources are still to be applied.
