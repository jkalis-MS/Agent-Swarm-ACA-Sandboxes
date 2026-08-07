#!/usr/bin/env bash
# ============================================================================
# ACA Sandboxes — Research Agent Swarm Setup
# ============================================================================
# Builds and pushes the research-agent and orchestrator container images to
# ACR using `az acr build` (no local Docker required).
#
# Prerequisites:
#   - Azure CLI (`az`) logged in
#   - Bicep deployment already applied (creates ACR + sandbox group + app)
#
# Usage:
#   export SUBSCRIPTION_ID=<sub-id>
#   export RESOURCE_GROUP=<rg-name>
#   ./setup.sh
# ============================================================================
set -euo pipefail

SUBSCRIPTION_ID="${SUBSCRIPTION_ID:?Set SUBSCRIPTION_ID env var}"
RESOURCE_GROUP="${RESOURCE_GROUP:?Set RESOURCE_GROUP env var}"
DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-main}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ACA Sandboxes — Research Agent Swarm Setup                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Read deployment outputs ─────────────────────────────────────
echo "▸ Reading Bicep deployment outputs from '$DEPLOYMENT_NAME'..."

OUTPUTS=$(az deployment group show \
    --subscription "$SUBSCRIPTION_ID" \
    -g "$RESOURCE_GROUP" \
    -n "$DEPLOYMENT_NAME" \
    --query properties.outputs -o json)

ACR_NAME=$(echo "$OUTPUTS" | jq -r '.acrName.value')
ACR_LOGIN_SERVER=$(echo "$OUTPUTS" | jq -r '.acrLoginServer.value')
ORCH_APP=$(echo "$OUTPUTS" | jq -r '.orchestratorAppName.value')
SG_NAME=$(echo "$OUTPUTS" | jq -r '.sandboxGroupName.value')

echo "  ACR:           $ACR_LOGIN_SERVER"
echo "  Orchestrator:  $ORCH_APP"
echo "  Sandbox Group: $SG_NAME"
echo ""

# ── Step 2: Build & push research-agent image (via ACR build) ────────────
echo "▸ Building research-agent image in ACR..."
az acr build \
    --registry "$ACR_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --subscription "$SUBSCRIPTION_ID" \
    --image research-agent:latest \
    "$SCRIPT_DIR/research-agent"
echo "  ✓ $ACR_LOGIN_SERVER/research-agent:latest"
echo ""

# ── Step 3: Build & push orchestrator image (via ACR build) ──────────────
echo "▸ Building agent-orchestrator image in ACR..."
az acr build \
    --registry "$ACR_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --subscription "$SUBSCRIPTION_ID" \
    --image agent-orchestrator:latest \
    "$SCRIPT_DIR/orchestrator"
echo "  ✓ $ACR_LOGIN_SERVER/agent-orchestrator:latest"
echo ""

# ── Step 4: Update orchestrator container app ────────────────────────────
echo "▸ Updating Container App '$ORCH_APP' with new image..."
az containerapp update \
    --name "$ORCH_APP" \
    --resource-group "$RESOURCE_GROUP" \
    --subscription "$SUBSCRIPTION_ID" \
    --image "$ACR_LOGIN_SERVER/agent-orchestrator:latest" \
    -o none
echo "  ✓ Orchestrator updated"
echo ""

FQDN=$(az containerapp show \
    --name "$ORCH_APP" \
    --resource-group "$RESOURCE_GROUP" \
    --subscription "$SUBSCRIPTION_ID" \
    --query "properties.configuration.ingress.fqdn" -o tsv)

echo "═══════════════════════════════════════════════════════════════"
echo "  ✓ Setup complete!"
echo ""
echo "  Open:  https://$FQDN"
echo "═══════════════════════════════════════════════════════════════"
