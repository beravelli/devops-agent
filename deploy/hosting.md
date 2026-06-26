# Hosting the DevOps triage agent

Two paths depending on whether you need a public URL (Copilot Chat integration)
or just a machine you can run triage commands from.

```
Option A — EC2 in your VPC          Option B — App Runner (public HTTPS)
─────────────────────────────        ──────────────────────────────────────────
SSH into EC2 → run CLI triage        GitHub Copilot Chat → App Runner → agent
Direct access to private EKS,        → private EKS / AWS resources via IAM
Prometheus, Grafana, Redis, DB       Public URL wired into GitHub App settings
No public URL needed                 Permanent URL, no ngrok
```

---

## Option A — EC2 instance (pure triage, no public URL)

### 1. Launch EC2

- AMI: Amazon Linux 2023 or Ubuntu 24.04
- Type: t3.small (enough for the LLM client + CLI tools)
- VPC: same VPC as your EKS clusters / RDS / Redis
- IAM instance profile: see the IAM section below
- Security group: inbound SSH only (port 22 from your IP)

### 2. Install dependencies

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc   # or re-login

# Install kubectl
curl -fsSL https://dl.k8s.io/release/stable.txt | xargs -I{} \
  curl -fsSLo /usr/local/bin/kubectl "https://dl.k8s.io/release/{}/bin/linux/amd64/kubectl"
chmod +x /usr/local/bin/kubectl

# Install helm
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# AWS CLI v2 is pre-installed on Amazon Linux 2023;
# for Ubuntu: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
```

### 3. Clone and install the agent

```bash
git clone https://github.com/<your-org>/devops-agent.git
cd devops-agent
uv sync --extra github    # adds langchain-openai; also add --extra bedrock if you have Bedrock access
```

### 4. Configure

```bash
cp .env.example .env
```

Edit `.env`:

```env
DEVOPS_AGENT_LLM_PROVIDER=github
GITHUB_MODELS_TOKEN=github_pat_...   # your GitHub PAT with models: read
DEVOPS_AGENT_TOOL_GROUPS=kubernetes,helm,aws,prometheus   # scope to what's reachable
DEVOPS_AGENT_KUBE_CONTEXT=           # leave empty — aws eks update-kubeconfig sets it
DEVOPS_AGENT_KUBE_NAMESPACE=         # leave empty to query all namespaces by default
```

### 5. Configure kubectl for EKS

```bash
aws eks update-kubeconfig --name <your-cluster-name> --region us-east-1
# For multiple clusters:
aws eks update-kubeconfig --name prod-cluster --region us-east-1
aws eks update-kubeconfig --name staging-cluster --region us-east-1
# List contexts:
kubectl config get-contexts
# Set the one you want in .env: DEVOPS_AGENT_KUBE_CONTEXT=<context-name>
```

### 6. Run triage

```bash
# One-shot triage
uv run devops-agent triage "check for any pod issues" --groups kubernetes

# Interactive chat
uv run devops-agent chat

# Check what's configured
uv run devops-agent doctor
```

---

## Option B — AWS App Runner (public HTTPS URL for Copilot Chat)

App Runner gives you a permanent HTTPS endpoint with zero load-balancer config.
The container runs inside AWS so it can reach private EKS, RDS, Redis, etc.

### 1. Build and push the image to ECR

```bash
export ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export REGION=${AWS_REGION:-us-east-1}
export REPO="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/devops-agent"

aws ecr create-repository --repository-name devops-agent --region "$REGION"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$REPO"

docker build -t "$REPO:latest" .
docker push "$REPO:latest"
```

### 2. Create the IAM role for App Runner

```bash
# Trust policy
cat > /tmp/apprunner-trust.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "tasks.apprunner.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
EOF

aws iam create-role \
  --role-name devops-agent-apprunner \
  --assume-role-policy-document file:///tmp/apprunner-trust.json

# Attach read-only AWS permissions the triage tools need
aws iam put-role-policy \
  --role-name devops-agent-apprunner \
  --policy-name devops-agent-triage \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "ec2:Describe*",
          "eks:DescribeCluster", "eks:ListClusters", "eks:DescribeNodegroup",
          "eks:ListNodegroups", "eks:AccessKubernetesApi",
          "cloudwatch:DescribeAlarms", "cloudwatch:GetMetricStatistics",
          "logs:FilterLogEvents", "logs:GetLogEvents"
        ],
        "Resource": "*"
      }
    ]
  }'
```

### 3. Grant the role Kubernetes access on your EKS cluster

```bash
# Modern EKS access entries (recommended):
aws eks create-access-entry \
  --cluster-name <your-cluster> \
  --principal-arn arn:aws:iam::$ACCOUNT:role/devops-agent-apprunner \
  --type STANDARD

aws eks associate-access-policy \
  --cluster-name <your-cluster> \
  --principal-arn arn:aws:iam::$ACCOUNT:role/devops-agent-apprunner \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy \
  --access-scope '{"type":"cluster"}'

# If your cluster uses the legacy aws-auth ConfigMap instead:
# Add the role ARN to the mapRoles section:
# rolearn: arn:aws:iam::<ACCOUNT>:role/devops-agent-apprunner
# username: devops-agent
# groups: ["system:viewers"]   # or a custom RBAC group with read-only verbs
```

### 4. Store secrets in AWS Secrets Manager

```bash
aws secretsmanager create-secret \
  --name devops-agent/github-token \
  --secret-string "github_pat_your_token_here"
```

Grant the App Runner role access to it:

```bash
aws iam put-role-policy \
  --role-name devops-agent-apprunner \
  --policy-name devops-agent-secrets \
  --policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [{
      \"Effect\": \"Allow\",
      \"Action\": [\"secretsmanager:GetSecretValue\"],
      \"Resource\": \"arn:aws:secretsmanager:$REGION:$ACCOUNT:secret:devops-agent/*\"
    }]
  }"
```

### 5. Create the App Runner service

```bash
cat > /tmp/apprunner-service.json <<EOF
{
  "ServiceName": "devops-agent",
  "SourceConfiguration": {
    "ImageRepository": {
      "ImageIdentifier": "$REPO:latest",
      "ImageRepositoryType": "ECR",
      "ImageConfiguration": {
        "Port": "8000",
        "RuntimeEnvironmentVariables": {
          "DEVOPS_AGENT_LLM_PROVIDER": "github",
          "DEVOPS_AGENT_ALLOW_MUTATIONS": "false",
          "DEVOPS_AGENT_TOOL_GROUPS": "kubernetes,helm,aws,prometheus,correlation",
          "AWS_REGION": "$REGION",
          "EKS_CLUSTERS": "prod-cluster,staging-cluster"
        },
        "RuntimeEnvironmentSecrets": {
          "GITHUB_MODELS_TOKEN": "arn:aws:secretsmanager:$REGION:$ACCOUNT:secret:devops-agent/github-token"
        }
      }
    },
    "AutoDeploymentsEnabled": false
  },
  "InstanceConfiguration": {
    "Cpu": "1 vCPU",
    "Memory": "2 GB",
    "InstanceRoleArn": "arn:aws:iam::$ACCOUNT:role/devops-agent-apprunner"
  },
  "HealthCheckConfiguration": {
    "Protocol": "HTTP",
    "Path": "/health"
  }
}
EOF

aws apprunner create-service \
  --cli-input-json file:///tmp/apprunner-service.json \
  --region "$REGION"
```

This prints a `ServiceUrl` like `https://abc123def456.us-east-1.awsapprunner.com`.
The `/health` endpoint goes green in ~2 minutes.

### 6. Wire into GitHub Copilot

In your GitHub App → **Copilot** tab:
- URL: `https://abc123def456.us-east-1.awsapprunner.com/agent`

No `--no-verify` needed — the deployed server verifies GitHub's ECDSA signatures
by default.

### 7. Redeploy after a code change

```bash
docker build -t "$REPO:latest" . && docker push "$REPO:latest"
aws apprunner start-deployment --service-arn <service-arn> --region "$REGION"
```

---

## IAM summary (both options)

| Permission | Why |
|---|---|
| `ec2:Describe*` | EC2 triage tools |
| `eks:DescribeCluster`, `eks:ListClusters` | EKS triage tools |
| `eks:AccessKubernetesApi` | kubectl calls through EKS API |
| `cloudwatch:DescribeAlarms` | AWS alarms tool |
| `secretsmanager:GetSecretValue` | App Runner secret injection (Option B only) |

The agent is **read-only by default** (`DEVOPS_AGENT_ALLOW_MUTATIONS=false`).
These are all read/describe permissions — no write access needed.

---

## What can each option reach?

| Resource | Option A (EC2 in VPC) | Option B (App Runner) |
|---|---|---|
| Private EKS endpoint | Yes (same VPC) | Needs VPC connector* |
| Private RDS / Redis | Yes (same VPC) | Needs VPC connector* |
| Internal Prometheus/Grafana | Yes | Needs VPC connector* |
| Public EKS endpoint | Yes | Yes |
| Public Prometheus/Grafana | Yes | Yes |
| AWS APIs (EC2, EKS, CloudWatch) | Yes (instance role) | Yes (task role) |

*App Runner VPC connector: add `"NetworkConfiguration": {"EgressConfiguration": {"EgressType": "VPC", "VpcConnectorArn": "<arn>"}}` to the service config. Create the VPC connector in the same subnets as your EKS/RDS/Redis.
