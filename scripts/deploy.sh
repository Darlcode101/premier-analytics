#!/usr/bin/env bash
# Build, push and roll out Premier Analytics on Azure Container Apps (production). Safe to re-run.
#
#   scripts/deploy.sh
#
# Talks to Azure Resource Manager directly (az rest): on this subscription the `az containerapp`
# commands refuse to run because the Microsoft.App provider reports "Registering" indefinitely,
# although the API itself accepts requests. The app and environment were created the same way
# (see docs/DEPLOYMENT.md). Keyless: the app signs in to Foundry with its managed identity.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUBSCRIPTION="Azure for Students"
RG="rg-premier-analytics"
ACR="premieranalytics0931ac23"
APP="premier-analytics"
API="2026-07-01"
TAG="$(git -C "$ROOT" rev-parse --short HEAD)"
IMAGE="$ACR.azurecr.io/premier-analytics:$TAG"

az account set --subscription "$SUBSCRIPTION"
SUB="$(az account show --query id -o tsv)"
URL="https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.App/containerApps/$APP?api-version=$API"

echo "==> build and push $IMAGE"
az acr login -n "$ACR"
docker build --platform linux/amd64 -t "$IMAGE" "$ROOT"
docker push "$IMAGE"

echo "==> roll out"
# PATCH with the full container spec (env, probes, resources) so the new revision keeps them.
CONTAINERS="$(az rest --method get --url "$URL" --query 'properties.template.containers' -o json \
  | python3 -c "import json,sys; c=json.load(sys.stdin); c[0]['image']='$IMAGE'; print(json.dumps(c))")"
az rest --method patch --url "$URL" --body "{\"properties\": {\"template\": {\"containers\": $CONTAINERS}}}" -o none

FQDN="$(az rest --method get --url "$URL" --query properties.configuration.ingress.fqdn -o tsv)"
echo "==> waiting for https://$FQDN to serve $TAG"
for _ in $(seq 1 60); do
  STATE="$(az rest --method get --url "$URL" --query 'properties.latestReadyRevisionName' -o tsv)"
  if [[ "$STATE" == *"$(az rest --method get --url "$URL" --query 'properties.latestRevisionName' -o tsv)"* ]] \
     && curl -sf -m 10 "https://$FQDN/api/health" >/dev/null; then
    curl -s "https://$FQDN/api/health"; echo; exit 0
  fi
  sleep 10
done
echo "not ready yet; check the revision in the portal or: az rest --method get --url '$URL'" >&2
exit 1
