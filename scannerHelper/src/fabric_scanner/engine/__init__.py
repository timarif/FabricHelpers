"""Pure-Python detection engine — no Spark / Fabric dependencies.

Public exports:
    scan_notebook_bytes — top-level scan over a single notebook's bytes
    PATTERNS, SUSPICIOUS_IMPORTS, IMPORT_CATEGORIES — the rule tables
    resolve_dest_workspace — URL → workspace classifier
"""
from .scanner   import scan_notebook_bytes
from .patterns  import (
    PATTERNS,
    SUSPICIOUS_IMPORTS,
    IMPORT_CATEGORIES,
    URL_PROTOCOL_SCHEMES,
)
from .resolve   import resolve_dest_workspace, parse_dest_workspace
from .extract   import extract_attached_lakehouse, extract_blocks

__all__ = [
    "scan_notebook_bytes",
    "PATTERNS", "SUSPICIOUS_IMPORTS", "IMPORT_CATEGORIES",
    "URL_PROTOCOL_SCHEMES",
    "resolve_dest_workspace", "parse_dest_workspace",
    "extract_attached_lakehouse", "extract_blocks",
]
