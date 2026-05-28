# fabric-splitter

> Split a Microsoft Fabric workspace into two by item type — with dry-run,
> audit log, and cross-workspace reference rewriting.

---

## Problem

Fabric workspaces often accumulate a mix of **engineering** items (lakehouses,
notebooks, pipelines) and **consumption** items (semantic models, reports).
Splitting them by hand is slow, error-prone, and leaves broken references
between items.  `fabric-splitter` automates the split in a repeatable,
auditable way.

---

## Install

```pwsh
pip install fabric-splitter
```

Or from source for development:

```pwsh
cd splitterHelper
pip install -e ".[dev]"
```

---

## Quick start

### Dry-run (default)

```pwsh
fabric-splitter \
    --source  <source-workspace-id> \
    --workspace-a-name "Engineering" \
    --workspace-b-name "Consumption" \
    --types-to-a notebook,lakehouse,datapipeline,sparkjobdefinition
```

This prints a summary and writes two report files:

| File | Contents |
|------|----------|
| `splitter_report.csv` | One row per item: `itemId, itemType, name, sourceWorkspaceId, targetWorkspace, targetWorkspaceId, action` |
| `splitter_report.json` | Same data as JSON array |

`action` is one of:
- `move` — item will be moved to the target workspace
- `leave` — item is already in the right workspace (idempotent second run)

No changes are made to Fabric until you add `--apply`.

### Apply the split

```pwsh
fabric-splitter \
    --source  <source-workspace-id> \
    --workspace-a-name "Engineering" \
    --workspace-b-name "Consumption" \
    --types-to-a notebook,lakehouse,datapipeline,sparkjobdefinition \
    --apply
```

Apply mode:
1. Creates workspace A and B if they don't exist.
2. Copies role assignments from source → both targets (disable with
   `--skip-permissions`).
3. Moves each item to its target workspace.
4. Runs a reference-rewrite pass so semantic models / reports / pipelines
   still point at the correct workspace.
5. Writes a JSON-lines audit log: `splitter_audit_<timestamp>.jsonl`.

---

## All CLI flags

| Flag | Required | Description |
|------|----------|-------------|
| `--source` | ✓ | Source workspace ID |
| `--workspace-a-name` | ✓ | Display name for workspace A |
| `--workspace-b-name` | ✓ | Display name for workspace B |
| `--types-to-a` | ✓ | Comma-separated item types → workspace A (case-insensitive) |
| `--dry-run` | — | (Default) Print plan, make zero changes |
| `--apply` | — | Execute the split |
| `--skip-permissions` | — | Don't copy role assignments |
| `--output-dir` | — | Where to write reports + audit log (default: `.`) |
| `--token` | — | Bearer token; resolved from env/CLI if omitted |
| `--fabric-base` | — | Fabric REST base URL (default: `https://api.fabric.microsoft.com`) |
| `-v / --verbose` | — | Debug logging |

---

## Worked example

**Before:**

| Workspace | Items |
|-----------|-------|
| `Mixed WS` | `NB-ETL` (Notebook), `LH-Raw` (Lakehouse), `SM-Sales` (SemanticModel), `Rpt-Q1` (Report) |

**Run:**

```pwsh
fabric-splitter \
  --source  "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" \
  --workspace-a-name "Engineering" \
  --workspace-b-name "Consumption" \
  --types-to-a notebook,lakehouse \
  --apply
```

**After:**

| Workspace | Items |
|-----------|-------|
| `Engineering` | `NB-ETL`, `LH-Raw` |
| `Consumption` | `SM-Sales` (references updated to point to `Engineering/LH-Raw`), `Rpt-Q1` (references updated to point to `Engineering/SM-Sales`) |

---

## Reference-rewrite matrix

| Item type | References rewritten | What you must fix manually |
|-----------|---------------------|---------------------------|
| `SemanticModel` | `workspaceId` inside model definition parts (e.g. `model.bim`, PBISM), including cross-group links (A→B / B→A) via referenced item IDs | Complex M-query / DirectQuery connection strings that embed workspace names as literals |
| `Report` | `workspaceId` inside `definition.pbir`, including cross-group links (A→B / B→A) via referenced item IDs | Report-level RLS rules referencing users by name |
| `DataPipeline` | `workspaceId` inside `pipeline-content.json` activity configs, including cross-group links (A→B / B→A) via referenced item IDs | External triggers, event-based triggers pointing at source workspace |
| All other types | *(none — pass-through)* | Any hard-coded workspace IDs embedded in notebook code cells |

---

## Move strategy

| Item type | Strategy |
|-----------|----------|
| Types in `NATIVE_MOVE_SUPPORTED` | Native Fabric `POST /items/{id}/move` |
| All others | `getDefinition` from source → `createItem` in target |

Currently `NATIVE_MOVE_SUPPORTED` is empty because Microsoft has not published
a generic `/move` endpoint.  Update `src/fabric_splitter/move.py` as the API
evolves.

---

## Idempotency

Re-running with the same inputs is a no-op:

- The CLI re-lists items from source + workspace A + workspace B.
- Each item is compared by current workspace vs derived target workspace.
- Items already in workspace A get `action=leave`.
- Items already in workspace B get `action=leave`.
- Zero API mutations are made.

---

## Audit log

Every API mutation is appended to `splitter_audit_<timestamp>.jsonl`:

```json
{"ts":"2024-01-15T10:30:00+00:00","action":"export_recreate","itemId":"nb1","itemType":"Notebook","itemName":"NB-ETL","targetWorkspaceId":"ws-eng"}
{"ts":"2024-01-15T10:30:01+00:00","action":"export_recreate","itemId":"lh1","itemType":"Lakehouse","itemName":"LH-Raw","targetWorkspaceId":"ws-eng"}
```

Possible `action` values in the audit log:

| Value | Meaning |
|-------|---------|
| `export_recreate` | Item was exported from source and recreated in target |
| `native_move` | Item was moved via the native Fabric move endpoint |
| `skip_no_definition` | `getDefinition` failed; item was skipped |
| `error_recreate` | `createItem` failed after a successful `getDefinition` |

---

## Package layout

```
fabric_splitter/
├── _version.py     Single source of truth for the version string
├── classify.py     classify() — item_id → "A" | "B"
├── plan.py         build_plan() + write_plan() — dry-run report
├── workspaces.py   get_or_create_workspace() + copy_role_assignments()
├── move.py         move_item() — native move + export/recreate fallback
├── rewrite.py      rewrite_references() — cross-workspace reference patcher
├── cli.py          fabric-splitter CLI entrypoint
└── _http.py        Internal urllib-based HTTP helper (no extra deps)
```

---

## Development

```pwsh
cd splitterHelper
pip install -e ".[dev]"
pytest tests/unit/ -q
```
