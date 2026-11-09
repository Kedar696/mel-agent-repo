# Infrastructure

One AWS account (Will's Workshop Studio sandbox from the event), one infrastructure-as-code setup (`terraform/`), one
Bedrock region for the models and the agent (us-west-2), one AgentCore runtime and one hosted link for the UI.
Nothing is deployed by CI; no command that creates or changes a resource runs there. No account IDs, access keys or
secrets are in any file: the state (`terraform.tfstate`) and `*.tfvars` are git-ignored because they hold ARNs.

| Piece | Where | Status (6 Nov) |
|---|---|---|
| **Agent side**: private S3 bucket, Bedrock Guardrail, least-privilege execution role, CloudWatch dashboard, optional budget, the agent's image registry + ARM CodeBuild project, the **AgentCore runtime** `fasal_pulse` | `terraform/agent.tf` (us-west-2) | In the state. The runtime the AgentCore toolkit launched on 5 Nov was imported on 6 Nov and rolled the same day to our own build (`fasal-pulse-agent:44ca6c5`, runtime version 3); the toolkit is no longer used |
| **Streamlit UI** on **ECS Express Mode**: ECR repository, CodeBuild project (builds the `Dockerfile`'s `ui` target from GitHub), the three ECS roles, cluster, Express service (Fargate behind an HTTPS load balancer, one task) | `terraform/ui.tf` (us-east-1) | **Live** at https://fa-bb1bdead4fb64190b7a68b8d8eae6ff2.ecs.us-east-1.on.aws/ ; the resources made by hand on 5 Nov were imported into the state on 6 Nov |

## Terraform (`terraform/`)
- `main.tf`: provider (one, with a `region` per resource), the variables and the one buildspec both images use.
- `agent.tf`: everything agent side, including `aws_bedrockagentcore_agent_runtime` with the agent's settings as a
  map (bucket, guardrail, models, prices, metrics namespace; `terraform output agent_env` shows it).
- `ui.tf`: everything UI side. The execution role, infrastructure role and cluster keep the names the service was
  first made with by hand (`execution_role_name`, `infrastructure_role_name`, `cluster_name`): those names cannot
  change in place. A fresh account can use any names.

Credentials: the event page gives temporary keys; export them in the shell (or put them in `~/.aws/credentials`).
Terraform itself: `brew install hashicorp/tap/terraform`, or the release zip from releases.hashicorp.com.

```bash
cd infra/terraform
terraform init
terraform plan
terraform apply
```
`live.auto.tfvars` (git-ignored) holds the two image tags the services run (`image_tag`, `agent_image_tag`), so a plain
`apply` keeps them. With both empty, the first apply makes everything except the two services.

## Build an image and roll a service
Both images are built by CodeBuild from GitHub (no Docker on a laptop): the project clones `git_ref` (`main`), builds
one target of the `Dockerfile` and pushes the short commit SHA and `latest`. The build log ends with
`PUSHED <registry>:<sha>`.
```bash
aws codebuild start-build --project-name fasal-pulse-ui-build --region us-east-1
aws codebuild start-build --project-name fasal-pulse-agent-build --region us-west-2
terraform apply -var image_tag=<ui sha> -var agent_image_tag=<agent sha>
```
A branch instead of `main`: add `--environment-variables-override name=GIT_REF,value=<branch>,type=PLAINTEXT` to
`start-build`. Watch a build: `aws codebuild batch-get-builds --ids <id> --query 'builds[0].buildStatus'`.
The UI service rolls in place (same URL; about 5 minutes); the runtime gets a new version (the UI's
`MEL_AGENTCORE_ARN` is `terraform output agentcore_arn`, applied with it). Try the agent:
`python -m mel.agent --remote $(terraform output -raw agentcore_arn) I-001253`.

To stop paying: `terraform destroy` (empty the two registries and the bucket first). Cost while running: one 1 vCPU /
2 GB Fargate task plus a load balancer, about US$2 a day; the runtime and Bedrock are billed per call.

### Why one copy
The UI keeps each visitor's Streamlit session in its process, so the service runs a single task. The REST API
(`mel/api`, `docker build --target api .`) keeps surveys, hand-offs, answer records and opt-outs in the SQLite file
`MEL_DATABASE_URL` names, and decides the weekly cap per request from that farmer's stored hand-offs, so a restart
of the process loses nothing. One copy per file; a shared database is the upgrade if a second copy is ever needed.
Every call but `/healthz` needs `Authorization: Bearer <MEL_API_TOKEN>`; pass it to the container as a secret.

### IAM action names (so no one copies the wrong ones)
The agent's execution role allows exactly `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream`,
scoped to the model families it uses and the inference profiles in its region. There is **no** `bedrock:Converse`
IAM action: the Converse and ConverseStream APIs are authorised by `InvokeModel` and
`InvokeModelWithResponseStream` respectively (AWS docs, "Inference using the Converse API").

## Production design only (NOT built)
Slide-only services from the team's AWS notes (`docs/TEAM.md`); there is no code or template for them here:
- **EventBridge / Step Functions**: the real "alarm clock" (send at the right time, retry on WhatsApp after 24 h).
  Here the simulated clock does that deterministically.
- **RDS for PostgreSQL**: the shared database more than one API copy would need. Here the API keeps a SQLite file.
- **Amazon Connect**: real automated phone calls for voice surveys. Here voice is simulated.

## What CI checks
`terraform fmt -check` and `terraform validate` (Terraform 1.17, AWS provider 6.72) on every PR, plus
`tests/test_infra.py` (the bucket's privacy settings, the roles' actions, the dashboard's metrics, the runtime's
settings map, the one-task service). Nothing in CI touches the account.
