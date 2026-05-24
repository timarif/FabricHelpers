"""fabric-core — shared low-level helpers for the FabricHelpers monorepo.

This wheel hosts code that ``fabric-scanner``, ``fabric-downloader``, and
``fabric-mpe`` need verbatim: token acquisition, REST path math, async
workspace enumeration, four-endpoint API probe diagnostics, a small
synchronous retrying HTTP client, and notebook-build plumbing.

Public modules:

* :mod:`fabric_core.auth`         — ``TokenError``, ``get_token``, ``_from_*`` sources,
                                   ``fetch_token_via_client_credentials``
* :mod:`fabric_core.http`         — ``request_json``, ``paged_get``, ``collect_paged``
                                   (urllib-based, retries 429 + 5xx)
* :mod:`fabric_core.paths`        — ``ONELAKE_HOST``, ``table_path``, ``files_path``,
                                   ``files_uri``, ``mounted_files_path``, ``fs_ls``,
                                   ``detect_notebook_runtime``, ``_import_nbu``
* :mod:`fabric_core.enumerate`    — ``_http_json``, workspace listers,
                                   admin→user fallback, ``enumerate_workspaces_items``
                                   with pluggable ``item_filter`` callback
* :mod:`fabric_core.diagnostics`  — ``probe_api``, ``ProbeResult``
* :mod:`fabric_core.build_notebook``
                                   — ``NotebookBuildSpec``, ``write_notebook``,
                                   ``_md``/``_code``/``_slug``/``_load_version`` helpers
"""
from ._version import __version__
from .auth import TokenError, fetch_token_via_client_credentials, get_token
from .build_notebook import NotebookBuildSpec, write_notebook
from .diagnostics import ProbeResult, probe_api
from .enumerate import enumerate_workspaces_items, run_enumeration_sync
from .http import collect_paged, paged_get, request_json
from .paths import (
    ONELAKE_HOST,
    detect_notebook_runtime,
    files_path,
    files_uri,
    fs_ls,
    mounted_files_path,
    table_path,
)

__all__ = [
    "__version__",
    "TokenError",
    "get_token",
    "fetch_token_via_client_credentials",
    "NotebookBuildSpec",
    "write_notebook",
    "ProbeResult",
    "probe_api",
    "enumerate_workspaces_items",
    "run_enumeration_sync",
    "request_json",
    "paged_get",
    "collect_paged",
    "ONELAKE_HOST",
    "detect_notebook_runtime",
    "files_path",
    "files_uri",
    "fs_ls",
    "mounted_files_path",
    "table_path",
]
