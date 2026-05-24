# fabric-downloader

Tenant-scale Fabric **notebook / pipeline / dataflow** downloader. Enumerates
every item of the requested types in every workspace the caller can see
(Fabric admin APIs when available, user APIs otherwise) and fans the download
out across a Spark cluster via `mapPartitions`. Each downloaded item lands
under `Files/<output_root>/<run_label>/<workspace>/<type>/...` on the
attached Lakehouse, and every attempt is recorded in a Delta manifest table.

The downloader ships as a normal Python wheel — install it once on your
cluster, then drive it from a thin five-phase orchestration notebook.

## Install

From a Fabric notebook:

```
%pip install -q fabric-downloader==0.1.0
```

This transitively installs [`fabric-core`](../coreHelper), which provides
the shared token acquisition, REST enumeration, path math, and
diagnostics-probe helpers that `fabric-downloader` and `fabric-scanner` both
build on. The downloader pins `fabric-core>=0.1,<1.0`.

Or from source for development:

```pwsh
cd coreHelper       ; pip install -e ".[dev,api,notebook]" ; cd ..
cd downloaderHelper ; pip install -e ".[dev,api,spark]"
```

Editable installs in dependency order (`coreHelper` first) so the downloader
resolves the local checkout rather than the published wheel.

## Usage

The thin orchestration notebook (`notebooks/fabric_downloader_v1.ipynb`) is
~12 short cells across five phases — install, configure, probe, run, explore.
The interesting ones look like this:

```python
# Phase 1 — install (one cell)
%pip install -q fabric-downloader==0.1.0

# Phase 2 — configure (one cell, the only one you usually edit)
from fabric_downloader import DownloaderConfig
cfg = DownloaderConfig(
    item_types     = ("Notebook", "DataPipeline", "Dataflow"),
    admin_mode     = True,
    output_root    = "fabric_item_backups",
    manifest_table = "fabric_download_manifest",
    skip_existing  = True,
    group_by_type  = True,
    executor_concurrency = 30,
)

# Phase 3 — probe (sanity-check resolved target + optionally API endpoints)
from fabric_downloader import resolve_paths, probe
resolved = resolve_paths(cfg)
probe(cfg, resolved)        # add token=<bearer> to probe Fabric REST too

# Phase 4 — run (downloads + appends one row per item to the manifest Delta)
from fabric_downloader.spark import run
result = run(cfg, spark)
print(f"{result.item_count} items attempted -> {result.manifest_table}")

# Phase 5 — explore (display rollups)
display(result.summary.by_status)
display(result.summary.by_type)
display(result.summary.by_workspace)
display(result.summary.errors)
display(result.summary.balance_check)
display(result.summary.run_summary)
```

That's the entire user-facing API. All enumeration, fetch, and write logic
lives in the wheel — bug fixes and new item-type support ship as new versions,
not as a re-uploaded notebook.

## Multi-item-type support

The same engine downloads any Fabric item type whose
`POST /v1/workspaces/{wid}/items/{iid}/getDefinition` endpoint returns a
parts array. Three knobs drive what gets pulled and how:

| knob | effect |
|---|---|
| `item_types` (tuple) | which types are enumerated + downloaded |
| `notebook_format` (str) | how Notebooks are saved — `"py"` (default), `"txt"`, `"ipynb"`, or `"parts"` |
| `format_by_type` (dict) | per-type `?format=` override for **non-Notebook** types; missing key = parts mode |

### Supported item types

| Item type | getDefinition? | Default content | Notes |
|---|---|---|---|
| `Notebook` | ✅ | `.py` / `.scala` / `.sql` / `.r` source | Use `notebook_format` for ipynb/parts/txt |
| `DataPipeline` | ✅ | `pipeline-content.json` + `.platform` | — |
| `Dataflow` | ✅ | `mashup.pq` + `.platform` + metadata | — |
| `Report` | ✅ | `report.json` + `definition.pbir` | PBIP format |
| `SemanticModel` | ✅ | `model.bim` or TMDL parts | — |
| `SparkJobDefinition` | ✅ | `SparkJobDefinitionV1.json` | — |
| `KQLDatabase` | ✅ | Database schema + config parts | — |
| `Eventstream` | ✅ | Topology JSON + metadata | — |
| `Environment` | ✅ | `environment.yml` + `.platform` | — |
| `Lakehouse` | ⚠️ metadata only | `lakehouse_metadata.json` | No Delta data; only id/name/properties |

Items not in this table are still attempted using the generic `getDefinition`
endpoint — a `parts` response body is saved verbatim; non-200 HTTP status
surfaces as an `error` row in the manifest.

Defaults:

| type | default mode | what you get |
|---|---|---|
| `Notebook`     | `py`    | one native source file per notebook — `<name>__<id>.py` for PySpark/Python, `.scala` / `.sql` / `.r` for the other Spark languages |
| `DataPipeline` | `parts` | `pipeline-content.json` + `.platform` (each saved with `.txt` suffix) |
| `Dataflow`     | `parts` | `mashup.pq` + `.platform` + … |
| `Report`, `SemanticModel`, … | `parts` | every part the API returns |

`notebook_format` choices:

- **`"py"`** *(default)* — single native source file per notebook. Calls the
  API without a `?format=` hint so Fabric returns the language-specific
  source (`notebook-content.py` + `.platform`) and we save just the source
  with the matching extension. **Note**: non-Python notebooks end up with
  `.scala`, `.sql`, or `.r` extensions — `"py"` is the user-facing name
  but the writer respects the notebook's actual language.
- **`"txt"`** — same fetch as `"py"`, but the source is always written as
  a single `<name>__<id>.txt` regardless of language. Handy for indexing
  pipelines that only consume plain text.
- **`"ipynb"`** — sends `?format=ipynb` and saves one self-contained
  `<name>__<id>.ipynb` per notebook (the previous default).
- **`"parts"`** — no `?format=` hint; writes every part of the definition
  envelope as a separate `.txt` file (same shape as non-notebook types).

**Migration note (v0.4):** The legacy
`format_by_type={"Notebook": "ipynb"}` knob is now rejected. Switch to
`notebook_format="ipynb"` for the previous default behavior, or accept the
new `"py"` default. Non-Notebook entries in `format_by_type` are
unchanged.

Set `group_by_type=False` to skip the per-type subfolder and lay every file
flat under `<workspace>/` (only safe when `item_types` is a single type — the
seed notebook's layout).

## CLI usage (laptop / CI, no Spark)

`fabric-downloader` is installed as a console-script entry-point when you
`pip install fabric-downloader`.  Authentication falls back to
`FABRIC_TOKEN` env-var, then Azure CLI / DefaultAzureCredential.

```pwsh
# Download all registered item types from one workspace
fabric-downloader \
    --workspace-id  <ws-uuid> \
    --output        ./backups

# Download only notebooks + pipelines, save notebooks as .ipynb
fabric-downloader \
    --workspace-id  <ws-uuid> \
    --item-types    Notebook,DataPipeline \
    --notebook-format ipynb \
    --output        ./backups

# Download everything except Lakehouse (metadata-only)
fabric-downloader \
    --workspace-id  <ws-uuid> \
    --exclude-item-types Lakehouse \
    --output        ./backups \
    --token         $MY_FABRIC_TOKEN
```

| CLI flag | default | description |
|---|---|---|
| `--workspace-id` | *(required)* | Fabric workspace UUID |
| `--output` | `fabric_downloads` | Root output directory |
| `--run-label` | UTC timestamp | Sub-folder label for this run |
| `--item-types` | `all` | Comma-separated types, or `all` |
| `--exclude-item-types` | *(none)* | Comma-separated types to exclude |
| `--notebook-format` | `py` | One of `py`, `txt`, `ipynb`, `parts` |
| `--token` | *(auto)* | Pre-fetched bearer token |
| `--no-admin-mode` | *(off)* | Use only user-scoped APIs |
| `--no-skip-existing` | *(off)* | Re-download already-written files |
| `--include-raw-definition` | *(off)* | Also save `_definition.json` per item |
| `--max-items` | `0` (unlimited) | Hard cap for dry-runs |
| `--manifest` | `<output>/<run>/_manifest.json` | Manifest file path |
| `-v` / `--verbose` | *(off)* | DEBUG-level logging |

The CLI writes a `_manifest.json` file next to the downloaded items.  Each
entry contains `item_type`, `item_id`, `display_name`, `endpoint`, `sha256`,
`bytes`, `status`, and `downloaded_at`.

### Migration note: default `--item-types=all` vs old notebook-only behavior

The CLI entry-point did not exist in versions prior to v0.4.  The
`DownloaderConfig`-based Spark path defaults to
`item_types=("Notebook",)` for backward compatibility — only notebooks are
downloaded unless you explicitly add other types.

When you use the new `fabric-downloader` CLI, `--item-types` defaults to
`all`, which means **all ten registered handlers** run.  If you want the
old notebook-only behavior, pass `--item-types Notebook` explicitly.


## Package layout

```
fabric_downloader/
├── _version.py       Single source of truth for the version string
├── config.py         DownloaderConfig dataclass (every knob lives here)
├── item_types.py     ItemHandler ABC + REGISTRY (type-registry pattern)
├── cli.py            fabric-downloader console-script entry-point
├── paths.py          Lakehouse mount + ABFSS path math, safe_segment(),
│                     resolve_paths(), build_paths(), write/exists helpers
├── diagnostics.py    probe() — resolved-target + optional API endpoint check
├── persist.py        write_manifest + SummaryReport (six SQL rollups)
├── handlers/         Built-in per-type handler implementations
│   ├── notebook.py             Notebook (py / txt / ipynb / parts modes)
│   ├── pipeline.py             DataPipeline
│   ├── dataflow.py             Dataflow (Gen2)
│   ├── report.py               Report (PBIP)
│   ├── semantic_model.py       SemanticModel (Power BI dataset)
│   ├── spark_job_definition.py SparkJobDefinition
│   ├── kql_database.py         KQLDatabase (Eventhouse)
│   ├── eventstream.py          Eventstream
│   ├── environment.py          Environment
│   └── lakehouse.py            Lakehouse (metadata-only)
├── api/              Fabric REST mode (requires the [api] extra)
│   ├── auth.py         token acquisition (5-source chain)
│   ├── enumerate.py    /workspaces + /items listing, multi-type filter
│   └── fetch.py        getDefinition with optional ?format= + LRO polling +
│                       401-refresh hook
└── spark/            Cluster fan-out (requires the [spark] extra)
    ├── schema.py       manifest_schema (21-col StructType, incl. sha256)
    ├── context.py      DownloadContext (immutable broadcast bag)
    ├── inventory.py    build_inventory + repartition_for_download
    ├── partition.py    process_definition_body (pure) + download_partition
    │                   (Spark generator with shared 401-refresh state)
    └── runner.py       run(cfg, spark) -> DownloaderResult
```

### How the layers fit together

```
DownloaderConfig ──► resolve_paths()    ──► ResolvedPaths
                                                │
                                                ▼
                              api.enumerate_items (per item_types)
                                                │
                                                ▼
                              build_inventory  (one row / item)
                                                │
                                                ▼   mapPartitions
                              download_partition  ─► fetch_item_definition
                                                │            │
                                                │            ▼
                                                │     process_definition_body
                                                │            │
                                                │            ▼
                                                │     write_text(.ipynb / parts)
                                                ▼
                              write_manifest + SummaryReport
```

- **`config.py` / `paths.py`** are pure Python — no Spark, no Fabric, no
  aiohttp. Run anywhere Python runs.
- **`api/`** and **`spark/`** are the two execution layers. Only the deps
  you opt into are pulled in (controlled by the `[api]` / `[spark]` extras).
- **`persist.py`** writes the Delta table and computes the rollups.

## Output layout

```
Files/<output_root>/<run_label>/
  <workspace_safe>__<wid>/
    Notebook/
      <name>__<id>.ipynb                  # ipynb mode (Notebook default)
      <name>__<id>.item.json              # if include_raw_definition=True
    DataPipeline/
      <name>__<id>__pipeline-content.txt  # parts mode (everything else)
      <name>__<id>__.platform.txt
    Dataflow/
      <name>__<id>__mashup.txt
      <name>__<id>__.platform.txt
      <name>__<id>__queryGroups.txt
```

With `group_by_type=False`, the per-type subfolder is dropped — files land
directly under `<workspace_safe>__<wid>/`.

## Manifest schema

One row per item attempt. The manifest is **appended** each run so multiple
runs accumulate (filter / partition by `run_label`).

| column | type | notes |
|---|---|---|
| `workspace_id` / `workspace_name` | string | from enumerate |
| `item_type` | string | `Notebook` / `DataPipeline` / `Dataflow` / ... |
| `item_id` / `display_name` | string | Fabric item id + name |
| `rel_path` | string | primary file path relative to `Files/` |
| `primary_target` | string | absolute write URI (mount or abfss://) |
| `item_json_target` | string | nullable; populated when `include_raw_definition=True` |
| `export_format` | string | `ipynb` or `parts` |
| `part_count` | int | parts returned by the API |
| `parts_saved` | int | parts actually written to disk (skips counted as 0) |
| `has_content_part` | bool | did the API return a content/mashup/pipeline-content part? |
| `payload_bytes` | long | decoded size of the primary content part |
| `sha256` | string | nullable; hex SHA-256 digest of the primary content bytes |
| `attempts` | int | API retry count |
| `token_refreshes` | int | how many times the partition refreshed its token |
| `http_status` | int | last HTTP status seen |
| `status` | string | `ok` / `skipped_exists` / `error` |
| `error` | string | nullable; populated on error or missing-content warnings |
| `run_label` | string | identifies the run batch |
| `downloaded_at` | timestamp | UTC |

## What this package handles that a single-cell script doesn't

| Scenario | Handling |
|---|---|
| Multiple item types | `item_types` tuple drives enumerate + download (Notebook + DataPipeline + Dataflow today) |
| Multiple workspaces | Tries PBI admin → Fabric admin → user `/workspaces` chain |
| Per-executor concurrency | `executor_concurrency=30` async fetches per partition |
| Distributed work | `mapPartitions` across `sc.defaultParallelism` workers |
| 401 token refresh | Single-flight refresh via per-partition `asyncio.Lock` |
| 202 LRO without Location | Falls back to `x-ms-operation-id` header |
| 429/5xx with Retry-After | Honors header, falls back to exponential backoff |
| Restart-safe | `skip_existing=True` skips already-written files |
| Balance check | SQL display flags items with missing content-part |
| Run accumulation | Manifest appended; rollups computed on the full table |

## Engine-only usage (no Spark)

The pure helpers in `paths.py` + the `process_definition_body` function in
`spark.partition` run anywhere Python runs — useful for unit-testing the
writer logic or for processing a pre-fetched getDefinition body:

```python
from fabric_downloader import DownloaderConfig, resolve_paths
from fabric_downloader.spark.context import build_download_context
from fabric_downloader.spark.partition import process_definition_body

cfg = DownloaderConfig(item_types=("Notebook",),
                       write_to_default_lakehouse=False,
                       write_workspace_id="...", write_lakehouse_id="...")
resolved = resolve_paths(cfg)
ctx = build_download_context(cfg, resolved)

writes = []
row = process_definition_body(
    ctx=ctx,
    workspace_id="ws-guid", workspace_name="ws",
    item_type="Notebook", item_id="nb-guid", display_name="My NB",
    body={"definition": {"parts": [
        {"path": "notebook-content.ipynb",
         "payload": "eyJjZWxscyI6W119", "payloadType": "InlineBase64"},
    ]}},
    http_status=200, attempts=1, token_refreshes=0, error=None,
    writer=lambda uri, text: writes.append((uri, text)),
    exists=lambda uri: False,
)
print(row["status"], row["primary_target"], len(writes))
```

## Build the notebook

After bumping the version or editing the cell template, regenerate the thin
orchestration notebook:

```pwsh
cd downloaderHelper
python scripts/build_notebook.py
# -> notebooks/fabric_downloader_v1.ipynb (pin updated)
```

## Tests

```pwsh
cd downloaderHelper
pip install -e ".[dev]"
pytest tests/unit/        # fast unit tests, no Spark required
```

## Build a wheel

```pwsh
cd downloaderHelper
pip install build
python -m build
ls dist/
# fabric_downloader-0.1.0-py3-none-any.whl
# fabric_downloader-0.1.0.tar.gz
```

Attach the wheel to your Fabric environment, or upload it to a release
artifact and update the `%pip install` URL in cell 1 of the notebook.

## Restoring an item back into Fabric

In parts mode (or with `include_raw_definition=True`), reconstruct the
`POST /v1/workspaces/{wid}/items` body from the saved files:

```python
import base64, json, requests
parts = []
for part_path, file_path in [
    ("notebook-content.py", "MyNotebook__<id>__notebook-content.txt"),
    (".platform",           "MyNotebook__<id>__.platform.txt"),
]:
    with open(file_path, "rb") as f:
        parts.append({
            "path": part_path,
            "payload": base64.b64encode(f.read()).decode("ascii"),
            "payloadType": "InlineBase64",
        })
body = {"displayName": "Restored", "type": "Notebook",
        "definition": {"parts": parts}}
requests.post(f"https://api.fabric.microsoft.com/v1/workspaces/{wid}/items",
              headers={"Authorization": f"Bearer {token}"}, json=body).json()
```

The same recipe works for DataPipeline (parts: `pipeline-content.json` +
`.platform`) and Dataflow (parts: `mashup.pq` + `.platform` + any extra
Gen2 metadata files).

## Limitations

- Notebook *outputs* are downloaded as-is — they may contain secrets if your
  notebooks have been executed with sensitive data. The output table /
  files should be access-controlled.
- `getDefinition` does not return useful Delta data for some Fabric item
  types (e.g. Warehouse).  `Lakehouse` is handled specially — only
  metadata (id, display name, properties) is saved; no Delta table data is
  copied.  Other unsupported types will surface as HTTP 400 errors in the
  manifest.
- The legacy `notebook_downloader.ipynb` (single-file Spark script) is kept
  for reference; this package supersedes it.

## Changelog

### 0.4.0 (pending)
- **ItemHandler registry** — new `item_types.py` with `ItemHandler` ABC and
  `REGISTRY` dict; `@register` decorator auto-enlists handlers.
- **Ten built-in handlers** — `Notebook`, `DataPipeline`, `Dataflow`, `Report`,
  `SemanticModel`, `SparkJobDefinition`, `KQLDatabase`, `Eventstream`,
  `Environment`, `Lakehouse` (metadata-only).
- **CLI** — `fabric-downloader` console-script entry-point with
  `--item-types`, `--exclude-item-types`, `--notebook-format`,
  `--skip-existing`, `--include-raw-definition`, and `--max-items` flags.
  Authentication falls back to `FABRIC_TOKEN` env-var → Azure CLI →
  DefaultAzureCredential.
- **sha256 in manifest** — `sha256` column added to the Spark manifest
  StructType and computed in `process_definition_body`; the CLI manifest
  JSON includes `sha256` and `bytes` per item.
- **Extended `KNOWN_ITEM_TYPES`** — added `KQLDatabase`, `Eventstream`,
  `Environment`, `Lakehouse` to the informational constant.

### 0.1.0
- Initial wheel-based release. Generalizes the single-file
  `notebook_downloader.ipynb` script into a layered package that supports
  Notebooks, DataPipelines, and Dataflows (plus any other Fabric item type
  that exposes `getDefinition`).
