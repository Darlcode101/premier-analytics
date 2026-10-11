#!/usr/bin/env bash
# Build and deploy Premier Analytics to Azure App Service (Linux, B1). Safe to re-run.
#
#   scripts/deploy_appservice.sh
#
# Current production host while Container Apps registration is pending on the subscription
# (scripts/deploy.sh is the Container Apps equivalent). Needs: az login on Azure for Students,
# Docker running, and .env with the Foundry endpoint and deployment names.
#
# Keyless: the web app signs in to Foundry with its managed identity (Entra ID). No API key is
# stored in Azure; any old key setting is removed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUBSCRIPTION="Azure for Students"
LOCATION="switzerlandnorth"
RG="rg-premier-analytics"
FOUNDRY_RG="rg-darling6-3123"
FOUNDRY_ACCOUNT="premieranalytics-resource"
ACR="premieranalytics0931ac23"
PLAN="pa-plan"
APP="premier-analytics-0931"
TAG="$(git -C "$ROOT" rev-parse --short HEAD)"
IMAGE="$ACR.azurecr.io/premier-analytics:$TAG"

set -a; source "$ROOT/.env"; set +a
az account set --subscription "$SUBSCRIPTION"

echo "==> build and push $IMAGE"
az acr login -n "$ACR"
docker build --platform linux/amd64 --build-arg GIT_SHA="$TAG" -t "$IMAGE" "$ROOT"
docker push "$IMAGE"

if ! az webapp show -n "$APP" -g "$RG" -o none 2>/dev/null; then
  echo "==> create plan and app"
  az appservice plan show -n "$PLAN" -g "$RG" -o none 2>/dev/null \
    || az appservice plan create -n "$PLAN" -g "$RG" -l "$LOCATION" --is-linux --sku B1 -o none
  az acr update -n "$ACR" --admin-enabled true -o none
  az webapp create -n "$APP" -g "$RG" -p "$PLAN" --container-image-name "$IMAGE" -o none
  az webapp config set -n "$APP" -g "$RG" --web-sockets-enabled true --always-on true -o none
  az webapp update -n "$APP" -g "$RG" --https-only true -o none
fi

echo "==> managed identity -> Foundry (Cognitive Services OpenAI User, scoped to the Foundry resource)"
PRINCIPAL="$(az webapp identity assign -n "$APP" -g "$RG" --query principalId -o tsv)"
FOUNDRY_ID="$(az cognitiveservices account show -n "$FOUNDRY_ACCOUNT" -g "$FOUNDRY_RG" --query id -o tsv)"
if [ -z "$(az role assignment list --assignee "$PRINCIPAL" --scope "$FOUNDRY_ID" --role "Cognitive Services OpenAI User" --query '[].id' -o tsv)" ]; then
  az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
    --role "Cognitive Services OpenAI User" --scope "$FOUNDRY_ID" -o none
fi

echo "==> configure"
ACR_PASSWORD="$(az acr credential show -n "$ACR" --query 'passwords[0].value' -o tsv)"
# Set the full image reference directly: passing a registry URL as well makes the CLI
# prefix the registry twice, and the pull then fails as "unauthorized".
az webapp config set -n "$APP" -g "$RG" --linux-fx-version "DOCKER|$IMAGE" -o none
az webapp config appsettings set -n "$APP" -g "$RG" -o none --settings \
  DOCKER_REGISTRY_SERVER_URL="https://$ACR.azurecr.io" \
  DOCKER_REGISTRY_SERVER_USERNAME="$ACR" DOCKER_REGISTRY_SERVER_PASSWORD="$ACR_PASSWORD" \
  WEBSITES_PORT=8000 PORT=8000 PA_MAX_SESSIONS="${PA_MAX_SESSIONS:-6}" \
  AZURE_OPENAI_ENDPOINT="$AZURE_OPENAI_ENDPOINT" \
  LIVE_MODEL_DEPLOYMENT="$LIVE_MODEL_DEPLOYMENT" RECAP_MODEL_DEPLOYMENT="$RECAP_MODEL_DEPLOYMENT"
az webapp config appsettings delete -n "$APP" -g "$RG" --setting-names AZURE_OPENAI_API_KEY -o none
az webapp restart -n "$APP" -g "$RG"

URL="https://$APP.azurewebsites.net"
echo "==> waiting for $URL"
for _ in $(seq 1 60); do
  if curl -sf -m 10 "$URL/api/health"; then echo; exit 0; fi
  sleep 10
done
echo "not healthy yet; logs: az webapp log tail -n $APP -g $RG" >&2
exit 1
