FROM python:3.12-slim

# --- CLI tools the agent shells out to ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates unzip iputils-ping traceroute \
    # kubectl
    && curl -fsSL https://dl.k8s.io/release/stable.txt > /tmp/kver \
    && curl -fsSLo /usr/local/bin/kubectl \
         "https://dl.k8s.io/release/$(cat /tmp/kver)/bin/linux/amd64/kubectl" \
    && chmod +x /usr/local/bin/kubectl \
    # helm
    && curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash \
    # aws cli v2
    && curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp && /tmp/aws/install \
    && rm -rf /tmp/awscliv2.zip /tmp/aws /tmp/kver \
    && apt-get purge -y curl unzip && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

# Install server + both LLM backends so the same image works with either
# provider — select at runtime via DEVOPS_AGENT_LLM_PROVIDER.
RUN pip install --no-cache-dir ".[server,bedrock,github]"

# Startup script: generate kubeconfig for every configured EKS cluster, then
# start the Copilot agent server.  Set EKS_CLUSTERS to a comma-separated list
# of cluster names, e.g. "prod-cluster,staging-cluster".
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENV DEVOPS_AGENT_LLM_PROVIDER=github \
    DEVOPS_AGENT_ALLOW_MUTATIONS=false \
    PORT=8000

EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
