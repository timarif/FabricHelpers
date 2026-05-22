# Fabric Notebook URL & Secret Scanner

A scalable Microsoft Fabric / Spark notebook that audits every notebook in your
tenant for URLs, hardcoded secrets, write operations, and cross-workspace data
flows. Designed to run at scale — tested against tenants with 10,000+
workspaces and 18,000+ notebooks.

The notebook is generated from a Python source file
(`build_fabric_url_scanner_nb.py`) and emitted as `fabric_url_scanner.ipynb`,
ready to upload into a Fabric workspace and run.

---

## What it does

For every notebook it can read, the scanner flags four classes of finding:

| Finding | What gets captured | Why it matters |
|---|---|---|
| **URL literal** | Any `https://`, `abfss://`, `wasbs://`, `s3://`, `gs://`, `dbfs://`, etc., found in code or markdown — classified as `read` / `write` / `read_write` / `reference` / `unknown`. | Inventory of every external system a notebook touches, with the direction of data flow. |
| **Cross-workspace flow** | Destination workspace ID + name parsed out of OneLake / Fabric REST / Power BI URLs, with a `cross_workspace` boolean. | Spot data egress between workspaces, including unintended ones. |
| **Hardcoded secret** | 15 regex patterns — storage keys, SAS tokens, SQL passwords, Cosmos keys, API keys, client secrets, connection strings, bearer JWTs, Event Hub keys, OpenAI keys, Spark account-key configs, JDBC passwords, and a generic `secret=…` catch-all. Match snippets are auto-redacted. | High-signal security audit. Catches secrets sitting in source even when no URL is involved. |
| **Potential write** | Destination-agnostic write API calls (e.g., `df.write_delta(path)`, `df.write.saveAsTable(...)`, `requests.post(...)`, `client.put_object(...)`, `open(path, "wb")`, `INSERT INTO …`). | Flags notebooks that write to runtime-built destinations where no URL literal exists to capture. Surfaced as a separate review queue. |

All findings land in a single flat Delta table keyed by workspace + notebook,
so you can pivot it any way you like.

---

## Architecture

```
                ┌────────────────────────────────────┐
                │  Driver: enumerate notebooks       │
                │   (admin API, user API, or         │
                │    Lakehouse Files listing)        │
                └────────────────────────────────────┘
                                 │
                                 ▼
                ┌────────────────────────────────────┐
                │  Build inventory DataFrame +       │
                │  partition  (TARGET_PARTITION_SIZE)│
                └────────────────────────────────────┘
                                 │
            ┌────────────────────┴────────────────────┐
            ▼                                         ▼
  ┌──────────────────────────┐         ┌──────────────────────────┐
  │ fetch_partition          │   or    │ scan_partition_lakehouse │
  │ (API mode)               │         │ (Lakehouse mode)         │
  │  - aiohttp async fanout  │         │  - decode binaryFile     │
  │  - getDefinition LROs    │         │  - scan in-place         │
  │  - URL + secret scan     │         │  - URL + secret scan     │
  │  - direction classify    │         │  - direction classify    │
  │  - write-call detect     │         │  - write-call detect     │
  │  - dest-workspace parse  │         │  - dest-workspace parse  │
  └──────────────────────────┘         └──────────────────────────┘
                                 │
                                 ▼
                ┌────────────────────────────────────┐
                │ Persist to Delta + display SQL     │
                │ summaries + notebook_review_queue  │
                └────────────────────────────────────┘
```

Concurrency: each Spark executor runs the partition function on its slice in
parallel, and **inside** each partition it fans out HTTP requests with
`aiohttp` (default 60 concurrent in-flight). For a 16-executor cluster that's
~960 concurrent `getDefinition` LROs at steady state.

---

## Two source modes

### API mode (`SOURCE_MODE = "api"`)
- Enumerates workspaces via the Fabric admin scanner API (`ADMIN_MODE=True`,
  requires Fabric Administrator) or the user-scoped workspaces API
  (`ADMIN_MODE=False`).
- Pulls notebook definitions via `getDefinition` LROs.
- Authoritative, but slower because each definition is a multi-step polling
  call.

### Lakehouse mode (`SOURCE_MODE = "lakehouse"`)
- Reads pre-exported notebook files (`.ipynb`, `.py`, `.md`) from a Lakehouse
  `Files/` path using `spark.read.format("binaryFile")`.
- No REST calls, no LROs — typically 10–100× faster than API mode.
- Use this when you already have an export from Git integration, `fabric-cli`,
  or your own pipeline.

Both modes converge on the same Delta schema, so dashboards and queries don't
care which mode produced the data.

---

## Output schema

One row per finding (or per error / per empty notebook), written to
`notebook_url_scan`:

| Column | Type | Populated when |
|---|---|---|
| `workspace_id` | string | always |
| `workspace_name` | string | always (resolved from enumeration) |
| `notebook_id` | string | always |
| `display_name` | string | always |
| `part_path` | string | URL / secret / write-call findings (path inside the notebook JSON) |
| `url` | string | URL findings |
| `direction` | string | `read` / `write` / `read_write` / `reference` / `unknown` / `potential_write` |
| `source_kind` | string | `code` / `markdown` / `output` / `raw` |
| `secret_type` | string | secret findings (label) or potential-write findings (call signature) |
| `match_snippet` | string | secret findings (redacted) or potential-write findings (source line) |
| `dest_workspace_id` | string | URL findings where workspace is parseable |
| `dest_workspace_name` | string | URL findings where workspace can be resolved |
| `cross_workspace` | boolean | `TRUE` if dest ≠ source, `FALSE` if same, `NULL` if unknown |
| `error` | string | per-notebook fetch / decode / scan errors |
| `scanned_at` | timestamp | always |

A companion `notebook_inventory` table records the enumerated workspace +
notebook list (one row per notebook) regardless of whether any findings hit.

---

## Configuration cheat sheet

Edit `CELL_CONFIG` in `build_fabric_url_scanner_nb.py` (or the first cell of
the generated `.ipynb`):

```python
# WHERE TO READ FROM
SOURCE_MODE = "api"          # or "lakehouse"
ADMIN_MODE = True            # tenant-wide admin scan vs caller-scoped
READ_WORKSPACE_IDS = None    # or ["guid1", "guid2", ...] to subset
MAX_NOTEBOOKS = None         # smoke-test cap

# Lakehouse-mode source (used when SOURCE_MODE = "lakehouse")
SOURCE_LAKEHOUSE_WORKSPACE_ID   = ""    # blank = attached workspace
SOURCE_LAKEHOUSE_WORKSPACE_NAME = ""    # stamped into workspace_name col
SOURCE_LAKEHOUSE_ID             = ""    # blank = attached default lakehouse
SOURCE_SUBPATH                  = "Files/notebooks"
SOURCE_FILE_GLOB                = "*.ipynb"

# WHERE TO WRITE TO
WRITE_TO_DEFAULT_LAKEHOUSE = True   # False to use ABFSS in another workspace
WRITE_WORKSPACE_ID  = "<guid>"
WRITE_LAKEHOUSE_ID  = "<guid>"
WRITE_SCHEMA        = None          # or "dbo", etc.
INVENTORY_TABLE     = "notebook_inventory"
OUTPUT_TABLE        = "notebook_url_scan"

# TUNING
TARGET_PARTITION_SIZE = 200    # notebooks per Spark partition
EXECUTOR_CONCURRENCY  = 60     # concurrent HTTP per partition
MAX_RETRIES           = 6      # 429/5xx retry budget per request
TOKEN_AUDIENCE        = "pbi"
```

---

## Permissions

- **API + admin mode** — Fabric Administrator role; or a service principal in
  a group that has admin, with the tenant setting *"Service principals can
  call read-only admin APIs"* enabled.
- **API + user mode** — `Workspace.Read.All` and `Item.Read.All` (Fabric
  delegated) for every workspace you want to scan.
- **Lakehouse mode** — Read on the source Lakehouse, Write on the destination
  Lakehouse.
- **Output** — Write on the lakehouse holding `notebook_url_scan` and
  `notebook_inventory`.

---

## Running it

1. Edit the config in cell 1 (or in `build_fabric_url_scanner_nb.py` if you
   plan to regenerate).
2. (Re)generate the notebook from the Python source if you edited the source:
   ```pwsh
   python build_fabric_url_scanner_nb.py
   ```
3. Upload `fabric_url_scanner.ipynb` to Fabric, attach a Lakehouse, and Run
   All. The generated notebook is 10 cells.
4. After it finishes, query the results. Suggested starting points:

   ```sql
   -- Summary
   SELECT COUNT(DISTINCT notebook_id) AS notebooks,
          SUM(CASE WHEN url         IS NOT NULL THEN 1 END) AS urls,
          SUM(CASE WHEN secret_type IS NOT NULL AND direction <> 'potential_write'
                   THEN 1 END) AS secrets,
          SUM(CASE WHEN direction = 'potential_write' THEN 1 END) AS potential_writes,
          SUM(CASE WHEN cross_workspace = TRUE THEN 1 END)        AS cross_ws
   FROM notebook_url_scan;

   -- Cross-workspace data flows
   SELECT workspace_name AS source, dest_workspace_name AS dest,
          direction, COUNT(*) AS rows
   FROM notebook_url_scan
   WHERE cross_workspace = TRUE
   GROUP BY 1,2,3 ORDER BY rows DESC;

   -- Notebooks that need human review
   SELECT * FROM notebook_review_queue
   WHERE review_status IN ('flag_for_review','cross_workspace_write');
   ```

The notebook's final cell builds a `notebook_review_queue` temp view that
classifies each writing notebook as:

- `flag_for_review` — calls write APIs but has no literal write URL (dest
  built at runtime; needs human investigation)
- `cross_workspace_write` — at least one write URL targets a different
  workspace
- `has_literal_write_url` — writes, but to its own workspace
- `no_write_activity` — read-only

---

## Files in this project

| File | Role |
|---|---|
| `build_fabric_url_scanner_nb.py` | **Source of truth.** Each cell is a string in this file. Edit here, then regenerate the `.ipynb`. |
| `fabric_url_scanner.ipynb` | The generated 10-cell scanner notebook. Don't hand-edit; rebuild from the `.py`. |
| `validate_patterns.py` | Standalone validator. Extracts the live regex / helper cell from the `.ipynb`, runs five test sections (cloud URI coverage, direction classification, secret patterns, write-call detection, cross-workspace parsing) plus a real-world NFL notebook check. Should print `PASS` for every section. |

---

## Regex coverage at a glance

- **URL schemes**: `http(s)`, `ftp(s)`, `file`, `abfs(s)`, `wasb(s)`, `s3`,
  `s3a`, `s3n`, `gs`, `dbfs`, `adl`, `hdfs`.
- **Read patterns**: `read_csv`, `read_parquet`, `read_delta`, `read_json`,
  `requests.get/head/options`, `urlopen`, `pd.read_*`, `pl.read_*`,
  `spark.read.*`.
- **Write patterns**: `write_delta`, `write_parquet`, `to_csv`, `to_parquet`,
  `requests.post/put/patch/delete`, `spark.write.*`, `writeStream.*`,
  `.saveAsTable(`, `.save(`.
- **Workspace parsers**: OneLake ABFSS userinfo, Fabric REST
  `/workspaces/<guid>`, Power BI `/groups/<guid>`.
- **Secret patterns** (15): see `SECRET_PATTERNS` in `CELL_URL_HELPERS`.

---

## Known limitations

- **Runtime-built paths can't be attributed.** If a notebook does
  `path = f"{ABFSS_BASE}/Tables/foo"; df.write_delta(path)`, the URL never
  appears as a literal. The scanner correctly flags this as `potential_write`
  but `dest_workspace_id` / `cross_workspace` will be `NULL` — these
  notebooks land in the `flag_for_review` bucket for human triage.
- **Secret snippet auto-redaction is best-effort.** It keeps the first 4
  characters and last 4 characters and masks the middle. Do **not** treat the
  output table as if it has no sensitive data — restrict access accordingly.
- **Notebook *outputs* are not scanned for secrets / writes by default** (only
  URLs in outputs are captured as `reference` rows). This is intentional —
  outputs frequently contain user data and aren't authoritative source.
- **Lakehouse mode trusts the export.** If your export process strips or
  alters cells, the scanner sees only what was exported.

---

## Extending it

Common changes and where to make them:

| To do this | Edit |
|---|---|
| Add a URL scheme | `URL_RE` (3 places: driver helper + 2 executors) |
| Add a read / write API pattern | `READ_RE` / `WRITE_RE` (3 places) |
| Add a secret pattern | `SECRET_PATTERNS` (3 places) |
| Add a write-API signature | `WRITE_CALL_RE` (3 places) |
| Add a workspace-URL parser | `WORKSPACE_URL_RE` (3 places) |
| Add a new output column | `result_schema` + every `Row(...)` emission |

Because the regex / helpers are duplicated across the driver cell and both
partition functions (Spark serialization gotcha), a one-shot Python patcher
script is the safest way to keep all three in sync — see
`_patch_cross_workspace.py` and `_patch_potential_write.py` for working
patterns.

After any change: rebuild the notebook, then run `python validate_patterns.py`
and confirm every section still prints `PASS`.
