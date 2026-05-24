"""Handler sub-package for fabric-downloader item types.

Importing this package registers all built-in handlers into
:data:`fabric_downloader.item_types.REGISTRY`.
"""
from __future__ import annotations

from . import (  # noqa: F401
    dataflow,
    environment,
    eventstream,
    kql_database,
    lakehouse,
    notebook,
    pipeline,
    report,
    semantic_model,
    spark_job_definition,
)

__all__ = [
    "dataflow",
    "environment",
    "eventstream",
    "kql_database",
    "lakehouse",
    "notebook",
    "pipeline",
    "report",
    "semantic_model",
    "spark_job_definition",
]
