# Terraform — Fabric Managed Private Endpoint Manager

A Terraform module that manages the **full lifecycle** of Microsoft Fabric
Managed Private Endpoints (MPEs) declaratively:

```
IMPORT  →  PLAN  →  APPLY  →  APPROVE  →  DESTROY
```

This is a Terraform-native companion to the
[`mpeHelper/mpe_manager.ipynb`](../README_mpe.md) notebook. Both tools live
side by side; pick the one that fits your workflow.

| | Notebook | Terraform module |
|---|---|---|
| **State lives in** | Delta audit tables | `terraform.tfstate` (Git-tracked) |
| **Drift detection** | Manual re-inventory | `terraform plan` |
| **Rollback** | Re-run notebook | `git revert` + `terraform apply` |
| **CI integration** | Fabric pipeline | Any Terraform CI/CD |
| **Auth** | Fabric session / SPN | Provider env vars / workload identity |

---

## Directory layout

```
mpeHelper/terraform/
├── .gitignore                          ← excludes .terraform/, *.tfstate*, *.tfvars.json
├── versions.tf                         ← provider version pins
├── providers.tf                        ← fabric + azurerm provider config
├── variables.tf                        ← input variables
├── outputs.tf                          ← output values
├── main.tf                             ← for_each over managed_private_endpoints map
├── README.md                           ← this file
├── modules/
│   └── managed_private_endpoint/
│       ├── main.tf                     ← fabric_workspace_managed_private_endpoint resource
│       ├── variables.tf                ← per-endpoint inputs
│       └── outputs.tf                  ← mpe_id, workspace_id, provisioning_state
└── scripts/
    ├── import_existing.py              ← discover existing MPEs → imports.tf + tfvars.json
    ├── approve_pending.py              ← approve Pending PECs after apply
    └── tests/
        ├── test_import_existing.py
        └── test_approve_pending.py
```

---

## Prerequisites

- Terraform ≥ 1.5 (for native `import` blocks)
- Python ≥ 3.10 (for the helper scripts)
- `azure-identity` Python package (optional — `approve_pending.py` falls back
  to `az CLI` if unavailable)
  ```bash
  pip install azure-identity
  ```

### Permissions

| Operation | Required role |
|---|---|
| `terraform plan` / `apply` (create MPEs) | **Fabric Workspace Admin** on every target workspace |
| `python import_existing.py` (inventory) | **Fabric Workspace Viewer** (or higher) |
| `python approve_pending.py` (approve PECs) | `*/privateEndpointConnections/write` on each target Azure resource (typically Owner or Contributor) |

---

## Authentication

### Fabric provider

The `microsoft/fabric` provider reads credentials from environment variables.
The recommended approach is a **Service Principal**:

```bash
export FABRIC_TENANT_ID="<tenant-guid>"
export FABRIC_CLIENT_ID="<spn-client-id>"
export FABRIC_CLIENT_SECRET="<spn-client-secret>"
```

For interactive local runs with `az login` already done:

```bash
export FABRIC_TENANT_ID="<tenant-guid>"
export FABRIC_CLIENT_ID="<spn-client-id>"
export FABRIC_USE_CLI=true
```

See the [provider docs](https://registry.terraform.io/providers/microsoft/fabric/latest/docs)
for the full list of accepted env vars.

### ARM token (approve_pending.py only)

```bash
# Option A — pre-acquired token
export ARM_TOKEN="$(az account get-access-token --resource https://management.azure.com --query accessToken -o tsv)"

# Option B — azure-identity DefaultAzureCredential (resolves workload identity, CLI, env vars, …)
# No env var needed if DefaultAzureCredential can resolve credentials automatically.

# Option C — az CLI (local only)
# No env var needed; approve_pending.py falls back to az automatically.
```

---

## Complete lifecycle walkthrough

### Step 0 — Install providers

```bash
cd mpeHelper/terraform
terraform init
```

### Step 1 — Import existing MPEs (one-time bootstrap)

If you already have MPEs in your Fabric workspaces that were created outside
Terraform, run the import bootstrap to bring them under management without
recreating them.

```bash
# Scan all visible workspaces
python scripts/import_existing.py --output-dir .

# Or target specific workspaces
python scripts/import_existing.py \
  --workspace-ids 00000000-0000-0000-0000-000000000001 \
                  00000000-0000-0000-0000-000000000002 \
  --output-dir .
```

This writes two files:

- **`imports.tf`** — Terraform import blocks, one per discovered MPE.
- **`terraform.tfvars.json`** — `managed_private_endpoints` variable populated
  from the live inventory.

Then import into state:

```bash
terraform plan    # shows what will be imported
terraform apply   # imports all blocks — no resources are created or destroyed
```

After a successful import, `terraform plan` should show **zero changes**.

### Step 2 — Declare new MPEs

Edit (or create) `terraform.tfvars.json`:

```json
{
  "managed_private_endpoints": {
    "ws_prod_storage_blob": {
      "workspace_id": "00000000-0000-0000-0000-000000000001",
      "name":         "myStorageBlob",
      "target_resource_id": "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-prod/providers/Microsoft.Storage/storageAccounts/mysa",
      "target_subresource_type": "blob",
      "request_message": "Managed by Terraform"
    },
    "ws_prod_keyvault": {
      "workspace_id": "00000000-0000-0000-0000-000000000001",
      "name":         "myKeyVault",
      "target_resource_id": "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-prod/providers/Microsoft.KeyVault/vaults/mykv",
      "target_subresource_type": "vault",
      "request_message": "Managed by Terraform"
    }
  }
}
```

Optional variables (add at the top level of the JSON):

```json
{
  "run_label": "2026-01-15_10-00-00",
  "auto_approve": true,
  "max_deletes_guard": 5
}
```

### Step 3 — Plan and apply

```bash
terraform plan
terraform apply
```

New entries in the map create MPEs on the Fabric side. After apply they land
in `Provisioning` / `Pending` state.

### Step 4 — Approve Pending PECs (Azure side)

```bash
# Approve all Pending PECs for resources in terraform.tfvars.json
python scripts/approve_pending.py --tfvars-file terraform.tfvars.json

# Scope to this run's PECs only (requires run_label to have been set)
python scripts/approve_pending.py \
  --tfvars-file terraform.tfvars.json \
  --run-label   "2026-01-15_10-00-00"

# Dry-run first
python scripts/approve_pending.py --tfvars-file terraform.tfvars.json --dry-run
```

### Step 5 — Delete an MPE

Remove the entry from `managed_private_endpoints` in `terraform.tfvars.json`,
then:

```bash
terraform plan     # shows the destroy
terraform apply    # executes the destroy
```

The `max_deletes_guard` variable (default: 25) acts as a safety cap. If a
plan would destroy more MPEs than the cap, Terraform fails the plan before any
API call. Lower it for extra safety:

```json
{ "max_deletes_guard": 3 }
```

To destroy a **single** MPE without touching others:

```bash
terraform destroy -target='module.mpe["ws_prod_storage_blob"]'
```

### Step 6 — Recreate an MPE (replace)

```bash
# Tear down + rebuild a single endpoint without affecting peers
terraform apply -replace='module.mpe["ws_prod_storage_blob"]'
```

Terraform destroys and then recreates the resource in a single plan. Combine
with `run_label` so `approve_pending.py` can scope approval to this run only.

---

## Variable reference

| Variable | Type | Default | Description |
|---|---|---|---|
| `managed_private_endpoints` | `map(object)` | `{}` | Map of MPEs to manage (see above). |
| `run_label` | `string` | `""` | Optional label prepended to every `request_message` as `[run=<label>]`. Enables run-scoped approval. |
| `max_deletes_guard` | `number` | `25` | Refuse plan if more deletions are pending than this cap. |
| `auto_approve` | `bool` | `false` | Informational flag — exposed as an output so CI can decide whether to run `approve_pending.py`. |

### `managed_private_endpoints` object fields

| Field | Required | Description |
|---|---|---|
| `workspace_id` | ✅ | Fabric workspace GUID. |
| `name` | ✅ | Display name of the MPE within the workspace. |
| `target_resource_id` | ✅ | Full ARM resource ID of the target Azure resource. |
| `target_subresource_type` | — | Sub-resource type (e.g. `blob`, `file`, `dfs`, `vault`, `sqlServer`). |
| `request_message` | — | Request message (default: `"Managed by Terraform"`). |

---

## Output reference

| Output | Description |
|---|---|
| `managed_private_endpoints` | Map of deployed MPEs: `mpe_id`, `workspace_id`, `name`, `provisioning_state`. |
| `auto_approve` | Mirrors `var.auto_approve` — useful for CI gate logic. |

---

## CI integration

The `.github/workflows/ci-terraform.yml` workflow includes a `terraform` job (path-filtered to
`mpeHelper/terraform/**`) that runs:

1. `terraform fmt -check` — formatting validation
2. `terraform validate` — schema and reference checks (no real credentials needed)

### Full CI/CD pipeline example (GitHub Actions)

```yaml
- name: Terraform init
  run: terraform init
  working-directory: mpeHelper/terraform

- name: Terraform plan
  run: terraform plan -var-file=terraform.tfvars.json
  working-directory: mpeHelper/terraform

- name: Terraform apply
  run: terraform apply -auto-approve -var-file=terraform.tfvars.json
  working-directory: mpeHelper/terraform

- name: Approve pending PECs
  if: ${{ fromJson(steps.tf_output.outputs.stdout).auto_approve }}
  run: python scripts/approve_pending.py --tfvars-file terraform.tfvars.json
  working-directory: mpeHelper/terraform
```

---

## Known limitations

- **PEC approval is out-of-band.** The `microsoft/fabric` Terraform provider
  creates MPEs on the Fabric side; approving the resulting Private Endpoint
  Connections on the Azure side requires ARM calls (the `approve_pending.py`
  script). There is no `azurerm_private_endpoint_connection_approval` resource
  that covers this scenario end-to-end.
- **Cross-tenant ARM approvals** are not supported — same constraint as the
  notebook.
- **`targetFQDNs` is not round-tripped.** The Fabric LIST API doesn't return
  the FQDNs supplied at create time; Terraform state stores only what the
  provider returns.
- **Provider is in preview.** The `microsoft/fabric` provider (≥ 0.1) is
  still preview. Pin `version = "~> 0.1"` in `versions.tf` and monitor the
  [provider changelog](https://github.com/microsoft/terraform-provider-fabric/releases)
  for breaking changes.

---

## Running the unit tests

```bash
cd mpeHelper/terraform
pytest scripts/tests/ -v
```

No real Azure or Fabric credentials are required — all HTTP calls are mocked.
