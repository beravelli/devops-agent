# Hosting the Copilot agent on AWS with Claude on Bedrock

The DevOps triage agent can run entirely inside your AWS account: the HTTP
server as a container, and the LLM as **Claude on Amazon Bedrock** — so no
Anthropic API key ever leaves AWS.

```
GitHub Copilot Chat ──HTTPS──▶  ALB / App Runner ──▶  container (this app)
   user types @devops-triage        (public URL)         │
                                                          ├─▶ Bedrock InvokeModel (Claude Opus 4.8)
                                                          ├─▶ EKS  (kubectl, via IRSA / kubeconfig)
                                                          └─▶ EC2  (aws CLI / boto3, via task role)
```

## 1. Model on Bedrock

- Enable model access for Claude Opus 4.8 in the Bedrock console for your region.
- Use a **cross-region inference profile** ID as the model, e.g.
  `us.anthropic.claude-opus-4-8` (or `eu.` / `apac.` for those geographies).
  Set it via `DEVOPS_AGENT_MODEL`; set `DEVOPS_AGENT_LLM_PROVIDER=bedrock`.
- The task/execution role needs:

```json
{
  "Effect": "Allow",
  "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
  "Resource": "*"
}
```

## 2. Build & push the image

```bash
aws ecr create-repository --repository-name devops-agent
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=${AWS_REGION:-us-east-1}
REPO="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/devops-agent"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REPO"
docker build -t "$REPO:latest" .
docker push "$REPO:latest"
```

## 3. Run it

Pick one. All inject `$PORT`; the container honors it.

- **App Runner** — simplest. Point a service at the ECR image, port 8000, give
  it an instance role with the Bedrock + EKS/EC2 permissions. You get an HTTPS
  URL out of the box for the Copilot endpoint.
- **ECS Fargate behind an ALB** — more control (VPC, security groups for
  reaching private EKS/EC2). Health check path `/health`. Task role carries the
  permissions below.
- **Lambda** — wrap with an adapter (e.g. Mangum) and front with API Gateway /
  a Function URL if you prefer serverless. Note: cold starts + the streaming
  response work best on App Runner / ECS.

### IAM the task role typically needs
- `bedrock:InvokeModel*` (the model)
- `eks:DescribeCluster`, `eks:ListClusters`, `eks:DescribeNodegroup` (EKS triage)
- `ec2:Describe*` (EC2 triage; read-only)
- For Kubernetes API access from inside the cluster, use **IRSA** and map the
  role to a Kubernetes RBAC group via the `aws-auth` ConfigMap / EKS access
  entries; the container then runs `kubectl` against the cluster.

## 4. Register as a GitHub Copilot agent

In your GitHub App settings → **Copilot** tab:
- Set the **App type** to *Agent*.
- Set the **URL** to `https://<your-app-url>/agent`.
- Copilot signs every request; this server verifies it against
  `https://api.github.com/meta/public_keys/copilot_api` automatically.

Then install the app on your org/account and invoke it in Copilot Chat with
`@your-agent-name payments pods are CrashLoopBackOff in prod`.

## 5. Config (env vars)

| Var | Purpose |
|---|---|
| `DEVOPS_AGENT_LLM_PROVIDER=bedrock` | Use Claude on Bedrock |
| `DEVOPS_AGENT_MODEL=us.anthropic.claude-opus-4-8` | Bedrock inference profile ID |
| `AWS_REGION` | Bedrock + AWS tooling region |
| `DEVOPS_AGENT_ALLOW_MUTATIONS=false` | Keep the hosted agent read-only |
| `DEVOPS_AGENT_KUBE_CONTEXT` / `_NAMESPACE` | Default cluster scope |

> Keep `DEVOPS_AGENT_ALLOW_MUTATIONS=false` in any internet-reachable
> deployment. The agent should recommend fixes, not execute them, when invoked
> from chat.
