# FabricHelpers

A collection of miscellaneous helpers for [Microsoft Fabric](https://www.microsoft.com/microsoft-fabric)
— self-contained notebooks and scripts that solve specific tenant-administration,
auditing, and operational problems we've hit in the wild.

Each helper lives in its own folder with its own README. The helpers are
independent — pick the one you need.

---

## Helpers

### 🧱 [`coreHelper/`](./coreHelper) — `fabric-core` shared library

The shared low-level helpers used by all sibling wheels: token
acquisition (six-source chain incl. SPN client credentials),
OneLake / Fabric REST URL math, workspace + item enumeration with
admin → user fallback, a retrying urllib JSON client with paged
iterators, endpoint-probe diagnostics, and notebook-build serialization.
Released as its own wheel so every consumer shares one bug-fix surface.

```
                  ┌──────────────────┐
                  │   fabric-core    │
                  └────────┬─────────┘
                           │   imported by
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
┌──────────────────┐ ┌──────────────────────┐ ┌──────────────┐
│  fabric-scanner  │ │  fabric-downloader   │ │  fabric-mpe  │
└──────────────────┘ └──────────────────────┘ └──────────────┘
```

See [`coreHelper/README.md`](./coreHelper/README.md) for the public API and
[`CONTRIBUTING.md`](./CONTRIBUTING.md) for the dependency rules.

---

### 🔍 [`scannerHelper/`](./scannerHelper) — Fabric Notebook URL & Secret Scanner

A scalable Fabric / Spark notebook that audits every notebook in your tenant
for **URLs, hardcoded secrets, write operations, and cross-workspace data
flows**. Tested against tenants with 10,000+ workspaces and 18,000+ notebooks.

For every notebook it can read, the scanner flags:

- **URL literals** — every `https://`, `abfss://`, `wasbs://`, `s3://`, etc.,
  classified as `read` / `write` / `read_write` / `reference`.
- **Cross-workspace data flows** — destination workspace parsed out of OneLake
  / Fabric REST / Power BI URLs.
- **Hardcoded secrets** — 15 regex patterns (storage keys, SAS tokens, SQL
  passwords, Cosmos keys, API keys, client secrets, bearer JWTs, OpenAI keys,
  JDBC passwords, etc.). Match snippets are auto-redacted.
- **Potential writes** — destination-agnostic write API calls
  (`df.write_delta(...)`, `requests.post(...)`, `INSERT INTO …`, etc.) that
  catch notebooks writing to runtime-built destinations.

Runs in two modes: **API mode** (Fabric admin scanner / user-scoped APIs with
async aiohttp fanout) or **Lakehouse mode** (pre-exported `.ipynb` files,
10–100× faster). Results land in a single flat Delta table.

A second scan mode — the **AI auditor**
(`fabric_scanner.ai.run_ai_audit`, notebook
`notebooks/fabric_scanner_ai_v1.ipynb`) — uses **Fabric AI Functions**
(LLM) to score every notebook for `external_resource_access_score` and
`exfiltration_risk_score` (both 0–100), with paragraph-length rationales
per finding. It shares the same workspace attribution + attached-lakehouse
enrichment as the rule-based scanner, so the AI table JOINs cleanly to
the regex findings table on `(workspace_id, source_dated_partition,
display_name)`. AI scanning is charged to your Fabric AI quota; the
rule-based scanner is free.

See [`scannerHelper/README.md`](./scannerHelper/README.md) for full setup,
configuration, output schema, and sample queries.

---

### 🔐 [`mpeHelper/`](./mpeHelper) — `fabric-mpe` Managed Private Endpoint Manager

An installable wheel (`fabric-mpe`) plus a thin eight-cell orchestration
notebook that gives you a safe, auditable, end-to-end lifecycle for
**Managed Private Endpoints** (MPEs) across one or more Fabric workspaces:

```
INVENTORY  →  DRY-RUN  →  DELETE  →  RECREATE  →  APPROVE
```

Every step is gated by an explicit flag on `MpeConfig`, capped by a hard
limit, and persisted to a Delta audit table — so nothing destructive
happens by accident and you always have a paper trail.

- **Inventory** every MPE the caller can see, written to Delta + JSON + CSV.
- **Dry-run** filters preview which MPEs would be deleted (refuses if
  matches exceed `max_deletes`).
- **Delete** only when `commit=True`, with every HTTP response logged.
- **Recreate** MPEs from the most-recent delete-audit or any prior
  inventory snapshot, stamping each `requestMessage` with a run marker.
- **Approve** the resulting Pending Private Endpoint Connections on the
  Azure side via the ARM REST API, matched by the run marker.

```python
from fabric_mpe import MpeConfig, inventory, delete, recreate, approve, probe
cfg = MpeConfig(workspace_scope="visible", name_filter=r"^test-")
probe(cfg)
inv = inventory.run(cfg, spark)
targets = delete.dry_run(cfg, spark)
# Flip cfg.commit=True when ready, then run delete.commit / recreate.run / approve.run.
```

See [`mpeHelper/README.md`](./mpeHelper/README.md) for full configuration,
output schemas, ARM RBAC notes, and troubleshooting.

---

### 💾 [`downloaderHelper/`](./downloaderHelper) — Fabric Item Downloader (Notebook / Pipeline / Dataflow)

An installable wheel (`fabric-downloader`) plus a thin five-cell orchestration
notebook that backs up **Fabric notebooks, data pipelines, and dataflows** to
a Lakehouse. Generalizes the legacy `notebook_downloader.ipynb` script to any
Fabric item type whose `getDefinition` endpoint returns a parts array, driven
by a single `item_types` tuple on the config:

```python
from fabric_downloader import DownloaderConfig
from fabric_downloader.spark import run

cfg = DownloaderConfig(
    item_types     = ("Notebook", "DataPipeline", "Dataflow"),
    output_root    = "fabric_item_backups",
    manifest_table = "fabric_download_manifest",
    skip_existing  = True,
    executor_concurrency = 30,
)
result = run(cfg, spark)
display(result.summary.by_type)
```

- **Multi-type by config** — Notebook (`?format=ipynb`), DataPipeline
  (parts: `pipeline-content.json` + `.platform`), Dataflow Gen2 (parts:
  `mashup.pq` + `.platform` + metadata), plus any other type that exposes
  `getDefinition`. Per-type `format_by_type` override available.
- **Tenant-scale fan-out** — Spark `mapPartitions` + async `aiohttp` with
  bounded per-executor concurrency, single-flight 401 token refresh,
  202 LRO polling, and 429/5xx exponential backoff.
- **Restart-safe** — `skip_existing=True` skips files already written so
  re-runs with the same `run_label` resume cleanly.
- **Accumulating manifest** — one row per item attempt is appended to a
  Delta table; six SQL rollups (by_status, by_type, by_workspace, errors,
  balance_check, run_summary) are computed automatically.
- **Wheel-based** — bug fixes and new item-type support ship as new wheel
  versions; the orchestration notebook stays a thin 12-cell shim pinned to
  a specific `fabric-downloader==X.Y.Z`.

See [`downloaderHelper/README.md`](./downloaderHelper/README.md) for install,
usage, manifest schema, output layout, and a restore recipe for re-uploading
saved items back into Fabric.

---

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the dependency-direction
rules, the mock-patching gotcha around `fabric_core.auth`, the tag and
release scheme, and local development setup.

## License

See [LICENSE](./LICENSE).
