# Fabric Managed Private Endpoint Manager

A Microsoft Fabric notebook (`mpe_manager.ipynb`) that gives you a safe,
auditable, end-to-end lifecycle for **Managed Private Endpoints** (MPEs)
across one or more Fabric workspaces:

```
INVENTORY  →  DRY-RUN  →  DELETE  →  RECREATE  →  APPROVE
```

Every step is gated by an explicit flag, capped by a hard limit, and persisted
to a Delta audit table — so nothing destructive happens by accident and you
always have a paper trail.

A standalone CLI variant (`fabric_mpe_manager.py`) covers inventory + delete
for workstation use without Spark.

---

## What it does

| Step | Cell | Default state | What you get |
|---|---|---|---|
| **Inventory** | 3 | Always runs | Every MPE the caller can see, written to a Delta table + JSON + CSV under `Files/`. Pageable across as many workspaces as you can list. |
| **Dry-run** | 4 | Always runs | Applies your filters and shows exactly which MPEs *would* be deleted. Refuses if matches exceed `MAX_DELETES`. |
| **Delete** | 5 | Skipped (`COMMIT=False`) | Deletes only when `COMMIT=True` *and* matches ≤ `MAX_DELETES`. Logs every HTTP response (success and failure) to an audit Delta table. |
| **Recreate** | 6 | Skipped (`RECREATE=False`) | Rebuilds MPEs from the most-recent delete-audit (default) or any prior inventory snapshot. Stamps each `requestMessage` with `[run=<RUN_LABEL>]` so cell 7 can match them. |
| **Approve** | 7 | Skipped (`APPROVE=False`) | Auto-approves the resulting Pending PECs on the Azure side via the ARM REST API. Matches by the run marker so only PECs from THIS run are touched. |

---

## Architecture

```
                    ┌──────────────────────────────┐
   cell 1 ─────────►│ Config + RUN_LABEL           │
                    │  WORKSPACE_SCOPE, filters,   │
                    │  COMMIT, RECREATE, APPROVE,  │
                    │  MAX_* caps                  │
                    └──────────────┬───────────────┘
                                   │
   cell 2 ─────────► get_token()   │  3-tier: MPE_TOKEN env →
   cell 2b (opt) ──► SPN sample    │           notebookutils("pbi") →
                                   │           az CLI
                                   ▼
   cell 3 ─────────► list_workspaces + list_mpes
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ mpe_inventory  (Delta)       │
                    │   + Files/inventory.json     │
                    │   + Files/inventory.csv      │
                    └──────────────┬───────────────┘
                                   │
   cell 4 ─────────► apply_filters (preview only)
                                   │
   cell 5 ─────────► delete_mpe + audit
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ mpe_delete_audit  (Delta)    │
                    └──────────────┬───────────────┘
                                   │
   cell 6 ─────────► create_mpe + audit
                                   │   (stamps [run=RUN_LABEL] marker
                                   │    into requestMessage)
                                   ▼
                    ┌──────────────────────────────┐
                    │ mpe_recreate_audit (Delta)   │
                    └──────────────┬───────────────┘
                                   │
   cell 7 ─────────► get_arm_token() [different audience]
                     list_pecs (ARM)
                     filter to Pending + marker
                     approve_pec (ARM PUT)
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ mpe_approve_audit  (Delta)   │
                    └──────────────────────────────┘
```

---

## Repository layout

The notebook is **generated** from one source file per cell so each piece can
be unit-tested, lint-checked, and reviewed in isolation:

```
C:\Users\timarif\
├── mpe_manager.ipynb               <- the final artifact (generated)
├── build_mpe_nb.py                 <- assembles the notebook from cells
├── validate_mpe_nb.py              <- 50+ offline assertions (compile + static-ref + safety)
├── fabric_mpe_manager.py           <- standalone CLI (inventory + delete)
├── test_fabric_mpe_manager.py      <- 28 offline tests for the CLI
└── _mpe_cells\
    ├── 00_cover.md                 <- markdown cover (title + workflow + prereqs)
    ├── 01_config.py                <- all knobs (one file = one cell)
    ├── 02_module.py                <- helpers (auth, REST, filters, Delta paths)
    ├── 02b_auth_spn_sample.py      <- optional SPN sample (unattended runs)
    ├── 03_inventory.py             <- discover + persist
    ├── 04_dry_run.py               <- filter preview, no writes
    ├── 05_commit.py                <- delete + delete-audit (gated by COMMIT)
    ├── 06_recreate.py              <- create + recreate-audit (gated by RECREATE)
    ├── 07_approve.py               <- Azure-side PEC approve + approve-audit (gated by APPROVE)
    └── 99_readme.md                <- embedded usage reference (becomes the last cell)
```

Rebuild + validate after any cell edit:

```powershell
python build_mpe_nb.py        # writes mpe_manager.ipynb
python validate_mpe_nb.py     # 50+ assertions, exits non-zero on failure
```

---

## Quick start

1. **Upload `mpe_manager.ipynb`** into a Fabric workspace and attach a default
   Lakehouse.
2. **Run cell 1** as-is (everything in dry-run mode by default).
3. **Run cells 2 → 3 → 4**. Cell 3 inventories every MPE you can see. Cell 4
   shows what your filters match.
4. **Inspect the dry-run output.** If it looks right, edit cell 1: set
   `COMMIT=True`, re-run cell 1, then run cell 5.
5. **To re-create what you just deleted:** set `RECREATE=True` in cell 1,
   re-run cell 1, then run cell 6.
6. **To auto-approve the resulting Pending PECs on the Azure side:** set
   `APPROVE=True` in cell 1, re-run cell 1, then run cell 7. (Requires a
   separate ARM token — see [Authentication](#authentication).)

---

## Configuration (cell 1)

Every knob lives in `_mpe_cells/01_config.py`. The cell prints a summary at
the top of every run.

### Scope

| Knob | Default | Notes |
|---|---|---|
| `WORKSPACE_SCOPE` | `"visible"` | `"visible"` = every workspace caller can see; `"list"` = just the IDs in `WORKSPACES`; `"from_inventory"` = reload from the latest matching run in Delta. |
| `WORKSPACES` | `[]` | List of workspace IDs (used only with `WORKSPACE_SCOPE="list"`). |

### Persistence

| Knob | Default | Notes |
|---|---|---|
| `INVENTORY_TABLE` | `"mpe_inventory"` | Delta table for inventories (appended every run, keyed by `run_label`). |
| `AUDIT_TABLE` | `"mpe_delete_audit"` | Delta table for delete results. |
| `RECREATE_TABLE` | `"mpe_recreate_audit"` | Delta table for create-after-delete results. |
| `APPROVE_TABLE` | `"mpe_approve_audit"` | Delta table for Azure-side approval results. |
| `WRITE_SCHEMA` | `""` | Optional Spark schema/database prefix (e.g. `"audit"` → `audit.mpe_inventory`). |
| `FILES_SUBDIR` | `"mpe_manager"` | Subfolder under `Files/` for JSON/CSV outputs. |

### Filters (apply in cells 4, 5, 6)

| Knob | Default | Notes |
|---|---|---|
| `NAME_FILTER` | `None` | Python regex over MPE display name. |
| `ID_FILTER` | `[]` | Explicit list of MPE IDs to include. Cell 6 ignores this because IDs change on recreate. |
| `TARGET_FILTER` | `None` | Regex over `targetPrivateLinkResourceId`. |

### Deletion safety (cell 5)

| Knob | Default | Notes |
|---|---|---|
| `COMMIT` | `False` | Master switch. Cell 5 is a no-op until this is `True`. |
| `MAX_DELETES` | `25` | Cell 5 aborts with `RuntimeError` if matches exceed this. |

### Recreate (cell 6)

| Knob | Default | Notes |
|---|---|---|
| `RECREATE` | `False` | Master switch. Cell 6 is a preview until this is `True`. |
| `RECREATE_SOURCE` | `"audit"` | `"audit"` rebuilds what was just deleted; `"inventory"` rebuilds from any inventory snapshot. |
| `RECREATE_RUN_LABEL` | `None` | Defaults to the current run; set to an older `RUN_LABEL` to reach back in time. |
| `RECREATE_REQUEST_MESSAGE` | `"Recreated via mpe_manager.ipynb"` | Cell 6 prepends `[run=<RUN_LABEL>]` so cell 7 can match. |
| `MAX_RECREATES` | `25` | Hard cap. |

### Approve (cell 7)

| Knob | Default | Notes |
|---|---|---|
| `APPROVE` | `False` | Master switch. Cell 7 is a preview until this is `True`. |
| `APPROVE_DESCRIPTION` | `"Approved by mpe_manager"` | Goes into the PEC's `description` field after approval. |
| `APPROVE_RUN_LABEL` | `None` | Defaults to current run; set to approve PECs from an older recreate run. |
| `MAX_APPROVES` | `25` | Hard cap. |

### API / Auth

| Knob | Default | Notes |
|---|---|---|
| `FABRIC_BASE` | `"https://api.fabric.microsoft.com"` | Fabric REST root. |
| `ARM_BASE` | `"https://management.azure.com"` | Azure ARM root (cell 7 only). |
| `TOKEN_AUDIENCE` | `"pbi"` | Audience name passed to `notebookutils.credentials.getToken(...)`. |

### Auto-generated

| Name | What it is |
|---|---|
| `RUN_LABEL` | UTC timestamp `YYYY-MM-DD_HH-MM-SS` set at cell-1 execution. Used as the partition key in every audit row and as the run marker stamped into recreate request messages. |

---

## Safety design

The notebook treats every destructive action as something the operator must
**actively opt into**.

1. **Two-step destructive flow.** Every destructive cell (5, 6, 7) is a no-op
   until you flip a boolean (`COMMIT`, `RECREATE`, `APPROVE`) and re-run
   cell 1.
2. **Hard caps.** Each destructive cell aborts with `RuntimeError` before any
   API call if `len(targets) > MAX_*`.
3. **Defensive table reads.** Cells 6 and 7 probe `spark.catalog.tableExists`
   before reading source tables. Missing audit tables produce a friendly skip
   in preview mode (`*=False`) and a clear `RuntimeError` in commit mode.
4. **Self-contained recompute.** Destructive cells re-read targets from Delta
   at the top, so out-of-order execution doesn't surprise you.
5. **Full audit.** Every HTTP response (success *and* failure, including LIST
   errors from cell 7) lands in a Delta table with its status code, response
   body, and a timestamp.
6. **Run-scoped approval.** Cell 7 only PUTs Approved on PECs whose
   description contains the `[run=<RUN_LABEL>]` marker that cell 6 stamped in
   — so you can never accidentally approve someone else's pending connection.
7. **Validator with safety asserts.** `validate_mpe_nb.py` has 17 cross-cell
   safety assertions (gated calls, ordering checks, no-cross-call rules) that
   run on every rebuild.

---

## Authentication

Two different token audiences are needed depending on the cell:

| Cells | Audience | Why |
|---|---|---|
| 3, 5, 6 | Fabric REST (`pbi`) | Workspace MPE LIST/POST/DELETE. |
| 7 | Azure ARM (`https://management.azure.com`) | LIST + PUT on the target Azure resource's `privateEndpointConnections`. |

### Fabric token — `get_token()`

Tries (in order):

1. **`MPE_TOKEN` env var** — pre-set by the user or by cell 2b.
2. **`notebookutils.credentials.getToken("pbi")`** — default in Fabric.
3. **`az account get-access-token --resource https://api.fabric.microsoft.com`** — local.

### ARM token — `get_arm_token()`

Tries (in order):

1. **`ARM_TOKEN` env var** — pre-set by the user (most reliable in Fabric).
2. **`notebookutils.credentials.getToken("https://management.azure.com/")`**
   and 3 variants — *usually fails in Fabric* because the workspace identity
   typically isn't allowed to mint ARM tokens; included for completeness.
3. **SPN client-credentials via `ARM_SPN_TENANT_ID` / `ARM_SPN_CLIENT_ID` /
   `ARM_SPN_CLIENT_SECRET` env vars** — reliable in Fabric; cell 2b sets
   these for you when its `SPN_*` are filled in.
4. **`az account get-access-token --resource https://management.azure.com`**
   — local only.

If all four fail, the `RuntimeError` includes the exact failure for every
attempt so you can see what to fix.

### Service principal (cell 2b — optional)

`02b_auth_spn_sample.py` is a no-op until you fill in three knobs:

```python
SPN_TENANT_ID     = "<tenant guid>"
SPN_CLIENT_ID     = "<app registration client id>"
SPN_CLIENT_SECRET = "<value>"      # or pull from Key Vault — see commented snippet
```

When set, the cell:

1. Mints a **Fabric** token via `client_credentials` and exports it as
   `MPE_TOKEN`. Refreshes the module-level `TOKEN` immediately.
2. Mirrors the SPN into `ARM_SPN_TENANT_ID` / `ARM_SPN_CLIENT_ID` /
   `ARM_SPN_CLIENT_SECRET` so `get_arm_token()` can fall back to it later.
3. Pre-fetches an **ARM** token from the same SPN and exports it as
   `ARM_TOKEN`. Non-fatal if the SPN lacks ARM RBAC — cell 7 will surface
   the real error.

#### Prerequisites for SPN

- Tenant admin: enable **"Service principals can use Fabric APIs"**
  (Admin portal → Tenant settings → Developer settings).
- Add the SPN as **Workspace Admin** on every workspace you want to scan.
- For cell 7: grant the SPN
  `Microsoft.<Provider>/<resourceType>/privateEndpointConnections/write`
  (typically `Contributor` or `Owner`) on each **target Azure resource**.
- Store the secret in Key Vault. Cell 2b includes a commented snippet using
  `notebookutils.credentials.getSecret(...)` so the workspace identity reads
  KV instead of you pasting the secret into the notebook.

### Quick token paste (one-off / local)

```powershell
# from your laptop
az login
az account get-access-token --resource https://management.azure.com `
    --query accessToken -o tsv > arm_token.txt
```

Then in a scratch cell of the notebook:

```python
import os
with open(r"C:\path\to\arm_token.txt") as f:
    os.environ["ARM_TOKEN"] = f.read().strip()
```

Lifetime: ~60–90 minutes.

---

## Audit tables

All three tables append-only, partitioned implicitly by `run_label`, with full
HTTP response bodies for forensics.

### `mpe_inventory`

| column | type | notes |
|---|---|---|
| `workspace_id` / `workspace_name` | string | |
| `mpe_id` / `mpe_name` | string | |
| `target_resource_id` | string | `targetPrivateLinkResourceId` from the Fabric API |
| `target_subresource_type` | string | `blob`, `sqlServer`, `dfs`, ... |
| `provisioning_state` | string | `Succeeded`, `Provisioning`, `Failed`, ... |
| `connection_status` | string | `Approved`, `Pending`, `Rejected`, ... |
| `connection_description` | string | |
| `run_label` | string | identifies this inventory batch |
| `collected_at` | timestamp | UTC |

### `mpe_delete_audit`

All inventory columns plus:

| column | type | notes |
|---|---|---|
| `delete_status` | int | HTTP status from the DELETE call |
| `delete_response` | string | JSON body (or raw text on parse failure) |
| `deleted_at` | timestamp | UTC |

### `mpe_recreate_audit`

| column | type | notes |
|---|---|---|
| `workspace_id` / `workspace_name` | string | |
| `original_mpe_id` | string | pre-delete MPE id |
| `new_mpe_id` | string | id returned by POST (NULL on failure) |
| `mpe_name` / `target_resource_id` / `target_subresource_type` | string | what was sent |
| `request_message` | string | prefixed with `[run=<RUN_LABEL>]` |
| `create_status` | int | HTTP status from POST |
| `create_response` | string | full JSON body |
| `new_provisioning_state` | string | `Provisioning` immediately after create |
| `source` | string | `audit` or `inventory` |
| `source_run_label` | string | run_label of the row we recreated from |
| `run_label` | string | this run's label |
| `created_at` | timestamp | UTC |

### `mpe_approve_audit`

| column | type | notes |
|---|---|---|
| `target_resource_id` | string | the Azure resource the PEC sits on |
| `target_rp` | string | e.g. `Microsoft.Storage/storageAccounts` |
| `api_version` | string | api-version used for the PUT |
| `pec_name` | string | Azure-side connection name (auto-generated) |
| `pec_description` | string | the PEC's description = the requestMessage cell 6 set |
| `mpe_name` / `original_mpe_id` / `new_mpe_id` | string | linkage to the Fabric MPE |
| `request_message` | string | what cell 6 originally posted |
| `approve_status` | int | HTTP status from PUT (LIST errors recorded with their status too) |
| `approve_response` | string | full JSON body |
| `new_connection_state` | string | `Approved` on success |
| `source_run_label` | string | recreate run we approved for |
| `run_label` | string | this run's label |
| `approved_at` | timestamp | UTC |

---

## Useful queries

```sql
-- Latest inventory snapshot per MPE
SELECT * FROM mpe_inventory
WHERE (workspace_id, mpe_id, collected_at) IN (
  SELECT workspace_id, mpe_id, MAX(collected_at)
  FROM mpe_inventory GROUP BY workspace_id, mpe_id);

-- MPEs deleted in the last 7 days, successful only
SELECT * FROM mpe_delete_audit
WHERE deleted_at > current_timestamp() - INTERVAL 7 DAYS
  AND delete_status BETWEEN 200 AND 299;

-- Recreate failures that need attention
SELECT * FROM mpe_recreate_audit
WHERE create_status >= 400
ORDER BY created_at DESC;

-- Approval failures, grouped by target resource provider
SELECT target_rp,
       COUNT(*) AS failed,
       MIN(approve_status) AS first_status
FROM mpe_approve_audit
WHERE approve_status >= 400
GROUP BY target_rp
ORDER BY failed DESC;

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

---

## Worked example — full round-trip

```text
# In cell 1, leave defaults except for whatever scope you want.
WORKSPACE_SCOPE = "list"
WORKSPACES      = ["<wid-1>", "<wid-2>"]
NAME_FILTER     = "^test-"        # only touch MPEs named test-*

# Run cells 1 → 2 → 3
[OK] Token acquired.
Inventoried 7 MPEs across 2 workspace(s).

# Run cell 4 — preview
COMMIT=False; skipping. 3 MPE(s) would be deleted.

# Edit cell 1: COMMIT = True, re-run cell 1, run cell 5
  [1/3] abcd1234-...: deleted (200)
  [2/3] efgh5678-...: deleted (200)
  [3/3] ijkl9012-...: deleted (200)
Done: 3 deleted, 0 failed. Audit appended to mpe_delete_audit.

# Edit cell 1: RECREATE = True, re-run cell 1, run cell 6
Source 'audit' (run_label=2026-05-22_05-04-06): 3 candidate row(s)
Filters match 3 MPE(s).
  [1/3] 'test-storage-prd': created (new_id=qrst3456-..., state=Provisioning)
  [2/3] 'test-storage-dev': created (new_id=uvwx7890-..., state=Provisioning)
  [3/3] 'test-sql-prd':     created (new_id=yzab1234-..., state=Provisioning)
Done: 3 created, 0 failed.

# Edit cell 1: APPROVE = True, re-run cell 1, run cell 7
Recreate audit (run_label=2026-05-22_05-04-06): 3 successful recreate(s).
  - /subscriptions/.../tvaadlssyn01: 1 pending PEC(s) match marker (rp=Microsoft.Storage/storageAccounts)
  - /subscriptions/.../tvaadlssyn02: 1 pending PEC(s) match marker
  - /subscriptions/.../tvasql01:     1 pending PEC(s) match marker
Total pending PECs queued for approval: 3
  [1/3] msstor_xx.<guid>: approved (state=Approved)
  [2/3] msstor_yy.<guid>: approved (state=Approved)
  [3/3] mssql_zz.<guid>:  approved (state=Approved)
Done: 3 approved, 0 failed.
```

---

## Troubleshooting

### `[TABLE_OR_VIEW_NOT_FOUND] mpe_delete_audit`

You're running cell 6 or 7 before populating the source table. Cells 6 and 7
probe `spark.catalog.tableExists` first; in preview mode they print a
friendly skip, in commit mode they raise. Either:

- Set `RECREATE_SOURCE = "inventory"` in cell 1 to bypass the delete audit
  entirely, or
- Run cell 5 with `COMMIT=True` first.

### `Could not acquire an ARM token`

In Fabric the workspace identity typically can't mint ARM tokens via
`notebookutils.credentials.getToken(...)`. Three reliable options:

```python
# Option 1 — paste a pre-acquired token (one-off)
import os
os.environ["ARM_TOKEN"] = "eyJ0eXAi..."

# Option 2 — set SPN env vars (cell 2b does this for you when SPN_* are filled)
os.environ["ARM_SPN_TENANT_ID"]     = "..."
os.environ["ARM_SPN_CLIENT_ID"]     = "..."
os.environ["ARM_SPN_CLIENT_SECRET"] = "..."

# Option 3 — run locally with az login
# az login; az account get-access-token --resource https://management.azure.com
```

### `HTTP 403 AuthorizationFailed` from cell 7's LIST or PUT

The ARM token is fine (Azure identified the caller) but the caller lacks
RBAC on the target Azure resource. Required action:

```
Microsoft.<Provider>/<resourceType>/privateEndpointConnections/read   (LIST)
Microsoft.<Provider>/<resourceType>/privateEndpointConnections/write  (PUT)
```

Built-in roles that work: `Owner`, `Contributor`, `Storage Account Contributor`
(for storage), `SQL Server Contributor` (for SQL), etc.

Cross-tenant: if the target resource lives in a different tenant from the
caller, `ARM_TOKEN` must come from that other tenant's identity.

### `RECREATE_REQUEST_MESSAGE too long` (HTTP 400 from cell 6)

The Fabric API caps `requestMessage` at 140 chars. Cell 6 truncates with
`[:140]` *after* prepending the run marker, so the marker always survives.
If you're still seeing 400s, shrink `RECREATE_REQUEST_MESSAGE` in cell 1.

### Cell 7 reports "0 pending PEC(s) match marker"

The target's PEC list either:

- has no Pending connections at all (cell 6 succeeded but the resource owner
  manually approved them already), or
- has Pending connections but their description doesn't include
  `[run=<RUN_LABEL>]` (cell 6 didn't run this session, so the marker is wrong).

Set `APPROVE_RUN_LABEL` in cell 1 to the older run's `RUN_LABEL` if you're
approving from a prior recreate.

### Cell 7 unknown resource provider

`get_arm_token()` succeeded but `list_pecs` got HTTP 400 / 404 because the
api-version isn't right for that resource provider. Add the RP to
`_PEC_API_VERSIONS` in `02_module.py`:

```python
_PEC_API_VERSIONS["Microsoft.YourRp/yourType"] = "2024-XX-XX"
```

Default fallback is `2023-09-01` (Microsoft.Network generic).

---

## Standalone CLI variant

`fabric_mpe_manager.py` is a thin sister script that covers
inventory + delete without Spark or a lakehouse. Useful from a workstation
with `az login`:

```powershell
# Dry-run (default)
python fabric_mpe_manager.py inventory --out C:\tmp\mpe_inv
python fabric_mpe_manager.py delete    --from-inventory C:\tmp\mpe_inv\inventory.json `
                                       --name-filter "^test-"

# Commit
python fabric_mpe_manager.py delete    --from-inventory ... --commit
```

28 offline tests in `test_fabric_mpe_manager.py` (`python -m unittest`).

The CLI does **not** implement recreate or approve — for those, use the
notebook.

---

## Terraform variant

A declarative IaC alternative lives under
[`mpeHelper/terraform/`](./terraform/). It manages the same
`INVENTORY → DELETE → RECREATE → APPROVE` lifecycle through the official
[`microsoft/fabric` provider](https://registry.terraform.io/providers/microsoft/fabric/latest/docs)
plus two thin Python scripts:

```
mpeHelper/terraform/
├── main.tf, variables.tf, outputs.tf, providers.tf, versions.tf
├── modules/
│   └── managed_private_endpoint/         # wraps fabric_workspace_managed_private_endpoint
└── scripts/
    ├── import_existing.py                # inventories existing MPEs and emits `terraform import` commands
    └── approve_pending.py                # ARM-side approve for any PECs still Pending after `apply`
```

Typical workflow:

```bash
# 1. Inventory + generate import commands from any existing MPEs
python scripts/import_existing.py --workspace <ws-id> --out import.sh

# 2. Bring the existing endpoints under Terraform state
terraform init
bash import.sh

# 3. Make changes declaratively, then apply
terraform plan
terraform apply

# 4. Approve the target-side PECs the provider can't approve itself
python scripts/approve_pending.py --workspace <ws-id>

# 5. Tear down
terraform destroy
```

Use the Terraform module when you need:

- **Reproducible state** across environments (dev / preprod / prod) without
  re-running notebook cells.
- **Plan + review** in PRs before any mutation hits Fabric.
- **`terraform destroy` + re-apply** as a routine MPE refresh pattern.

The notebook and Terraform variants are independent — pick whichever matches
your operational model. See
[`mpeHelper/terraform/README.md`](./terraform/README.md) for the full
provider configuration, authentication options, and the `import` /
`approve` script reference.

---

## Developer notes

### Cells-and-build pattern

Each cell is one file under `_mpe_cells/`. Lex-ordered:

- `.md` → markdown cell
- `.py` → code cell

`build_mpe_nb.py` globs the directory, builds a notebook JSON with Synapse
PySpark kernel metadata, and writes `mpe_manager.ipynb`. Re-run after any
cell edit:

```powershell
python build_mpe_nb.py
```

### Validator (`validate_mpe_nb.py`)

Runs entirely offline. 52 assertions across three layers:

1. **Compile** — every code cell parses.
2. **Static reference** — every `ast.Name(ctx=Load)` resolves against
   accumulated `ast.Name(ctx=Store)` defs from prior cells, runtime knowns
   (`spark`, `display`, etc.), and stdlib.
3. **Safety asserts** — 17 cross-cell rules:
   - Inventory cell never calls `delete_mpe` or `create_mpe`.
   - Commit cell gates `delete_mpe` behind `COMMIT`, references `MAX_DELETES`
     before `delete_mpe(`, writes `audit_df` to `AUDIT_TABLE`.
   - Recreate cell gates `create_mpe` behind `RECREATE`, references
     `MAX_RECREATES` first, writes to `RECREATE_TABLE`, never calls
     `delete_mpe`, stamps the `[run=...]` marker into `requestMessage`.
   - Approve cell gates `approve_pec` behind `APPROVE`, references
     `MAX_APPROVES` first, never calls `delete_mpe`/`create_mpe`, filters
     PECs by `marker_substr`, writes to `APPROVE_TABLE`.
   - SPN sample is a no-op unless all three `SPN_*` are set, exports both
     `MPE_TOKEN` and `ARM_TOKEN`.
4. **Offline exec** — runs cells 0 + 1 + 2 with `notebookutils` stubbed,
   asserts `get_token`, `get_arm_token`, `_fetch_token_via_spn`, `list_pecs`,
   `approve_pec`, `apply_filters`, `_delta_target`, `_files_path`,
   `_pec_api_version` are defined and behave correctly on synthetic inputs.

Exit code is non-zero on any failure — wire into CI / pre-commit.

```powershell
python build_mpe_nb.py && python validate_mpe_nb.py
```

### Adding a new cell

1. Create `_mpe_cells/NN_<name>.py` (or `.md`) with a name that sorts where
   you want it (e.g. `04b_<name>.py` sits between cells 4 and 5).
2. Run `python build_mpe_nb.py`.
3. Update the safety_checks cell indices in `validate_mpe_nb.py` if you
   inserted a code cell in the middle (each existing index shifts by +1).
4. Add safety + offline-exec assertions for the new cell.
5. Run `python validate_mpe_nb.py`.
6. Update `_mpe_cells/00_cover.md` and `_mpe_cells/99_readme.md` so the
   embedded docs stay in sync.

---

## API reference

| Operation | Endpoint | Role |
|---|---|---|
| List MPEs | `GET /v1/workspaces/{wid}/managedPrivateEndpoints` | Fabric Viewer |
| Create MPE | `POST /v1/workspaces/{wid}/managedPrivateEndpoints` | **Fabric Admin** |
| Delete MPE | `DELETE /v1/workspaces/{wid}/managedPrivateEndpoints/{mpeId}` | **Fabric Admin** |
| List PECs (Azure) | `GET {targetResourceId}/privateEndpointConnections?api-version=…` | Reader on target resource |
| Approve PEC (Azure) | `PUT {targetResourceId}/privateEndpointConnections/{name}?api-version=…` body `{properties.privateLinkServiceConnectionState.status: "Approved"}` | `*/privateEndpointConnections/write` on target resource |

All calls go through the shared `_req` helper, which honours 429
`Retry-After` and does exponential backoff on 5xx. ARM and Fabric have the
same response shape, so the helper is reused for both audiences — only the
token is different.

### Supported resource-provider api-versions (cell 7)

`_PEC_API_VERSIONS` in `_mpe_cells/02_module.py` ships with conservative GA
versions for these RPs. Anything else falls back to `2023-09-01`
(`Microsoft.Network` generic).

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

---

## Known limitations

- **`targetFQDNs` is not round-tripped.** Fabric's LIST API doesn't return
  the FQDNs you supplied at create time. For most providers (Storage, SQL,
  KV, etc.) the platform derives FQDNs automatically from
  `targetPrivateLinkResourceId`, so this rarely matters. For RPs that need
  explicit FQDNs, set them in `_mpe_cells/06_recreate.py` before calling
  `create_mpe(...)`.
- **Cell 7's matching depends on `requestMessage`.** If a different tool
  recreated the same MPE without stamping the `[run=...]` marker, cell 7
  won't approve it. This is intentional — fall back to the Azure portal for
  PECs the notebook didn't create.
- **Cross-tenant ARM is manual.** The SPN flow assumes the same SPN works in
  both tenants. For true cross-tenant scenarios, set `ARM_TOKEN` directly
  from whatever flow your security org allows.
- **Capacity / network scope is not validated.** The notebook calls Fabric
  REST; if the workspace's capacity is in a region or VNet that can't reach
  the target Azure resource at all, MPE creation will succeed but the
  connection itself will fail later. Out of scope for this tool — that's a
  network / capacity admin concern.

---

## Changelog

- **v1** — inventory + delete (cells 1–5). CLI sister script in parallel.
- **v2** — added recreate (cell 6) sourced from audit or inventory.
- **v3** — added SPN sample (cell 2b) for unattended runs.
- **v4** — added Azure-side approve (cell 7) with per-RP api-version dispatch
  and run-scoped PEC matching. Hardened `get_arm_token` with 4-path
  fallback. Defensive `tableExists` checks in cells 6 and 7.

---

## License

Same as your other notebooks in this folder — internal use only unless
explicitly relicensed.
