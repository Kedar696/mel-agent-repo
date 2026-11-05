# Infrastructure

These files **describe** how the REST API (`mel/api`) and the Streamlit UI could run on AWS. Nothing
is deployed by this repo's build or CI, and no AWS command that creates or changes a resource is
run as part of them. There are no account IDs, access keys or secrets in any file. Treat this as
a design you can read and, if you choose, apply by hand later.

## Three templates: two deployed, one a design
| Template | What it is | Status |
|---|---|---|
| `fasal-pulse.yaml` (P5) | Everything around the **agent on Bedrock AgentCore**: private S3 bucket, least-privilege execution role, Bedrock Guardrail, CloudWatch dashboard, optional budget. | **Deployed** in the event account (us-west-2, stack `fasal-pulse`, 5 Nov). Steps: `docs/agentcore.md`. |
| `cloudformation.yaml` (P1) | The **REST API** (`mel/api`) on App Runner, with its ECR repository and role. | Definition only (the rest of this README). |
| `ui-express.yaml` (P2) | The **Streamlit UI** (`app/streamlit_app.py`) on **Amazon ECS Express Mode**: ECR repository, a CodeBuild project that builds `ui.Dockerfile` from GitHub, the three ECS roles, a cluster and the Express service. | **Live** in the event account (us-east-1, 5 Nov) at https://fa-bb1bdead4fb64190b7a68b8d8eae6ff2.ecs.us-east-1.on.aws/ , created with the CLI commands in "The Streamlit UI on ECS Express Mode" below (the template holds the same settings). **Second copy, deployed from this template** in Michael's account (us-east-1, stack `fasal-pulse-ui`, image `13ef538`, 5 Nov) with `AgentCoreArn` set, so "Run the agent" runs live on AgentCore (~4 s, ~$0.004): https://fa-53ba052ceabd447d83bc7d8b64823279.ecs.us-east-1.on.aws/ . Use this one for the live demo; Will's copy is in another account and can't call the agent. |

## The Streamlit UI on ECS Express Mode (live since 5 Nov)
`ui.Dockerfile` at the repo root packages `app/streamlit_app.py` with the participant pack and the
recorded agent runs; `ui.Dockerfile.dockerignore` next to it decides what is copied in (Docker uses
`<Dockerfile>.dockerignore` when it exists; `.dockerignore` belongs to the API image). CI builds the
image and checks `/_stcore/health`. `ui-express.yaml` is the same setup as infrastructure-as-code.

Why Express Mode: App Runner stopped taking new customers on 30 April 2026, and Express Mode is the
replacement AWS points to. One container image in; ECS creates the Fargate service, the HTTPS load
balancer, the logs and the URL. The service runs **one task** (`MinTaskCount` = `MaxTaskCount` = 1)
because Streamlit keeps each visitor's session inside the process. The task role may only call
`bedrock-agentcore:InvokeAgentRuntime`, so the app needs no keys: once `MEL_AGENTCORE_ARN` is set,
"Run the agent" in the Survey demo runs live on AgentCore; until then it shows the recorded runs.

**Event account (us-east-1).** Created by hand on 5 Nov with the AWS CLI and the event's temporary
credentials; the template creates the same things under the same names, so in this account deploy it
only with another `Name` (or delete these first).
1. `aws ecr create-repository --repository-name fasal-pulse-ui`
2. Roles: `ecsTaskExecutionRole` (trust `ecs-tasks.amazonaws.com`, managed policy
   `AmazonECSTaskExecutionRolePolicy`), `ecsInfrastructureRoleForExpressServices` (trust
   `ecs.amazonaws.com`, managed policy `AmazonECSInfrastructureRoleforExpressGatewayServices`),
   `fasal-pulse-ui-task` and `fasal-pulse-ui-codebuild` (inline policies = `TaskRole` and `BuildRole`
   in the template).
3. CodeBuild project `fasal-pulse-ui-build` with the template's buildspec, then
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
to that primary container. Our runtime is `arn:aws:bedrock-agentcore:us-west-2:423685956569:runtime/fasal_pulse-ixRznG8rYr`:
**us-west-2**, while this UI runs in us-east-1. The app now calls the runtime in the ARN's own region
(`mel/agent/remote.py`), and `ui-express.yaml` allows both hackathon regions. The live service's task role was
made with the CLI, so check that its `InvokeAgentRuntime` permission also covers
`arn:aws:bedrock-agentcore:us-west-2:<account>:runtime/*`; if it only lists us-east-1, the button shows an
AccessDenied error and the recorded runs are still there.

**Fresh account, from the template:**
```bash
aws cloudformation deploy --template-file infra/ui-express.yaml --stack-name fasal-pulse-ui --capabilities CAPABILITY_IAM --region us-east-1
aws codebuild start-build --project-name fasal-pulse-ui-build      # prints "PUSHED ...:<sha>" in its log
aws cloudformation deploy --template-file infra/ui-express.yaml --stack-name fasal-pulse-ui --capabilities CAPABILITY_IAM --region us-east-1 --parameter-overrides ImageTag=<sha>
```
The first deploy makes the registry and the build project; the second, with an image to run, makes
the service and prints its URL as the `Url` output. To stop paying, delete the stack (empty the
registry first) or, in the event account, `aws ecs delete-express-gateway-service --service-arn <arn>`.
Cost while running: one 1 vCPU / 2 GB Fargate task plus a load balancer, about US$2 a day.

## What each file does

| File | Plain words |
|---|---|
| `cloudformation.yaml` | One AWS "recipe" that creates three things: a private image registry (**ECR**) to hold the API's Docker image, an **App Runner** service that pulls that image and runs it behind an HTTPS URL, and a small **IAM role** (a locked-down identity) the running API uses. The role may only call Amazon Bedrock to run a model and nothing else. |
| `k8s/deployment.yaml` | The same API described for **Kubernetes** (Digital Green's EKS cluster): run **one** copy of the container, check it is alive on `/healthz`, run it as a non-root user with a read-only filesystem. |
| `k8s/service.yaml` | A stable internal address inside the cluster that points at the running copy. |

### Why one copy only
The API keeps its scheduler state (the weekly-cap ledger, the opt-out list and the queue of
hand-offs) **in memory**. Two copies would each hold a different, out-of-step state and would
disagree about what is due. So the Kubernetes Deployment sets `replicas: 1`, and App Runner runs
a single small instance. Running more than one needs a shared store (see "Production design"
below); that is not built.

### IAM action names (so no one copies the wrong ones)
The instance role allows exactly `bedrock:InvokeModel` and
`bedrock:InvokeModelWithResponseStream`, scoped to foundation models and inference profiles in
the chosen Bedrock region. There is **no** `bedrock:Converse` IAM action: the Converse and
ConverseStream APIs are authorised by `InvokeModel` and `InvokeModelWithResponseStream`
respectively (AWS docs, "Inference using the Converse API"). Those two actions therefore cover
both the Invoke-style and the Converse-style calls P4's writer and P5's judge make.

## How to deploy (by hand, if and when you decide to)
You need the AWS CLI configured with the event's temporary credentials and a region where the
Bedrock models are enabled. Replace `<region>` and `<account>` with real values.

1. **Create the stack** (makes the ECR repo, the roles and the App Runner service):
   ```bash
   aws cloudformation deploy \
     --template-file infra/cloudformation.yaml \
     --stack-name mel-survey-agent-api \
     --capabilities CAPABILITY_NAMED_IAM \
     --parameter-overrides BedrockRegion=<region> \
     --region <region>
   ```
2. **Build and push the image** to the ECR repo the stack created (its URI is a stack output,
   `EcrRepositoryUri`):
   ```bash
   aws ecr get-login-password --region <region> \
     | docker login --username AWS --password-stdin <account>.dkr.ecr.<region>.amazonaws.com
   docker build -t mel-survey-agent-api .
   docker tag mel-survey-agent-api:latest <account>.dkr.ecr.<region>.amazonaws.com/mel-survey-agent-api:latest
   docker push <account>.dkr.ecr.<region>.amazonaws.com/mel-survey-agent-api:latest
   ```
   App Runner then runs that image; the public URL is the stack output `ServiceUrl`.

For EKS instead of App Runner: push the image as above, point `k8s/deployment.yaml`'s `image:`
at it, then `kubectl apply -f infra/k8s/`.

## What it costs to leave running
Rough, on-demand, one small instance (check current AWS pricing for your region):
- **App Runner**: you pay for the provisioned instance (0.25 vCPU / 0.5 GB here) plus a little
  for requests. A single small always-on instance is on the order of a few US dollars a month;
  it is the main cost. **Pause or delete the service when you are not demoing.**
- **ECR**: storage for the images only (cents per month for a handful of images; a lifecycle
  rule keeps just the last 10).
- **Bedrock**: pay-per-token, only when a model is actually called. Zero when idle.
- **EKS** (if you use that path instead): an EKS cluster has its own hourly control-plane charge
  on top of the node, so it costs more than App Runner to leave running for a demo.

To stop paying, delete the stack: `aws cloudformation delete-stack --stack-name mel-survey-agent-api`
(and delete the EKS resources with `kubectl delete -f infra/k8s/` if you used that path).

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
- `cloudformation.yaml`: validated with **cfn-lint** — no errors (one informational warning,
  W3697, about the App Runner resource type). App Runner is kept because the team contract names
  it as the optional demo link; the EKS path in `k8s/` is the alternative.
- `k8s/*.yaml`: validated offline with **kubeconform** against the Kubernetes schemas — both
  valid.
- No AWS account call was made. Nothing here has been deployed.
