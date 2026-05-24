# fabric-mpe

Safe, auditable, end-to-end lifecycle for **Microsoft Fabric Managed
Private Endpoints** (MPEs) across one or many workspaces.

```
INVENTORY  →  DRY-RUN  →  DELETE  →  RECREATE  →  APPROVE
```

Every step is gated by an explicit flag on `MpeConfig`, capped by a hard
limit, and persisted to a Delta audit table — so nothing destructive
happens by accident and you always have a paper trail.

The package ships as a normal Python wheel — install it once on your
cluster, then drive it from a thin eight-cell orchestration notebook
(`notebooks/mpe_manager.ipynb`).

## Install

From a Fabric notebook:

```
%pip install -q fabric-mpe==0.1.0
```

Or from source for development:

```pwsh
cd mpeHelper
pip install -e ".[dev]"
```

## Usage

The thin orchestration notebook runs eight cells — install, configure,
probe, inventory, dry-run, delete, recreate, approve. The interesting
ones look like this:

```python
# Cell 1 — install
%pip install -q fabric-mpe==0.1.0

# Cell 2 — configure (the only cell most users touch)
from fabric_mpe import MpeConfig
cfg = MpeConfig(
    workspace_scope = "visible",     # or "list" + workspaces=(...,)
    name_filter     = r"^test-",     # regex over mpe_name
    commit          = False,         # set True ONLY when you really want to delete
    max_deletes     = 25,
    recreate        = False,         # rebuild MPEs from the delete audit
    approve         = False,         # auto-approve resulting Pending PECs
)

# Cell 3 — probe (one-screen sanity banner)
from fabric_mpe import probe; probe(cfg)

# Cell 4 — inventory
from fabric_mpe import inventory
inv = inventory.run(cfg, spark)

# Cell 5 — dry-run
from fabric_mpe import delete
targets = delete.dry_run(cfg, spark)

# Cell 6 — commit
result = delete.commit(cfg, spark)

# Cell 7 — recreate (gated by cfg.recreate)
from fabric_mpe import recreate
rec = recreate.run(cfg, spark)

# Cell 8 — approve (gated by cfg.approve)
from fabric_mpe import approve
app = approve.run(cfg, spark)
```

## What it does

| Step | API | Default | What you get |
|---|---|---|---|
| **Inventory** | `inventory.run` | Always runs | Every MPE the caller can see, written to a Delta table + JSON + CSV under `/lakehouse/default/Files/<files_subdir>/<run_label>/`. |
| **Dry-run** | `delete.dry_run` | Always runs | Applies filters and returns the MPEs `delete.commit` *would* remove. No HTTP calls. |
| **Delete** | `delete.commit` | Skipped (`commit=False`) | Deletes only when `cfg.commit=True` *and* matches ≤ `cfg.max_deletes`. Logs every HTTP response to an audit Delta table. |
| **Recreate** | `recreate.run` | Skipped (`recreate=False`) | Rebuilds MPEs from the most-recent delete audit (default) or any prior inventory snapshot. Stamps each `requestMessage` with `[run=<run_label>]`. |
| **Approve** | `approve.run` | Skipped (`approve=False`) | Auto-approves the resulting Pending PECs on the Azure side via the ARM REST API. Matches by the run marker so only PECs from THIS run are touched. |

## Auth

Tokens flow through `fabric_core.auth.get_token`, which tries six
sources in order:

1. `notebookutils.credentials.getToken(audience)` (in Fabric)
2. `mssparkutils.credentials.getToken(audience)` (legacy Synapse)
3. `FABRIC_BEARER_TOKEN` / `AZURE_ACCESS_TOKEN` env vars
4. **SPN client-credentials** via `FABRIC_SPN_TENANT_ID` /
   `FABRIC_SPN_CLIENT_ID` / `FABRIC_SPN_CLIENT_SECRET` env vars
   (the reliable path for unattended runs)
5. `az account get-access-token --resource <audience>`
6. `azure.identity.DefaultAzureCredential`

The ARM token (for the Approve step) reuses the same chain against
`https://management.azure.com`, with two MPE-specific escape hatches
consulted first:

- `ARM_TOKEN` env var — paste a pre-acquired token.
- `ARM_SPN_TENANT_ID` / `ARM_SPN_CLIENT_ID` / `ARM_SPN_CLIENT_SECRET` —
  client-credentials grant for a different SPN than the Fabric one
  (typical when the target Azure resource lives in a different tenant
  or RBAC scope).

## Output tables

All four are append-only Delta. Every row is stamped with `run_label`
(the configured `MpeConfig.run_label`).

### `mpe_inventory`

| column | type | notes |
|---|---|---|
| `workspace_id` / `workspace_name` | string | |
| `mpe_id` / `mpe_name` | string | |
| `target_resource_id` | string | `targetPrivateLinkResourceId` |
| `target_subresource_type` | string | `blob`, `sqlServer`, `dfs`, … |
| `provisioning_state` | string | `Succeeded`, `Provisioning`, `Failed`, … |
| `connection_status` | string | `Approved`, `Pending`, `Rejected`, … |
| `connection_description` | string | |
| `run_label` | string | identifies the inventory batch |
| `collected_at` | timestamp | UTC |

### `mpe_delete_audit`

Inventory columns plus:

| column | type | notes |
|---|---|---|
| `delete_status` | int | HTTP status from the DELETE call |
| `delete_response` | string | JSON body (or raw text) returned |
| `deleted_at` | timestamp | UTC |

### `mpe_recreate_audit`

| column | type | notes |
|---|---|---|
| `workspace_id` / `workspace_name` | string | |
| `original_mpe_id` | string | the pre-delete MPE id |
| `new_mpe_id` | string | id returned by the create call (NULL on failure) |
| `mpe_name` / `target_resource_id` / `target_subresource_type` | string | what was sent to create |
| `request_message` | string | prefixed with `[run=<run_label>]` so approve can match it |
| `create_status` | int | HTTP status from the POST call |
| `create_response` | string | full JSON body |
| `new_provisioning_state` | string | typically `Provisioning` immediately after create |
| `source` | string | `audit` or `inventory` |
| `source_run_label` | string | run_label of the row we recreated from |
| `run_label` | string | this run's label |
| `created_at` | timestamp | UTC |

### `mpe_approve_audit`

| column | type | notes |
|---|---|---|
| `target_resource_id` | string | the Azure resource the PEC sits on |
| `target_rp` | string | e.g. `Microsoft.Storage/storageAccounts` |
| `api_version` | string | api-version used for the PUT (or LIST on error) |
| `pec_name` | string | the Azure-side connection name (auto-generated) |
| `pec_description` | string | the connection's description = the requestMessage we set in recreate |
| `mpe_name` / `original_mpe_id` / `new_mpe_id` | string | linkage back to the Fabric MPE |
| `approve_status` | int | HTTP status from the PUT (LIST errors also recorded with their status) |
| `approve_response` | string | full JSON body |
| `new_connection_state` | string | `Approved` on success |
| `source_run_label` | string | run_label of the recreate run we approved for |
| `run_label` | string | this run's label |
| `approved_at` | timestamp | UTC |

## Useful follow-up queries

```sql
-- Most-recent record per (workspace, mpe)
SELECT * FROM mpe_inventory
WHERE (workspace_id, mpe_id, collected_at) IN (
  SELECT workspace_id, mpe_id, MAX(collected_at)
  FROM mpe_inventory GROUP BY workspace_id, mpe_id);

-- MPEs deleted in the last 7 days
SELECT * FROM mpe_delete_audit
WHERE deleted_at > current_timestamp() - INTERVAL 7 DAYS
  AND delete_status BETWEEN 200 AND 299;

-- Full round-trip: deleted → recreated → approved
SELECT d.mpe_name, d.workspace_name,
       d.mpe_id AS old_id, r.new_mpe_id,
       d.deleted_at, r.created_at, a.approved_at,
       r.create_status, a.approve_status, a.new_connection_state
FROM mpe_delete_audit d
LEFT JOIN mpe_recreate_audit r ON r.original_mpe_id = d.mpe_id
LEFT JOIN mpe_approve_audit  a ON a.new_mpe_id     = r.new_mpe_id
WHERE d.delete_status BETWEEN 200 AND 299
ORDER BY d.deleted_at DESC;
```

## API reference

| Operation | Endpoint | Role |
|---|---|---|
| List MPEs | `GET /v1/workspaces/{wid}/managedPrivateEndpoints` | Fabric Viewer |
| Create MPE | `POST /v1/workspaces/{wid}/managedPrivateEndpoints` | **Fabric Admin** |
| Delete MPE | `DELETE /v1/workspaces/{wid}/managedPrivateEndpoints/{mpeId}` | **Fabric Admin** |
| List PECs (Azure) | `GET {targetResourceId}/privateEndpointConnections?api-version=…` | Reader on target resource |
| Approve PEC (Azure) | `PUT {targetResourceId}/privateEndpointConnections/{name}?api-version=…` | `*/privateEndpointConnections/write` on target |

All calls go through `fabric_core.http.request_json`, which honours 429
`Retry-After` and does exponential backoff on 5xx. Pagination
(`continuationToken` / `continuationUri` / `nextLink`) is handled by
`fabric_core.http.collect_paged`.

### Supported resource-provider api-versions

`fabric_mpe.arm.PEC_API_VERSIONS` ships with conservative GA versions
for these RPs. Anything else falls back to `2023-09-01`
(`Microsoft.Network` generic). Mutate the dict at runtime to add or
override.

| Resource provider | api-version |
|---|---|
| `Microsoft.Storage/storageAccounts` | `2023-05-01` |
| `Microsoft.Sql/servers` | `2023-08-01-preview` |
| `Microsoft.KeyVault/vaults` | `2023-07-01` |
| `Microsoft.DocumentDB/databaseAccounts` | `2023-04-15` |
| `Microsoft.EventHub/namespaces` | `2024-01-01` |
| `Microsoft.ServiceBus/namespaces` | `2022-10-01-preview` |
| `Microsoft.Synapse/workspaces` | `2021-06-01` |
| `Microsoft.Search/searchServices` | `2023-11-01` |
| `Microsoft.CognitiveServices/accounts` | `2023-05-01` |
| `Microsoft.AppConfiguration/configurationStores` | `2023-03-01` |
| `Microsoft.Web/sites` | `2023-12-01` |
| `Microsoft.ContainerRegistry/registries` | `2023-11-01-preview` |
| `Microsoft.DataFactory/factories` | `2018-06-01` |
| `Microsoft.Purview/accounts` | `2021-12-01` |

## Troubleshooting

### `Could not acquire an ARM token`

In Fabric the workspace identity typically can't mint ARM tokens. Three
reliable options, in order of preference:

```python
# Option 1 — SPN env vars (auto-detected by get_arm_token)
import os
os.environ["ARM_SPN_TENANT_ID"]     = "..."
os.environ["ARM_SPN_CLIENT_ID"]     = "..."
os.environ["ARM_SPN_CLIENT_SECRET"] = "..."

# Option 2 — paste a pre-acquired token (one-off)
os.environ["ARM_TOKEN"] = "eyJ0eXAi..."

# Option 3 — run locally with az login
# az login; the chain picks up Azure CLI automatically.
```

### `HTTP 403 AuthorizationFailed` from the approve step

The ARM token is fine but the caller lacks RBAC on the target Azure
resource. Required action: `*/privateEndpointConnections/read` (for
LIST) and `*/privateEndpointConnections/write` (for PUT). Built-in
roles that work: `Owner`, `Contributor`, RP-specific contributor roles.

Cross-tenant: if the target resource lives in a different tenant from
the caller, `ARM_TOKEN` must come from that other tenant's identity.

### Approve reports "0 pending PEC(s) match marker"

Either there are no Pending connections (recreate succeeded but the
resource owner approved manually), or their description doesn't include
`[run=<run_label>]` (recreate didn't run this session). Set
`approve_run_label` on the config to point at an older recreate run.

### Add a new resource provider's api-version

```python
from fabric_mpe.arm import PEC_API_VERSIONS
PEC_API_VERSIONS["Microsoft.YourRp/yourType"] = "2024-XX-XX"
```

## Tests

`pytest tests/unit -q` runs the offline test suite (config, filters,
ARM/api wrappers, persist, inventory, delete, recreate, approve, auth
shim, and the no-cross-imports guard).

## License

MIT. See [LICENSE](../LICENSE).
