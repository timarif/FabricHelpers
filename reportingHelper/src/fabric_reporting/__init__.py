"""fabric_reporting — shared reporting adapter for Fabric helpers.

Provides a canonical Delta table schema and a thin adapter that every
Fabric helper can call (opt-in) to write findings, downloads, and MPE
lifecycle events into a shared lakehouse landing zone.

Quick start::

    from fabric_reporting import ReportingAdapter

    adapter = ReportingAdapter(spark, "abfss://.../reporting_lakehouse")
    adapter.ensure_tables()
    adapter.write_facts("fact_scan_findings", rows)

The adapter validates every row against the Pydantic model for the
target table before touching Delta, so schema mismatches surface as
Python errors rather than corrupted data.

See ``SCHEMA.md`` for the full canonical schema documentation.
"""
from .adapter import ReportingAdapter
from ._version import __version__

__all__ = [
    "ReportingAdapter",
    "__version__",
]
