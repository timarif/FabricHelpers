# fabric-reporting

Shared reporting adapter for the **FabricHelpers** suite.  Provides a
canonical Delta table schema and a thin `ReportingAdapter` that any Fabric
helper can call (opt-in) to write findings, downloads, and MPE lifecycle
events into a **single shared lakehouse landing zone** — the "single pane of
glass" for Fabric administrators.

---

## Overview

Each helper today writes its results to its own table or file:

| Helper | Native output |
|---|---|
| `scannerHelper` | `v2_findings` + `v2_inventory` Delta tables |
| `downloaderHelper` | per-run manifest + artifact files |
| `mpeHelper` | MPE inventory table |

`fabric-reporting` adds a **shared landing schema** that every helper can
write into via a single function call.  The shared schema is defined in
[`SCHEMA.md`](SCHEMA.md).

---

## Quick start

```python
from fabric_reporting import ReportingAdapter

adapter = ReportingAdapter(spark, "abfss://<ws>@onelake.dfs.fabric.microsoft.com/<lh>.Lakehouse/Tables")

# Idempotently create the six canonical tables (safe to call every run).
adapter.ensure_tables()

# Write rows — validated against the Pydantic schema before touching Delta.
n = adapter.write_facts("fact_scan_findings", [
    {
        "finding_id":             "550e8400-e29b-41d4-a716-446655440000",
        "scan_run_id":            "run-2024-01-15",
        "workspace_id":           "ws-guid",
        "source_dated_partition": "2024-01-15",
        "notebook_id":            "nb-guid",
        "severity":               "high",
        "kind":                   "entropy",
        "redacted_snippet":       "token = '***'",
        "url":                    None,
        "detected_at":            datetime(2024, 1, 15, 10, 0, 0),
    }
])
print(f"Wrote {n} rows")
```

---

## Shared-lakehouse contract

The adapter writes into six Delta tables under a single root path:

```
<lakehouse_path>/
├── fact_scan_findings/     # scannerHelper findings
├── fact_downloads/         # downloaderHelper downloads
├── fact_mpe_lifecycle/     # mpeHelper MPE events
├── dim_workspace/          # workspace dimension
├── dim_item_type/          # item-type dimension
└── dim_severity/           # severity dimension
```

See [`SCHEMA.md`](SCHEMA.md) for full column definitions and primary keys.

---

## Helper integration

Each helper adds a thin `reporting.py` module that maps its native output
into the shared schema and calls the adapter.  The integration is **opt-in
and off by default** — existing workflows are unchanged unless the user
explicitly enables it.

### scannerHelper

Add `reporting_lakehouse` to your `ScannerConfig`:

```python
from fabric_scanner import ScannerConfig
from fabric_scanner.spark import run

cfg = ScannerConfig(
    source_mode       = "lakehouse",
    reporting_lakehouse = "abfss://.../Tables",  # opt-in
)
result = run(cfg, spark)
# The adapter is called automatically after the scan completes.
```

---

## Package layout

```
reportingHelper/
├── SCHEMA.md                       Canonical table documentation
├── pyproject.toml
└── src/fabric_reporting/
    ├── __init__.py                 Public API: ReportingAdapter, __version__
    ├── _version.py
    ├── adapter.py                  ReportingAdapter (ensure_tables + write_facts)
    └── models.py                   Pydantic v2 row models + TABLE_REGISTRY
```

---

## Installation

```bash
# Engine only (Pydantic validation, no Spark writes):
pip install fabric-reporting

# With Spark support:
pip install "fabric-reporting[spark]"
```

---

## Development

```bash
cd reportingHelper
pip install -e "../coreHelper"
pip install -e ".[dev]"
pytest tests/unit/ -q
```
