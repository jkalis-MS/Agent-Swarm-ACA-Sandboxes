"""
Shared Azure OpenAI chat client factory for MAF agents in the orchestrator.
"""
from __future__ import annotations

import os

from agent_framework.openai import OpenAIChatClient
from azure.identity.aio import DefaultAzureCredential


def build_chat_client() -> OpenAIChatClient:
    """
    Returns an OpenAIChatClient configured for Azure OpenAI from environment
    variables. Auth is keyless: uses DefaultAzureCredential (managed identity
    in Azure, `az login` locally) to mint Cognitive Services bearer tokens.
    The orchestrator's principal needs 'Cognitive Services OpenAI User' on
    the AOAI account (granted by infra/main.bicep).
    """
    endpoint   = _required("AZURE_OPENAI_ENDPOINT")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini")

    return OpenAIChatClient(
        model=deployment,
        azure_endpoint=endpoint,
        credential=DefaultAzureCredential(),
    )


def _required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"{name} env var is required for MAF agents.")
    return val
