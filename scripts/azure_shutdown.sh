#!/usr/bin/env bash
# FinSight Azure shutdown – list and optionally delete all FinSight Azure resources to stop billing.
# Run: ./scripts/azure_shutdown.sh [--delete]
# Without --delete: only lists resources. With --delete: deletes the resource group (irreversible).

set -e

RG_NAME="${AZURE_FINSIGHT_RG:-finsight-rg}"
DRY_RUN=true
if [[ "${1:-}" == "--delete" ]]; then
  DRY_RUN=false
fi

if ! command -v az &>/dev/null; then
  echo "Azure CLI not found. Install: brew install azure-cli && az login"
  exit 1
fi

echo "=== Azure account & subscription ==="
az account show 2>/dev/null || { echo "Not logged in. Run: az login"; exit 1; }
echo ""

echo "=== Subscription (change with: az account set -s <subscription-id>) ==="
az account show --query "{name:name, id:id}" -o table
echo ""

echo "=== Resource groups matching *finsight* ==="
az group list --query "[?contains(name, 'finsight')].{name:name, location:location}" -o table
echo ""

if ! az group show --name "$RG_NAME" &>/dev/null; then
  echo "Resource group '$RG_NAME' not found. List all: az group list -o table"
  exit 0
fi

echo "=== Resources in '$RG_NAME' ==="
az resource list --resource-group "$RG_NAME" --query "[].{name:name, type:type}" -o table
echo ""

echo "=== Cost (current month, subscription-level; FinSight may be part of this) ==="
az consumption usage list --start-date "$(date +%Y-%m-01)" --end-date "$(date +%Y-%m-%d)" --query "[].{cost:pretaxCost, name:instanceName}" -o table 2>/dev/null || echo "Consumption API may require permissions or take a moment."
echo ""

if [[ "$DRY_RUN" == true ]]; then
  echo "DRY RUN. To delete resource group '$RG_NAME' and stop all billing, run:"
  echo "  $0 --delete"
  echo "Or: az group delete --name $RG_NAME --no-wait"
  exit 0
fi

echo "This will DELETE resource group '$RG_NAME' and ALL resources in it (e.g. finsight-db)."
echo "Data cannot be recovered after deletion."
read -p "Type 'yes' to confirm: " confirm
if [[ "$confirm" != "yes" ]]; then
  echo "Aborted."
  exit 1
fi

echo "Deleting resource group '$RG_NAME'..."
az group delete --name "$RG_NAME" --yes --no-wait
echo "Delete started (--no-wait). Check status: az group show -n $RG_NAME"
echo "Billing stops when the group and resources are fully deleted."
