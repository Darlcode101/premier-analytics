"""Keyless speech tokens for the desk's Listen button (FC-0, FC-1).

The browser transcribes the commentator with the Azure AI Speech SDK on the same AIServices resource as the
models. It never sees a key: the app signs in with its managed identity (or `az login` locally) and hands the
browser a short-lived Entra token in the form the Speech SDK expects, `aad#<resource id>#<token>`.
"""
from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"
DEFAULT_REGION = "switzerlandnorth"

TokenGetter = Callable[[str], Awaitable[str]]


async def speech_token(resource_id: str, region: str, get_token: TokenGetter) -> dict:
    token = await get_token(COGNITIVE_SCOPE)
    return {"status": "ok", "token": f"aad#{resource_id}#{token}", "region": region}


def token_getter_from_env() -> TokenGetter | None:
    """Entra tokens from the managed identity in Azure, or the developer's `az login` locally."""
    if not os.environ.get("AZURE_SPEECH_RESOURCE_ID"):
        return None
    from azure.identity.aio import DefaultAzureCredential, ManagedIdentityCredential

    credential = (ManagedIdentityCredential(client_id=os.environ.get("AZURE_CLIENT_ID") or None)
                  if os.environ.get("IDENTITY_ENDPOINT") else DefaultAzureCredential())

    async def get(scope: str) -> str:
        return (await credential.get_token(scope)).token
    return get
