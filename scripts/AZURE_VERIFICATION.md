# Azure cost verification (100% certainty)

## What was verified via Azure CLI

**Subscription:** `61782b55-5ce1-473f-b1a4-a0a2f1437892` (Azure subscription 1, default at time of check)

1. **Only FinSight resources in this subscription**
   - `az group list`: only resource group = `finsight-rg` (westeurope)
   - `az resource list`: only resource = `finsight-db` (type: `Microsoft.DBforPostgreSQL/flexibleServers`)
   - So **100% of billable resources in this subscription were FinSight** (PostgreSQL Flexible Server).

2. **Delete status**
   - `az group delete --name finsight-rg --yes --no-wait` was run.
   - `az group show -n finsight-rg` showed `"provisioningState": "Deleting"`.
   - After delete started, `az resource list` returned **no resources** in the subscription.
   - When the group finishes deleting, ongoing cost from this subscription will be **zero**.

3. **Other subscriptions**
   - Account has 3 subscriptions; the other two (`2acb4726-...`, `0450786c-...`) could not be listed (token expired). If your 333 DKK bill is from a different subscription, that subscription was not modified.

## What could not be verified via CLI

- **Exact 333 DKK attribution:** Azure CLI did not return cost/usage data (`az consumption usage list` was empty; `az costmanagement` has no direct query in this environment). So the 333 DKK figure was not programmatically tied to `finsight-rg` / `finsight-db`.

## How to be 100% sure the bill was from FinSight and is now zero

1. **In Azure Portal:** Cost Management + Billing → Cost analysis.
2. **Scope:** Select subscription `61782b55-5ce1-473f-b1a4-a0a2f1437892` (Azure subscription 1).
3. **Check:** Filter or group by "Resource group" and confirm the charge was for `finsight-rg` (and that there are no other resource groups with cost).
4. **After delete completes:** In Cost analysis, confirm no new charges for that subscription (or that the only charges are historical, before the delete).

To confirm delete is complete from CLI:

```bash
az group show -n finsight-rg
# When the group is gone: ResourceGroup 'finsight-rg' could not be found.
```
