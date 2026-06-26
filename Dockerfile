# Container image for the GitHub Copilot agent server.
# Builds with the server + bedrock extras so it can run fully inside AWS with
# Claude hosted on Amazon Bedrock (no Anthropic API key required).
FROM python:3.12-slim

# kubectl, helm, and the aws CLI are the triage tools' backends. Install the
# ones you actually use; kubectl + aws cover EKS/EC2. (helm via its installer.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates iputils-ping traceroute \
    && curl -fsSL https://dl.k8s.io/release/stable.txt > /tmp/kver \
    && curl -fsSLo /usr/local/bin/kubectl "https://dl.k8s.io/release/$(cat /tmp/kver)/bin/linux/amd64/kubectl" \
    && chmod +x /usr/local/bin/kubectl \
    && curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* /tmp/kver

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[server,bedrock]"

# Default to Bedrock-hosted Claude; override via task/role env as needed.
ENV DEVOPS_AGENT_LLM_PROVIDER=bedrock \
    DEVOPS_AGENT_MODEL=us.anthropic.claude-opus-4-8 \
    DEVOPS_AGENT_ALLOW_MUTATIONS=false \
    PORT=8000

EXPOSE 8000
# Honor $PORT (App Runner / ECS inject it); default 8000.
CMD ["sh", "-c", "uvicorn devops_agent.copilot.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
