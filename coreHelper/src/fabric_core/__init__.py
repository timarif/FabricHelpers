"""fabric-core — shared low-level helpers for the FabricHelpers monorepo.

This wheel hosts code that both ``fabric-scanner`` and ``fabric-downloader``
need verbatim: token acquisition, REST path math, async workspace
enumeration, four-endpoint API probe diagnostics, and notebook-build
plumbing.

Public modules:

* :mod:`fabric_core.auth`         — ``TokenError``, ``get_token``, ``_from_*`` sources
* :mod:`fabric_core.paths`        — ``ONELAKE_HOST``, ``table_path``, ``files_path``,
                                   ``files_uri``, ``fs_ls``, ``detect_notebook_runtime``,
                                   ``_import_nbu``
* :mod:`fabric_core.enumerate`    — ``_http_json``, workspace listers,
                                   admin→user fallback, ``enumerate_workspaces_items``
                                   with pluggable ``item_filter`` callback
* :mod:`fabric_core.diagnostics`  — ``probe_api``, ``ProbeResult``
* :mod:`fabric_core.build_notebook``
                                   — ``NotebookBuildSpec``, ``write_notebook``,
                                   ``_md``/``_code``/``_slug``/``_load_version`` helpers
"""
from ._version import __version__
from .auth import TokenError, get_token
from .build_notebook import NotebookBuildSpec, write_notebook
from .diagnostics import ProbeResult, probe_api
from .enumerate import enumerate_workspaces_items, run_enumeration_sync
from .paths import (
    ONELAKE_HOST,
    detect_notebook_runtime,
    files_path,
    files_uri,
    fs_ls,
    table_path,
)

__all__ = [
    "__version__",
    "TokenError",
    "get_token",
    "NotebookBuildSpec",
    "write_notebook",
    "ProbeResult",
    "probe_api",
    "enumerate_workspaces_items",
    "run_enumeration_sync",
    "ONELAKE_HOST",
    "detect_notebook_runtime",
    "files_path",
    "files_uri",
    "fs_ls",
    "table_path",
]
