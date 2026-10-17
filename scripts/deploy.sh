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
FOUNDRY_RG="rg-darling6-3123"            # the AIServices resource: models and (FC-1) speech
FOUNDRY_ACCOUNT="premieranalytics-resource"
IMAGE="$ACR.azurecr.io/premier-analytics:$TAG"

az account set --subscription "$SUBSCRIPTION"
SUB="$(az account show --query id -o tsv)"
URL="https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.App/containerApps/$APP?api-version=$API"
SPEECH_ID="$(az cognitiveservices account show -n "$FOUNDRY_ACCOUNT" -g "$FOUNDRY_RG" --query id -o tsv)"
SPEECH_REGION="$(az cognitiveservices account show -n "$FOUNDRY_ACCOUNT" -g "$FOUNDRY_RG" --query location -o tsv)"

echo "==> build and push $IMAGE"
az acr login -n "$ACR"
docker build --platform linux/amd64 --build-arg GIT_SHA="$TAG" -t "$IMAGE" "$ROOT"
docker push "$IMAGE"

echo "==> roll out"
# PATCH with the full container spec (env, probes, resources) so the new revision keeps them, plus the
# speech settings for the desk's Listen button (FC-1; not secrets: keyless via the managed identity).
CONTAINERS="$(az rest --method get --url "$URL" --query 'properties.template.containers' -o json \
  | python3 -c "
import json, sys
c = json.load(sys.stdin)
c[0]['image'] = '$IMAGE'
env = [e for e in c[0].get('env', []) if e['name'] not in ('AZURE_SPEECH_RESOURCE_ID', 'AZURE_SPEECH_REGION')]
c[0]['env'] = env + [{'name': 'AZURE_SPEECH_RESOURCE_ID', 'value': '$SPEECH_ID'},
                     {'name': 'AZURE_SPEECH_REGION', 'value': '$SPEECH_REGION'}]
print(json.dumps(c))")"
az rest --method patch --url "$URL" --body "{\"properties\": {\"template\": {\"containers\": $CONTAINERS}}}" -o none

FQDN="$(az rest --method get --url "$URL" --query properties.configuration.ingress.fqdn -o tsv)"
echo "==> waiting for https://$FQDN to report version $TAG"
# Ask the app which build it is running (Express environments don't report ready revisions).
for _ in $(seq 1 60); do
  if curl -sf -m 10 "https://$FQDN/api/health" | grep -q "\"version\":\"$TAG\""; then
    curl -s "https://$FQDN/api/health"; echo; exit 0
  fi
  sleep 10
done
echo "not serving $TAG yet; check: az rest --method get --url '$URL'" >&2
exit 1
