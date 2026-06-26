#!/bin/sh
# Generate kubeconfig for EKS clusters before starting the server.
# Set EKS_CLUSTERS=cluster1,cluster2 to auto-configure multiple clusters.
# Set AWS_REGION or let it fall through to the instance metadata.
set -e

if [ -n "$EKS_CLUSTERS" ]; then
  REGION="${AWS_REGION:-us-east-1}"
  echo "[entrypoint] Configuring kubeconfig for EKS clusters: $EKS_CLUSTERS"
  for cluster in $(echo "$EKS_CLUSTERS" | tr ',' ' '); do
    aws eks update-kubeconfig --name "$cluster" --region "$REGION" || \
      echo "[entrypoint] WARNING: could not configure $cluster — continuing"
  done
fi

exec uvicorn devops_agent.copilot.server:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}"
