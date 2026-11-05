# Infrastructure (definition only)

These files **describe** how the REST API (`mel/api`) could run on AWS. Nothing here is
deployed from this repo, and no AWS command that creates or changes a resource is run as part
of the build or CI. There are no account IDs, access keys or secrets in any file. Treat this as
a design you can read and, if you choose, apply by hand later.

## Two templates: one deployed, one a design
| Template | What it is | Status |
|---|---|---|
| `fasal-pulse.yaml` (P5) | Everything around the **agent on Bedrock AgentCore**: private S3 bucket, least-privilege execution role, Bedrock Guardrail, CloudWatch dashboard, optional budget. | **Deployed** in the event account (us-west-2, stack `fasal-pulse`, 5 Nov). Steps: `docs/agentcore.md`. |
| `cloudformation.yaml` (P1) | The **REST API** (`mel/api`) on App Runner, with its ECR repository and role. | Definition only (the rest of this README). |

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
