# fabric-scanner

Audit Microsoft Fabric notebooks for URLs, secrets, API keys, and
external-write operations.

The scanner ships as a normal Python wheel — install it once on your
cluster, then drive it from a thin five-phase orchestration notebook.

## Install

From a Fabric notebook:

```
%pip install -q fabric-scanner==0.3.3
```

Or from source for development:

```pwsh
cd scannerHelper
pip install -e ".[dev,api,spark]"
```

## Two scanners, one wheel

| | Rule-based scanner | AI auditor |
|---|---|---|
| Notebook | `notebooks/fabric_scanner_v2.ipynb` | `notebooks/fabric_scanner_ai_v1.ipynb` |
| Python entry | `fabric_scanner.spark.run` | `fabric_scanner.ai.run_ai_audit` |
| Detection | Regex + AST + entropy on notebook bytes | Fabric AI Functions (LLM) over notebook text |
| Output | One row per finding | One row per notebook + per-chunk debug rows |
| Severity model | `low` / `medium` / `high` / `critical` | `external_resource_access_score` + `exfiltration_risk_score` (both 0-100) |
| Spend | Free | Charged by your Fabric AI quota |
| Cross-table JOIN | Shares `(workspace_id, source_dated_partition, display_name)` enrichment with the AI auditor (see `## AI Auditor` below) | ditto |

Both scanners reuse the same shared inventory + path-based workspace
attribution + attached-lakehouse metadata extraction, so their output
tables JOIN cleanly without alignment work.

## Usage

The thin orchestration notebook (`notebooks/fabric_scanner_v2.ipynb`)
runs five phases — install, configure, probe, run, explore — across
~13 short cells. The interesting ones look like this:

```python
# Phase 1 — install (one cell)
%pip install -q fabric-scanner==0.3.3

# Phase 2 — configure (one cell, the only one you usually edit)
from fabric_scanner import ScannerConfig
cfg = ScannerConfig(
    source_mode      = "lakehouse",       # or "api" for tenant scan
    source_layout    = "flat",            # or "ws_dated"
    source_subpath   = "Files/notebooks",
    source_file_glob = "*.ipynb",         # widens to "*.{ipynb,py}" if needed
    min_severity     = "low",
)

# Phase 3 — probe (sanity-check what will be scanned)
from fabric_scanner import resolve_paths, probe
resolved = resolve_paths(cfg)
probe(cfg, resolved)

# Phase 4 — run (writes inventory + findings Delta tables)
from fabric_scanner.spark import run
result = run(cfg, spark)
print(f"{result.findings_count} findings / {result.notebook_count} notebooks")

# Phase 5 — explore (display rollups)
display(result.summary.by_severity)
display(result.summary.review_queue)
display(result.summary.cross_workspace_flows)
display(result.summary.sample_critical)
```

That's the entire user-facing API. All detection logic and Spark
plumbing lives in the wheel — bug fixes and new patterns ship as new
versions, not as a re-uploaded notebook.

## Engine-only usage (no Spark)

The detection engine is a pure-Python module that runs on any laptop:

```python
from fabric_scanner import ScannerConfig, scan_notebook_bytes

cfg = ScannerConfig(min_severity="medium")
findings = scan_notebook_bytes(
    open("notebook.ipynb", "rb").read(), "notebook.ipynb", cfg)
for f in findings:
    print(f["severity"], f["finding_type"], f["message"])
```

This is the same scanner the Spark partition function runs — just
without the cluster fan-out. Useful for CI lint, pre-commit hooks, or
quick spot-checks.

## Package layout

```
fabric_scanner/
├── _version.py       Single source of truth for the version string
├── config.py         ScannerConfig dataclass (every knob lives here)
├── engine/           Pure-Python detection logic (no Spark, no Fabric)
│   ├── patterns.py     URL_RE, READ_RE, WRITE_RE, SECRET_PATTERNS, ...
│   ├── extract.py      .ipynb / .py-source walker + attached-LH parser
│   ├── enrich.py       Shared attached-lakehouse enrichment (used by
│   │                   BOTH the rule-based partition AND the AI auditor)
│   ├── resolve.py      cross-workspace URL classification
│   ├── utils.py        entropy, AST scan, snippet redaction
│   └── scanner.py      scan_notebook_bytes() — the entry point
├── paths.py          ABFSS path math, ws_dated enumeration,
│                     and PATH_GUID_DATE_RE (universal
│                     /<guid>/<datestamp>/ extraction)
├── diagnostics.py    probe() — paths + endpoint sanity check
├── api/              Fabric REST mode (requires the [api] extra)
│   ├── auth.py         token acquisition (5-source chain)
│   ├── enumerate.py    /workspaces + /items listing
│   └── fetch.py        getDefinition + 202 LRO polling
├── spark/            Rule-based cluster fan-out (requires the [spark] extra)
│   ├── schema.py       result_schema (27-col StructType)
│   ├── context.py      PartitionContext (broadcast bag)
│   ├── inventory.py    build_inventory_lakehouse / _api
│   ├── partition.py    scan_row + scan_partition_lakehouse + fetch_partition
│   └── runner.py       run(cfg, spark) -> ScannerResult
├── ai/               AI auditor (requires the [spark] extra + Fabric AI Functions)
│   ├── prompt.py       AI_AUDIT_PROMPT + AI_AUDIT_RESPONSE_FORMAT + PROMPT_VERSION
│   ├── chunker.py      Cell-boundary-aware bin-packing chunker
│   ├── schema.py       Three schemas (chunk, result, pre-AI chunk)
│   ├── partition.py    mapPartitions glue + pure-Python chunk_notebook()
│   ├── aggregate.py    Defensive JSON parsing + per-notebook rollup
│   └── runner.py       run_ai_audit(cfg, opts, spark) -> AIAuditResult
└── persist.py        write_findings + SummaryReport (10 rollups)
```

### How the layers fit together

```
ScannerConfig  ──►  resolve_paths()  ──►  ResolvedPaths
                                              │
                                              ▼
                                  build_inventory_*  (one row / notebook)
                                              │
                                              ▼   foreachPartition
                                  scan_partition_*  ─►  scan_row()
                                              │            │
                                              │            ▼
                                              │     engine.scanner
                                              │     scan_notebook_bytes()
                                              ▼
                                  write_findings + SummaryReport
```

* **`engine/`** is the pure detection core — no Spark, no Fabric APIs,
  no I/O. It takes bytes in and returns finding dicts. Runs anywhere
  Python runs.
* **`paths.py`** owns all path math: building ABFSS URLs, enumerating
  `ws_dated` directory layouts, and extracting workspace GUIDs from
  arbitrary paths via `PATH_GUID_DATE_RE`.
* **`api/`** and **`spark/`** are the two execution modes. Only the
  selected mode's dependencies are pulled in (controlled by the
  `[api]` / `[spark]` extras).
* **`persist.py`** writes the two Delta tables and computes the 10
  summary rollups returned in `ScannerResult.summary`.

## Output schema

One row per finding (or one empty row per file with no findings).
Inventory table is one row per scanned notebook.

| Column | Type | Notes |
|---|---|---|
| `workspace_id` / `workspace_name` | string | Path-derived when the path matches `<…>/<guid>/<datestamp>/<file>` (any layout); otherwise the source default. `workspace_name` falls back to the GUID itself when no friendly name is known. |
| `source_lakehouse_id` / `_name` | string | lakehouse mode only |
| `source_dated_partition` | string | populated whenever the path matches `<…>/<guid>/<datestamp>/<file>` (universal — not just `ws_dated`) |
| `notebook_id` / `display_name` | string | always |
| `attached_lakehouse_id` / `_name` / `_workspace_id` / `_workspace_name` | string | extracted from notebook metadata |
| `part_path` / `source_kind` | string | where in the .ipynb the finding came from |
| `cell_index` / `line_number` | int | always |
| `finding_type` | string | `url` / `secret` / `entropy` / `dynamic_exec` / `potential_write` / `api_key` |
| `category` | string | secret family, write category, etc. |
| `severity` | string | `low` / `medium` / `high` / `critical` |
| `message` / `code_snippet` | string | description + redacted snippet |
| `url` / `direction` | string | `read` / `write` / `read_write` / `reference` / `unknown` / `potential_write` |
| `dest_workspace_id` / `_name` / `cross_workspace` | string + bool | parsed from URL findings |
| `error` | string | per-file fetch/decode/scan errors |
| `scanned_at` | timestamp | always |

### Workspace attribution from the path (v0.3.2+)

Both the inventory snapshot and the per-finding rows look at the file
path and apply this universal regex (see `paths.py`):

```
/<workspace-guid>/<datestamp>/<file>
```

where `<workspace-guid>` is a standard 8-4-4-4-12 hex GUID and
`<datestamp>` is a folder name beginning with at least 8 digits
(`yyyymmdd[hhmmss]`, etc.). When the path matches, the extracted GUID
becomes `workspace_id` and the datestamp becomes
`source_dated_partition` — regardless of whether `source_layout` is
`flat` or `ws_dated`. This lets you scan a single lakehouse that holds
exports from many workspaces and still attribute each finding to the
correct source workspace.

Priority order: `ws_dated_base` anchor > universal regex > source
lakehouse default.

## AI Auditor

The AI auditor is a second scan mode that uses **Fabric AI Functions**
to score each notebook for external-resource access and data
exfiltration risk. It writes two Delta tables — one row per notebook
(the aggregate) and one row per chunk (debug + future resume).

> **⚠ Privacy boundary.** The AI auditor sends notebook source code
> (cells, comments, embedded strings) to the Fabric AI model endpoint
> configured for your workspace. Only run it on notebook corpora that
> are already permitted to flow to that endpoint. Secrets present in
> the source — and dataset names, customer identifiers, table names —
> are part of the model input. The rule-based scanner stays the
> private-by-default option.

### Flow

```
ScannerConfig + AIAuditOptions ──►  run_ai_audit(cfg, opts, spark)
                                          │
                                          ▼
                              build_inventory_lakehouse  (shared with scanner)
                                          │
                                          ▼   mapPartitions
                              chunk_notebook(path, content, ctx)
                                          │      ── cell-boundary-aware chunker
                                          │      ── enrich_attached_lakehouse()
                                          ▼
                                  chunks_df.persist().count()
                                          │   ── materialize BEFORE AI to
                                          │      prevent Spark retries
                                          │      from doubling AI cost
                                          ▼
                              df.ai.generate_response(prompt=AI_AUDIT_PROMPT,
                                                       response_format=...)
                                          │
                                          ▼
                              parse_ai_response_df()
                                          │   ── defensive: clamps scores,
                                          │      empty arrays for nulls,
                                          │      synthesizes parse_error
                                          ▼
                              aggregate_chunks_to_notebooks()
                                          │   ── max scores across chunks
                                          │   ── distinct-flattened sources/dests
                                          │   ── top_rationale from highest-risk chunk
                                          ▼
                              write Delta:
                                ai_chunks_table  (per chunk, debug)
                                ai_output_table  (per notebook)
```

### Output tables

**`notebook_ai_audit_results`** — one row per notebook. Same enrichment
columns as the rule-based findings table (`workspace_id`,
`source_dated_partition`, `attached_lakehouse_*`) so the two tables
JOIN cleanly. Adds:

| Column | Type | Notes |
|---|---|---|
| `chunk_count` / `chunks_parsed` / `chunks_errored` | int | Per-notebook chunk stats |
| `external_resource_access_score` | int | 0–100, **max** across chunks |
| `exfiltration_risk_score` | int | 0–100, **max** across chunks |
| `sources` | `array<struct<endpoint,type,deterministic>>` | Distinct-flattened across chunks |
| `destinations` | same | Distinct-flattened across chunks |
| `top_rationale` | string | Rationale from the highest-risk chunk |
| `content_hash` | string | sha256[:16] of the extracted text (resume key + collision precision) |
| `auditor_version` / `prompt_version` / `run_id` / `assessed_at` | string + ts | Provenance — pin scores to the prompt that produced them |

**`notebook_ai_audit_chunks`** — one row per (notebook, chunk). Same
columns plus `chunk_index`, `chunk_text`, `ai_response`, `ai_error`,
and the per-chunk parsed scores. Useful when you need to look at the
specific chunk that drove a high score.

### JOIN with the rule-based findings table

```sql
SELECT
  r.workspace_id, r.display_name, r.severity, r.finding_type,
  a.external_resource_access_score, a.exfiltration_risk_score,
  a.top_rationale
FROM   notebook_findings r
LEFT JOIN notebook_ai_audit_results a
       ON r.workspace_id           = a.workspace_id
      AND r.source_dated_partition = a.source_dated_partition
      AND r.display_name           = a.display_name
ORDER BY a.exfiltration_risk_score DESC NULLS LAST,
         a.external_resource_access_score DESC NULLS LAST;
```

### Setup checklist

Before running the AI auditor on a Fabric workspace:

1. **AI Functions enabled** on the workspace (Fabric admin portal →
   tenant settings → AI Functions for Fabric).
2. **Workspace capacity allows AI calls** — quota is shared with other
   AI workloads.
3. **Lakehouse mode only.** v1 raises `RuntimeError` for
   `source_mode='api'`. Export notebooks to a lakehouse first (see the
   companion downloader helper).
4. **Privacy review of the corpus.** Confirm sending these notebooks'
   text to the AI endpoint is acceptable for your org.
5. **Start with a budget cap.** Set `ai_max_total_chunks` to a small
   number (e.g. 50) for the first run; remove the cap only after you
   know the cost shape of your corpus.

### Python API

```python
from fabric_scanner import ScannerConfig
from fabric_scanner.ai import AIAuditOptions, run_ai_audit

cfg = ScannerConfig(
    source_mode="lakehouse",
    source_layout="ws_dated",
    source_subpath="Files/notebook_exports",
)
opts = AIAuditOptions(
    ai_max_chunks_per_notebook=50,
    ai_max_total_chunks=500,     # hard budget cap (recommended)
    write_chunks_table=True,
)

result = run_ai_audit(cfg, opts, spark)
print(result.notebooks_count, result.chunks_total, result.run_id)
```



After changing the wheel version or the cell template, regenerate the
orchestration notebooks (both `_v2` and `_ai_v1`) so they point at the
right pin:

```pwsh
cd scannerHelper
python scripts/build_notebook.py
# -> notebooks/fabric_scanner_v2.ipynb       (rule-based; pin updated)
# -> notebooks/fabric_scanner_ai_v1.ipynb   (AI auditor; pin updated)

# Build just one:
python scripts/build_notebook.py --target v2
python scripts/build_notebook.py --target ai
```

CI fails if `notebooks/` is out of sync with the script — every
release pin updates both notebooks.

## Tests

```pwsh
cd scannerHelper
pip install -e ".[dev]"
pytest tests/unit/        # 228 fast unit tests, no Spark required
```

Integration tests (`tests/integration/`) need a local PySpark + Java and
are not included by default; run with `pytest -m integration`.

## Build a wheel

```pwsh
cd scannerHelper
pip install build
python -m build
ls dist/
# fabric_scanner-0.3.2-py3-none-any.whl
# fabric_scanner-0.3.2.tar.gz
```

Attach the wheel to your Fabric environment, or upload it to a release
artifact and update the `%pip install` URL in cell 1 of the notebook.

## Continuous integration

Four GitHub Actions workflows live under `.github/workflows/`:

| Workflow | Trigger | Purpose |
|---|---|---|
| `build.yml` | `workflow_call` | Reusable: install deps, run **228 unit tests**, verify notebooks are in sync with `build_notebook.py`, build wheel + sdist, smoke-test the wheel in a clean venv, upload artifacts as `dist`. |
| `ci.yml` | PR to `main` | Calls `build.yml`. Provides the green-check gate before merge. Concurrency-cancels stale runs on the same PR. |
| `main.yml` | push to `main`, manual dispatch | The auto-tag + release pipeline. Three jobs: (1) bump `_version.py`, regenerate the notebook, commit + tag + push; (2) call `build.yml` against the new tag; (3) **`environment: production`** — pauses for manual approval, then publishes the GitHub Release with the wheel + sdist attached. |
| `release.yml` | manual dispatch only | Fallback to re-release any existing tag (e.g. if a previous artifact upload failed). Also gated by `environment: production`, so the manual approval requirement cannot be bypassed. |

The release always publishes the **exact same** wheel that was
tested + smoke-tested in the same workflow run — there is no
separate "build for release" path that could drift.

## How releases work

Every push to `main` automatically bumps the patch version, tags the
commit, builds the wheel, and queues a GitHub Release that waits for a
maintainer to approve it.

### The everyday flow

```text
PR merged to main
        │
        ▼
main.yml fires (push: main)
        │
        ▼
┌──────────────────────────────────────┐
│ 1. tag                               │
│    - Read latest v*.*.* git tag      │
│    - Bump patch (default)            │
│    - Update _version.py              │
│    - Regenerate notebook             │
│    - Commit "chore: bump to vX.Y.Z   │
│      [skip ci]" and push to main     │
│    - Create + push tag vX.Y.Z        │
│    - Idempotent: re-runs against an  │
│      already-tagged HEAD reuse the   │
│      existing tag instead of bumping │
└──────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────┐
│ 2. build (calls build.yml)           │
│    - Checkout new tag                │
│    - pytest tests/unit (228)         │
│    - python -m build                 │
│    - Smoke-test wheel in clean venv  │
│    - Upload `dist` artifact          │
└──────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────┐
│ 3. release  (environment:production) │
│    ⏸ PAUSES for manual approval     │
│    ✓ Reviewer clicks "Approve and    │
│      deploy" in the Actions UI       │
│    - Download dist artifact          │
│    - Publish GitHub Release at the   │
│      new tag with auto-generated     │
│      notes + wheel + sdist           │
└──────────────────────────────────────┘
```

### Approving (or rejecting) a release

1. Go to **Actions** → the most recent **main** workflow run.
2. The `release` job will be in **Waiting** state with a "Review deployments" button.
3. Choose **Approve and deploy** (publishes the release) or **Reject** (cancels — the tag stays, but no GitHub Release is created).

### Opting out of a release for a single commit

Add `[skip release]` anywhere in the commit message of the merge into `main`. The pipeline exits before bumping/tagging — useful for docs-only changes you don't want to release.

### Overriding the bump (minor / major / explicit version)

From the **Actions** tab → **main** workflow → **Run workflow**:

| Input | Behavior |
|---|---|
| `bump = patch` (default) | 0.3.2 → 0.3.3 |
| `bump = minor` | 0.3.x → 0.4.0 |
| `bump = major` | 0.x.y → 1.0.0 |
| `version = 1.2.0` (explicit) | Tags `v1.2.0` directly. Must be greater than the latest tag and not already exist. |

### One-time GitHub UI setup (required before this works)

After merging this workflow, configure the repo once:

1. **Settings → Actions → General → Workflow permissions** → select **Read and write permissions**. This lets the `tag` job push commits + tags back to `main`.
2. **Settings → Environments → New environment `production`** → add yourself (or a maintainer group) as a **Required reviewer**. This is what creates the manual approval gate. *Until this is configured, the release job will run immediately without pausing.*
3. **Settings → Branches** (if branch protection is enabled on `main`) → allow `github-actions[bot]` to bypass the required PR/review rules, otherwise the tag job's push will be rejected.

### Re-running a failed release for an existing tag

If the tag was created but the release publish failed (e.g. transient artifact-upload error), use the `release.yml` fallback:

1. **Actions** → **release** workflow → **Run workflow** → enter the tag (e.g. `v0.3.3`).
2. It will rebuild the wheel from the tag's commit, then prompt for manual approval before publishing.

## Distribution options

| Option | Trade-off |
|---|---|
| GitHub release artifact | Lowest friction; URL changes per version |
| Fabric environment library | Best UX per workspace; manual upload |
| Internal PyPI / Azure Artifacts | Best org-wide rollout; needs feed infra |

For v0.3 the recommended path is **GitHub release artifact**: pin the
notebook against the release-asset URL.

## Migrating from the legacy notebook

The legacy single-file `fabric_scanner_v2.ipynb` and the original
`fabric_url_scanner.ipynb` (documented in `README_legacy_v1.md`) keep
working — they're not removed in this release. They will be deleted in
v0.4 once the wheel-based notebook has had a release cycle of stability.

To migrate:

1. Replace your current scanner notebook with
   `notebooks/fabric_scanner_v2.ipynb`.
2. Move your customizations (cell 1 config) into the new `ScannerConfig`
   call. Every legacy knob has the same name on the dataclass.
3. Run cell 2 (`probe`) to confirm it's pointed at the same source.
4. Run cell 3 (`run`) — the inventory + findings tables come out
   identical to the legacy run.

## Limitations

- Runtime-built paths still can't be attributed (legacy behavior
  preserved). Findings land in the `flag_for_review` bucket.
- Secret snippets are auto-redacted (first/last 4 chars kept) but the
  output table should still be access-controlled.
- Notebook *outputs* are not scanned for secrets / writes by default
  (only URLs in outputs are captured as `reference` rows). Toggle
  `cfg.scan_markdown_and_outputs = False` to skip them entirely.

## Changelog

### 0.3.2
- Workspace GUID is now extracted from the notebook path universally
  for any layout via the new `PATH_GUID_DATE_RE` in `paths.py`. Both
  the inventory snapshot and per-finding rows benefit. Priority:
  `ws_dated_base` anchor > universal `/<guid>/<datestamp>/<file>`
  pattern > source-lakehouse default.
- `workspace_name` always falls back to the GUID itself when no
  friendly name is known (instead of remaining empty).

### 0.3.1
- Fabric `.py` source-format notebooks: the default lakehouse ID,
  name, and workspace ID are now parsed out of the `# META` block at
  the top of the file (previously only handled in `.ipynb` JSON).
- Inventory scanner walks both `*.ipynb` and `*.py` Fabric exports
  when `source_file_glob` is widened.

### 0.3.0
- Initial wheel-based release. Replaced the single-file
  `fabric_scanner_v2.ipynb` with a five-phase thin orchestrator
  and an installable `fabric-scanner` wheel.
