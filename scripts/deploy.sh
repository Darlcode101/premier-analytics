#!/usr/bin/env bash
# Build and deploy Premier Analytics to Azure Container Apps. Safe to re-run.
#
#   scripts/deploy.sh            # build image, push, create or update the app
#
# Needs: az login (Azure for Students subscription), Docker running, and .env with the
# Foundry endpoint, key and deployment names. The key is stored as a Container Apps secret.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUBSCRIPTION="Azure for Students"
LOCATION="switzerlandnorth"          # subscription policy only allows a few regions
RG="rg-premier-analytics"
ACR="${ACR:-premieranalytics$(az account show --subscription "$SUBSCRIPTION" --query id -o tsv | tr -d '-' | cut -c1-8)}"
ENV_NAME="pa-env"
APP="premier-analytics"
TAG="$(git -C "$ROOT" rev-parse --short HEAD)"
IMAGE="$ACR.azurecr.io/$APP:$TAG"

set -a; source "$ROOT/.env"; set +a
az account set --subscription "$SUBSCRIPTION"

echo "==> resource group and registry"
az group create -n "$RG" -l "$LOCATION" -o none
az acr show -n "$ACR" -g "$RG" -o none 2>/dev/null || az acr create -n "$ACR" -g "$RG" -l "$LOCATION" --sku Basic -o none
az acr login -n "$ACR"

echo "==> build and push $IMAGE"
docker build --platform linux/amd64 -t "$IMAGE" "$ROOT"
docker push "$IMAGE"

echo "==> container apps environment"
az containerapp env show -n "$ENV_NAME" -g "$RG" -o none 2>/dev/null \
  || az containerapp env create -n "$ENV_NAME" -g "$RG" -l "$LOCATION" -o none

ENV_VARS=(
  "AZURE_OPENAI_ENDPOINT=$AZURE_OPENAI_ENDPOINT"
  "AZURE_OPENAI_API_KEY=secretref:foundry-key"
  "LIVE_MODEL_DEPLOYMENT=$LIVE_MODEL_DEPLOYMENT"
  "RECAP_MODEL_DEPLOYMENT=$RECAP_MODEL_DEPLOYMENT"
  "PA_MAX_SESSIONS=${PA_MAX_SESSIONS:-6}"
)

echo "==> app"
if az containerapp show -n "$APP" -g "$RG" -o none 2>/dev/null; then
  az containerapp secret set -n "$APP" -g "$RG" --secrets "foundry-key=$AZURE_OPENAI_API_KEY" -o none
  az containerapp update -n "$APP" -g "$RG" --image "$IMAGE" --set-env-vars "${ENV_VARS[@]}" -o none
else
  ACR_PASSWORD="$(az acr credential show -n "$ACR" --query 'passwords[0].value' -o tsv 2>/dev/null || true)"
  if [ -z "$ACR_PASSWORD" ]; then
    az acr update -n "$ACR" --admin-enabled true -o none
    ACR_PASSWORD="$(az acr credential show -n "$ACR" --query 'passwords[0].value' -o tsv)"
  fi
  # Sessions live in memory, so exactly one replica: scaling out would split viewers across matches.
  az containerapp create -n "$APP" -g "$RG" --environment "$ENV_NAME" \
    --image "$IMAGE" --registry-server "$ACR.azurecr.io" --registry-username "$ACR" --registry-password "$ACR_PASSWORD" \
    --target-port 8000 --ingress external --transport auto \
    --cpu 0.5 --memory 1.0Gi --min-replicas 0 --max-replicas 1 \
    --secrets "foundry-key=$AZURE_OPENAI_API_KEY" --env-vars "${ENV_VARS[@]}" -o none
fi

URL="https://$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
echo "==> deployed: $URL"
for i in $(seq 1 30); do
  if curl -sf "$URL/api/health"; then echo; exit 0; fi
  sleep 5
done
echo "health check did not pass yet; check: az containerapp logs show -n $APP -g $RG" >&2
exit 1
