# fabric-scanner

Audit Microsoft Fabric notebooks for URLs, secrets, API keys, and
external-write operations.

The scanner ships as a normal Python wheel — install it once on your
cluster, then drive it from a five-cell orchestration notebook.

## Install

From a Fabric notebook:

```
%pip install -q fabric-scanner==0.3.0
```

Or from source for development:

```pwsh
cd scannerHelper
pip install -e ".[dev,api,spark]"
```

## Usage

The thin orchestration notebook (`notebooks/fabric_scanner_v2.ipynb`) is
five cells:

```python
# Cell 1 — install
%pip install -q fabric-scanner==0.3.0

# Cell 2 — config
from fabric_scanner import ScannerConfig
cfg = ScannerConfig(
    source_mode    = "lakehouse",    # or "api"
    source_layout  = "flat",         # or "ws_dated"
    source_subpath = "Files/notebooks",
    min_severity   = "low",
)

# Cell 3 — probe (sanity-check what will be scanned)
from fabric_scanner import resolve_paths, probe
resolved = resolve_paths(cfg)
probe(cfg, resolved)

# Cell 4 — run
from fabric_scanner.spark import run
result = run(cfg, spark)
print(f"{result.findings_count} findings / {result.notebook_count} notebooks")

# Cell 5 — explore
display(result.summary.review_queue)
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
├── config.py         ScannerConfig dataclass
├── engine/           Pure-Python detection logic (no Spark, no Fabric)
│   ├── patterns.py     URL_RE, READ_RE, WRITE_RE, SECRET_PATTERNS, ...
│   ├── extract.py      .ipynb walker + attached-lakehouse parser
│   ├── resolve.py      cross-workspace URL classification
│   ├── utils.py        entropy, AST scan, snippet redaction
│   └── scanner.py      scan_notebook_bytes() — the entry point
├── paths.py          ABFSS path math + ws_dated enumeration
├── diagnostics.py    probe() — paths + endpoint sanity check
├── api/              Fabric REST mode (requires the [api] extra)
│   ├── auth.py         token acquisition (5-source chain)
│   ├── enumerate.py    /workspaces + /items listing
│   └── fetch.py        getDefinition + 202 LRO polling
├── spark/            Cluster fan-out (requires the [spark] extra)
│   ├── schema.py       result_schema (27-col StructType)
│   ├── context.py      PartitionContext (broadcast bag)
│   ├── inventory.py    build_inventory_lakehouse / _api
│   ├── partition.py    scan_row + scan_partition_lakehouse + fetch_partition
│   └── runner.py       run(cfg, spark) -> ScannerResult
└── persist.py        write_findings + SummaryReport (10 rollups)
```

## Output schema

One row per finding (or one empty row per file with no findings).
Inventory table is one row per scanned notebook.

| Column | Type | Notes |
|---|---|---|
| `workspace_id` / `workspace_name` | string | always |
| `source_lakehouse_id` / `_name` | string | lakehouse mode only |
| `source_dated_partition` | string | populated when `source_layout="ws_dated"` |
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

## Build the notebook

After changing the wheel version or the cell template, regenerate the
orchestration notebook so it points at the right pin:

```pwsh
cd scannerHelper
python scripts/build_notebook.py
# -> notebooks/fabric_scanner_v2.ipynb (pin updated)
```

## Tests

```pwsh
cd scannerHelper
pip install -e ".[dev]"
pytest tests/unit/        # ~200 fast unit tests, no Spark required
```

Integration tests (`tests/integration/`) need a local PySpark + Java and
are not included by default; run with `pytest -m integration`.

## Build a wheel

```pwsh
cd scannerHelper
pip install build
python -m build
ls dist/
# fabric_scanner-0.3.1-py3-none-any.whl
# fabric_scanner-0.3.1.tar.gz
```

Attach the wheel to your Fabric environment, or upload it to a release
artifact and update the `%pip install` URL in cell 1 of the notebook.

## Cutting a release

Releases are automated via the `release.yml` GitHub Actions workflow.
Tagging a commit with `vX.Y.Z` triggers a job that runs the unit tests,
verifies the tag matches `src/fabric_scanner/_version.py`, builds the
wheel + sdist, smoke-tests the wheel in a clean venv, and creates a
GitHub Release with both artifacts attached and auto-generated notes.

```pwsh
# 1. Bump the version (single source of truth)
#    src/fabric_scanner/_version.py  ->  __version__ = "0.3.2"
# 2. Regenerate the orchestration notebook so the pin matches
python scripts/build_notebook.py
# 3. Commit, merge to main, then tag + push
git tag -a v0.3.2 -m "fabric-scanner v0.3.2"
git push origin v0.3.2
```

The workflow can also be re-run manually via the **Actions** tab
(`workflow_dispatch`) against any existing tag.

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
