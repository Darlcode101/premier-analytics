# Deployment

Production runs on **Azure Container Apps** in Switzerland North, subscription *Azure for Students*.

| Resource | Name | Notes |
|---|---|---|
| Resource group | `rg-premier-analytics` | |
| Container registry | `premieranalytics0931ac23` (Basic) | images tagged with the git commit |
| Container Apps environment | `pa-env`, **Express** mode | Standard mode "is not currently available in this region" for this subscription |
| Container app | `premier-analytics` | 0.5 vCPU / 1 GiB, **exactly 1 replica** (match sessions are in memory), liveness probe `/api/health` |
| User-assigned identity | `pa-identity` | *Cognitive Services OpenAI User* on the Foundry resource, *AcrPull* on the registry. Pulls images and calls Foundry: no keys or registry passwords stored |
| Foundry | `premieranalytics-resource` in `rg-darling6-3123` | |

URL: https://premier-analytics.salmondune-d779c5b4.switzerlandnorth.azurecontainerapps.io

Deploy: `scripts/deploy.sh` (build, push, roll out a new revision, wait for health).

## Keyless model access
No API key is stored anywhere in Azure. The app uses its user-assigned managed identity
(`ManagedIdentityCredential(client_id=AZURE_CLIENT_ID)`; Express environments don't allow system-assigned ones,
token audience `https://ai.azure.com/.default`, which Foundry project endpoints require). Locally the same
code uses `az login`. The first token is fetched at startup, outside the 4 s per-call timeout.

## Why Express, and why `az rest` instead of `az containerapp`
Creating a Standard environment in Switzerland North fails with `ManagedEnvironmentModeNotSupported`, so the
environment runs in Express mode (no system-assigned identity, session affinity or HTTP/2; none needed here,
since there is one replica and WebSockets work).
The `Microsoft.App` resource provider on this subscription has reported `Registering` for over a day, and
`az containerapp` refuses to run until it reports `Registered`. The Resource Manager API itself accepts
requests, so the environment, the app and every rollout go through `az rest`.

## Fallback
App Service (`premier-analytics-0931`, B1 Linux) ran the same image before Container Apps was available;
`scripts/deploy_appservice.sh` still deploys there.
